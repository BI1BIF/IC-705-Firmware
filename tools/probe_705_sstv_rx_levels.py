"""Replay calibrated PCM at the native SSTV queue in a delivered J140 DAT."""
import argparse
from array import array
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
import subprocess
import wave

from tools.decode_705_main import decode_main
from tools.emulate_705 import BASE, SCRATCH, call, machine
from tools.probe_705_sstv_arm import counters


def measure(image, symbols, samples, target, full, canvas_out=None):
    cpu = machine(image)
    cpu.mem_write(symbols["counts"], pack("<I", 1))
    cpu.mem_write(symbols["generation"], pack("<I", 1))
    cpu.mem_write(symbols["pixels"], pack("<I", 0x20800000))
    cpu.mem_write(0x203e84c9, pack("<H", 21))
    source = samples if full else samples[:3*8000]
    scale = target / max(map(abs, samples))
    groups = 0
    for i in range(0, len(source)-5, 6):
        cpu.mem_write(SCRATCH, pack("<6h", *(round(v*scale) for v in source[i:i+6])))
        call(cpu, symbols["sstv_capture"], SCRATCH, timeout_us=0)
        groups += 1
        if groups % 18 == 0:
            call(cpu, symbols["sstv_worker"], timeout_us=0, instruction_limit=2_000_000)
    call(cpu, symbols["sstv_worker"], timeout_us=0, instruction_limit=2_000_000)
    result = counters(cpu, symbols)
    assert result["processed"] == groups and result["dropped"] == 0
    report={key: result[key] for key in ("locks", "mode", "rows", "dropped", "processed", "phase")}
    if "robot_loss" in symbols:
        report["loss"]=int.from_bytes(cpu.mem_read(symbols["robot_loss"],4),"little")
    if full:
        canvas=cpu.mem_read(0x20800000,320*240*2)
        report["image_sha256"]=sha256(canvas).hexdigest()
        if canvas_out is not None: canvas_out.extend(canvas)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dat", type=Path)
    p.add_argument("--nm", type=Path, required=True)
    p.add_argument("--rx2", action="store_true")
    args = p.parse_args()
    root = args.dat.parent
    data = args.dat.read_bytes()
    image = bytes(decode_main(data)[1])
    entries = subprocess.check_output([str(args.nm), str(root/"build/rx.elf")], text=True)
    symbols = {s[2]: int(s[0],16) for line in entries.splitlines() if len(s:=line.split())==3}
    start = symbols["sstv_pcm_hook"] - BASE
    code = (root/"build/rx.bin").read_bytes()
    # The ELF entry can follow other routines. Match the full linked binary at its actual origin.
    assert code and image.count(code)==1 and image.index(code)<=start<image.index(code)+len(code)
    with wave.open(".analysis/sstv-robot36-v1/robot36.wav") as wav:
        assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,48000)
        samples = array("h",wav.readframes(wav.getnframes()))[::6]
    levels = {}
    for target in (0,300,700,1500,3000,15000):
        full = args.rx2 and target==700
        r = measure(image,symbols,samples,target,full)
        locks = target>0 if args.rx2 else target>=3000
        assert r["locks"]==int(locks) and (r["rows"]==240 if full else bool(r["rows"])==locks), (target,r)
        levels[target]=r
        print(target,r,flush=True)
    (root/"pcm-levels.json").write_text(json.dumps(dict(dat_sha256=sha256(data).hexdigest(),
        source="Robot 36; first 3 seconds, full image for RX2 peak 700",levels=levels),indent=2))


if __name__=="__main__":
    main()
