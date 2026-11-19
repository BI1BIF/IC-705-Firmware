"""Interactive J140 panel driven by a single offline ARM guest."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from math import sin, tau
from pathlib import Path
from struct import pack
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory
from time import monotonic
import tkinter as tk
from tkinter import messagebox, ttk
import wave

from PIL import Image, ImageChops, ImageDraw, ImageFont

from tools.emulate_705 import PROFILES, call
from tools.make_cw_fixtures import PAD_FRAMES, render
from tools.probe_705_cw_break_in import audio
from tools.probe_705_cw_filter import adjacent_fixture, tracking_fixture
from tools.probe_705_cw_menu import CASES
from tools.probe_705_cw_pcm import feed_dsp_tx
from tools.probe_705_cw_session import (
    FFT_H, FFT_W, FFT_X, HOLD_TICKS_PER_SECOND, KEY_HALF_MS, KEY_SPEED_RAW, Lab, SCOPE_CANVAS, SCOPE_H, TEST_STATE,
    SCOPE_W, SCOPE_X, SCOPE_Y, TX_ICON_UPDATE, WAVE_LABEL, WAVE_W, build, check_waveform_marks, hold_touch,
    seed_key_speed, waveform_fixture,
)
from tools.probe_705_tx_icon import ICON_FIELD
from tools.render_705_display import PAGE, load
from tools.render_705_stock_row import require
from tools.replay_705_settings import FRAME_DRAW, GRID_PAGE, TOUCH_POLL, TOUCH_SAMPLE
from tools.replay_705_vfo_split import SELECT_VFO, seed_vfos


SHORTCUT = (9, 229, 149, 265)
ICON = (0, 0, 43, 21)
SPEED = (331, 150, 477, 163)
SOFTKEYS = [(2+96*i, 241, 94+96*i, 269) for i in range(5)]
HOLD_SOFTKEY = SOFTKEYS[1]
HOLD_CENTER = (144, 254)
CHOICES = {"AUTO": (12, 217, 97, 237), "LOCK": (98, 217, 183, 237), "MANUAL": (184, 217, 269, 237)}
MODE = {name: raw for name, raw, *_ in CASES}
CW = ("CW", "CW-R")
FIRST, SECOND = "CQ TEST 123", "DE IC705"
RATE = 8000
TICK_MS = 75  # A whole number of six-sample DMA groups.


def speed_fixture(second="RIG TEST"):
    pcm = bytearray(300 * 16)
    marks = []
    for wpm, text, pause in ((20, "CQ DE TEST", 420), (20, second, 2000), (24, "W9XYZ DE N0ABC", 350),
                             (20, "T", 420), (28, "W9XYZ DE N0ABC", 300), (12, "TU AND 73", 700)):
        start = len(pcm) // 16
        pcm.extend(render(text, wpm, 600, None)[PAD_FRAMES*2:-PAD_FRAMES*2])
        pcm.extend(bytes(-len(pcm) % 160))
        end = len(pcm) // 16
        pcm.extend(bytes(pause * 16))
        marks.append((start, end, end + pause))
    return bytes(pcm), marks


def picture(data):
    return Image.open(BytesIO(data)).convert("RGBA")


def button(image, box, label, font):
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=4, fill="#1a1a1a", outline="#4d4d4d")
    draw.text(((left + right) // 2, (top + bottom) // 2), label, font=font, fill="white", anchor="mm")


class Panel:
    def __init__(self, images, extension):
        self.lab = Lab(images, *extension)
        self.guest = self.lab.guest
        seed_vfos(self.guest.cpu, pair=(7_030_000, 7_035_000))
        require(call(self.guest.cpu, SELECT_VFO[0]) == 0, "stock VFO initialization failed")
        seed_key_speed(self.guest.cpu, 85)  # 20 WPM for the offline panel fixture.
        self.font = ImageFont.truetype("segoeuib.ttf", 16)
        self.rx = audio(FIRST) + bytes(9600) + audio(SECOND) + bytes(9600)
        self.side = audio("VVV", trim_leading=True)
        self.mode = None
        self.set_mode("CW")

    @property
    def active(self):
        return bool(self.lab.view()["active"])

    def render_stock(self):
        self.labels, self.stock = self.guest.render()
        if self.guest.cpu.mem_read(PAGE+1, 1)[0] == 1:
            self.home = self.stock

    def set_mode(self, mode):
        if mode == self.mode:
            return
        if self.mode is not None:
            self.exit()
        self.mode = mode
        self.tx = False
        self.lab.mode(MODE[mode])
        self.render_stock()

    def press_menu(self):
        if self.active:
            self.exit()
        self.guest.press_menu()
        self.render_stock()

    def shortcut_shown(self):
        return (self.mode in CW and self.labels == ["MENU"]
                and self.guest.cpu.mem_read(GRID_PAGE, 1)[0] == 1)

    def exit(self):
        if self.tx:
            self.set_tx(False)
        self.guest.press_exit()
        self.render_stock()

    def click(self, x, y):
        if self.active:
            return self.guest.click(x, y)
        hit = self.guest.click(x, y)
        if self.active:
            self.rx_pos = self.tx_pos = 0
            self.icon_code = None
            self.background = None
            self.last_body = None
        else:
            self.render_stock()
        return hit

    def set_tx(self, down):
        if not self.active or self.tx == down:
            return
        self.lab.civ_request(down)
        self.lab.publish()
        feed_dsp_tx(self.guest.cpu, down)
        self.tx = down
        self.tx_pos = 0

    def advance(self, groups):
        if not self.active:
            return
        span = groups * 12
        if self.tx:
            source = (self.side * (2 + span // len(self.side)))[self.tx_pos:self.tx_pos+span]
            self.tx_pos = (self.tx_pos + span) % len(self.side)
        else:
            source = self.rx[self.rx_pos:self.rx_pos+span].ljust(span, b"\0")
            self.rx_pos = min(len(self.rx), self.rx_pos + span)
        self.lab.feed(source)

    def draw_scopes(self, image):
        call(self.lab.cpu, self.lab.symbols["cw_lab_scope_draw"], instruction_limit=650_000)
        raw = bytes(self.lab.cpu.mem_read(SCOPE_CANVAS, 2*SCOPE_W*SCOPE_H))
        scopes = Image.frombytes("RGB", (SCOPE_W, SCOPE_H), raw, "raw", "BGR;16")
        image.paste(scopes, (SCOPE_X, SCOPE_Y))

    def update_icon(self):
        cpu, surface = self.guest.cpu, self.guest.surface
        call(cpu, TX_ICON_UPDATE)
        code = cpu.mem_read(ICON_FIELD, 1)[0]
        if code == self.icon_code:
            return
        # Draw an original HOME frame for the icon, then restore the stock UI selector.
        # The MENU flag and touch page remain live in the same CPU.
        page = bytes(cpu.mem_read(PAGE+1, 1))
        cpu.mem_write(PAGE+1, b"\x01")
        surface.image_draws.clear()
        try:
            call(cpu, FRAME_DRAW, instruction_limit=12_000_000, timeout_us=10_000_000)
        finally:
            cpu.mem_write(PAGE+1, page)
        surface.select_target()
        original = Image.frombytes("RGBA", (surface.width, surface.height), bytes(surface.pixels))
        self.icon = original.crop(ICON)
        self.icon_code = code

    def draw_body(self, state):
        body = (state["shown_text"], state["held"], state["speed_wpm"], state["speed_mode"],
                state["speed_picker"], state["menu_two"], state["adjust"], state["setup"],
                state["fixed_hz"], state["filter_mode"], state["threshold"], state["manual_threshold"],
                state["tracked_hz"] if state["setup"] == "FILTER" else 0,
                state["color_open"], state["color_item"], state["color_channel"], state["colors"])
        if body == self.last_body:
            return
        # Provide the CW background; the same guest paints its title and transcript.
        image = picture(self.home)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 149, 479, 271), fill="black")
        draw.line((2, 237, 478, 237), fill="#4a494a")
        for x in (2, 287, 382, 478):
            draw.line((x, 165, x, 237), fill="#4a494a")
        if state["color_open"]:
            draw.line((14, 220, 269, 220), fill="#4a494a")
        elif state["speed_picker"] or state["setup"]:
            draw.rectangle((12, 202, 269, 216), fill="#292829")
            selected = (("AUTO", "LOCK", "MANUAL").index(state["speed_mode"]) if state["speed_picker"] else
                        ("AUTO", "FIX", "WIDE").index(state["filter_mode"]) if state["setup"] == "FILTER" else 0)
            for index, box in enumerate(CHOICES.values()):
                draw.rectangle(box, fill="#4a494a" if selected == index else "#292829",
                               outline="#4d4d4d")
        surface = self.guest.surface
        surface.events.clear()
        # Stock text selects target 18 itself. Give it a clean, temporary surface;
        # leave original display and target contents alone for the next stock frame.
        target = surface.targets[18]
        dirty = surface.dirty.copy()
        pixels = bytearray(4 * image.width * image.height)
        surface.targets[18] = (*target[:3], pixels)
        try:
            call(self.guest.cpu, self.lab.symbols["cw_lab_title_strip"], instruction_limit=1_000_000)
            call(self.guest.cpu, self.lab.symbols["cw_lab_softkeys"], instruction_limit=1_000_000)
            call(self.guest.cpu, self.lab.draw, instruction_limit=4_000_000)
        finally:
            surface.targets[18] = target
            surface.dirty[:] = dirty
            surface.select_target()
        self.glyph_runs = ["".join(chr(g["key"]) for g in row["glyphs"]) for row in surface.events]
        self.background = image
        self.foreground = Image.frombytes("RGBA", image.size, bytes(pixels))
        self.last_body = body

    def display(self):
        state = self.lab.refresh_rx()
        if not state["active"]:
            image = picture(self.stock)
            if self.shortcut_shown():
                button(image, SHORTCUT, "CW DECODE", self.font)
            return image
        self.update_icon()
        self.draw_body(state)
        image = self.background.copy()
        image.paste(self.icon, ICON[:2])
        self.draw_scopes(image)
        return Image.alpha_composite(image, self.foreground)


def verify_panel(panel, output):
    evidence = {}
    for name, _, _, menu_id, subpanel, _ in CASES:
        panel.set_mode(name)
        panel.press_menu()
        require(panel.labels == ["MENU"] and panel.shortcut_shown() == (name in CW), name)
        before = picture(panel.stock)
        opened = panel.display()
        diff = ImageChops.difference(opened.convert("RGB"), before.convert("RGB")).getbbox()
        if name in CW:
            require(diff == (9, 229, 150, 266), "shortcut changed stock MENU pixels outside tile")
            opened.save(output / f"menu-{name.lower()}.png")
            require(panel.click(274, 251) == 0x1BB and not panel.shortcut_shown(), "page 2 not reached")
            require(panel.click(80, 247) == 0 and not panel.active, "shortcut opened on page 2")
            require(panel.click(186, 251) == 0x1BA and panel.shortcut_shown(), "page 1 not reached")
            require(panel.click(80, 247) == 0 and panel.active, "original touch did not open CW")
            panel.click(437, 247)
            require(panel.active, "LCD corner acted as EXIT")
            panel.exit()
            require(not panel.active and name in panel.labels, "EXIT did not return to HOME")
            panel.press_menu()
        else:
            require(diff is None and panel.click(80, 247) == 0 and not panel.active, f"wrong tile in {name}")
        require(panel.click(240, 77) == 0x1B2 and panel.guest.state()["menu"] == menu_id, name)
        require(panel.guest.cpu.mem_read(PAGE+2, 1)[0] == subpanel and panel.guest.language() == [1, 1], name)
        label = {13: "KEYER", 14: "RTTY DECODE"}.get(menu_id)
        if label:
            require(label in panel.labels, f"stock {label} did not render")
            panel.display().save(output / f"stock-{name.lower()}.png")
        evidence[name] = dict(shortcut_visible=name in CW, original_label=label, original_menu_id=menu_id)
        panel.exit()
        require(name in panel.labels, f"stock EXIT did not return to {name} HOME")

    panel.set_mode("CW")
    panel.press_menu()
    panel.click(80, 247)
    rx = panel.display().crop(ICON)
    interval = RATE * TICK_MS // 6000
    first_glyph_tick = wave_frame = None
    control = audio(FIRST)
    while panel.rx_pos < len(control) + 4800:
        panel.advance(interval)
        image = panel.display()
        state = panel.lab.view()
        text = state["text"]
        require(" ".join(panel.glyph_runs[1:panel.glyph_runs.index(WAVE_LABEL)]) == text.strip(),
                "original glyphs differ from ARM output")
        if first_glyph_tick is None and text:
            first_glyph_tick = panel.rx_pos // 16
        if wave_frame is None and text and min(state["scope"]) < -8000 < 8000 < max(state["scope"]):
            wave_frame = image
    require(first_glyph_tick and wave_frame and text == FIRST, "realtime text/waveform did not appear")
    require(wave_frame.crop((0, 21, 480, 149)).tobytes() ==
            picture(panel.home).crop((0, 21, 480, 149)).tobytes(), "CW obscured the stock HOME header")
    wave_frame.save(output / "cw-live-rx.png")
    wave_frame.crop((SCOPE_X, SCOPE_Y, SCOPE_X+SCOPE_W, SCOPE_Y+SCOPE_H)).save(output / "rx-scope.png")
    tx_stages = {}
    side = panel.side[:interval*12]
    require(len(side) == interval*12 and any(side), "TX control needs nonzero audio")

    def require_flat_trace(frame):
        scope = frame.crop((SCOPE_X, SCOPE_Y, SCOPE_X+WAVE_W, SCOPE_Y+SCOPE_H))
        green = (0, 255, 0, 255)
        require([sum(scope.getpixel((x, y)) == green for x in range(scope.width))
                 for y in range(scope.height)] == [0]*27 + [WAVE_W] + [0]*(SCOPE_H-28),
                "TX scope did not draw a level line")

    # A DSP report can arrive between two PCM callbacks. Repaint without feeding
    # any new audio, so a cached waveform cannot hide behind the packet timer.
    state = panel.lab.feed(audio("T", trim_leading=True)[:1920])
    require(state["text"] == FIRST and any(state["scope"]), "need existing text and a live scope")
    pcm_groups = panel.lab.blocks
    feed_dsp_tx(panel.guest.cpu, True)
    tx_without_pcm = panel.display()
    require_flat_trace(tx_without_pcm)
    halted = panel.lab.view()
    require(panel.icon_code == 2 and panel.lab.stock_tx() == 0 and panel.lab.blocks == pcm_groups
            and halted["blocked"] and (halted["fed"], halted["text"]) == (state["fed"], FIRST),
            "DSP-only repaint did not pause CW without accepting PCM")
    tx_without_pcm.save(output / "cw-live-tx-without-new-audio.png")
    tx_stages["feedback-between-audio-callbacks"] = dict(stock_icon=2, stock_ci_v_tx=0,
                                                        accepted_blocks=0, scope_flat=True, text=FIRST,
                                                        new_pcm_groups=0)
    feed_dsp_tx(panel.guest.cpu, False)
    require_flat_trace(panel.display())
    require(panel.icon_code == 1 and not panel.lab.view()["blocked"] and panel.lab.blocks == pcm_groups,
            "RX did not clear TX before the next audio group")

    def blocked_frame(label, expected_icon, expected_status):
        blocked = panel.lab.feed(side)
        require(blocked["blocked"] and not any(blocked["scope"]) and blocked["text"] == FIRST
                and blocked["fed"] == state["fed"], f"simulated side-tone reached CW: {label}")
        frame = panel.display()
        require(panel.icon_code == expected_icon and panel.lab.stock_tx() == expected_status
                and (frame.crop(ICON).tobytes() == rx.tobytes()) == (expected_icon == 1), label)
        tx_stages[label] = dict(stock_icon=expected_icon, stock_ci_v_tx=expected_status,
                                accepted_blocks=0, scope_flat=True, text=blocked["text"])
        return frame

    # Separate the stock events that the interactive button sends together.
    panel.lab.civ_request(True)
    blocked_frame("request-before-icon", 1, 0).save(output / "cw-live-tx-pending.png")
    panel.lab.publish()
    blocked_frame("published-before-feedback", 1, 1)
    feed_dsp_tx(panel.guest.cpu, True)
    tx_frame = blocked_frame("solid-tx", 2, 1)
    require_flat_trace(tx_frame)
    tx_frame.save(output / "cw-live-tx.png")

    panel.lab.civ_request(False)
    panel.lab.publish()
    blocked_frame("rx-before-feedback-clears", 2, 0).save(output / "cw-live-rx-pending.png")
    feed_dsp_tx(panel.guest.cpu, False)
    while panel.rx_pos < len(panel.rx):
        panel.advance(interval)
        resumed_frame = panel.display()
    expected = FIRST + " " + SECOND
    require(panel.lab.view()["text"] == expected and panel.icon_code == 1
            and resumed_frame.crop(ICON).tobytes() == rx.tobytes(),
            f"RX did not recover cleanly: {panel.lab.view()['text']!r}")
    resumed_frame.save(output / "cw-live-resumed.png")
    panel.exit()
    require(not panel.active and panel.lab.view()["text"] == "", "EXIT retained ARM session")
    disconnected_blocks = panel.lab.blocks
    panel.advance(interval)
    require(panel.lab.blocks == disconnected_blocks, "panel kept feeding after EXIT")
    panel.display().save(output / "cw-exit-home.png")
    panel.press_menu()
    panel.click(80, 247)
    require(panel.active and not panel.lab.view()["text"], "reopen did not start an empty session")
    panel.set_tx(True)
    panel.display()
    require(panel.icon_code == 2 and panel.lab.view()["blocked"], "simulate TX button did not stop CW")
    panel.set_tx(False)
    panel.advance(1)
    panel.display()
    require(panel.icon_code == 1 and not panel.lab.view()["blocked"], "simulate RX button did not resume CW")
    panel.set_mode("RTTY")
    require(not panel.active and "RTTY" in panel.labels, "mode change did not close session")
    result = dict(mode_checks=evidence, first_text=FIRST, resumed_text=expected,
                  first_char_audio_time_ms=first_glyph_tick, dma_groups=panel.lab.blocks,
                  stock_glyphs_in_same_guest=True, stock_tx_marker_verified=True, tx_stages=tx_stages,
                  tx_scope_flat=True, exit_stops_pcm=True, resumable=True, hold=verify_hold(panel, output),
                  right_scopes=verify_scopes(panel, output), transcript_wrap=verify_transcript_wrap(panel, output))
    (output / "panel-evidence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"J140 live CW panel: {result['dma_groups']} DMA groups; {output}")


def verify_transcript_wrap(panel, output):
    panel.press_menu()
    panel.click(80, 247)
    require(panel.active, "could not open CW for wrap test")
    widths = {}
    for name, text in (("wide-letters", "W" * 40), ("narrow-letters", "I" * 46),
                       ("word-boundary", "W" * 14 + " WIDE")):
        # Seed only the isolated transcript so recognition does not affect the layout check.
        panel.lab.cpu.mem_write(TEST_STATE + 20, pack("<I", len(text)))
        panel.lab.cpu.mem_write(TEST_STATE + 344, text.encode("ascii"))
        frame = panel.display()
        rows = panel.glyph_runs[1:panel.glyph_runs.index(WAVE_LABEL)]
        require("".join(rows).replace(" ", "") == text.replace(" ", ""), f"{name} dropped text: {rows}")
        require(len(rows) == {"wide-letters": 3, "narrow-letters": 1, "word-boundary": 2}[name],
                f"{name} wrapped at the wrong width: {rows}")
        if name == "word-boundary":
            require(" ".join(rows) == text, f"word was split at the right edge: {rows}")
        pixels = panel.foreground.crop((287, 165, 480, 237)).tobytes()
        for r, g, b, a in zip(pixels[::4], pixels[1::4], pixels[2::4], pixels[3::4], strict=True):
            require(not (a and g > r+18 and g > b+18), f"{name} overlaps either scope")
        widths[name] = rows
        frame.save(output / f"wrap-{name}.png")
    panel.exit()
    return widths


def verify_hold(panel, output):
    panel.set_mode("CW")
    panel.press_menu()
    panel.click(80, 247)
    cpu = panel.guest.cpu
    full = HOLD_TICKS_PER_SECOND

    def press(tick, *, up=False, point=HOLD_CENTER):
        hold_touch(cpu, *point, tick, up=up)
        return panel.lab.view()

    def short(tick):
        press(tick)
        return press(tick + full // 10, up=True)

    def label(text, held, file):
        image = panel.display()
        visible = " ".join(panel.glyph_runs[1:panel.glyph_runs.index(WAVE_LABEL)])
        require(visible == text and ("HOLD" in panel.glyph_runs) == held and
                "HOLD/CLR" in panel.glyph_runs, f"wrong LCD glyphs: {panel.glyph_runs}")
        image.save(output / file)

    first = panel.lab.feed(audio(FIRST) + bytes(4800))
    require(first["text"] == FIRST and short(100)["held"], "short HOLD press did not freeze")
    received = panel.lab.feed(audio(SECOND) + bytes(4800))
    expected = f"{FIRST} {SECOND}"
    require(received["held"] and received["shown_text"] == FIRST and received["text"] == expected and
            received["fed"] > first["fed"], "freezing the display stalled the live decoder")
    live = panel.lab.feed(audio("T", trim_leading=True)[:240])
    require(min(live["scope"]) < 0 < max(live["scope"]), "HOLD hid the receiving waveform")
    label(FIRST, True, "hold-frozen-live-wave.png")
    require(short(100 + full)["shown_text"] == expected, "second short press did not catch up")
    label(expected, False, "hold-resumed.png")

    press(100 + 2*full)
    press(100 + 2*full + full//10, point=(270, 250))
    require(not press(100 + 2*full + full//5, up=True)["held"], "dragged hold toggled on release")
    require(short(100 + 3*full)["held"], "second freeze failed")
    start = 0xffffffff - full//2
    press(start)
    almost = press(start + full - 1)
    require(almost["held"] and almost["shown_text"] == expected, "cleared before one second")
    cleared = press(start + full)
    require(not cleared["held"] and not cleared["shown_text"] and not cleared["text"] and
            cleared["fed"] == live["fed"] and cleared["scope"] == live["scope"], "clear reset reception")
    require(not press(start + full*2)["held"] and not press(start + full*2, up=True)["held"],
            "continued hold or release toggled after clear")
    label("", False, "hold-long-clear.png")
    # A release sample can be the next sample after the one-second threshold.
    panel.lab.feed(bytes(9600) + audio("CQ"))
    require(panel.lab.view()["text"].endswith("CQ"), "receiver failed to decode after clear")
    press(start + full*3)
    late = press(start + full*4, up=True)
    require(not late["held"] and not late["text"], "late release should clear once")
    next_text = panel.lab.feed(audio("CQ") + bytes(4800))
    require(next_text["text"] == "CQ" and next_text["fed"] > cleared["fed"],
            f"first message after clear was lost or prefixed: {next_text['text']!r}")
    label("CQ", False, "hold-next-text.png")
    require(short(start + full*5)["held"], "third freeze failed")
    panel.exit()
    require(not panel.active and not panel.lab.view()["held"], "EXIT kept the frozen text")
    panel.press_menu()
    panel.click(80, 247)
    require(panel.active and not panel.lab.view()["shown_text"], "reopen restored frozen text")
    panel.exit()
    return dict(frozen=FIRST, decoded_while_frozen=expected, visible_after_clear=cleared["shown_text"],
                next_message=next_text["text"], audio_blocks_while_frozen=received["fed"]-first["fed"],
                exact_one_second=True, wraps=True, waveform_unchanged_at_clear=True, exit_discards_hold=True)


def verify_scopes(panel, output):
    panel.press_menu()
    panel.click(80, 247)
    require(panel.active, "scope fixture did not open")

    def play(hz):
        samples = [round(16000*sin(tau*hz*n/RATE)) for n in range(4800)]
        panel.lab.feed(pack(f"<{len(samples)}h", *samples))

    def waterfall(image):
        return image.crop((FFT_X, SCOPE_Y+FFT_H, FFT_X+FFT_W, SCOPE_Y+SCOPE_H))

    def peak(history, y):
        return max(range(FFT_W), key=lambda x: sum(history.getpixel((x, y))[:3]))

    panel.lab.feed(audio(FIRST) + bytes(4800))
    play(600)
    first = panel.display()
    play(900)
    second = panel.display()
    history = waterfall(second)
    first_x, newest_x, old_x = peak(waterfall(first), 0), peak(history, 0), peak(history, 20)
    expected = lambda hz: (hz-300)*(FFT_W-1)/950
    require(abs(first_x-expected(600)) <= 3 and abs(newest_x-expected(900)) <= 3 and old_x == first_x,
            f"wrong frequency order in waterfall: {first_x=}, {newest_x=}, {old_x=}")
    fft = second.crop((FFT_X, SCOPE_Y, FFT_X+FFT_W, SCOPE_Y+FFT_H))
    # Isolate the cyan trace from the antialiased white frequency label.
    cyan = [(y, x) for y in range(fft.height) for x in range(fft.width)
            if (rgb := fft.getpixel((x, y)))[2] > rgb[0]+100 and rgb[1] > rgb[0]+100]
    require(cyan and any(abs(x-newest_x) <= 3 for y, x in cyan if y == cyan[0][0]),
            "spectrum and waterfall peaks disagreed")
    require(panel.glyph_runs[-6:-2] == ["< 1 >", "HOLD/CLR", "TX MEM", "SET"],
            "reference bottom key order changed")
    with Image.open(output / "stock-rtty.png") as reference:
        stock_rtty = reference.copy()

    def check_stock_key_borders(frame, *, gap=False):
        # Compare above and below the labels, plus the gaps across their full height.
        spans = ((0, 194), (287, 480)) if gap else ((0, 480),)
        borders = [(left, top, right, bottom) for left, right in spans for top, bottom in ((241, 249), (265, 270))]
        borders += [(x, 241, x+1, 270) for x in (95, 191, 287, 383)]
        for box in borders:
            require(frame.crop(box).tobytes() == stock_rtty.crop(box).tobytes(),
                    f"softkey border differs from stock RTTY at {box}")

    check_stock_key_borders(second, gap=True)
    second.save(output / "mk2-layout-two-tones.png")
    panel.click(336, 254)
    require(panel.active and not panel.lab.view()["speed_picker"] and not panel.lab.view()["color_open"],
            "inactive TX memory changed session")
    panel.click(48, 254)
    require(panel.lab.view()["menu_two"], "reference bottom page did not switch")
    page2 = panel.display()
    require(panel.glyph_runs[-5:-2] == ["< 2 >", "ADJ", "SET"], "reference second row changed")
    check_stock_key_borders(page2)
    page2.save(output / "mk2-layout-page-two.png")
    panel.click(336, 254)
    require(panel.lab.view()["adjust"], "second page ADJ did not open adjustments")
    panel.click(240, 254)
    require(panel.lab.view()["speed_picker"], "SPEED did not open from ADJ")
    panel.click(336, 254)
    panel.click(48, 254)
    require(not panel.lab.view()["menu_two"] and not panel.lab.view()["speed_picker"], "page one did not restore")
    panel.lab.feed(waveform_fixture())
    keyed = panel.display()
    green = (0, 255, 0)
    timing = check_waveform_marks([sum(keyed.getpixel((x, y))[:3] == green
                                       for y in range(SCOPE_Y+7, SCOPE_Y+SCOPE_H)) >= 3
                                  for x in range(SCOPE_X, SCOPE_X+WAVE_W)])
    keyed.save(output / "cw-waveform-dash-dot.png")
    panel.click(430, 254)
    require(panel.lab.view()["color_open"], "SET did not open")
    panel.display().save(output / "cw-decode-set.png")
    require({"CW DECODE SET", "FFT Scope Color", "Signal Wave Color", "RX Font Color"} <= set(panel.glyph_runs),
            "SET did not render the three receive items")
    panel.click(160, 186)
    panel.click(44, 254)  # R
    panel.click(269, 220)
    panel.click(430, 254)
    recolored = panel.display()
    require(panel.lab.view()["colors"] == (0, 0xffff00ff, 0) and
            any(rgb == (255, 255, 0, 255) for _, rgb in recolored.crop((291, 180, 379, 236)).getcolors(480*272)) and
            waterfall(recolored).tobytes() == waterfall(keyed).tobytes(), "SET changed the wrong scope")
    recolored.save(output / "cw-wave-color-yellow.png")
    panel.set_tx(True)
    tx = panel.display()
    require(waterfall(tx).convert("RGB").getbbox() is None and panel.lab.view()["blocked"],
            "waterfall retained or accepted TX samples")
    panel.set_tx(False)
    panel.click(430, 254)
    panel.exit()
    require(not panel.active and not panel.lab.view()["color_open"] and not any(panel.lab.view()["colors"]),
            "EXIT kept volatile CW colors")
    return dict(waterfall_peak_x_600=first_x+FFT_X, waterfall_peak_x_900=newest_x+FFT_X,
                older_600_below_newer_900=True, same_pcm_for_waveform_and_spectrum=True,
                waterfall_blank_in_tx=True, page_one_center_slot_empty=True, stock_rtty_borders_on_retained_keys=True,
                waveform_window_ms=640, waveform_timing=timing, receive_color_set=True)


def verify_cw_languages(panel, output, language_bytes):
    cpu = panel.guest.cpu
    before = bytes(cpu.mem_read(language_bytes, 2))
    cases = []
    try:
        for display, system in ((0, 0), (1, 0), (0, 1), (1, 1)):
            settings = bytes((display, system))
            cpu.mem_write(language_bytes, settings)  # Emulated language fixture only.
            panel.press_menu()
            panel.click(80, 247)
            require(panel.active, "CW did not open")
            frame = panel.display()
            require("和文" not in panel.glyph_runs and
                    frame.crop((194, 241, 287, 270)).convert("RGB").getbbox() is None,
                    f"retired softkey is still visible: {display}/{system}")
            # Click the old slot while a letter is buffered; it must leave decoding alone.
            pcm = audio("CQ") + bytes(2400)
            cut = 760 * 12
            state = panel.lab.feed(pcm[:cut])
            require(state["partial_symbol"], "fixture did not start a symbol before the click")
            panel.click(240, 254)
            after = panel.lab.view()
            require(all(after[key] == state[key] for key in
                        ("active", "text", "partial_symbol", "menu_two", "speed_picker", "color_open")),
                    "retired softkey changed the CW session")
            state = panel.lab.feed(pcm[cut:])
            require(state["text"] == "CQ" and "CQ" in state["shown_text"],
                    f"international CW decode after old key: {state['text']!r}")
            snapshot = f"cw-lang-{display}-{system}.png"
            frame = panel.display()
            require("CQ" in panel.glyph_runs, "international text was not drawn to the LCD")
            frame.save(output / snapshot)
            panel.exit()
            require(bytes(cpu.mem_read(language_bytes, 2)) == settings, "CW changed stock language settings")
            cases.append(dict(display=display, system=system, transcript=state["text"], snapshot=snapshot,
                              old_slot_blank_and_inert=True, stock_language_bytes_unchanged=True))
        (output / "language-evidence.json").write_text(json.dumps(cases, indent=2)+"\n", encoding="utf-8")
        print(f"J140 international CW: CQ and no Wabun key for all four language combinations; {output}")
    finally:
        cpu.mem_write(language_bytes, before)


def verify_speed(panel, output):
    panel.rx, marks = speed_fixture()
    pcm_sha = sha256(panel.rx).hexdigest()
    with wave.open(str(output / "speed-demo.wav"), "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(panel.rx)
    expected = "CQ DE TEST RIG TEST W9XYZ DE N0ABC T W9XYZ DE N0ABC TU AND 73"
    reports = {}

    def pick(mode, snapshot=None):
        panel.click(430, 158)
        require(panel.active and panel.lab.view()["speed_picker"], "WPM did not open SPEED")
        image = panel.display()
        require(panel.glyph_runs[-4:] == ["SPEED", "AUTO", "LOCK", "MANUAL"], "wrong SPEED labels")
        if snapshot:
            image.save(output / snapshot)
        left, top, right, bottom = CHOICES[mode]
        panel.click((left+right)//2, (top+bottom)//2)
        require(panel.active and not panel.lab.view()["speed_picker"], "SPEED touched a hidden stock control")

    for switched in (False, True):
        panel.press_menu()
        require(panel.click(80, 247) == 0 and panel.active, "could not open CW")
        stages = {}

        def point(name, ms, dot, locked, *, mode=None, snapshot=False):
            gap = ms*16 - panel.rx_pos
            require(gap >= 0, f"rewound audio at {name}")
            panel.advance((gap + 11)//12)
            if mode:
                pick(mode, "02a-speed-chooser.png" if name == "03-lock-20" else None)
            state = panel.lab.view()
            require((state["speed_dot"], state["speed_locked"]) == (dot, locked), f"{name}: {state}")
            image = panel.display()
            label = f"{int(120/dot+0.5)} WPM" if dot else "-- WPM"
            mode = "LOCK" if locked else "AUTO"
            require(panel.glyph_runs[-2:] == [label, mode], f"original glyphs at {name}: {panel.glyph_runs}")
            stages[name] = dict(audio_ms=ms, dot=dot, glyphs=panel.glyph_runs, text=state["text"])
            if snapshot:
                filename = f"{name}.png"
                image.save(output / filename)
                stages[name]["png_sha256"] = sha256((output / filename).read_bytes()).hexdigest()
            return state["text"]

        point("01-auto-unknown", marks[0][0]+250, 0, False, mode="LOCK" if switched else None, snapshot=switched)
        point("02-auto-20", marks[0][2]-10, 6, False, snapshot=switched)
        point("03-lock-20", marks[1][0]+130, 6, switched, mode="LOCK" if switched else None, snapshot=switched)
        quiet = point("quiet-begin", marks[1][1]+600, 6, switched)
        require(point("quiet-end", marks[2][0]-10, 6, switched) == quiet, "silence appended text")
        point("04-lock-during-24", marks[2][2]-10, 6 if switched else 5, switched, snapshot=switched)
        point("back-to-auto", marks[4][0]-10, 6 if switched else 5, False, mode="AUTO" if switched else None)
        point("05-auto-fast", marks[4][2]-10, 4, False, snapshot=switched)
        require(point("06-auto-12", marks[5][2]-10, 10, False, snapshot=switched) == expected,
                "switching speed lost or repeated text")
        require(panel.lab.view()["drops"] == 0, "speed input lost PCM groups")
        panel.exit()
        require(not panel.active and "CW" in panel.labels and not panel.lab.view()["speed_dot"],
                "EXIT did not clear speed or restore stock HOME")
        reports["switch" if switched else "auto_control"] = stages

    # Hold, rather than click, while a complete E and the next active mark are
    # still buffered. One press must lock once and the following PCM must emit E.
    panel.rx, marks = speed_fixture("ETR TEST")
    panel.press_menu()
    require(panel.click(80, 247) == 0 and panel.active, "could not reopen CW to verify held touch")

    def advance_to(ms):
        panel.advance((ms*16-panel.rx_pos+11)//12)

    advance_to(marks[1][0]+250)
    cpu = panel.guest.cpu
    panel.click(430, 158)
    require(panel.lab.view()["speed_picker"], "failed to open SPEED before held tap")
    cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 0, 138, 227))
    for _ in range(8):
        call(cpu, TOUCH_POLL)
        state = panel.lab.view()
        require(state["speed_locked"] and state["speed_dot"] == 6, "held touch toggled repeatedly")
    cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 1, 0, 0))
    for _ in range(2):
        call(cpu, TOUCH_POLL)
    advance_to(marks[1][2]-10)
    state = panel.lab.view()
    require(state["text"] == "CQ DE TEST ETR TEST" and not state["drops"], "locking lost a buffered letter")
    reports["held_touch"] = dict(pcm_sha256=sha256(panel.rx).hexdigest(), text=state["text"], lock_ticks=state["speed_dot"])
    panel.exit()
    panel.press_menu()
    require(panel.click(80, 247) == 0 and panel.active, "could not reopen CW after locked EXIT")
    require(panel.lab.view()["speed_dot"] == 0 and not panel.lab.view()["speed_locked"],
            "locking persisted after EXIT and re-entry")
    panel.display()
    require(panel.glyph_runs[-2:] == ["-- WPM", "AUTO"], "re-entry did not show AUTO with unknown speed")
    cpu = panel.guest.cpu
    original_pages = (cpu.mem_read(0x203807dd, 1), cpu.mem_read(0x203e84c9, 2))
    panel.click(430, 158)
    panel.click(412, 32)
    require(original_pages == (cpu.mem_read(0x203807dd, 1), cpu.mem_read(0x203e84c9, 2)) and
            not panel.lab.view()["speed_picker"], "dismissal touched a hidden stock control")
    # Only the PC test driver supplies the keyer setting. Use the original setter's
    # cache routine to establish the same read-only live setting the radio exposes.
    seed_key_speed(cpu, 85)
    panel.rx = audio("T 0")
    pick("MANUAL")
    require(panel.lab.view()["speed_dot"] == 6 and panel.glyph_runs[-4:] == ["SPEED", "AUTO", "LOCK", "MANUAL"],
            "MANUAL did not acquire the original 20 WPM setting")
    panel.advance((len(panel.rx)+11)//12)
    state = panel.lab.view()
    require(state["text"] == "T 0" and state["speed_mode"] == "MANUAL" and state["speed_wpm"] == 20 and
            cpu.mem_read(KEY_SPEED_RAW, 1) == bytes((85,)) and cpu.mem_read(KEY_HALF_MS, 2) == b"\x78\0",
            "MANUAL did not decode with, or changed, the keyer speed")
    panel.display().save(output / "07-manual-20.png")
    require(panel.glyph_runs[-2:] == ["20 WPM", "MANUAL"], "wrong MANUAL glyphs")
    seed_key_speed(cpu, 128)
    panel.advance(24)
    state = panel.lab.view()
    require(state["speed_dot"] == 4 and state["speed_wpm"] == 27 and state["speed_mode"] == "MANUAL" and
            cpu.mem_read(KEY_SPEED_RAW, 1) == b"\x80" and cpu.mem_read(KEY_HALF_MS, 2) == b"\x58\0",
            "MANUAL did not follow a change made by the stock keyer")
    panel.display().save(output / "08-manual-27.png")
    require(panel.glyph_runs[-2:] == ["27 WPM", "MANUAL"], "MANUAL displayed quantized instead of keyer speed")
    panel.click(430, 158)
    require(panel.lab.view()["speed_picker"], "could not open SPEED before EXIT")
    panel.exit()
    require(not panel.active and not panel.lab.view()["speed_picker"], "physical EXIT did not clear SPEED")
    result = dict(pcm_sha256=pcm_sha, same_guest=True, receive_only=True, **reports,
                  manual=dict(keyer_unchanged=True, wpm=[20, 27], timing_ticks=[6, 4], cold_text="T 0",
                              cleared_on_exit=True, hidden_controls_untouched=True))
    (output / "speed-evidence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"J140 CW speed A/B: full transcript in both cases; {output}")


def window(root, panel):
    root.title("IC-705 J140 | CW 解码")
    root.resizable(False, False)
    lcd = tk.Label(root, borderwidth=0)
    lcd.pack()
    keys = ttk.Frame(root, padding=8)
    keys.pack(fill="x")
    mode = ttk.Combobox(keys, values=tuple(MODE), state="readonly", width=8)
    mode.set(panel.mode)
    mode.pack(side="left")
    pending = None
    anchor = None
    groups_done = 0
    held_key = None

    def touch_time(point, *, up=False):
        hold_touch(panel.guest.cpu, *point, int(monotonic()*HOLD_TICKS_PER_SECOND), up=up)

    def ticking():
        return panel.active and (held_key is not None or panel.tx or panel.rx_pos < len(panel.rx))

    def draw():
        output = BytesIO()
        panel.display().save(output, "PNG")
        lcd.photo = tk.PhotoImage(data=output.getvalue())
        lcd.configure(image=lcd.photo)
        tx.configure(text="模拟接收" if panel.tx else "模拟发射",
                     state="normal" if panel.active else "disabled")

    def tick():
        nonlocal pending, anchor, groups_done
        pending = None
        elapsed = monotonic() - anchor
        target = int(elapsed * RATE / 6)
        # Avoid a long GUI stall if the window is suspended while the app is running.
        step = min(target - groups_done, 300)
        if step > 0:
            panel.advance(step)
            groups_done += step
        if target - groups_done > 300:
            anchor = monotonic()
            groups_done = 0
        if held_key is not None and panel.active:
            touch_time(held_key)
        draw()
        if ticking():
            pending = root.after(TICK_MS, tick)

    def act(fn, *args):
        nonlocal pending, anchor, groups_done
        if pending is not None:
            root.after_cancel(pending)
            pending = None
        fn(*args)
        if ticking():
            anchor, groups_done = monotonic(), 0
            pending = root.after(TICK_MS, tick)
        draw()

    def down(event):
        nonlocal held_key
        left, top, right, bottom = HOLD_SOFTKEY
        if panel.active and not panel.lab.view()["menu_two"] and left <= event.x <= right and top <= event.y <= bottom:
            held_key = (event.x, event.y)
            act(touch_time, held_key)
        else:
            act(panel.click, event.x, event.y)

    def move(event):
        nonlocal held_key
        if held_key is not None and panel.active:
            held_key = (min(479, max(1, event.x)), min(272, max(1, event.y)))
            touch_time(held_key)

    def up(event):
        nonlocal held_key
        if held_key is None:
            return
        move(event)
        point, held_key = held_key, None
        if panel.active:
            act(lambda: touch_time(point, up=True))

    mode.bind("<<ComboboxSelected>>", lambda _event: act(panel.set_mode, mode.get()))
    lcd.bind("<Button-1>", down)
    lcd.bind("<B1-Motion>", move)
    lcd.bind("<ButtonRelease-1>", up)
    ttk.Button(keys, text="MENU", command=lambda: act(panel.press_menu)).pack(side="left", padx=8)
    ttk.Button(keys, text="EXIT", command=lambda: act(panel.exit)).pack(side="left")
    tx = ttk.Button(keys, command=lambda: act(panel.set_tx, not panel.tx))
    tx.pack(side="left", padx=8)
    root.bind("<Escape>", lambda _event: act(panel.exit))
    ttk.Label(keys, text="离线演示").pack(side="right")
    draw()
    return lcd, keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="run regression and capture LCD frames")
    mode.add_argument("--verify-speed", action="store_true", help="play the same changing-speed file with and without LOCK")
    mode.add_argument("--verify-languages", action="store_true", help="verify international CW for every stock language pair")
    mode.add_argument("--speed-demo", action="store_true", help="open the panel with the changing-speed recording")
    mode.add_argument("--filter-demo", action="store_true", help="open the panel with two interfering CW stations")
    mode.add_argument("--track-demo", action="store_true", help="open the panel with CW at 600 and then 900 Hz")
    args = parser.parse_args()
    try:
        images = load(args.dat.read_bytes())
        args.output.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.output) as folder:
            extension = build(Path(folder))
        panel = Panel(images, extension)
    except (OSError, ValueError, CalledProcessError) as error:
        if not (args.verify or args.verify_speed or args.verify_languages):
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("IC-705 CW preview", str(error))
            root.destroy()
        raise
    if args.verify:
        verify_panel(panel, args.output)
    elif args.verify_speed:
        verify_speed(panel, args.output)
    elif args.verify_languages:
        verify_cw_languages(panel, args.output, PROFILES[images[3]].language_bytes)
    else:
        if args.speed_demo:
            panel.rx, _ = speed_fixture()
        elif args.filter_demo:
            panel.rx, _ = adjacent_fixture()
            # Give time to set FIX on the touch panel before the first mark.
            panel.rx = bytes(12*8000) + panel.rx
        elif args.track_demo:
            panel.rx = bytes(12*8000) + b"".join(pcm for _, _, pcm in tracking_fixture())
            panel.rx += bytes(-len(panel.rx) % 12)
        root = tk.Tk()
        window(root, panel)
        root.mainloop()


if __name__ == "__main__":
    main()
