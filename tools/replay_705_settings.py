"""Replay original J140 settings actions on one offline ARM guest and save the frames."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack

from tools.emulate_705 import PROFILES, STOP, arm, call, uc
from tools.render_705_display import DAT_HASH, GRAPHICS_FLASH, LIST_STATE, PAGE, load
from tools.render_705_stock_row import FONT_HASH, make_surface, png, require


MENU, ROW_INPUT = 0x203E84BF, 0x2038042C
OPEN_MENU, DISPATCH, SELECT_ROW, BACK = 0x200F1600, 0x2007D360, 0x2008B548, 0x20089DA0
UPDATE, DRAW, UI_HANDOFF = 0x20095DBC, 0x2015ADDC, 0x2008F700
PREVIOUS_PAGE, NEXT_PAGE = 0x17D, 0x17E
TOUCH_SAMPLE, TOUCH_POLL, TOUCH_STATE = 0x203E1F23, 0x2007F104, 0x204021B6
TOUCH_RECT, TOUCH_ACTION = 0x20107418, 0x201088F4
KEY_SAMPLE, KEY_SCAN, KEY_EVENT = 0x203E1F1C, 0x2007F010, 0x2007D6C0
FRAME_DRAW, HOME_DRAW, GRID_DRAW = 0x2013C5E8, 0x201636F8, 0x2013D82C
BRIGHTNESS_DRAW = 0x20159854
GRID_PAGE = 0x204BD24B  # guest uses 1 and 2, at offset 11 of its grid state


def attach_front_surface(cpu, surface, *, double_buffered=False, graphics_shift=0):
    table = unpack("<I", cpu.mem_read(0x201952CC+graphics_shift, 4))[0]
    for index in range(19):
        base, width, height = unpack("<IHH", cpu.mem_read(table+8*index, 8))
        surface.targets[index] = (base, width, height, bytearray(width*height*4))

    def select(_cpu, address, _size, _data):
        index = surface.reg("R1")
        if address == 0x20194C18+graphics_shift:
            require(index == 0 or double_buffered and index == 1, f"unmodeled EGL output {index}")
            # Both EGL slots target the same logical virtual LCD.
            surface.select_target()
        else:
            surface.select_target(index)

    for address in (0x20194C18+graphics_shift, 0x201951AC+graphics_shift):
        cpu.hook_add(uc.UC_HOOK_CODE, select, begin=address, end=address)


class SettingsGuest:
    def __init__(self, images, *, front_panel=False, rom=lambda address: address, language_address=None):
        main, font, graphics, self.main_hash, small_font = images
        self.front_panel = front_panel
        self.rom = rom
        shift = rom(FRAME_DRAW) - FRAME_DRAW
        cpu, surface = self.cpu, self.surface = make_surface(main, font, small_font if front_panel else None, graphics_shift=shift)
        cpu.mem_map(GRAPHICS_FLASH, len(graphics), uc.UC_PROT_READ)
        cpu.mem_write(GRAPHICS_FLASH, graphics)
        self.language_address = language_address or PROFILES[self.main_hash].language_bytes
        cpu.mem_write(self.language_address, b"\x01\x01")
        cpu.mem_write(TOUCH_SAMPLE, b"\x01\x00\x00\x00\x00")
        self.writes, self.visits = [], []

        def missing(_cpu, _access, address, _size, _value, _data):
            raise ValueError(f"unmodeled guest access at {address:#x} from {surface.reg('PC'):#x}")

        def graphics_boundary(_cpu, address, _size, _data):
            require(address in surface.handlers, f"unmodeled OpenVG entry at {address:#x}")

        def visited(_cpu, address, _size, _data):
            self.visits.append(hex(address))

        def handoff(_cpu, address, _size, _data):
            # shortcut: schedule the original draw pass here until the RTX UI task can run.
            require(surface.reg("LR") == STOP, "unexpected call to the UI task boundary")
            self.visits.append(hex(address))
            cpu.reg_write(arm.UC_ARM_REG_PC, STOP)

        def record_write(_cpu, _access, address, size, value, _data):
            self.writes.append({"pc": hex(surface.reg("PC")), "address": hex(address), "size": size, "value": value})

        cpu.hook_add(uc.UC_HOOK_MEM_INVALID, missing)
        cpu.hook_add(uc.UC_HOOK_CODE, graphics_boundary, begin=0x20263100+shift, end=0x20263DFF+shift)
        cpu.hook_add(uc.UC_HOOK_CODE, handoff, begin=rom(UI_HANDOFF), end=rom(UI_HANDOFF))
        watched = (OPEN_MENU, DISPATCH, SELECT_ROW, BACK, 0x2008B668, 0x2008B670,
                   0x200F0954, 0x200F022C, 0x200A2EE4, 0x200AD034, 0x201549B4,
                   TOUCH_RECT, TOUCH_ACTION, 0x2007D574, 0x2008B734)
        if front_panel:
            watched += (KEY_SCAN, KEY_EVENT, 0x200872E8, 0x20087340, FRAME_DRAW, HOME_DRAW, GRID_DRAW, BRIGHTNESS_DRAW)
            attach_front_surface(cpu, surface, graphics_shift=shift)
        for address in watched:
            cpu.hook_add(uc.UC_HOOK_CODE, visited, begin=rom(address), end=rom(address))
        for first, last in ((MENU+10, MENU+11), (MENU+63, MENU+63), (LIST_STATE+16, LIST_STATE+19),
                            (ROW_INPUT, ROW_INPUT), (ROW_INPUT+18, ROW_INPUT+19),
                            (self.language_address, self.language_address+1)):
            cpu.hook_add(uc.UC_HOOK_MEM_WRITE, record_write, begin=first, end=last)

    def state(self):
        cpu = self.cpu
        return dict(menu=unpack("<H", cpu.mem_read(MENU+10, 2))[0], depth=cpu.mem_read(MENU+63, 1)[0],
                    selection=unpack("<H", cpu.mem_read(LIST_STATE+16, 2))[0],
                    first=unpack("<H", cpu.mem_read(LIST_STATE+18, 2))[0])

    def language(self):
        return list(self.cpu.mem_read(self.language_address, 2))

    def click(self, x, y):
        surface, cpu = self.surface, self.cpu
        require(0 <= x < surface.width and 0 <= y < surface.height, "touch is outside the guest LCD")
        # shortcut: feed one down and two release polls at the input sample buffer; no digitizer model.
        cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 0, x, y))
        call(cpu, self.rom(TOUCH_POLL))
        hit_id, = unpack("<H", cpu.mem_read(TOUCH_STATE+2, 2))
        cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 1, 0, 0))
        call(cpu, self.rom(TOUCH_POLL))
        call(cpu, self.rom(TOUCH_POLL))
        return hit_id

    def press_menu(self):
        # The original input task cycles seven banks. Bank 0 bit 3 is the MENU key's sample.
        self._press_key(0, 3)

    def press_exit(self):
        self._press_key(1, 2)

    def _press_key(self, bank, bit):
        for sample in (1 << bit, 0):
            self.cpu.mem_write(KEY_SAMPLE + bank, bytes((sample,)))
            for _ in range(7):
                call(self.cpu, self.rom(TOUCH_POLL))

    def render(self):
        cpu, surface = self.cpu, self.surface
        before = self.state()
        surface.events.clear()
        surface.clears.clear()
        surface.image_draws.clear()
        surface.pixel_writes.clear()
        self.visits.clear()
        call(cpu, self.rom(UPDATE), instruction_limit=2_000_000)
        mode = cpu.mem_read(PAGE+1, 1)[0]
        if self.front_panel:
            target = {1: HOME_DRAW, 2: GRID_DRAW, 12: 0x201549B4, 13: 0x201549B4, 15: BRIGHTNESS_DRAW}.get(mode)
            require(target is not None, f"unmodeled panel UI mode {mode}")
            call(cpu, self.rom(FRAME_DRAW), instruction_limit=12_000_000, timeout_us=10_000_000)
            surface.select_target()
        else:
            target = 0x201549B4
            call(cpu, DRAW, instruction_limit=8_000_000, timeout_us=10_000_000)
        require(self.state() == before, "display update altered navigation state")
        labels = ["".join(chr(g["key"]) for g in event["glyphs"]).rstrip() for event in surface.events]
        require(min(surface.pixels[3::4]) == 255, "expected an opaque original frame")
        require(hex(self.rom(UI_HANDOFF)) in self.visits and hex(self.rom(target)) in self.visits, "missing original draw path")
        return labels, png(surface.width, surface.height, surface.pixels)


def replay(dat, output):
    guest = SettingsGuest(load(dat))
    cpu, visits, writes = guest.cpu, guest.visits, guest.writes
    output.mkdir(parents=True, exist_ok=True)
    steps = []

    def step(name, entry, arg=None, row=None, *, expected, words):
        before = guest.state()
        writes.clear()
        visits.clear()
        if row is not None:
            cpu.mem_write(ROW_INPUT, bytes((row,)))  # Already hit-tested, zero-based row.
        result = call(cpu, entry, *(() if arg is None else (arg,)))
        after = guest.state()
        require(tuple(after.values()) == expected, f"{name}: unexpected original state {after}")
        action_visits, action_writes = visits.copy(), writes.copy()
        labels, image = guest.render()
        require(labels[:len(words)] == words, f"{name}: unexpected original frame {labels!r}")
        (output / f"{name}.png").write_bytes(image)
        steps.append({"frame": name, "entry": hex(entry), "argument": arg, "row_input": row,
                      "before": before, "after": after, "return": result, "action_calls": action_visits,
                      "action_writes": action_writes, "draw_calls": visits.copy(), "ui_mode": cpu.mem_read(PAGE+1, 1)[0],
                      "highlight_row_one_based": cpu.mem_read(PAGE+898, 1)[0],
                      "text": labels, "png_sha256": sha256(image).hexdigest()})

    display, display_lang, system_lang = "ディスプレイ設定", "表示言語", "システム言語"
    step("00-set", OPEN_MENU, 22, expected=(22, 1, 0, 0), words=["セット", "1/4"])
    step("01-set-page2", DISPATCH, NEXT_PAGE, expected=(22, 1, 0, 4), words=["セット", "2/4"])
    step("02-display-page1", SELECT_ROW, row=3, expected=(67, 2, 0, 0),
         words=[display, "1/6", "LCDバックライト"])
    for page, label in enumerate(("受信LED", "受信コールサイン表示", "自動応答位置表示", "スクロール速度", display_lang), 2):
        step(f"0{page+1}-display-page{page}", DISPATCH, NEXT_PAGE, expected=(67, 2, 0, (page-1)*4),
             words=[display, f"{page}/6", label])
    step("08-display-end", DISPATCH, NEXT_PAGE, expected=(67, 2, 0, 20),
         words=[display, "6/6", display_lang, "日本語", system_lang, "日本語"])
    require(steps[-1]["return"] == 2 and steps[-1]["png_sha256"] == steps[-2]["png_sha256"],
            "next-page at the end should leave the image unchanged")
    step("09-display-language", SELECT_ROW, row=0, expected=(286, 3, 1, 0),
         words=[display_lang, "1/1", "英語", "日本語"])
    step("10-back-to-display", BACK, expected=(67, 2, 20, 20), words=[display, "6/6", display_lang])
    step("11-system-language", SELECT_ROW, row=1, expected=(286, 3, 1, 0),
         words=[system_lang, "1/1", "英語", "日本語"])
    step("12-back-to-display", BACK, expected=(67, 2, 21, 20), words=[display, "6/6", display_lang])
    step("13-display-previous", DISPATCH, PREVIOUS_PAGE, expected=(67, 2, 21, 16),
         words=[display, "5/6", "スクロール速度"])
    step("14-back-to-set", BACK, expected=(22, 1, 7, 4), words=["セット", "2/4"])
    require(steps[-1]["text"][-1] == display and steps[-1]["highlight_row_one_based"] == 4,
            "original return did not restore the parent row highlight")
    require(guest.language() == [1, 1], "language preferences changed")
    report = {"input_sha256": DAT_HASH, "main_sha256": guest.main_hash, "font_sha256": FONT_HASH,
              "engine": f"Unicorn {uc.__version__}", "steps": steps}
    (output / "trace.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="original Japanese 705J140.dat")
    parser.add_argument("output", type=Path, help="local output directory under .analysis")
    args = parser.parse_args()
    replay(args.dat.read_bytes(), args.output)


if __name__ == "__main__":
    main()
