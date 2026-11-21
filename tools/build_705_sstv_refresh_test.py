"""Remove hidden SSTV peak-meter redraws from the fixed-layout TX2j field images."""
import argparse
from hashlib import md5, sha256
import json
from pathlib import Path
from struct import pack, unpack_from
from zipfile import ZipFile, ZIP_DEFLATED

from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_main
from tools.emulate_705 import BASE, call, machine
from tools.replay_705_nor_boot import with_pc_main
from tools.replay_705_stock_install import load_a

BASELINES = {
    "3d9fa69f89b3c1c6b3bcd2be34825c516ec9f2c934c474fb41a3d6df88e7c9d9": ("J", 2),
    "993c49a2d1622d59517ebef0c73b74d78ca82aefb577914649d83980ab48839b": ("E", 20),
    "8dcb44ae45c02d963d4eba6c9feca23d97f1e90b1f0409f75366de7d467c3c68": ("J", 2),
    "eae5fe51c75e93ba8531c1d2045f459d207daacb0ac9bee03558192f31a85d94": ("E", 20),
}


def probe(main, symbols):
    cpu = machine(main)
    def word(address, n):
        cpu.mem_write(address, pack("<I", n))
    def refresh():
        cpu.mem_write(0x20380c98, bytes(1))
        call(cpu, symbols["sstv_prepare_frame"])
        return cpu.mem_read(0x20380c98, 1)[0] & 1
    cpu.mem_write(0x203e84c9, pack("<H", 21))
    counts = symbols["counts"]
    word(counts, 1)
    word(counts+4, 1)
    word(counts+12, 1)
    refresh()
    redundant = 0
    for n in range(32):
        word(symbols["displayed_peak"], 512 if n % 2 else 8192)
        redundant += refresh()
    word(symbols["vis_status"], 9)
    assert refresh() and not refresh()
    word(counts+36, 8)
    word(counts+24, 2)
    assert refresh() and not refresh()
    return redundant


def build(source, out, symbols):
    package = source.read_bytes()
    region, depth = BASELINES[sha256(package).hexdigest()]
    original = bytes(decode_main(package)[1])
    _, flash = load_a(package, sha256(original).hexdigest())
    main = bytearray(original)
    # Both regional station builds have external references into this fixed ELF.
    # Compare visible status unconditionally instead of comparing it only if the
    # old and new (now hidden) peaks are equal. Keep all entry points in place.
    pc = 0x20377e94 - BASE
    assert unpack_from("<II", main, pc) == (0xe1560007, 0x01530002)
    main[pc+4:pc+8] = pack("<I", 0xe1530002)
    before, after = probe(original, symbols), probe(bytes(main), symbols)
    assert (before, after) == (32, 0)
    updated = with_pc_main(flash, bytes(main), match_depth=depth)
    # Only the encoded main slot, the feedback byte after it, and group A's
    # digest can change. Reuse all regional assets and the published header.
    end = BOOT_SIZE + 8 + unpack_from("<I", updated, BOOT_SIZE)[0] + 1
    assert updated[end:] == flash[end:]
    _, group = checked_group_a(package)
    start, stop = group["offset"], group["end_exclusive"]
    dat = bytearray(package)
    for i in range(BOOT_SIZE, end):
        dat[start+i] = updated[i] ^ ((updated[i-1]+start+i-0x19) & 255)
    dat[stop:stop+16] = md5(dat[start:stop], usedforsecurity=False).digest()
    rebuilt, full = load_a(bytes(dat), sha256(main).hexdigest())
    assert rebuilt == main and full == updated
    name = f"705{region}140"
    out.mkdir(parents=True, exist_ok=True)
    zpath = out/f"{name}-SSTV-refresh-test.zip"
    with ZipFile(zpath, "w", ZIP_DEFLATED) as z:
        z.writestr(f"IC-705/{name}.dat", dat)
    with ZipFile(zpath) as z:
        assert z.read(f"IC-705/{name}.dat") == dat
    report = dict(region=region,baseline_sha256=sha256(package).hexdigest(),dat_sha256=sha256(dat).hexdigest(),
                  peak_only_redraws_before=before,peak_only_redraws_after=after,
                  vis_and_row_redraws_pass=True,changed_main_bytes=sum(a!=b for a,b in zip(original,rebuilt)))
    print(report,flush=True)
    (out/f"{name}.json").write_text(json.dumps(report,indent=2))


if __name__ == "__main__":
    from subprocess import check_output
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dat", type=Path)
    p.add_argument("--elf", type=Path, required=True)
    p.add_argument("--nm", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    names = {v[2]:int(v[0],16) for l in check_output([args.nm,str(args.elf)],text=True).splitlines()
             if len(v:=l.split()) == 3}
    build(args.dat,args.out,names)
