"""Replay selected stock resource paths on verified Japanese main CPU images.

Run: python -m tools.probe_705_resource_paths MAIN_132 MAIN_140
Requires Unicorn. Inputs are read-only; fixtures and device state live in RAM.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack

from unicorn import arm_const as arm

from tools.emulate_705 import PROFILES, SCRATCH, call, machine


LAYOUTS = {
    "705J132": {
        "bitmap_check": 0x2012DED0, "bitmap_convert": 0x2012E164, "pixels": 0x206C3C40,
        "opening_path": 0x200F5BF8, "opening_queue": 0x20067D78, "file_wake": 0x202E8874,
        "file_dispatch": 0x20070A74, "opening_worker": 0x20068230, "path_buffer": 0x203D87C4,
        "font_init": 0x20101364, "font_table": 0x20380898,
        "rtty_init": 0x2003CDE8, "rtty_consume": 0x2003B1D4, "rtty_copy": 0x20095764,
        "rtty_queue": 0x203E1AA8, "rtty_decode": 0x20115408, "rtty_symbol": 0x204986CB,
        "rtty_poll": 0x20115218, "rtty_mode": 0x20380B14,
        "ring": 0x2038AD54, "snapshot": 0x204BD1A0, "rtty_width": 0x203E230E,
        "rtty_view": 0x2003C90C,
    },
    "705J140": {
        "bitmap_check": 0x20131538, "bitmap_convert": 0x201317CC, "pixels": 0x206C5E40,
        "opening_path": 0x200F9188, "opening_queue": 0x20068F90, "file_wake": 0x202D47B4,
        "file_dispatch": 0x20071C8C, "opening_worker": 0x20069448, "path_buffer": 0x203D8824,
        "font_init": 0x20104984, "font_table": 0x2038089C,
        "rtty_init": 0x2003DFD4, "rtty_consume": 0x2003C3C0, "rtty_copy": 0x20096C14,
        "rtty_queue": 0x203E1B30, "rtty_decode": 0x20118A44, "rtty_symbol": 0x2049876B,
        "rtty_poll": 0x20118854, "rtty_mode": 0x20380B1C,
        "ring": 0x2038ADA8, "snapshot": 0x204BD240, "rtty_width": 0x203E2396,
        "rtty_view": 0x2003DAF8,
    },
}

BITMAP_WORK = 0x209652C0
FLASH_RECORDS = (0x18C00000, 0x18FA2588)
FILE_STATE = 0x203802BC
GPIO_PPR0 = 0xFCFE3200


def require(condition, message):
    if not condition:
        raise ValueError(message)


def opening_queue(main, layout):
    cpu = machine(main)
    source = layout["opening_path"]
    # Stop at the RTOS boundary, after the original wrapper enqueues the request.
    cpu.mem_write(FILE_STATE + 0x1A, b"\xff")
    cpu.reg_write(arm.UC_ARM_REG_SP, SCRATCH)
    cpu.reg_write(arm.UC_ARM_REG_R0, source)
    cpu.emu_start(layout["opening_queue"], layout["file_wake"], count=256)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == layout["file_wake"], "file wake not reached")
    expected = b"C:\\IC-705\\Opening\\opening.bmp"
    require(bytes(cpu.mem_read(layout["path_buffer"], len(expected) + 1)) == expected + b"\0",
            "unexpected opening file path")
    command, = unpack("<I", cpu.mem_read(FILE_STATE + 0x60, 4))
    mode = cpu.mem_read(FILE_STATE + 0x1A, 1)[0]
    require((command, mode) == (0x37, 0), "unexpected opening file command")
    # Advance the original command dispatcher to the worker entry.
    cpu.reg_write(arm.UC_ARM_REG_R4, FILE_STATE)
    cpu.emu_start(layout["file_dispatch"], layout["opening_worker"], count=16)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == layout["opening_worker"], "opening worker not reached")
    return {"path": expected.decode("ascii"), "command": hex(command), "mode": mode,
            "worker": hex(layout["opening_worker"])}


def bitmap(main, layout):
    cpu = machine(main)
    pixels = 480 * 272
    image_bytes = pixels * 3
    # BGR red, green, blue, white; a repeating row with no padding at width 480.
    tile = bytes.fromhex("0000ff 00ff00 ff0000 ffffff")
    dib = pack("<IiiHHIIiiII", 40, 480, 272, 1, 24, 0, image_bytes, 0, 0, 0, 0)
    header = pack("<2sIHHI", b"BM", image_bytes + 54, 0, 0, 54) + dib
    cpu.mem_write(BITMAP_WORK, header + tile * (pixels // 4))
    entry = layout["bitmap_check"]
    good = call(cpu, entry, BITMAP_WORK)
    cpu.mem_write(BITMAP_WORK, b"ZZ")
    bad_magic = call(cpu, entry, BITMAP_WORK)
    cpu.mem_write(BITMAP_WORK, header)
    cpu.mem_write(BITMAP_WORK + 18, pack("<i", 479))
    bad_width = call(cpu, entry, BITMAP_WORK)
    require((good, bad_magic, bad_width) == (0, 1, 1), "unexpected BMP parser results")
    cpu.mem_write(BITMAP_WORK, header)
    call(cpu, layout["bitmap_convert"], BITMAP_WORK, instruction_limit=4_000_000, timeout_us=5_000_000)
    rendered = bytes(cpu.mem_read(layout["pixels"], pixels * 2))
    rgb565 = (0xF800, 0x07E0, 0x001F, 0xFFFF)
    require(rendered == pack("<4H", *rgb565) * (pixels // 4), "unexpected BMP pixel output")
    return {"parser_result": {"valid": good, "bad_magic": bad_magic, "width_479": bad_width},
            "output_bytes": len(rendered), "rgb565_tile": [hex(p) for p in rgb565],
            "output_sha256": sha256(rendered).hexdigest()}


def font(main, layout):
    cpu = machine(main)
    # Synthetic, distinct length words verify the data flow without loading font files.
    lengths = (0x123456, 0x3456)
    for address, length in zip(FLASH_RECORDS, lengths):
        cpu.mem_map(address & ~0xFFF, 0x1000)
        cpu.mem_write(address, pack("<I", length))
    start = layout["font_init"]
    end = start + 40
    cpu.reg_write(arm.UC_ARM_REG_R4, layout["font_table"])
    cpu.emu_start(start, end, count=10)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == end, "font initialization did not complete")
    words = unpack("<4I", cpu.mem_read(layout["font_table"] + 4, 16))
    expected = (FLASH_RECORDS[0] + 4, lengths[0], FLASH_RECORDS[1] + 4, lengths[1])
    require(words == expected, "unexpected font initialization table")
    return {"table": hex(layout["font_table"]), "pointer_length_words": [hex(word) for word in words],
            "lengths_are_synthetic": True}


def rtty_frame(cpu, layout, symbol, stop=1):
    # 22 samples per bit in the stock state machine. This is fixture time;
    # the physical interrupt schedule is not simulated.
    levels = [(1, 44), (0, 22)]
    levels += [((symbol >> i) & 1, 22) for i in range(5)]
    levels.append((stop, 33))
    for level, ticks in levels:
        cpu.mem_write(GPIO_PPR0, pack("<H", level << 5))
        for _ in range(ticks):
            call(cpu, layout["rtty_poll"])
    mailbox = list(cpu.mem_read(layout["rtty_symbol"], 2))
    require(mailbox == [symbol, 1 if stop else 3], "unexpected RTTY symbol or stop flag")
    call(cpu, layout["rtty_decode"])
    return mailbox


def rtty(main, layout):
    cpu = machine(main)
    call(cpu, layout["rtty_init"])
    message = b"CQ TEST"
    dest = layout["snapshot"]
    # The line fit calculation requires a nonzero UI width. Font metrics stay at
    # their zero-initialized fixture values; this checks byte/attribute flow.
    cpu.mem_write(layout["rtty_width"], pack("<H", 460))
    call(cpu, layout["rtty_view"], layout["ring"])
    call(cpu, layout["rtty_copy"], 0)
    before = bytes(cpu.mem_read(dest, 8 * 83))
    # Original code receives only simulated GPIO levels and initial mode state.
    # The other transport and logging state stays off.
    cpu.mem_map(GPIO_PPR0 & ~0xFFF, 0x1000)
    cpu.mem_write(layout["rtty_mode"], b"\x02")
    figures_then_letters = bytes([27, 1, 31])  # figures "3", then letters
    letters = bytes([14, 23, 4, 16, 1, 5, 16])  # "CQ TEST" in letters mode
    expected = b"3" + message
    for symbol in figures_then_letters + letters:
        rtty_frame(cpu, layout, symbol)
    bad_stop = rtty_frame(cpu, layout, 23, stop=0)
    queue = layout["rtty_queue"]
    require(bytes(cpu.mem_read(queue + 0x30E, len(expected))) == expected
            and cpu.mem_read(queue + 0x31E, 1)[0] == len(expected),
            "original symbol converter did not populate the byte queue")
    cpu.mem_write(layout["ring"] - 0x18, b"\x01")
    call(cpu, layout["rtty_consume"], 0)
    require(cpu.mem_read(0x20380120, 1)[0] == len(expected), "RTTY queue did not advance")
    call(cpu, layout["rtty_copy"], 0)
    body = bytes(cpu.mem_read(dest, len(before)))
    require(expected not in before and body.count(expected) == 1, "RTTY snapshot did not gain the text")
    row, column = divmod(body.index(expected), 83)
    attrs = bytes(cpu.mem_read(dest + 0x298 + 42 * row, 42))
    nibbles = [(attrs[i // 2] >> (4 * (i % 2))) & 15 for i in range(column, column + len(expected))]
    require(nibbles == [2] * len(expected), "RTTY snapshot did not gain the text attributes")
    return {"text": expected.decode("ascii"), "input_symbols": list(figures_then_letters + letters),
            "input_gpio": hex(GPIO_PPR0), "input_bit": 5, "bad_stop_mailbox": bad_stop,
            "consumed_bytes": len(expected), "row": row, "column": column,
            "attributes": nibbles, "snapshot": hex(dest)}


def probe(path):
    main = path.read_bytes()
    digest = sha256(main).hexdigest()
    profile = PROFILES.get(digest)
    require(profile is not None, f"unrecognized main CPU image: {path} ({digest})")
    layout = LAYOUTS[profile.name]
    return {"sample": profile.name, "main_sha256": digest, "opening_queue": opening_queue(main, layout),
            "bmp": bitmap(main, layout), "font_init": font(main, layout), "rtty": rtty(main, layout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="decoded main.bin images")
    args = parser.parse_args()
    print(json.dumps([probe(path) for path in args.images], indent=2))


if __name__ == "__main__":
    main()
