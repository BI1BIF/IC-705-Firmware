"""Run small, original IC-705 ARM routines or trace reset to the first missing device."""

import argparse
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import struct

import unicorn as uc
from unicorn import arm_const as arm


BASE = 0x20005000
RAM = 0x20000000
RAM_BYTES = 0xA00000
SP = RAM + RAM_BYTES - 0x1000
STOP = SP + 0x100
SCRATCH = SP + 0x200
BOOT = 0x18000000
AXI_PAGE = 0xFCFE1000
AXI_REGS = {0xA04 + 4 * i: f"AXIBUSCTL{i}" for i in range(11)}


@dataclass(frozen=True)
class Profile:
    name: str
    language: int
    language_bytes: int
    row_hidden: int
    draw_row: int
    draw_text: int
    convert: int
    gps: int


PROFILES = {
    "d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9":
        Profile("705J140", 0x2009F520, 0x203EAE44, 0x2009FE30, 0x2014B548, 0x20142698, 0x20144CAC, 0x2021710C),
    "e2367bf67ec7969ef42cf74a4d0da22d3b75b825377c223ccc131f1ba217617f":
        Profile("705J132", 0x2009E02C, 0x203EADBC, 0x2009E920, 0x20147E2C, 0x2013EF7C, 0x20141590, 0x20212350),
}
BOOT_HASH = "8c55e7f49477985f994e79d83b111048ace533bfacce70a62ef80a6543d732db"


def machine(main=b"", bootstrap=b""):
    cpu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    cpu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    cpu.mem_map(RAM, RAM_BYTES)
    if main:
        cpu.mem_write(BASE, main)
    if bootstrap:
        cpu.mem_map(BOOT, len(bootstrap), uc.UC_PROT_READ | uc.UC_PROT_EXEC)
        cpu.mem_write(BOOT, bootstrap)
    return cpu


def call(cpu, entry, *args, instruction_limit=100_000, timeout_us=2_000_000, stack=SP):
    cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)  # ARM System mode; the guest has its own stack.
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, STOP)
    regs = (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)
    for reg, arg in zip(regs, args):
        cpu.reg_write(reg, arg)
    if len(args) > 4:
        cpu.mem_write(stack, struct.pack(f"<{len(args)-4}I", *args[4:]))
    cpu.emu_start(entry, STOP, timeout=timeout_us, count=instruction_limit)
    if cpu.reg_read(arm.UC_ARM_REG_PC) != STOP:
        raise ValueError(f"original function did not return: 0x{entry:08x}")
    return cpu.reg_read(arm.UC_ARM_REG_R0)


def original_menu(main, profile):
    cpu = machine(main)
    # Synthetic caller record; lookup, strings and the row's draw request come from the firmware.
    cpu.mem_write(SCRATCH + 12, struct.pack("<BxH", 2, 0xA7))
    requests = []

    def record_draw(_cpu, address, _size, _data):
        r0, r1, r2, r3, sp, lr = map(cpu.reg_read, (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
                                                  arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3,
                                                  arm.UC_ARM_REG_SP, arm.UC_ARM_REG_LR))
        style, _, _, xy = struct.unpack("<4I", cpu.mem_read(sp, 16))
        requests.append({"pc": hex(address), "caller": hex(lr - 4), "group": r0, "target": r1,
                         "text_address": r2, "text_bytes": r3, "style": style,
                         "local_xy": list(struct.unpack("<HH", cpu.mem_read(xy, 4)))})
        cpu.reg_write(arm.UC_ARM_REG_PC, lr)  # Observe the boundary; no renderer or pixels yet.

    cpu.hook_add(uc.UC_HOOK_CODE, record_draw, begin=profile.draw_text, end=profile.draw_text)
    rows = []
    for system, display in ((0, 0), (0, 1), (1, 0), (1, 1)):
        cpu.mem_write(profile.language_bytes, bytes((display, system)))
        effective = call(cpu, profile.language)
        hidden = call(cpu, profile.row_hidden, 0xA7)
        requests.clear()
        # Invoke the isolated row even when the original visibility predicate would hide it.
        call(cpu, profile.draw_row, SCRATCH, 0, effective, 0)
        if len(requests) != 1:
            raise ValueError("expected one original draw request for the isolated row")
        draw = requests[0]
        if (draw["group"], draw["style"], draw["local_xy"]) != (18, 1, [10, 23]):
            raise ValueError("unexpected original menu row draw parameters")
        text_addr, length = draw["text_address"], draw["text_bytes"]
        if not (1 <= length <= 32 and BASE <= text_addr <= BASE + len(main) - length):
            raise ValueError("label span is outside the original main image")
        raw = bytes(cpu.mem_read(text_addr, length))
        count = call(cpu, profile.convert, text_addr, length, SCRATCH + 0x100)
        if count > len(raw):
            raise ValueError("invalid original character count")
        value = bytes(cpu.mem_read(SCRATCH + 0x100, count * 2)).decode("utf-16le")
        expected = "\u8868\u793a\u8a00\u8a9e" if system and display else "Display Language"
        if effective != (system & display) or hidden != (1 - system) or value != expected:
            raise ValueError(f"unexpected language result: {system=}, {display=}, {value=!r}")
        draw["text_address"] = hex(text_addr)
        rows.append({"system": system, "display": display, "effective": effective, "hidden": bool(hidden),
                     "original_bytes": raw.hex(), "text": value, "draw_request": draw})
    return rows


