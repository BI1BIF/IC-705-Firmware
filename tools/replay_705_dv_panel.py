"""Replay the J140 DV receive strip and D-PRS position window on the stock ARM panel."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack

from tools.emulate_705 import call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.render_705_display import load
from tools.replay_705_gps_inputs import GPS_INIT, GPS_MODE, BYTE_RX, RMC, nmea
from tools.replay_705_settings import KEY_EVENT, KEY_SCAN, TOUCH_RECT
from tools.virtual_705_panel import start


PREFERENCES = 0x203EAA49
DV_STRIP = 0x20393020
RX_POSITION = 0x205DDDC8
LIVE_WINDOW, DRAW_WINDOW, WINDOW_AGE = 0x203807DD, 0x204BD0F4, 0x203808FA
RX_TASK, GPS_REQUEST, GPS_WORK = 0x20048778, 0x200746BC, 0x20073F40
OPEN, CLOSE = 0x200F2030, 0x200EFE64
REOPEN, PREPARE, DRAW_POSITION, DRAW_STRIP = 0x200801C0, 0x2004944C, 0x2018842C, 0x20162F50
CALL, MESSAGE = b"JA1ABC", b"STOCK PANEL REPLAY"


def attach_position_graphics(guest):
    """Model the solid RGBA paint and quarter-turn used by this fixture's compass mask."""
    cpu, surface = guest.cpu, guest.surface
    rotation = 0
    angles = []

    def bind(entry, handler):
        entry = guest.rom(entry)
        if entry not in surface.handlers:
            cpu.hook_add(uc.UC_HOOK_CODE, surface.dispatch, begin=entry, end=entry)
        surface.handlers[entry] = handler

    def paint_color():
        handle, parameter, count, pointer = surface.args(4)
        assert (parameter, count) == (0x1A01, 4)
        surface.colors[handle] = bytes(round(255 * min(1., max(0., v)))
                                       for v in surface.read(pointer, 4, "f"))
        for mode, current in surface.bound_handles.items():
            if current == handle:
                surface.bound[mode] = surface.colors[handle]

    def reset(handler):
        nonlocal rotation
        if surface.matrix_mode == 0x1401:
            rotation = 0
        handler()

    def rotate():
        nonlocal rotation
        angle = surface.floats()[0]
        assert surface.matrix_mode == 0x1401 and angle in (90., 180., 270.) and not rotation
        rotation = int(angle)
        angles.append(angle)

    def translate():
        if not rotation or surface.matrix_mode != 0x1401:
            surface.translate()
            return
        x, y = surface.floats()
        sx, sy, tx, ty = surface.matrix()
        dx, dy = {90: (-y, x), 180: (-x, -y), 270: (y, -x)}[rotation]
        surface.matrices[0x1401] = (sx, sy, tx + sx*dx, ty + sy*dy)

    def draw_image():
        if not rotation:
            surface.draw_image()
            return
        handle, = surface.args(1)
        assert surface.matrix_mode == 0x1401 and handle in surface.alpha_images
        original = surface.images[handle]
        width, height, (ptr, stride, mask) = original
        assert stride == width
        sx, sy, tx, ty = original_matrix = surface.matrix()
        if rotation == 90:
            pixels = bytes(mask[y*width+x] for x in range(width) for y in reversed(range(height)))
            surface.images[handle] = [height, width, (ptr, height, pixels)]
            surface.matrices[0x1401] = (sx, sy, tx - sx*height, ty)
        elif rotation == 180:
            surface.images[handle] = [width, height, (ptr, width, mask[::-1])]
            surface.matrices[0x1401] = (sx, sy, tx - sx*width, ty - sy*height)
        else:
            pixels = bytes(mask[y*width+x] for x in reversed(range(width)) for y in range(height))
            surface.images[handle] = [height, width, (ptr, height, pixels)]
            surface.matrices[0x1401] = (sx, sy, tx, ty - sy*width)
        try:
            surface.draw_image()
        finally:
            surface.images[handle] = original
            surface.matrices[0x1401] = original_matrix

    bind(0x20263330, paint_color)
    bind(0x2026342E, lambda: reset(surface.identity))
    bind(0x2026344C, lambda: reset(surface.load_matrix))
    bind(0x202634AC, translate)
    bind(0x2026351E, rotate)
    bind(0x20263AC4, draw_image)
    # shortcut: the replay calls GPS_WORK cooperatively after the original RTX wake request.
    bind(0x202D4848, lambda: 0)
    return angles


