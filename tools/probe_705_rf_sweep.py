"""Verify the original J140 spectrum receiver with synthetic blocks, offline."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack

from tools.emulate_705 import PROFILES, SCRATCH, call, machine


def sweep_blocks(values, tag):
    words = [0x80000000 | a << 8 | b << 17 for a, b in zip(values[::2], values[1::2], strict=True)]
    blocks = [[0x40000000 | tag << 16 | 1 << 8, *words[:35]]]
    blocks += [words[i:i + 36] for i in range(35, len(words), 36)]
    return [pack("<36I", *block, *([0] * (36 - len(block)))) for block in blocks]


def verify(main):
    digest = sha256(main).hexdigest()
    if digest not in PROFILES or PROFILES[digest].name != "705J140":
        raise ValueError("use the unmodified 705J140 main.bin")

    spectrum, config, flags = 0x203E1BA4, 0x20499498, 0x20380BAC
    values = [(i * 17 + 11) % 256 for i in range(476)]
    expected = bytes(min(160, max(0, v - 40)) for v in values[:475])
    cases = {}
    for name, tag, count in (("matching", 5, 7), ("wrong_tag", 4, 7), ("incomplete", 5, 6)):
        cpu = machine(main)
        cpu.mem_write(flags, b"\x01\x01\x01\x01")
        cpu.mem_write(config + 1, b"\x01")  # Spectrum consumer enabled, no bin shift.
        cpu.mem_write(config + 54, b"\x15")
        cpu.mem_write(0x203E1B30 + 0x86, pack("<H", 200))
        for block in sweep_blocks(values, tag)[:count]:
            cpu.mem_write(SCRATCH, block)
            call(cpu, 0x201203F4, SCRATCH)
        state = bytes(cpu.mem_read(flags, 7))
        call(cpu, 0x2012038C)
        raw = bytes(cpu.mem_read(config - 476, 475))
        # On valid input, use the original publisher. The two negative controls
        # also call it with no completed frame, so it must leave its output empty.
        call(cpu, 0x2011FE38)
        published = bytes(cpu.mem_read(spectrum + 20, 475))
        want = expected if name == "matching" else bytes(475)
        if raw != want or published != want:
            raise ValueError(f"unexpected stock sweep: {name}")
        cases[name] = {"blocks": count, "pre_conversion_state": state.hex(),
                       "range": [min(published), max(published)],
                       "published_sha256": sha256(published).hexdigest()}
    return {"main_sha256": digest, "points": 475, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.main.read_bytes()), indent=2))