def original_gps(main, profile):
    cpu = machine(main)
    distances = []
    for metres, valid, expected in ((500, 1, "500m"), (5000, 1, "5000m" if profile.name == "705J140" else "5.0km"),
                                   (12000, 1, "12.0km"), (0, 0, "-----km")):
        count = call(cpu, profile.gps, SCRATCH, metres * 10, valid, 0, 1, 1, 0)
        if not 1 <= count <= 7:
            raise ValueError("GPS formatter returned an unexpected text length")
        text = bytes(cpu.mem_read(SCRATCH, count)).decode("ascii")
        if text != expected:
            raise ValueError(f"unexpected GPS formatter output: {metres=}, {text=!r}")
        distances.append({"metres": metres, "valid": bool(valid), "text": text})
    return distances


def trace_reset(cpu, entry, model_axi=False):
    last = deque(maxlen=8)
    fault = {}
    mmio = []
    axi_values = {}
    count = 0

    def instruction(_cpu, address, _size, _data):
        nonlocal count
        count += 1
        last.append(hex(address))

    def record_fault(kind, address, size, value):
        fault.update(kind=kind, address=hex(address), bytes=size,
                     pc=hex(cpu.reg_read(arm.UC_ARM_REG_PC)))
        if kind in ("write", "write-protected"):
            fault["value"] = hex(value)

    def unmapped(_cpu, access, address, size, value, _data):
        kind = {uc.UC_MEM_READ_UNMAPPED: "read", uc.UC_MEM_WRITE_UNMAPPED: "write",
                uc.UC_MEM_FETCH_UNMAPPED: "fetch", uc.UC_MEM_WRITE_PROT: "write-protected"}.get(access, access)
        record_fault(kind, address, size, value)
        return False  # Stop; do not guess any register value.

    def axi_access(kind, offset, size, value=0):
        # Only write/read-back; no defaults for uninitialized registers and no hardware effects.
        if (size != 4 or offset not in AXI_REGS or len(mmio) >= 64
                or (kind == "read" and offset not in axi_values)):
            record_fault(kind, AXI_PAGE + offset, size, value)
            cpu.emu_stop()
            return 0
        if kind == "write":
            axi_values[offset] = value
        value = axi_values[offset]
        mmio.append({"kind": kind, "register": AXI_REGS[offset], "address": hex(AXI_PAGE + offset),
                     "pc": hex(cpu.reg_read(arm.UC_ARM_REG_PC)), "value": hex(value)})
        return value

    if model_axi:
        cpu.mmio_map(AXI_PAGE, 0x1000, lambda _, offset, size, data: axi_access("read", offset, size), None,
                     lambda _, offset, size, value, data: axi_access("write", offset, size, value), None)
    cpu.hook_add(uc.UC_HOOK_CODE, instruction)
    cpu.hook_add(uc.UC_HOOK_MEM_INVALID, unmapped)
    cpu.reg_write(arm.UC_ARM_REG_CPSR, 0xD3)  # SVC, IRQ/FIQ masked; no board state synthesized.
    try:
        cpu.emu_start(entry, 0, timeout=2_000_000, count=100_000)
        reason = "unsupported-mmio" if fault else "instruction-or-time-limit"
    except uc.UcError as exc:
        reason = str(exc)
    return {"entry": hex(entry), "stop": reason, "fault": fault, "instructions": count,
            "axi_accesses": mmio, "last_pcs": list(last)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_dir", type=Path, help="local decode_705_main output for J132 or J140")
    args = parser.parse_args()
    image = (args.image_dir / "main.bin").read_bytes()
    bootstrap = (args.image_dir / "bootstrap.bin").read_bytes()
    digest = sha256(image).hexdigest()
    if digest not in PROFILES or sha256(bootstrap).hexdigest() != BOOT_HASH:
        parser.error("unrecognized original J132/J140 images")
    profile = PROFILES[digest]
    print(json.dumps({
        "version": profile.name, "main_sha256": digest, "bootstrap_sha256": BOOT_HASH,
        "engine": f"Unicorn {uc.__version__} Cortex-A9",
        "menu": original_menu(image, profile), "gps": original_gps(image, profile),
        "reset": {"from_flash": trace_reset(machine(bootstrap=bootstrap), BOOT),
                  "post_unpack_main": trace_reset(machine(main=image), BASE),
                  "post_unpack_with_axi": trace_reset(machine(main=image), BASE, model_axi=True)},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
