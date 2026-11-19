"""Exercise CW menu/EXIT, decoder and TX gate in a single offline J140 ARM guest."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack
from subprocess import check_output, run
from tempfile import TemporaryDirectory

from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_break_in import MAILBOX, UNPACK_STATUS, audio
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_cw_pcm import (
    BUILD_REQUEST, DECIMATED, DMAC, FILTER_REQUEST, KEY_ACTIVITY, LAYOUT, REC_TASK_STEP,
    TEST_CODE, TEST_STATE, feed_dsp_tx, simulated_gpio,
)
from tools.probe_705_rx_audio import AUDIO_GATE, completed, require
from tools.probe_705_tx_icon import ICON_FIELD, TX_GRAY_FLAGS
from tools.render_705_display import load
from tools.replay_705_ptt_tune import STATUS_TASK, byte
from tools.replay_705_settings import TOUCH_POLL, TOUCH_SAMPLE
from tools.replay_705_vfo_split import exchange_in_guest, read_in_guest, seed_vfos
from tools.virtual_705_panel import start


INPUT, TOUCH_HIT = 0x2007F1A4, 0x2007F10C
KEY_HALF_MS, KEY_SPEED_RAW, KEY_SPEED_UPDATE = 0x2038024A, 0x203EB126, 0x20060420
HOLD_CLOCK = 0x20381E08
HOLD_TICKS_PER_SECOND = 1000
SCOPE_CANVAS, SCOPE_MEMORY = 0x2100D000, 0x6000
SCOPE_X, SCOPE_Y, SCOPE_W, SCOPE_H, WAVE_W = 291, 176, 184, 60, 88
WAVE_BINS, WAVE_SAMPLES, WAVE_LABEL = 80, 64, "AF 640 ms"
FFT_X, FFT_W, FFT_H, WATER_ROWS = 387, 87, 27, 33
TX_ICON_UPDATE = 0x20095784
SOURCE = Path(__file__).resolve().parents[1] / "samples"
EXTENT = 1740
SESSION_FED = TEST_STATE + 8
SESSION_MARK = TEST_STATE + 472 + 12  # Session.decoder + Decoder.signal
SESSION_AUTO_DOT = TEST_STATE + 1516
SESSION_TRACKED_HZ = TEST_STATE + 1704
WORKER_STACK = TEST_CODE + 0x3000
RTX_CODE = TEST_CODE + 0x8000
RTX_MEMORY = SCOPE_CANVAS - RTX_CODE


def seed_key_speed(cpu, raw, *, invoke=None):
    """Set the keyer input on an isolated test guest, then run its stock timing update."""
    cpu.mem_write(KEY_SPEED_RAW, bytes((raw,)))
    (invoke or (lambda entry: call(cpu, entry)))(KEY_SPEED_UPDATE)


def hold_touch(cpu, x, y, ticks, *, up=False):
    """Advance the stock clock and issue a touch sample in the isolated panel fixture."""
    cpu.mem_write(HOLD_CLOCK, pack("<I", ticks & 0xffffffff))
    cpu.mem_write(TOUCH_SAMPLE, b"\1\0\0\0\0" if up else pack(">BHH", 0, x, y))
    call(cpu, TOUCH_POLL)


def build(out, *, rtx=False, stock_canvas=False, stock_state=False, text_base=RTX_CODE, sim_boot=False,
          merged_entry=False, rx_diagnostics=False):
    elf, binary = out / "session.elf", out / "session.bin"
    extra = ["-DCW_RTX", "-Wa,--defsym,CW_RTX_DRAW=1", "-mfpu=neon",
             str(SOURCE / "cw-j140-rtx.s")] if rtx else []
    if stock_canvas:
        require(rtx, "only the RTX renderer can allocate the stock canvas")
        extra.append("-DCW_STOCK_CANVAS")
    if stock_state:
        require(rtx, "stock-state replay requires the RTX worker")
        extra.extend(("-DCW_STOCK_STATE", "-Wa,--defsym,CW_RTX_ALLOC_STATE=1"))
    if sim_boot:
        require(stock_canvas and stock_state, "packaged CW needs the original heap and RTX")
        extra.append("-Wa,--defsym,CW_SIM_BOOT=1")
    if merged_entry:
        require(rtx, "the native selector requires the stock display path")
        extra.extend(("-DCW_MERGED_ENTRY", "-Wa,--defsym,CW_MERGED_ENTRY=1"))
    if rx_diagnostics:
        require(merged_entry and sim_boot, "RX diagnostics require the packaged selector and stock tasks")
        extra.extend(("-DCW_RX_DIAGNOSTICS", "-Wa,--defsym,CW_RX_DIAGNOSTICS=1"))
    run(["arm-none-eabi-gcc", "-mcpu=cortex-a9", "-marm", "-mfloat-abi=soft",
         "-Os", "-ffreestanding", "-fno-builtin", "-nostdlib",
         f"-Wl,-Ttext={text_base:#x},-e,cw_input_bridge,--build-id=none",
         str(SOURCE / "cw-j140-lab.s"), str(SOURCE / "cw-j140-lab.c"), *extra, "-o", str(elf)], check=True)
    symbols = {row[2]: int(row[0], 16)
               for line in check_output(["arm-none-eabi-nm", "--defined-only", str(elf)], text=True).splitlines()
               if len(row := line.split()) == 3}
    run(["arm-none-eabi-objcopy", "-O", "binary", str(elf), str(binary)], check=True)
    return (binary.read_bytes(), {INPUT: symbols["cw_input_bridge"], TOUCH_HIT: symbols["cw_touch_bridge"],
                                  DECIMATED: symbols["cw_pcm_bridge"]}, symbols)


def pcm_ranges(pcm):
    """Reference waveform for PCM supplied from an empty history."""
    samples = unpack(f"<{len(pcm)//2}h", pcm)
    blocks = [samples[i:i+WAVE_SAMPLES] for i in range(0, len(samples), WAVE_SAMPLES)]
    return (0,)*(2*max(0, WAVE_BINS-len(blocks))) + tuple(
        peak for b in blocks[-WAVE_BINS:] for peak in (min(b), max(b)))


def waveform_fixture():
    # 20 WPM N: 160 ms silence, 180 ms dash, 60 ms gap, 60 ms dot, 182 ms silence.
    return bytes(2560) + audio("N", trim_leading=True)[:4800] + bytes(2912)


def check_waveform_marks(active):
    edges = [i for i, (a, b) in enumerate(zip([False, *active], [*active, False])) if a != b]
    require(len(edges) == 4, f"expected a separate dash and dot in the waveform: {edges}")
    a, b, c, d = edges
    require(23 <= b-a <= 27 and 6 <= c-b <= 9 and 7 <= d-c <= 11,
            f"waveform did not preserve dash / gap / dot durations: {edges}")
    return dict(dash_pixels=b-a, gap_pixels=c-b, dot_pixels=d-c)


def read_session(cpu, base=TEST_STATE):
    raw = cpu.mem_read(base, EXTENT)
    active, blocked, fed, pending, cursor, length = unpack("<6I", raw[:24])
    generation, worker, read, write, drops, count = unpack("<6I", raw[724:748])
    dot, locked_dot, _, picker, mode, held, held_len, _ = unpack("<8I", raw[1516:1548])
    menu_two, adjust, setup, fixed_hz, threshold, manual_threshold, filter_mode, tracked_hz = unpack("<8I", raw[1676:1708])
    scope_pending, low, high = unpack("<I2h", raw[1708:1716])
    color_open, color_item, color_channel, r, g, b = unpack("<6I", raw[1716:])
    colors = (r, g, b)
    require(mode < 3 and picker < 2 and held < 2 and held_len <= 128 and menu_two < 2 and
            adjust < 2 and setup < 3 and manual_threshold < 2 and filter_mode < 3 and
            (300 <= fixed_hz <= 1250 if filter_mode == 2 else not fixed_hz) and
            (not tracked_hz or (filter_mode == 1 and 300 <= tracked_hz <= 1250)) and
            (350 <= threshold <= 9850 if active else threshold == 0) and
            color_open < 2 and color_item < 3 and color_channel < 3 and
            all(not k or k & 255 == 255 for k in colors),
            "invalid display state")
    half_ms, = unpack("<H", cpu.mem_read(KEY_HALF_MS, 2)) if mode == 2 else (0,)
    half_ms = half_ms if 50 <= half_ms <= 400 else 0
    speed_dot = (half_ms+10)//20 if half_ms else 0
    if mode != 2:
        speed_dot = locked_dot if mode == 1 else dot
    queued = (write-read) & 0xffffffff
    require(cursor < WAVE_BINS and length <= 128 and pending < 80 and count <= WAVE_BINS
            and scope_pending < WAVE_SAMPLES and queued <= 64,
            "invalid guest state")
    scope = unpack(f"<{2*WAVE_BINS}h", raw[24:344])
    ordered = scope[2*cursor:]+scope[:2*cursor] if count == WAVE_BINS else (0,)*(2*(WAVE_BINS-count))+scope[:2*count]
    if scope_pending:
        ordered = ordered[2:]+(low, high)
    live_decoder = active and not blocked and generation == worker
    text = raw[344:344+length].decode("ascii")
    shown_text = raw[1548:1548+held_len].decode("ascii") if held else text
    text_rows = shown_rows = None
    extra = cpu.mem_read(base+0x1000, 824)
    if unpack("<I", extra[:4])[0] == 0x43575235:
        def extended_page(offset):
            size, rows = unpack("<2I", extra[offset:offset+8])
            starts = unpack("<4H", extra[offset+8:offset+16])
            lengths = unpack("<4H", extra[offset+16:offset+24])
            require(size <= 384 and rows <= 4 and
                    all(starts[i]+lengths[i] <= size for i in range(rows)),
                    "invalid extended receive text")
            value = extra[offset+24:offset+24+size].decode("ascii")
            return value, [value[starts[i]:starts[i]+lengths[i]] for i in range(rows)]
        text, text_rows = extended_page(8)
        if held:
            extended_held, extended_rows = extended_page(416)
            if extended_held or not held_len:
                shown_text, shown_rows = extended_held, extended_rows
        else:
            shown_text, shown_rows = text,text_rows
    return dict(active=active, blocked=blocked, fed=fed, pending=pending if live_decoder else 0,
                scope=ordered, text=text, held=bool(held),
                shown_text=shown_text, text_rows=text_rows, shown_rows=shown_rows, menu_two=bool(menu_two),
                adjust=bool(adjust), setup=("", "FILTER", "THRESH")[setup], fixed_hz=fixed_hz,
                filter_mode=("WIDE", "AUTO", "FIX")[filter_mode], tracked_hz=tracked_hz,
                threshold=threshold, manual_threshold=bool(manual_threshold),
                partial_symbol=bool(live_decoder and any(raw[472:560])),
                queued=queued, drops=drops, speed_dot=speed_dot, speed_locked=mode == 1,
                speed_wpm=(2400//half_ms if half_ms else 0) if mode == 2 else
                (120 + speed_dot//2)//speed_dot if speed_dot else 0,
                speed_mode=("AUTO", "LOCK", "MANUAL")[mode] if active else "", speed_picker=bool(picker),
                color_open=bool(color_open), color_item=color_item, color_channel=color_channel, colors=colors)


class Lab:
    stock = {INPUT: "d2f8ffeb", TOUCH_HIT: "3a2502eb", DECIMATED: "0040a0e3"}

    def __init__(self, images, code, hooks, symbols):
        self.guest = start(images)
        cpu = self.cpu = self.guest.cpu
        self.symbols = symbols
        self.hooks = hooks
        self.draw = symbols["cw_lab_draw"]
        self.blocks = 0
        seed_vfos(cpu)
        simulated_gpio(cpu)
        cpu.mem_map(DMAC, 4096)
        cpu.mem_map(TEST_STATE, 8192)
        cpu.mem_map(RTX_CODE, RTX_MEMORY)
        cpu.mem_map(SCOPE_CANVAS, SCOPE_MEMORY)
        require(len(code) <= RTX_MEMORY, "test extension is larger than code mapping")
        cpu.mem_write(RTX_CODE, code)
        cpu.mem_protect(RTX_CODE, RTX_MEMORY, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
        # Change only the emulated PC. Never write the original instructions.
        for entry, dest in hooks.items():
            require(cpu.mem_read(entry, 4).hex() == self.stock[entry], f"stock instruction mismatch at {entry:#x}")
            cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_args, pc=dest: c.reg_write(arm.UC_ARM_REG_PC, pc),
                         begin=entry, end=entry)
        cpu.mem_write(AUDIO_GATE, b"\x01")

    def mode(self, n):
        for address in (MODE_UI_A, MODE_VFO_A):
            self.cpu.mem_write(address, bytes((n << 4,)))
        call(self.cpu, TOUCH_POLL)

    def view(self):
        return read_session(self.cpu)

    def refresh_rx(self):
        call(self.cpu, self.symbols["cw_lab_refresh_rx"])
        return self.view()

    def work(self, budget=64):
        return call(self.cpu, self.symbols["cw_lab_work"], budget,
                    instruction_limit=200_000, timeout_us=0, stack=WORKER_STACK)

    def feed(self, pcm, *, service=16):
        cpu = self.cpu
        require(len(pcm) % 12 == 0, "audio must contain whole six-sample groups")
        for offset in range(0, len(pcm), 12):
            six = unpack("<6h", pcm[offset:offset+12])
            left = tuple(x for x in six for _ in range(6))
            completed(cpu, LAYOUT["rec_dma"], DMAC+0xE4, LAYOUT["rec_bank"], self.blocks, left, (0,)*36,
                      timeout_us=0)
            call(cpu, REC_TASK_STEP, timeout_us=0)
            self.blocks += 1
            if service and self.blocks % service == 0:
                self.work()
        if service:
            self.work()
        require(cpu.mem_read(LAYOUT["rec_ring"]+0x240, 2) == bytes((self.blocks % 8,))*2,
                "stock audio task lost or retained DMA blocks")
        return self.view()

    def civ_request(self, down):
        response, _ = exchange_in_guest(self.cpu, bytes((0x1C, 0, down)))
        require(response[2:-1] == b"\xfb", "emulated stock CI-V request rejected")

    def publish(self):
        for routine in (BUILD_REQUEST, FILTER_REQUEST, STATUS_TASK):
            call(self.cpu, routine)

    def stock_tx(self):
        value, = read_in_guest(self.cpu, "1c 00")[0]
        return value


def probe(images, code, hooks, symbols):
    lab = Lab(images, code, hooks, symbols)
    cpu, guest = lab.cpu, lab.guest
    mode, view, feed = lab.mode, lab.view, lab.feed
    civ_request, publish, stock_tx = lab.civ_request, lab.publish, lab.stock_tx

    def menu():
        guest.press_menu()
        require(guest.render()[0] == ["MENU"], "stock MENU did not open")

    def shortcut():
        require(guest.click(80, 247) == 0, "CW shortcut overlapped a stock tile")

    def inactive():
        state = view()
        require(state["filter_mode"] == "WIDE"
                and not any(value for key, value in state.items() if key not in ("scope", "filter_mode", "colors"))
                and not any(state["scope"]) and not any(state["colors"]),
                "closed session exposed state")

    def waiting(before, state, label, expected_tx, expected_icon):
        require(state["active"] and state["blocked"] and not any(state["scope"])
                and (state["fed"], state["text"]) == (before["fed"], before["text"])
                and not state["pending"] and not state["partial_symbol"] and stock_tx() == expected_tx,
                f"TX samples or partial symbol reached CW: {label}")
        call(cpu, TX_ICON_UPDATE)
        require(byte(cpu, ICON_FIELD) == expected_icon, f"unexpected stock TX icon code: {label}")
        stages[label] = dict(stock_ci_v_tx=expected_tx, accepted_blocks=0, scope_flat=True,
                             stock_icon=expected_icon, text=state["text"])

    mode(2)
    guest.render()
    signal = audio("CQ TEST 123")
    side_tone = audio("VVV", trim_leading=True)
    require(any(side_tone[:960]), "short TX control must contain nonzero PCM")
    feed(signal[:1920])
    inactive()
    menu()
    require(guest.click(274, 251) == 0x1BB, "stock MENU page 2 did not open")
    guest.render()
    shortcut()
    inactive()
    require(guest.click(186, 251) == 0x1BA, "stock MENU page 1 did not reopen")
    guest.render()
    shortcut()
    require(view()["active"], "stock touch did not open the ARM session")

    # Prove the scope contains signed PCM extrema, in order, before decoding an entire message.
    prelude = audio("T", trim_leading=True)[:1920]
    before = feed(prelude)
    expected = pcm_ranges(prelude)
    require(before["scope"] == expected and min(expected) < 0 < max(expected)
            and before["partial_symbol"], "scope did not follow stock PCM or establish a partial symbol")
    call(cpu, TX_ICON_UPDATE)
    require(byte(cpu, ICON_FIELD) == 1, "idle TX outline missing")
    stages = {}
    civ_request(True)
    waiting(before, feed(side_tone), "request_before_tx_status", 0, 1)
    publish()
    waiting(before, feed(side_tone[:960]), "stock_tx", 1, 1)
    feed_dsp_tx(cpu, True)
    waiting(before, feed(side_tone[:960]), "solid_tx", 1, 2)
    civ_request(False)
    publish()
    waiting(before, feed(side_tone[:960]), "ci_v_rx_while_solid_tx_feedback_remains", 0, 2)
    feed_dsp_tx(cpu, False)
    flags = byte(cpu, TX_GRAY_FLAGS)
    cpu.mem_write(TX_GRAY_FLAGS, bytes((flags | 0x08,)))
    call(cpu, TX_ICON_UPDATE)
    require(byte(cpu, ICON_FIELD) == 3 and not feed(bytes(24))["blocked"],
            "gray marker by itself blocked clean RX")
    receiving = view()
    feed_dsp_tx(cpu, True)
    blocked = feed(side_tone[:960])  # Leave the stored icon untouched while audio is processed.
    require(byte(cpu, ICON_FIELD) == 3, "audio path unexpectedly updated the icon")
    waiting(receiving, blocked, "dsp_feedback_while_icon_stays_gray", 0, 3)
    feed_dsp_tx(cpu, False)
    resumed = feed(signal)
    require(resumed["active"] and not resumed["blocked"] and resumed["fed"] > before["fed"]
            and resumed["text"] == "CQ TEST 123", "RX did not recover with correct text")
    call(cpu, TX_ICON_UPDATE)
    require(byte(cpu, ICON_FIELD) == 3, "gray marker changed when RX resumed")
    cpu.mem_write(TX_GRAY_FLAGS, bytes((flags,)))
    # The stock DSP parser gets a simulated key-down before any request is generated.
    def key_input(down):
        cpu.mem_write(MAILBOX, bytes((0x20 if down else 0,)))
        cpu.mem_write(MAILBOX+0x40, b"\x01")
        call(cpu, UNPACK_STATUS)
        require(byte(cpu, KEY_ACTIVITY) == down, "stock DSP parser missed the key state")

    key_input(True)
    waiting(resumed, feed(side_tone[:960]), "early_cw_key_with_outline_icon", 0, 1)
    key_input(False)
    require(not feed(bytes(24))["blocked"], "RX did not resume after early CW key cleared")
    # The stock recording gate is independent of reception; silence the PCM
    # rather than treating this recording-only flag as an RX/TX condition.
    cpu.mem_write(AUDIO_GATE, b"\x00")
    silent = feed(bytes(960))
    require(not silent["blocked"] and silent["text"] == resumed["text"], "silent RX changed the transcript")
    cpu.mem_write(AUDIO_GATE, b"\x01")
    guest.press_exit()
    inactive()  # Check before rendering: the ARM input exchange already closed CW.
    feed(signal[:1920])
    inactive()
    require("CW" in guest.render()[0], "physical EXIT did not return to original CW HOME")
    menu()
    shortcut()
    require(view()["active"] and not view()["text"], "reopening exposed stale text")
    guest.press_exit()
    guest.render()
    menu()
    require(guest.click(240, 77) == 0x1B2 and "KEYER" in guest.render()[0], "stock KEYER changed")
    inactive()
    guest.press_exit()
    mode(3)
    guest.render()
    menu()
    shortcut()
    require(view()["active"], "CW-R did not open CW DECODE")
    mode(4)
    # A no-touch physical poll runs the original scanner, then the ARM input extension.
    call(cpu, TOUCH_POLL)
    inactive()
    guest.press_exit()
    guest.render()
    menu()
    shortcut()
    inactive()
    require(guest.click(240, 77) == 0x1B2 and "RTTY DECODE" in guest.render()[0], "stock RTTY changed")
    feed(signal[:1920])
    inactive()
    guest.press_exit()
    require("RTTY" in guest.render()[0] and guest.language() == [1, 1], "RTTY EXIT or language changed")
    require(all(cpu.mem_read(entry, 4).hex() == word for entry, word in lab.stock.items()),
            "stock hook instruction was overwritten")
    return dict(stock_main_sha256=guest.main_hash, arm_test_bytes=len(code), dma_groups=lab.blocks,
                text=resumed["text"], decoded_blocks=resumed["fed"]-before["fed"],
                scope_exact_pcm=True, menu_page_2_rejected=True, exit_before_redraw=True,
                cw_r_opened=True, mode_switch_cleared=True, keyer_and_rtty_unchanged=True,
                stock_hook_instructions_unchanged=True, stages=stages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    original = args.dat.read_bytes()
    with TemporaryDirectory() as scratch:
        result = probe(load(original), *build(Path(scratch)))
    result["original_dat_sha256"] = sha256(original).hexdigest()
    require(args.dat.read_bytes() == original, "original DAT changed")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(f"J140 ARM session: {result['text']}; {result['dma_groups']} stock DMA groups; {args.evidence}")


if __name__ == "__main__":
    main()
