"""Build the FT RTC log fix on the published four-feature v1.4.0 packages."""
from argparse import ArgumentParser
from hashlib import md5
from pathlib import Path
from struct import pack_into, unpack_from
from subprocess import run

from elftools.elf.elffile import ELFFile
from tools.build_705_aprs_slot import FIRST_OFFSET
from tools.build_705_e140_log_test import BASE, ROOT, decode_main, digest, load_a, offline_test_page
from tools.decode_705_main import BOOT_SIZE, checked_group_a
from tools.replay_705_nor_boot import with_pc_main

BASELINES = {
    "d17a9bb40555b8faebd9dc22cad6412eed45495f64973099d4b82dd5946fbaa6": "J",
    "3863d5372d0649e638d66dd2b372b1b8d3643f849dafbae745ceb45bfe7c17d6": "E",
}


def apply_timezone(main, folder):
    folder.mkdir(parents=True, exist_ok=True)
    sections = {
        ".touch": (0x2037b658, 4), ".display": (0x2037bebc, 0x2037bf2a - 0x2037bebc),
        ".stamp": (0x2037db18, 8), ".offset_ptr": (0x2037dc1c, 4),
    }
    script = "SECTIONS {\n" + "".join(
        f"{name} {at:#x} : {{ *({name}) }}\n" for name, (at, _) in sections.items()
    ) + "".join(f".{name} {at:#x} : {{ *(.import_{name}) }}\n" for name, at in
                (("ignore_touch", 0x2037b4a6), ("number2", 0x2037ac70), ("show_zone", 0x2037bf2a))) + "}\n"
    (folder/"timezone.ld").write_text(script, encoding="ascii")
    run(["arm-none-eabi-as", ROOT/"samples/ftx/v140_log_timezone.S", "-o", "timezone.o"], cwd=folder, check=True)
    run(["arm-none-eabi-ld", "-T", "timezone.ld", "timezone.o", "-o", "timezone.elf"], cwd=folder, check=True)
    with (folder/"timezone.elf").open("rb") as fp:
        elf = ELFFile(fp)
        for name, (at, capacity) in sections.items():
            section = elf.get_section_by_name(name)
            data = section.data()
            assert section["sh_addr"] == at and 0 < len(data) <= capacity
            main[at-BASE:at-BASE+len(data)] = data


def build(source, folder):
    dat = bytearray(source.read_bytes())
    region = BASELINES[digest(dat)]
    main = bytearray(decode_main(bytes(dat))[1])
    _, flash = load_a(bytes(dat), digest(main))
    apply_timezone(main, folder)

    # Use the v1.4.0 integration build's reserved compressed-program range.
    # Its unused tail can contain padding retained from an earlier package.
    assert BOOT_SIZE + 8 + unpack_from("<I", flash, BOOT_SIZE)[0] <= FIRST_OFFSET
    envelope = bytearray(flash)
    pack_into("<I", envelope, BOOT_SIZE, FIRST_OFFSET-BOOT_SIZE-8)
    packed = with_pc_main(envelope, bytes(main), match_depth=32, lazy=True)
    end = BOOT_SIZE + 8 + unpack_from("<I", packed, BOOT_SIZE)[0]
    assert end <= FIRST_OFFSET and packed[end:] == flash[end:]
    _, group = checked_group_a(bytes(dat))
    start, stop = group["offset"], group["end_exclusive"]
    for i in range(BOOT_SIZE, end+1):
        dat[start+i] = packed[i] ^ ((packed[i-1]+start+i-0x19) & 255)
    dat[stop:stop+16] = md5(dat[start:stop], usedforsecurity=False).digest()
    assert load_a(bytes(dat), digest(main)) == (main, packed)
    name = f"705{region}140.dat"
    (folder/name).write_bytes(dat)
    offline_test_page(folder/"FT-RTC.html", (ROOT/"firmware"/name).read_bytes(), dat,
                      region, f"IC-705 {region}140 · FT 日志时区测试")
    print(name, digest(dat))


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    build(args.source, args.folder)
