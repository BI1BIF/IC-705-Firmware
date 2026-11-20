"""Replay MENU > PICTURE > DV/SSTV and a completed Robot 36 frame on J140."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
from unittest.mock import patch

from PIL import Image
from tools import render_705_stock_row as renderer
from tools.build_705_cw_sim import PICKER_EMPTY_ROW, PICKER_REFERENCES, PICKER_TABLE, picker_table
from tools.decode_705_main import J140_MAIN_SHA
from tools.emulate_705 import call
from tools.render_705_display import PAGE, load
from tools.render_705_stock_row import png, require
from tools.replay_705_settings import FRAME_DRAW, UPDATE, SettingsGuest
from tools.sstv_robot36 import wav_pairs

# Emulator-only memory for an independent selector. No allocation or layout for installation.
LAB = 0x21000000
SELECT, DV, SSTV, EMPTY = (LAB + n for n in (0x40, 0x80, 0xC0, 0x100))
CHOICE, TABLE = LAB + 0x180, LAB + 0x200
PICTURE_CALL = 0x2008744C
OPEN_APP, OPEN_PAGE = 0x200801E4, 0x200F1600
RX_IMAGE = 0x20625D84
WIDTH, HEIGHT = 320, 240


def branch(site, target, opcode=0xEA000000):
    delta = target - site - 8
    require(delta % 4 == 0 and -(1 << 25) <= delta < (1 << 25), "invalid A32 branch")
    return opcode | ((delta >> 2) & 0xFFFFFF)


def mov_half(reg, value, *, top=False):
    opcode = 0xE3400000 if top else 0xE3000000
    return opcode | ((value & 0xF000) << 4) | (reg << 12) | (value & 0xFFF)


def address(reg, value):
    return [mov_half(reg, value & 0xFFFF), mov_half(reg, value >> 16, top=True)]


def install_guest_picker(guest, main):
    """Small A32 callbacks use the same stock deferred selection protocol as KEYER."""
    cpu = guest.cpu
    require(sha256(main).hexdigest() == J140_MAIN_SHA, "stock J140 only")
    cpu.mem_map(LAB, 0x10000)

    def replace(site, old, new):
        require(bytes(cpu.mem_read(site, 4)) == pack("<I", old), f"unexpected code at {site:#x}")
        cpu.mem_write(site, pack("<I", new))

    def routine(start, words):
        cpu.mem_write(start, pack(f"<{len(words)}I", *words))

    push, pop_pc, pop_lr = 0xE92D4010, 0xE8BD8010, 0xE8BD4010  # {r4,lr} stack pair
    bl = 0xEB000000
    routine(LAB, [
        push, 0xE3A00000, branch(LAB+8, 0x200EFE64, bl),  # dismiss the MENU grid
        *address(2, 0x203E1B1A), mov_half(1, 0x0202), 0xE1C210B0,  # close policy
        mov_half(0, 277), mov_half(1, 0xFFFF), pop_lr, branch(LAB+40, 0x200CD628),
    ])
    routine(SELECT, [
        push, *address(1, CHOICE), 0xE5D11000, 0xE3510000,  # ldrb r1,[r1]; cmp r1,#0
        *address(0, DV), 0x12800040,  # addne r0,r0,#0x40 selects SSTV
        branch(SELECT+32, 0x200CD7DC, bl), 0xE3A00002, pop_pc,
    ])
    for start in (DV, SSTV):
        routine(start, [push, branch(start+4, 0x200CD828, bl), mov_half(0, 21),
                        pop_lr, branch(start+16, OPEN_APP)])
    routine(EMPTY, [mov_half(0, 0xFFFF), 0xE1550000,  # compare row ID to blank marker
                    branch(EMPTY+8, 0x200CE238, 0x0A000000), 0xE3550047,
                    branch(EMPTY+16, 0x200CDD0C)])
    table = picker_table(main, TABLE, {"cw_picker_select": SELECT, "cw_picker_choice": CHOICE},
                         labels=(b"PICTURE", b"DV", b"SSTV"))
    cpu.mem_write(TABLE, table)
    for site in PICKER_REFERENCES:
        replace(site, PICKER_TABLE, TABLE)
    replace(0x200CDCB0, 0xE5D52000, 0xE1D520B0)  # native row ID is now a halfword
    replace(PICKER_EMPTY_ROW, 0xE3550047, branch(PICKER_EMPTY_ROW, EMPTY))
    replace(PICTURE_CALL, branch(PICTURE_CALL, OPEN_APP, bl), branch(PICTURE_CALL, LAB, bl))


def frame(guest):
    guest.surface.events.clear()
    guest.surface.pixel_writes.clear()
    call(guest.cpu, guest.rom(FRAME_DRAW), instruction_limit=12_000_000, timeout_us=10_000_000)
    surface = guest.surface
    surface.select_target()
    labels = ["".join(chr(g["key"]) for g in event["glyphs"]).strip() for event in surface.events]
    return labels, png(surface.width, surface.height, surface.pixels)


def tick(guest):
    call(guest.cpu, guest.rom(UPDATE), instruction_limit=2_000_000)


def enter(guest):
    guest.press_menu()
    tick(guest)
    require(guest.click(274, 251) == 0x1BB, "MENU page 2")
    tick(guest)
    require(guest.click(52, 175) == 0x1B5, "PICTURE touch")
    tick(guest)


def run(images, input_file, out):
    out.mkdir(parents=True, exist_ok=True)
    report = {"stock_main_sha256": J140_MAIN_SHA, "source_sha256": sha256(input_file.read_bytes()).hexdigest()}
    # The default PC font allocator overlaps the radio's original Picture buffers.
    with patch.object(renderer, "HEAP_START", 0x20700000):
        for route in ("stock", "DV", "SSTV", "cancel"):
            g = SettingsGuest(images, front_panel=True)
            g.cpu.mem_write(g.language_address, bytes(2))
            if route != "stock":
                install_guest_picker(g, images[0])
            enter(g)
            labels, screen = frame(g)
            if route != "stock":
                require("DV" in labels and "SSTV" in labels, f"missing chooser: {labels}")
                (out/"chooser.png").write_bytes(screen)
                if route == "cancel":
                    g.press_exit()
                else:
                    g.click(115, 52 if route == "DV" else 116)
                tick(g)
                labels, screen = frame(g)
            report[route] = {"menu": g.state()["menu"], "labels": labels, "frame_sha256": sha256(screen).hexdigest()}
            if route == "cancel":
                require("SSTV" not in labels and g.state()["menu"] == 0, "EXIT failed")
            elif route in ("stock","DV"):
                require(g.state()["menu"] == 21 and "TX ALL" in labels, f"unexpected DV page: {labels}")
                if route == "DV":
                    require(report["DV"] == report["stock"], "DV differs from the unmodified control")
                    (out/"dv.png").write_bytes(screen)
                    require(g.click(230, 193) == 0x171, "TX thumbnail touch")
                    tick(g)
                    tx_labels, _ = frame(g)
                    require("No SD Card is found." in tx_labels, "missing stock SD message")
                    report["tx_picker_no_card"] = {"menu": g.state()["menu"], "message": tx_labels[-1]}
            else:
                require(g.state()["menu"] == 21 and "PICTURE" in labels, "SSTV must open the half panel")
                require(g.click(60,193) == 0x170, "RX thumbnail touch")
                tick(g)
                labels, _ = frame(g)
                require(g.state()["menu"] == 274 and "RX PICTURE" in labels, f"unexpected RX page: {labels}")
                g.cpu.mem_write(RX_IMAGE, bytes(WIDTH*HEIGHT*2))
                state = PAGE+348
                g.cpu.mem_write(state+3, bytes([1]))  # image available
                g.cpu.mem_write(state+53, bytes([0]))  # hide DV tile marker
                g.cpu.mem_write(state+57, bytes([0]))  # hide DV percentage
                report["rgb565"] = receive_frame(g, input_file, out)
                g.press_exit()
                tick(g)
                require(g.state()["menu"] == 21, "RX detail EXIT did not return to PICTURE")
                g.press_exit()
                tick(g)
                require(g.state()["menu"] == 0, f"RX EXIT: {g.state()}")
                report["rx_exit_menu"] = g.state()["menu"]
    (out/"evidence.json").write_text(json.dumps(report, indent=2),encoding="utf-8")
    return report


def receive_frame(guest, wav, out):
    reference = bytearray(WIDTH * HEIGHT * 3)
    checkpoints = []
    count = 0
    for y, rgb in wav_pairs(wav):
        require(y == count, "decoder skipped rows")
        words = [((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                 for r, g, b in zip(rgb[::3], rgb[1::3], rgb[2::3])]
        guest.cpu.mem_write(RX_IMAGE + y*WIDTH*2, pack(f"<{len(words)}H", *words))
        count += 2
        reference[y*WIDTH*3:count*WIDTH*3] = bytes(channel for word in words for channel in (
            ((word >> 11)*255+15)//31, (((word >> 5)&63)*255+31)//63, ((word&31)*255+15)//31))
        if count % 60:
            continue
        # The replay supplies the repaint request normally owned by the UI task.
        guest.cpu.mem_write(0x20380C98, bytes([1]))
        _, screen = frame(guest)
        surface = guest.surface
        pixels = Image.frombytes("RGBA", (480,272), bytes(surface.pixels))
        region = pixels.crop((4,28,324,268)).convert("RGB").tobytes()
        require(region == reference, f"RGB565 viewport differs after {count} rows")
        name = "sstv-rx.png" if count == HEIGHT else f"sstv-rx-{count}.png"
        (out/name).write_bytes(screen)
        checkpoints.append({"rows": count, "frame_sha256": sha256(screen).hexdigest()})
    require(count == HEIGHT, f"incomplete Robot 36 image: {count} rows")
    return {"checkpoints": checkpoints, "pixels_checked_per_frame": WIDTH*HEIGHT,
            "top_left": [4,28], "writes": guest.surface.pixel_writes.copy()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path)
    parser.add_argument("wav", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(load(args.firmware.read_bytes()), args.wav, args.output), indent=2))