def replay(dat, output):
    guest = start(load(dat))
    cpu, surface = guest.cpu, guest.surface
    angles = attach_position_graphics(guest)
    trace, frames = [], []
    watched = (RX_TASK, GPS_REQUEST, GPS_WORK, OPEN, CLOSE, REOPEN, PREPARE, DRAW_POSITION,
               DRAW_STRIP, KEY_SCAN, KEY_EVENT, TOUCH_RECT)
    for entry in watched:
        cpu.hook_add(uc.UC_HOOK_CODE, lambda _, address, _size, _user:
                     trace.append([hex(address), hex(surface.reg("LR")), surface.reg("R0")]),
                     begin=entry, end=entry)

    def state():
        return [*cpu.mem_read(LIVE_WINDOW, 2), *cpu.mem_read(DRAW_WINDOW, 2)]

    def frame(name, title, opened=False, action=None):
        input_calls = trace.copy()
        trace.clear()
        labels, png = guest.render()
        assert title in labels and ("RX POSITION DISPLAY" in labels) == opened, (name, labels)
        assert state()[:2] == ([13, 0] if opened else [0, 0]), (name, state())
        if opened:
            assert state()[2:] == [1, 15] and "JA1ABC" in labels and MESSAGE.decode() in labels
            assert "35ﾟ31.00'N139ﾟ30.00'E" in "".join(labels)
        (output / f"{name}.png").write_bytes(png)
        frames.append(dict(frame=name, action=action, window=state(), text=labels, input_calls=input_calls,
                           draw_calls=trace.copy(), png_sha256=sha256(png).hexdigest()))
        trace.clear()
        return labels

    def mode(value):
        for addr in (MODE_UI_A, MODE_VFO_A):
            cpu.mem_write(addr, bytes((value << 4,)))

    def gps_work():
        call(cpu, GPS_REQUEST)
        call(cpu, GPS_WORK)

    def tick():
        call(cpu, RX_TASK)

    def position_tap():
        assert guest.click(401, 101) == 0x15
        assert any(address == hex(REOPEN) for address, _, _ in trace)
        gps_work()

    cpu.mem_write(guest.language_address, b"\0\0")
    for addr in (0x20380714, 0x203EBC2F):
        cpu.mem_write(addr, pack("<I", 445_670_000))
    mode(9)
    frame("01-dv-idle", "DV")
    cpu.mem_write(DV_STRIP+2, b"\1\2")
    cpu.mem_write(DV_STRIP+0x0A, CALL.ljust(13))
    cpu.mem_write(DV_STRIP+0x17, bytes((len(CALL),)))
    labels = frame("02-dv-caller", "DV")
    assert "RX:" in labels and CALL.decode() in labels
    cpu.mem_write(DV_STRIP+3, b"\3")
    cpu.mem_write(DV_STRIP+0x76, MESSAGE.ljust(20))
    cpu.mem_write(DV_STRIP+0x8A, bytes((len(MESSAGE),)))
    labels = frame("03-dv-message", "DV")
    assert "MSG:" in labels and MESSAGE.decode() in labels
    cpu.mem_write(DV_STRIP+3, b"\2")
    cpu.mem_write(PREFERENCES+0x3E8, b"\1\1\1\0")
    cpu.mem_write(GPS_MODE, b"\1")
    call(cpu, GPS_INIT)
    for byte in nmea(RMC.format(time="120000")):
        call(cpu, BYTE_RX, byte)
    assert call(cpu, 0x20074650) == 1
    # shortcut: seed post-decode records; RF and DV slow-data assembly are outside this panel replay.
    cpu.mem_write(RX_POSITION, b"\1\0")
    cpu.mem_write(RX_POSITION+4, CALL.ljust(9))
    cpu.mem_write(RX_POSITION+0x0D, b"35310000N139300000E")
    cpu.mem_write(RX_POSITION+0x24, b"\2")
    cpu.mem_write(RX_POSITION+0x22, b"\xff\xff")
    cpu.mem_write(0x203813EE, b"\1")
    cpu.mem_write(0x203800A8, b"\1")
    cpu.mem_write(0x203E23C1, CALL.ljust(12))
    cpu.mem_write(0x203E24A5, MESSAGE.ljust(20))
    cpu.mem_write(DV_STRIP+6, b"\4")
    tick()
    assert state()[:2] == [0, 0], "position did not have its received flag yet"
    cpu.mem_write(0x203800AA, b"\1")
    tick()
    gps_work()
    assert any(address == hex(OPEN) and arg == 13 for address, _, arg in trace)
    assert "1852m" in frame("04-dprs-auto-open", "DV", True)

    # shortcut: advance the elapsed counter to the original comparison's edges, not wall-clock time.
    timeout, = unpack("<H", cpu.mem_read(0x202DE598+2, 2))
    cpu.mem_write(WINDOW_AGE, pack("<H", timeout))
    tick()
    assert state()[:2] == [13, 0]
    cpu.mem_write(WINDOW_AGE, pack("<H", timeout+1))
    tick()
    assert [hex(CLOSE), "0x20048648", 1] in trace
    frame("05-dprs-timeout", "DV", action={"elapsed_ticks": timeout+1})
    position_tap()
    assert "1852m" in frame("06-dprs-reopen", "DV", True, {"touch": [401, 101], "hit": 0x15})
    guest.press_exit()
    assert {hex(KEY_SCAN), hex(KEY_EVENT), hex(CLOSE)} <= {entry[0] for entry in trace}
    frame("07-dv-physical-exit", "DV", action="EXIT")
    position_tap()
    assert guest.click(375, 244) == 0x21A
    assert [hex(CLOSE), "0x20089de0", 1] in trace
    frame("08-dv-soft-back", "DV", action={"touch": [375, 244], "hit": 0x21A})
    mode(7)
    labels = frame("09-fm-dv-record-retained", "FM")
    assert "RX:" in labels and any(CALL.decode() in text for text in labels)
    position_tap()
    assert "1852m" in frame("10-fm-native-position", "FM", True, {"touch": [401, 101], "hit": 0x15})
    guest.press_exit()
    assert [hex(CLOSE), "0x20089c1c", 1] in trace
    frame("11-fm-physical-exit", "FM", action="EXIT")
    cpu.mem_write(DV_STRIP+2, b"\0")
    cpu.mem_write(DV_STRIP+6, b"\0")
    hit = guest.click(401, 101)
    assert hit != 0x15 and not any(entry[0] == hex(REOPEN) for entry in trace)
    labels = frame("12-fm-no-indicator", "FM", action={"touch": [401, 101], "hit": hit})
    assert "RX:" not in labels and angles

    return dict(dat_sha256=sha256(dat).hexdigest(), main_sha256=guest.main_hash,
                timer_boundary=[timeout, timeout+1], compass_rotation_degrees=angles, frames=frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = replay(args.dat.read_bytes(), args.output)
    (args.output / "replay.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(result['frames'])} stock panel frames and the window timer boundary.")


if __name__ == "__main__":
    main()
