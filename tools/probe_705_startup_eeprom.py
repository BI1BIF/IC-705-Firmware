"""Replay stock J140 EEPROM reads and their startup decision on a PC."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tools.emulate_705 import BASE, SCRATCH, arm, call, machine, uc
from tools.render_705_display import load
from tools.render_705_stock_row import require


GPIO, INPUT = 0xFCFE3000, 0x204
READ, SEND = 0x2005E3CC, 0x2005D788
LOAD_RECORD, DESTINATION = 0x2007BA7C, 0x203E2174
TAG_BYTES, DEFAULT_BYTES = 0x2007B598, 0x202E2869


def probe(main, entry, reads, *args):
    cpu = machine(main)
    registers, requested, sent, received = {}, [], [], []
    wave = iter(())

    def outgoing(c, *_):
        sent.append(c.reg_read(arm.UC_ARM_REG_R0) & 255)

    def request(c, *_):
        nonlocal wave
        require(next(wave, None) is None, "guest did not read the entire previous response")
        address, size = (c.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R2))
        require(len(requested) < len(reads), "unexpected read request")
        expected, data = reads[len(requested)]
        require((address, size) == (expected, len(data)),
                f"read {address:#x}/{size}, expected {expected:#x}/{len(data)}")
        requested.append([hex(address), size])
        wave = iter((byte >> bit) & 1 for byte in data for bit in range(7, -1, -1))
        received.append([])

    def gpio_read(c, offset, size, _):
        pc = c.reg_read(arm.UC_ARM_REG_PC)
        if offset == INPUT and size == 2:
            if pc == 0x2005E2EC:
                return 0  # Simulated EEPROM ACK.
            require(pc == 0x2005D720, f"unexpected EEPROM data read at {pc:#x}")
            bit = next(wave, None)
            require(bit is not None, "guest read more data bits than provided")
            received[-1].append(bit)
            return bit << 1
        return registers.get(offset, 0)

    def gpio_write(_c, offset, _size, value, _):
        registers[offset] = value

    cpu.mmio_map(GPIO, 4096, gpio_read, None, gpio_write, None)
    cpu.mem_map(0xFCFE7000, 4096)
    for address, hook in ((READ, request), (SEND, outgoing)):
        cpu.hook_add(uc.UC_HOOK_CODE, hook, begin=address, end=address)
    call(cpu, entry, *args, instruction_limit=2_000_000)
    expected_bytes = bytearray()
    for address, _ in reads:
        select = 0xA0 | (address >> 15 & 6)
        expected_bytes.extend((select, address >> 8 & 255, address & 255, select | 1))
    require(bytes(sent) == expected_bytes and len(requested) == len(reads) and next(wave, None) is None,
            f"unexpected read-only EEPROM transfer: {bytes(sent).hex()}")
    require([len(bits) for bits in received] == [8*len(data) for _, data in reads], "missed data bits")
    return cpu, dict(requests=requested, guest_tx_bytes=bytes(sent).hex(), data_bits=[len(bits) for bits in received])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    dat = args.dat.read_bytes()
    program, _, _, digest, _ = load(dat)
    tag = program[TAG_BYTES-BASE:TAG_BYTES-BASE+16]
    default = program[DEFAULT_BYTES-BASE:DEFAULT_BYTES-BASE+30]
    data = bytes((i*29+0xA5) & 255 for i in range(30))
    require(data != default, "fixture must differ from stock defaults")
    control = bytes.fromhex("96e8017c2df314ab40c5d7698a30be52")

    cpu, direct = probe(program, READ, [(0x3FE40, control)], 0x3FE40, SCRATCH, len(control))
    require(bytes(cpu.mem_read(SCRATCH, len(control))) == control, "original reader changed the bits")
    cpu, boundary = probe(program, 0x2005E4C8, [(0x1FFBC, control[:4]), (0x3FF80, control[4:8])],
                          0x3FF3C, SCRATCH, 8)
    require(bytes(cpu.mem_read(SCRATCH, 8)) == control[:8], "cross-device read changed the bits")
    cases = {}
    for label, marker, record, expected in (
        ("stock-default", b"\xff"*16, [], default),
        ("eeprom-record", tag, [(0x3FF90, data)], data),
    ):
        cpu, detail = probe(program, LOAD_RECORD, [(0x3FFB0, marker), *record])
        copied = bytes(cpu.mem_read(DESTINATION, len(expected)))
        require(copied == expected, f"stock startup did not select {label}")
        detail["output_sha256"] = sha256(copied).hexdigest()
        cases[label] = detail
    require(args.dat.read_bytes() == dat, "official DAT changed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(stock_main_sha256=digest, gpio_read=direct, cross_device_read=boundary, startup_cases=cases)
    args.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(f"J140 stock EEPROM reader and startup record/default selection matched: {args.output}")


if __name__ == "__main__":
    main()
