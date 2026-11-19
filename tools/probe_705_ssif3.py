"""Replay both SSIF3 receive slots through the unmodified IC-705 J140 main."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack

from tools.emulate_705 import PROFILES, SCRATCH, arm, call, machine
from tools.probe_705_rf_sweep import sweep_blocks

DMA = 0xE8200424
BANK = 0x20400C80
RING = 0x204016E4


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def write_bank(cpu, i, audio, spectrum):
    words = [w for j, (sample, word) in enumerate(zip(audio, spectrum, strict=True))
             for w in ((sample & 0xFFFF) << 16 | (0x1357 + j), word)]
    cpu.mem_write(BANK + i % 2 * 0x120, pack("<72I", *words))


def scope_modes(main):
    """Observe what the original RTTY spectrum routine accepts from the first slot."""
    audio = [i * 103 - 1800 for i in range(36)]
    want = tuple(float(v) for v in audio[7::8])
    report = {}
    for mode, lower, expected in (("RTTY", 14, want), ("RTTY", 0, ()),
                                  ("CW", 14, ()), ("CW", 10, ())):
        cpu = machine(main)
        cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
        cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
        cpu.mem_map(DMA & ~0xFFF, 0x1000)
        cpu.mem_write(0x203E84CB, pack("<H", lower))
        cpu.mem_write(0x203E2128, b"\x40" if mode == "RTTY" else b"\x20")
        call(cpu, 0x200635A0)  # Let the original page and mode selection reset its reader.
        write_bank(cpu, 0, audio, (0,) * 36)
        cpu.mem_write(DMA, pack("<I", 0xC1))
        call(cpu, 0x200FFF4C)
        call(cpu, 0x200635A0)
        count = unpack("<I", cpu.mem_read(0x2039E8AC, 4))[0]
        require(count <= 4, "unexpected size in original FFT staging")
        actual = unpack(f"<{count}f", cpu.mem_read(0x2039D6AC, count * 4)) if count else ()
        require(actual == expected, f"unexpected RTTY FFT input: {mode}, {lower}, {actual}")
        report[f"{mode}_page_{lower}"] = {"fft_input": actual, "reader": cpu.mem_read(RING+0x242, 1)[0]}
    return report


def verify(main):
    digest = sha256(main).hexdigest()
    require(digest in PROFILES and PROFILES[digest].name == "705J140", "use original 705J140 main.bin")
    values = [(i * 17 + 11) % 256 for i in range(476)]
    packets = sweep_blocks(values, 5)
    want_sweep = bytes(min(160, max(0, v - 40)) for v in values[:475])
    cases = {}
    for first, second in ((True, True), (True, False), (False, True)):
        cpu = machine(main)
        cpu.mem_map(DMA & ~0xFFF, 0x1000)
        cpu.mem_write(0x20380BAC, b"\x01" * 4)
        cpu.mem_write(0x20499499, b"\x01")
        cpu.mem_write(0x204994CE, b"\x15")
        cpu.mem_write(0x203E1BB6, pack("<H", 200))
        observed = bytearray()
        for i, packet in enumerate(packets):
            audio = tuple((i * 8191 + j * 1949) % 65536 - 32768 if first else 0 for j in range(36))
            spectrum = unpack("<36I", packet if second else bytes(144))
            write_bank(cpu, i, audio, spectrum)
            cpu.mem_write(DMA, pack("<I", 0x81))  # Enabled, but no completed buffer.
            call(cpu, 0x200FFF4C)
            require(cpu.mem_read(RING + 0x240, 1)[0] == i, "advanced before completion")
            cpu.mem_write(DMA, pack("<I", 0x41 if i % 2 else 0xC1))
            call(cpu, 0x200FFF4C)
            require(cpu.mem_read(RING + 0x240, 1)[0] == i + 1, "write cursor did not advance")
            require(bytes(cpu.mem_read(0x20401D7C, 144)) == pack("<36I", *spectrum), "second slot changed")
            for reader in (0, 1):
                call(cpu, 0x200FF92C, SCRATCH, 0, reader)
                data = bytes(cpu.mem_read(SCRATCH, 72))
                require(data == pack("<36h", *audio), "first slot did not reach both readers")
            observed.extend(data)
        call(cpu, 0x2012038C)
        call(cpu, 0x2011FE38)
        sweep = bytes(cpu.mem_read(0x203E1BA4 + 20, 475))
        require(sweep == (want_sweep if second else bytes(475)), "first slot affected RF spectrum")
        cases[f"slot0_{int(first)}_slot1_{int(second)}"] = {
            "banks_used": 2, "blocks": len(packets), "samples": len(observed) // 2,
            "slot0_peak": max(map(abs, unpack(f"<{len(observed)//2}h", observed))),
            "pcm_sha256": sha256(observed).hexdigest(), "sweep_max": max(sweep),
            "sweep_sha256": sha256(sweep).hexdigest(),
        }
    return {"main_sha256": digest, "cases": cases, "scope_modes": scope_modes(main),
            "input": "synthetic DMA blocks; not board capture"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path, help="unmodified, unpacked original Japanese 1.40 main.bin")
    args = parser.parse_args()
    print(json.dumps(verify(args.main.read_bytes()), indent=2))
