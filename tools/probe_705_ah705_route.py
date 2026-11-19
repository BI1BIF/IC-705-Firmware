"""Replay the original J140 AH-705 SD route up to, but not including, file open."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack, unpack_from

from unicorn import arm_const as arm

from tools.decode_705_main import J140_MAIN_SHA
from tools.emulate_705 import BASE, SP, call, machine
from tools.probe_705_resource_paths import LAYOUTS, bitmap, opening_queue, require


def probe(main):
    require(sha256(main).hexdigest() == J140_MAIN_SHA, "expected original 705J140 main.bin")
    title, _, entry = unpack_from("<3I", main, 0x202E5980 - BASE)
    label = main[title - BASE:].split(b"\0", 1)[0]
    require(label == b"Firmware Update (AH-705)", "unexpected stock menu label")

    ui_mailbox = 0x203807F0
    file_mailbox = 0x203802BC
    cpu = machine(main)
    empty_list = call(cpu, entry)
    require((empty_list, bytes(cpu.mem_read(ui_mailbox, 2))) == (2, b"\0\0"),
            "empty list unexpectedly queued a file request")

    # Seed a filename record only. No SD storage, update bytes, or tuner is mapped.
    cpu = machine(main)
    fixture = b"PROBE.DAT"
    row = 0x2039F8C0
    cpu.mem_write(row, fixture)
    cpu.mem_write(row + 31, bytes([len(fixture)]))
    cpu.mem_write(ui_mailbox + 0x30, pack("<I", 1))
    require(call(cpu, entry) == 1, "original file selection did not return ready")
    ui_command, drive = cpu.mem_read(ui_mailbox, 2)
    require((ui_command, drive) == (0x48, 0), "unexpected UI request")

    cpu.reg_write(arm.UC_ARM_REG_SP, SP)
    ui_dispatch, wake = 0x200F96C4, 0x202D47B4
    cpu.emu_start(ui_dispatch, wake, count=500)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == wake, "original file wake not reached")
    command, = unpack("<I", cpu.mem_read(file_mailbox + 0x60, 4))
    require(command == 0x3B, "unexpected SD command")

    cpu.reg_write(arm.UC_ARM_REG_R4, file_mailbox)
    sd_dispatch, file_open = 0x20071C8C, 0x201F2864
    cpu.emu_start(sd_dispatch, file_open, count=40)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == file_open, "original file-open boundary not reached")
    require(cpu.reg_read(arm.UC_ARM_REG_LR) == 0x2006F454, "unexpected file-open caller")
    path_address = cpu.reg_read(arm.UC_ARM_REG_R0)
    file_mode = cpu.reg_read(arm.UC_ARM_REG_R1)
    path = bytes(cpu.mem_read(path_address, 46)).split(b"\0", 1)[0]
    require((path, file_mode) == (b"C:\\IC-705\\AH-705\\" + fixture, 0), "unexpected file-open args")

    layout = LAYOUTS["705J140"]
    return {
        "main_sha256": J140_MAIN_SHA,
        "stock_label": label.decode(), "stock_callback": hex(entry),
        "negative_empty_list": {"return": empty_list, "queued": False},
        "synthetic_filename_only": fixture.decode(),
        "ui_dispatch": hex(ui_dispatch), "ui_command": hex(ui_command),
        "sd_dispatch": hex(sd_dispatch), "sd_command": hex(command), "sd_worker": "0x2006f434",
        "stopped_before_open": {"entry": hex(file_open), "callsite": "0x2006f450",
                                "path": path.decode(), "mode": file_mode},
        "stock_bmp_positive_control": {"queue": opening_queue(main, layout), "parser": bitmap(main, layout)},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("j140_main", type=Path)
    print(json.dumps(probe(parser.parse_args().j140_main.read_bytes()), indent=2))
