"""Use the paired FAT short name for long SSTV picker entries on v1.3.2."""
from argparse import ArgumentParser
import json
from pathlib import Path
from struct import pack, unpack_from
from subprocess import run

from tools.build_705_e140_log_test import BASE, ROOT, decode_main, digest, load_a, offline_test_page, repack_main
from tools.emulate_705 import call, machine

BASELINES = {
    "eb7d2d1bb969241e17dbc7effb387cf4c9d73ab2e58c7267c4c461014febff65": "J",
    "be19795bc4f0fbf0daa058b838ccfc0bcb694def4415ee0213f2bd1e8eca0471": "E",
}
FT_CANDIDATES = {
    "5c985561d9217588b07b31571a05bf36638dbdacd51b131e1763e9e4935ab167": "J",
    "1c96571f7aa158778e81ffb94ce4bef920b0025c132e2bd557179d44edc3ca17": "E",
}


def compare(main, name, preview):
    # Enter the actual filename comparison after the independent readiness checks.
    from tools.emulate_705 import arm
    cpu = machine(bytes(main))
    field = 0x203e1038
    cpu.mem_write(field, name.ljust(28, b"\0"))
    cpu.mem_write(field-208, preview.ljust(28, b"\0"))
    cpu.reg_write(arm.UC_ARM_REG_R4, field)
    from tools.emulate_705 import SP, STOP
    cpu.mem_write(SP, pack("<4I", 0, 0, 0, STOP))
    return call(cpu, 0x20376868, 0)


def branch(pc, target):
    return 0xeb000000 | (((target-pc-8)//4) & 0xffffff)


def build(source, out, *, combined_base=False):
    dat = bytearray(source.read_bytes())
    region = (FT_CANDIDATES if combined_base else BASELINES)[digest(dat)]
    main = bytearray(decode_main(bytes(dat))[1])
    _, flash = load_a(bytes(dat), digest(main))
    full = b"X"*24 + b".jpg"
    assert compare(main, full, full) == 0
    pc = 0x20376898 - BASE
    assert main[pc-8:pc+4] == pack("<3I", 0xe371001c, 0x1afffff4, 0xeaffffe7)
    # All 28 bytes matched. Branch to the same success return as a matching NUL.
    main[pc:pc+4] = pack("<I", 0xea000001)
    assert compare(main, full, full) == 1
    assert compare(main, full, full[:-1]+b"G") == 0
    assert compare(main, b"Short.jpg", b"Short.jpg") == 1
    from tools.replay_705_stock_install import european_update_rom
    out.mkdir(parents=True, exist_ok=True)
    rom = lambda pc: pc
    if region == "E":
        japan = decode_main((ROOT/"firmware/705J140.dat").read_bytes())[1]
        europe = decode_main((ROOT/"firmware/705E140.dat").read_bytes())[1]
        rom = european_update_rom(japan, europe)
    hook, original = rom(0x20064bf0), rom(0x200644e8)
    # Unallocated gap between TX2j .station and .tail (same in both regions).
    start, end = 0x2037d9f8, 0x2037da38
    run(["arm-none-eabi-as", ROOT/"samples/sstv-picker-name.S", "-o", "name.o"], cwd=out, check=True)
    run(["arm-none-eabi-ld", "-Ttext", hex(start), "--defsym", f"stock_name={original}",
         "-e", "sstv_picker_name", "name.o", "-o", "name.elf"], cwd=out, check=True)
    run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".text", "name.elf", "name.bin"], cwd=out, check=True)
    code = (out/"name.bin").read_bytes()
    assert len(code) <= end-start and not any(main[start-BASE:end-BASE])
    assert unpack_from("<I", main, hook-BASE)[0] == branch(hook, original)
    main[start-BASE:start-BASE+len(code)] = code
    main[hook-BASE:hook-BASE+4] = pack("<I", branch(hook, start))
    from tools.verify_705_sstv_picker_name import verify
    evidence = verify(main, rom, region)
    if combined_base:
        # QTH repacked a shorter program over v1.3.2. Reuse only the
        # verified inactive suffix of that stream, retaining all FT assets.
        from tools.decode_705_main import BOOT_SIZE
        public = (ROOT/".analysis/sstv-refresh-tx2j1"/source.name).read_bytes()
        assert BASELINES[digest(public)] == region
        _, previous = load_a(public, digest(decode_main(public)[1]))
        current_size, = unpack_from("<I", flash, BOOT_SIZE)
        envelope, = unpack_from("<I", previous, BOOT_SIZE)
        tail = slice(BOOT_SIZE+8+current_size, BOOT_SIZE+8+envelope)
        assert current_size <= envelope and flash[tail] == previous[tail]
        flash = bytearray(flash)
        flash[BOOT_SIZE:BOOT_SIZE+4] = pack("<I", envelope)
    repack_main(dat, flash, main, 32 if region == "E" or combined_base else 3)
    out.mkdir(parents=True, exist_ok=True)
    stock = (ROOT/"firmware"/source.name).read_bytes()
    if combined_base:
        (out/source.name).write_bytes(dat)
    else:
        offline_test_page(out/f"{region}-SSTV.html", stock, dat, region, "SSTV · 长文件名重发测试")
    (out/"evidence.json").write_text(json.dumps(dict(region=region, sha256=digest(dat), **evidence), indent=2))
    print(region, digest(dat))


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--combined-base", action="store_true")
    args = parser.parse_args()
    build(args.source, args.out, combined_base=args.combined_base)
