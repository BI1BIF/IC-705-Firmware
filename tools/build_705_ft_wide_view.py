"""Apply the confirmed FT receive layout to a verified regional build."""
import argparse
from hashlib import md5, sha256
import json
from pathlib import Path
from struct import pack_into, unpack_from
from subprocess import run

from elftools.elf.elffile import ELFFile

from tools.build_705_aprs_slot import FIRST_OFFSET
from tools.build_705_ftx_rx import FT_DATA_OFFSET, FT_DATA_RAM
from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_main
from tools.emulate_705 import BASE
from tools.replay_705_nor_boot import with_pc_main
from tools.replay_705_stock_install import load_a


OVERLAY = 0x20826BC0
NUMBER = 0x20373DE4

# The old instructions are checked before changes. Calls to the number renderer
# pass right edges in the new layout. The existing touch targets are shared by FT8 and FT4.
EDITS = {
    0x2037D4DA: ("movs r1,#42", "movs r1,#144"),  # ECO after the live slot rail
    0x2037D502: ("movs r1,#199", "movs r1,#223"),
    0x2037D510: ("movw r1,#269", "movw r1,#299"),
    0x2037D520: ("movw r1,#307", "movw r1,#335"),
    0x2037D542: ("mov.w r1,#362", "movw r1,#367"),
    0x2037D684: ("cmp r6,#20", "cmp r6,#23"),
    0x2037D6F2: ("mov.w r1,#362", "movw r1,#396"),
    0x2037D6F6: ("bl resident_number", "bl wide_number"),
    0x2037D72C: ("cmp r3,#20", "cmp r3,#23"),
    0x2037D732: ("cmp r4,#19", "cmp r4,#22"),
    0x2037D738: ("rsb.w r0,r4,#20", "rsb.w r0,r4,#23"),
    0x2037D84E: ("mov.w r1,#362", "movw r1,#382"),
    0x2037D872: ("movw r1,#269", "movw r1,#313"),
    0x2037D876: ("bl resident_number", "bl wide_number"),
    0x2037D882: ("movw r1,#307", "movw r1,#349"),
    0x2037D88A: ("bl resident_number", "bl wide_number"),
    0x2037D980: ("movw r1,#269", "movw r1,#299"),
    0x208269EA: ("movs r1,#100", "movs r1,#30"),
    0x20826A0C: ("movs r1,#115", "movs r1,#45"),
    0x20826A10: ("movs r3,#72", "movs r3,#90"),
    0x20826A18: ("movs r3,#70", "movs r3,#88"),
    0x20826A1C: ("movs r1,#116", "movs r1,#46"),
    0x20826A40: ("movs r1,#101", "movs r1,#31"),
    0x20826A46: ("movs r3,#70", "movs r3,#88"),
    0x20826A5A: ("movs r1,#116", "movs r1,#46"),
    0x20826AAE: ("add.w r3,r1,#20", "add.w r3,r1,#23"),
    0x20826AD6: ("movs r5,#187", "movs r5,#211"),
    0x20826AD8: ("movs r1,#187", "movs r1,#211"),
    0x20826AF0: ("cmp r5,#196", "cmp r5,#220"),
    0x20826B14: ("movs r1,#199", "movs r1,#223"),
}


def assemble(folder, version, edits=EDITS):
    src = Path(__file__).resolve().parents[1] / "samples/ftx/v140_wide_view.S"
    asm = ".syntax unified\n.thumb\n.cpu cortex-a9\n"
    layout = [f".wide_number {OVERLAY:#x} : {{ *(.wide_number) }}",
              f".number_import {NUMBER:#x} : {{ *(.number_import) }}"]
    for address, operations in edits.items():
        name = f".edit_{address:x}"
        asm += f'.section {name},"ax"\n{operations[version]}\n'
        layout.append(f"{name} {address:#x} : {{ *({name}) }}")
    (folder / "wide-edits.S").write_text(asm, encoding="ascii")
    (folder / "wide.ld").write_text("SECTIONS {\n" + "\n".join(layout) + "\n}\n", encoding="ascii")
    run(["arm-none-eabi-as", src, "-o", "wide.o"], cwd=folder, check=True)
    run(["arm-none-eabi-as", "wide-edits.S", "-o", "wide-edits.o"], cwd=folder, check=True)
    elf_path = folder / ("wide.elf" if version else "original-layout.elf")
    run(["arm-none-eabi-ld", "-T", "wide.ld", "wide.o", "wide-edits.o", "-o", elf_path.name], cwd=folder, check=True)
    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        return ({address: elf.get_section_by_name(f".edit_{address:x}").data() for address in edits},
                elf.get_section_by_name(".wide_number").data())


def build(source, folder, *, expected_base):
    dat = bytearray(source.read_bytes())
    meta = json.loads((source.parent / "package.json").read_text())
    region = meta["region"]
    assert region in ("J", "E") and meta["sha256"] == expected_base == sha256(dat).hexdigest()
    main, original_flash = load_a(bytes(dat), meta["main_sha256"])
    main, flash = bytearray(main), bytearray(original_flash)
    folder.mkdir(parents=True, exist_ok=True)
    original, _ = assemble(folder, 0)
    edits, overlay = assemble(folder, 1)
    for address, code in edits.items():
        assert len(code) == len(original[address])
        image, pos = (flash, FT_DATA_OFFSET + address - FT_DATA_RAM) if address >= FT_DATA_RAM else (main, address - BASE)
        assert image[pos:pos+len(code)] == original[address], hex(address)
        image[pos:pos+len(code)] = code

    offset = FT_DATA_OFFSET + OVERLAY - FT_DATA_RAM
    assert flash[offset:offset+len(overlay)] == b"\xff" * len(overlay)
    assert OVERLAY+len(overlay) <= 0x20826E60  # FT runtime workspace begins here.
    flash[offset:offset+len(overlay)] = overlay
    assert unpack_from("<I", main, 0x2037CC28-BASE)[0] == 0x20826BB0
    pack_into("<I", main, 0x2037CC28-BASE, OVERLAY+len(overlay))

    pack_into("<I", flash, BOOT_SIZE, FIRST_OFFSET-BOOT_SIZE-8)
    packed = with_pc_main(flash, bytes(main), match_depth=32, lazy=True)
    end = BOOT_SIZE+8+unpack_from("<I", packed, BOOT_SIZE)[0]
    assert end <= FIRST_OFFSET and packed[end:offset] == flash[end:offset]
    _, group = checked_group_a(bytes(dat))
    start, stop = group["offset"], group["end_exclusive"]
    # Encode each changed byte and its successor, which depends on that byte.
    for pos in range(BOOT_SIZE, len(packed)):
        prev = pos-1
        if packed[pos] != original_flash[pos] or packed[prev] != original_flash[prev]:
            dat[start+pos] = packed[pos] ^ ((packed[prev]+start+pos-0x19)&255)
    dat[stop:stop+16] = md5(dat[start:stop],usedforsecurity=False).digest()
    main_sha = sha256(main).hexdigest()
    assert load_a(bytes(dat),main_sha) == (main, packed)
    assert bytes(decode_main(bytes(dat))[1]) == main
    target = folder / f"705{region}140.dat"
    target.write_bytes(dat)
    meta.update(sha256=sha256(dat).hexdigest(),main_sha256=main_sha,flash_end=end,ft_layout_base=expected_base)
    (folder/"package.json").write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    print(target, meta["sha256"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--expected-base", required=True)
    args = parser.parse_args()
    build(args.source,args.folder,expected_base=args.expected_base)
