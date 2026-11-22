"""Exercise manual APRS Beacon through the stock panel, PTT, and TX SSI0 DMA."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack

from tools.emulate_705 import SCRATCH, arm, call, uc
from tools.probe_705_cw_feedback import BEEP
from tools.probe_705_cw_pcm import BUILD_REQUEST, FILTER_REQUEST, FILTERED, REQUEST, feed_dsp_tx, simulated_gpio
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC
from tools.render_705_display import PAGE
from tools.replay_705_aprs_fm import GUARD, RATE, load_aprs_panel, original_fm, require, write_wav
from tools.replay_705_aprs_panel import Panel
from tools.replay_705_aprs_rx import dire_wolf
from tools.replay_705_aprs_task import APRS_SYMBOL_LIST, FM_HZ, build_task, e140_rom
from tools.replay_705_gps_inputs import GPS_MODE, POSITION_AGE
from tools.replay_705_ptt_tune import INIT_RANGES, PORT_PTT, PTT_PASSES
from tools.replay_705_settings import GRID_PAGE, UPDATE
from tools.replay_705_vfo_split import ACTIVE_HZ, SELECT_VFO, SET_SPLIT, seed_vfos


ATEST = Path(".analysis/aprs-fm-pcm/direwolf/direwolf-1.8.1-a231971_x86_64/atest.exe")
SELECTOR, CLOCK, FLAGS, PTT = 0x203E1A28, 0x20381E08, 0x203806F4, 0x203809C4
EDITOR_TEXT, DPRS_COMMENTS = 0x20399DC8, 0x203EA8CA
DPRS_SYMBOLS = 0x203EA8C1
DEFAULT_COMMENT = "ICOM IC-705 APRS TEST"
EDITED_COMMENT = "A" + DEFAULT_COMMENT[1:]
MAX_COMMENT = "A"*43
PATHS = ("Direct", "WIDE2-1", "WIDE1-1,WIDE2-1")


def replay(images, output, european, *, installed_symbols=None, atest=ATEST):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    atest = atest.resolve(strict=True)
    task = build_task(output, european=european) if installed_symbols is None else (None, installed_symbols)
    guest = original_fm(images, output, rom=e140_rom if european else None)
    panel = Panel(guest, output, task, channel=0, european=european)
    cpu, rom, sym = guest.cpu, guest.rom, panel.symbols
    confirmation = []
    beep = rom(BEEP)
    cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: confirmation.append(c.reg_read(arm.UC_ARM_REG_R0)),
                 begin=beep, end=beep)
    proof, transmissions = {}, []
    seed_vfos(cpu, (FM_HZ, 145_000_000))
    call(cpu, rom(INIT_RANGES))
    call(cpu, rom(SELECT_VFO[0]))
    panel.mode(7)
    simulated_gpio(cpu, rom=rom)
    for address in (0x203E212F, 0x203E2136):
        cpu.mem_write(address, b"\x70")
    cpu.mem_write(0x203EAAc8, bytes(2))
    cpu.mem_write(0x203EAAc7, b"\x80")
    cpu.mem_write(0x2038087C, pack("<5I", 65536, 43690, 32768, 21845, 10922))
    feed_dsp_tx(cpu, False, rom(0x200D4A28))
    cpu.mem_write(AUDIO_GATE, b"\0")

    def read(addr, size=4):
        return int.from_bytes(cpu.mem_read(addr, size), "little")

    def write(addr, value, size=4):
        cpu.mem_write(addr, value.to_bytes(size, "little"))

    def state():
        return read(sym["stage"])

    def screen(name=None, *words):
        labels, png = guest.render()
        require(set(words) <= set(labels), f"{name} missing {words}: {labels}")
        if name:
            (output / f"{name}.png").write_bytes(png)
            proof[name] = labels
        return labels

    def click(x, y):
        guest.click(x, y)
        return screen()

    def home():
        for _ in range(6):
            if "FM" in screen() and not read(SELECTOR, 2):
                return
            guest.press_exit()
        raise ValueError("native EXIT did not reach FM")

    def gps():
        guest.press_menu()
        screen()
        if read(GRID_PAGE, 1) != 2:
            click(274, 251)
        require("GPS" in click(145, 178), "native GPS settings missing")

    def settings():
        gps()
        require("Beacon Comment" in click(130, 169), "native APRS settings missing")

    def mode(value):
        gps()
        require({"GPS TX Mode", "OFF", "D-PRS", "NMEA", "APRS"} <= set(click(160, 104)), "native mode list missing")
        if value:
            require({"RX Only", "RX & TX"} <= set(click(150, 240)), "native APRS Mode selector missing")
            labels = click(130, 55 + 61*(value-1))
            require(guest.state()["selection"] == 3 and "GPS TX Mode" in labels and "APRS Mode" not in labels,
                    f"APRS selection did not return to GPS TX Mode: {labels}")
        else:
            require("GPS Set" in click(150, 55), "OFF did not return to the GPS list")
        require(read(sym["aprs_tx_enabled"], 1) == int(value == 2), "incorrect APRS TX mode")
        require(read(sym["aprs_channel_hz"]) == (FM_HZ if value else 0), "incorrect APRS receive mode")
        home()

    def edit_comment(*, accept, fill=False):
        def update_keyboard():
            call(cpu, rom(UPDATE), instruction_limit=2_000_000)
            require(guest.state()["menu"] == 349 and read(PAGE+1, 1) == 37,
                    "original Comment keyboard did not open")

        settings()
        screen("04b-comment-setting", "Beacon Comment")
        require(guest.click(140, 177) == 0x223, "Beacon Comment row did not open")
        update_keyboard()
        before = EDITED_COMMENT if fill else DEFAULT_COMMENT
        require(bytes(cpu.mem_read(EDITOR_TEXT, 43)).rstrip(b" ") == before.encode(),
                "original keyboard was not prefilled with the current comment")
        if fill:
            for _ in before:
                require(guest.click(443, 91) == 0x86, "original CLR key did not dispatch")
            for index in range(43):
                require(guest.click(210, 90) == 0x8b, "original ABC key did not dispatch")
                if index < 42:
                    require(guest.click(450, 46) != 0, "original right arrow did not dispatch")
        else:
            require(guest.click(443, 91) == 0x86 and guest.click(210, 90) == 0x8b,
                    "original CLR and ABC keys did not dispatch")
        after = MAX_COMMENT if fill else EDITED_COMMENT
        require(bytes(cpu.mem_read(EDITOR_TEXT, 43)).rstrip(b" ") == after.encode(), "native keys did not edit the comment")
        if accept:
            require(guest.click(443, 194) == 0x88, "original ENT did not dispatch")
        else:
            guest.press_exit()
            update_keyboard()
            require(guest.click(229, 193) == 0x22f, "original Cancel edit confirmation did not dispatch")
        screen("04c-comment-accepted" if accept else "04c-comment-canceled", "APRS", "Beacon Comment")
        require(read(SELECTOR, 2) == 277, "editor did not return to APRS settings")
        home()

    def tx_path(value):
        settings()
        require({"TX Path", *PATHS} <= set(click(130, 239)), "native TX selector did not open")
        click(130, 55 + 61*value)
        label = "TX Path  " + PATHS[value]
        screen(f"selected-tx-path-{value}", "1/2", label, "Beacon Comment")
        require("TX Path" in click(130, 239), "TX path option did not reopen")
        screen(f"tx-path-{value}", "TX Path", *PATHS)
        highlighted = ["".join(chr(g["key"]) for g in event["glyphs"])
                       for event in guest.surface.events if event["rgba"] == "000000ff"]
        require(PATHS[value] in highlighted, "native list did not highlight the new path")
        guest.press_exit()
        screen(f"exit-tx-path-{value}", "1/2", label, "Beacon Comment")
        home()

    def tx_symbol(pair, name):
        def enter(group):
            require({"Primary Symbols", "Alternate Symbols", "Overlay Symbols"} <= set(click(130, 55)),
                    "APRS symbol groups did not open")
            click(130, 55 + 61*group)
            require(read(SELECTOR, 2) == APRS_SYMBOL_LIST, "native symbol list did not open")

        def pairs():
            count = read(sym["catalog_count"], 1)
            return [read(sym["catalog_symbols"] + 2*i, 2).to_bytes(2, "big").decode() for i in range(count)]

        def move(target):
            index = pairs().index(target)
            current_page, desired_page = read(SELECTOR + 3, 1)//4, index//4
            for _ in range(abs(current_page-desired_page)):
                guest.click(394, 165 if current_page < desired_page else 68)
            require(read(SELECTOR + 3, 1) == 4*desired_page, "symbol list did not reach the correct page")
            return index

        settings()
        require({"2/2", "Beacon Symbol"} <= set(click(394, 165)), "APRS second page missing")
        group = 0 if pair[0] == "/" else 1 if pair[0] == "\\" else 2
        enter(group)
        base_table = "/" if group == 0 else "\\"
        expected_count = 86 if group == 0 else 77
        catalog = pairs()
        require(len(catalog) == expected_count and catalog == sorted(set(catalog)) and
                all(code[0] == base_table for code in catalog), "symbol table incomplete or out of order")
        if group == 2:
            index = move("\\" + pair[1])
            guest.click(135, 55+61*(index%4))
            require(pairs() == [ch + pair[1] for ch in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
                    "overlay list omitted a letter or digit")
        index = move(pair)
        tag = pair.encode().hex()
        labels = screen(f"beacon-symbol-catalog-{tag}", "Beacon Symbol", name)
        require(pair not in labels, "symbol codes were drawn alongside the English labels")
        require(len(guest.surface.pixel_writes) >= 1, "symbol artwork was not drawn on the target page")
        confirmation.clear()
        guest.click(135, 55+61*(index%4))
        require([n for n in confirmation if n] == [1], f"wrong symbol confirmation: {confirmation}")
        screen(f"exit-beacon-symbol-{tag}", "2/2", "Beacon Symbol")

        def selected():
            return bytes(cpu.mem_read(call(cpu, sym["aprs_beacon_symbol"]), 2)).decode()

        require(selected() == pair, "native selector did not save the APRS symbol pair")
        enter(group)
        if group == 2:
            require(read(SELECTOR + 3, 1) == 4*(pairs().index("\\" + pair[1])//4), "wrong overlay base page")
            index = move("\\" + pair[1])
            guest.click(135, 55+61*(index%4))
        require(read(SELECTOR + 3, 1) == 4*(pairs().index(pair)//4), "wrong saved symbol page")
        if group == 2:
            guest.press_exit()
            require(read(SELECTOR, 2) == APRS_SYMBOL_LIST and pairs()[0][0] == "\\", "overlay EXIT did not return to base symbols")
        guest.press_exit()
        screen(None, "Primary Symbols", "Alternate Symbols", "Overlay Symbols")
        guest.press_exit()
        screen(f"cancel-beacon-symbol-{tag}", "2/2", "Beacon Symbol")
        require(selected() == pair, "browsing and cancel changed the symbol")
        home()

    def quick(name, *, enabled, tx=False):
        guest._press_key(1, 1)
        labels = screen(name, "QUICK MENU", "Group Select")
        require(("APRS RX List" in labels, "Send APRS Beacon" in labels) == (enabled, tx),
                f"incorrect QUICK entries: {labels}")

    def request(expected):
        for address in (BUILD_REQUEST, FILTER_REQUEST, 0x20109E74):
            call(cpu, rom(address), timeout_us=0)
        values = tuple(read(address) for address in (REQUEST, FILTERED))
        require(tuple(bool(value & 0x8000) for value in values) == (expected, expected),
                f"unexpected native PTT request/filter: {values}, stage {state()}")
        require(bool(read(FLAGS, 1) & 0x80) == expected, "stock did not publish the requested TX state")
        return values

    def blocked(name, reason, *, at_click=None):
        quick(None, enabled=True, tx=True)
        if at_click:
            write(*at_click)
        click(130, 116)
        screen(name, "APRS Beacon", reason)
        require(state() == 0, f"{name} armed transmission")
        guest.press_exit()
        home()

    quick("01-quick-off", enabled=False)
    guest.press_exit()
    home()
    mode(1)
    quick("02-quick-rx-only", enabled=True)
    guest.press_exit()
    home()
    mode(2)
    quick("03-quick-rx-tx", enabled=True, tx=True)
    guest.press_exit()
    home()
    settings()
    require("Beacon SSID" in click(130, 116), "SSID picker did not open")
    require("2/4" in click(394, 164) and "Beacon SSID  7" in click(130, 241), "SSID 7 did not return and display")
    require(read(sym["aprs_beacon_ssid"], 1) == 7, "SSID did not apply")
    screen("04-ssid", "APRS", "Beacon SSID  7")
    home()

    blocked("05-no-callsign", "Set My Call Sign")
    cpu.mem_write(SCRATCH, b"N0CALL  TEST")
    call(cpu, rom(0x201FBA54), 0, SCRATCH, 0)  # Native current MY call selection.
    require(bytes(cpu.mem_read(0x203E2499, 12)) == b"N0CALL  TEST", "stock did not publish MY call")
    identity = bytes(cpu.mem_read(0x203E2499, 12))
    write(GPS_MODE, 0, 1)
    blocked("06-gps-off", "Check GPS position")
    write(GPS_MODE, 1, 1)
    write(POSITION_AGE, 115, 1)
    blocked("07-last-fix", "Check GPS position")
    panel.feed_gps("GPRMC,120102.00,A,3530.0000,N,13930.0000,E,0.0,0.0,211126,,,A")
    write(AUDIO_GATE, 1, 1)
    blocked("08-busy", "APRS channel busy")
    write(AUDIO_GATE, 0, 1)
    write(FILTERED, 0x200)  # Stock request builder's accepted mic PTT bit.
    blocked("09-accepted-ptt", "Other TX request")
    write(FILTERED, 0)
    for mask in (0x40, 0x80):
        blocked(f"09-inhibit-{mask:x}", "Radio TX inhibit", at_click=(PTT, mask, 1))
        write(PTT, 0, 1)
    blocked("09-remote-ptt", "Remote PTT active", at_click=(FLAGS, read(FLAGS, 1) | 0x20, 1))
    write(FLAGS, read(FLAGS, 1) & ~0x20, 1)
    dsp = 0x203809A1
    rx_status = read(dsp, 1)
    blocked("09-dsp-tx", "Radio TX active", at_click=(dsp, rx_status | 0x10, 1))
    write(dsp, rx_status, 1)
    write(ACTIVE_HZ, FM_HZ+5000)
    blocked("10-off-channel", "Tune APRS FM channel")
    write(ACTIVE_HZ, FM_HZ)
    call(cpu, rom(SET_SPLIT), 0, 1)
    blocked("11-split", "Use simplex FM")
    call(cpu, rom(SET_SPLIT), 0, 0)
    request(False)

    cpu.reg_write(arm.UC_ARM_REG_R4, DMAC)
    cpu.reg_write(arm.UC_ARM_REG_R5, 288)
    cpu.emu_start(rom(0x200FEF1C), rom(0x200FEF40))
    banks = [unpack("<III", cpu.mem_read(DMAC+0x100+12*i, 12)) for i in range(2)]
    require(banks == [(0x20400A40, 0xE820B018, 288), (0x20400B60, 0xE820B018, 288)], str(banks))
    blocks = 0

    def audio_block():
        nonlocal blocks
        bank = blocks & 1
        blocks += 1
        write(DMAC+0x124, 0x41 if bank else 0xc1)
        call(cpu, rom(0x200FFD48), timeout_us=0)
        words = cpu.mem_read(banks[bank][0], 288)
        return tuple(unpack("<h", words[index+6:index+8])[0] for index in range(0, 288, 8))

    def route():
        call(cpu, rom(0x20060C74))
        return read(0x203E1E60, 1), read(0x20380875, 1)

    def arm_beacon():
        quick(None, enabled=True, tx=True)
        confirmation.clear()
        labels = click(130, 116)
        require([n for n in confirmation if n] == [1], f"wrong QUICK beacon confirmation: {confirmation}")
        require(state() == 1 and read(SELECTOR, 2) == 0,
                f"quick tap did not arm one beacon: stage={state()}, picker={read(SELECTOR, 2)}, {labels}")
        return read(CLOCK)

    def transmit(name, start, lead):
        require(request(True) == (0x8000, 0x8000), "TX had a non-APRS owner")
        require(route() == (8, 2) and not any(audio_block()), "audio leaked before DSP transmit grant")
        screen(f"{name}-tx", "FM")
        write(CLOCK, (start + lead) & 0xffffffff)
        request(True)
        feed_dsp_tx(cpu, True, rom(0x200D4A28))
        samples = []
        for i in range(1800):
            write(CLOCK, (start + lead + i*3//4) & 0xffffffff)
            samples.extend(audio_block())
            if state() == 4:
                break
            if i % 12 == 0:
                request(True)
        require(state() == 4 and max(map(abs, samples)) > 1900 and not any(samples[-72:]),
                "missing PCM, modulation scaling or DMA drain")
        request(False)
        feed_dsp_tx(cpu, False, rom(0x200D4A28))
        request(False)
        require(state() == 0 and route() == (1, 0), "APRS ownership or modulation route persisted after native RX")
        wav = f"{name}.wav"
        digest = write_wav(output / wav, GUARD + tuple(samples) + GUARD, RATE)
        return samples, digest, dire_wolf(atest, output, wav, output)

    dprs_comments = bytes(cpu.mem_read(DPRS_COMMENTS, 43*4))
    dprs_symbols = bytes(cpu.mem_read(DPRS_SYMBOLS, 8))
    edit_comment(accept=False)
    for name, position, comment, path, pair, symbol_name in (
        ("12-live", "3530.00N/13930.00E", DEFAULT_COMMENT, 0, "/-", None),
        ("13-manual", "3351.23S/15112.67W", EDITED_COMMENT, 0, "/-", None),
        ("13-one-hop", "3351.23S/15112.67W", EDITED_COMMENT, 1, "/>", "Car"),
        ("13-two-hops", "3351.23S/15112.67W", MAX_COMMENT, 2, "\\_", "Weather site"),
        ("13-extra-symbol", "3351.23S/15112.67W", MAX_COMMENT, 1, "/$", "Telephone"),
        ("13-overlay", "3351.23S/15112.67W", MAX_COMMENT, 2, "R&", "Receive-only iGate"),
        ("13-number", "3351.23S/15112.67W", MAX_COMMENT, 2, "2&", "Two-hop TX iGate"),
    ):
        raw_ptt = name == "12-live"
        if raw_ptt:
            write(PORT_PTT, 0, 2)
            call(cpu, rom(PTT_PASSES[0]))
            require(read(PTT, 1) & 1 and not read(FLAGS, 1) & 0xa0 and request(False) == (0, 0),
                    "raw PTT fixture had no sample or already had a native TX request")
        if name == "13-manual":
            edit_comment(accept=True)
            cpu.mem_write(0x203EA85D, pack(">BHcBHc", 33, 51234, b"S", 151, 12678, b"W"))
            write(GPS_MODE, 2, 1)
        if path:
            tx_path(path)
            tx_symbol(pair, symbol_name)
        if name == "13-two-hops":
            edit_comment(accept=True, fill=True)
        start = arm_beacon()
        lead = 449 if path == 2 else 15
        samples, digest, frames = transmit(name, start, lead)
        if raw_ptt:
            write(PORT_PTT, 0x2000, 2)
            call(cpu, rom(PTT_PASSES[0]))
            require(not read(PTT, 1) & 1, "raw PTT sample did not clear")
        via = f",{PATHS[path]}" if path else ""
        expected = f"N0CALL-7>APRS{via}:!{position.replace('/', pair[0])}{pair[1]}{comment}"
        require([frame["text"] for frame in frames] == [expected], f"FCS-checked frame differs: {frames}")
        octets = bytes.fromhex(frames[0]["octets"])
        address_flags = octets[6:14+7*path:7]
        require(address_flags == bytes([0xe0, 0x6f if path == 0 else 0x6e] +
                                       ([0x62]*(path-1) + [0x63] if path else [])),
                f"unexpected AX.25 extension/SSID/H bits {address_flags.hex()}")
        transmissions.append(dict(name=name, raw_ptt_sample=raw_ptt, frame=expected, samples=len(samples),
                                  tx_path=PATHS[path], symbol=pair, address_flags=address_flags.hex(),
                                  pcm_sha256=digest, peak=max(map(abs, samples)), ssif_banks=[hex(bank[0]) for bank in banks]))

    start = arm_beacon()
    request(True)
    write(CLOCK, start+451)
    request(False)
    request(False)
    require(state() == 0, "missing DSP grant did not release PTT")

    arm_beacon()
    request(True)
    write(FLAGS, read(FLAGS, 1) | 0x20, 1)
    request(True)
    require(state() == 4 and read(FLAGS, 1) & 0x20 and route() == (1, 0),
            "APRS kept ownership or overrode the original remote request")
    write(FLAGS, read(FLAGS, 1) & ~0x20, 1)
    request(False)
    require(state() == 0, "remote PTT handover did not return to idle")

    automatic = []

    def timing_page():
        settings()
        click(394, 165)
        require(read(SELECTOR+3, 1) == 4, "Beacon timing was not on APRS page 2")

    def set_auto(enabled):
        timing_page()
        require({"Auto Beacon", "OFF", "ON"} <= set(click(135, 116)), "Auto Beacon picker missing")
        click(135, 116 if enabled else 55)
        screen(f"auto-beacon-{'on' if enabled else 'off'}", "Auto Beacon  " + ("ON" if enabled else "OFF"))
        home()

    def tick(ms, expected=0):
        write(CLOCK, ms & 0xffffffff)
        panel.refresh()
        require(state() == expected, f"wrong automatic beacon state at {ms:#x}: {state()} != {expected}")

    def scheduled(name, deadline):
        tick(deadline-1)
        tick(deadline, 1)
        waveform = transmissions[-1]
        samples, digest, frames = transmit(name, read(CLOCK), 449)
        require([frame["text"] for frame in frames] == [waveform["frame"]] and digest == waveform["pcm_sha256"],
                "automatic beacon differs from equivalent manual modulation")
        automatic.append(dict(name=name, tick=deadline & 0xffffffff, frame=waveform["frame"],
                              samples=len(samples), pcm_sha256=digest))

    epoch = 1_000_000
    timing_page()
    screen("auto-beacon-defaults", "Auto Beacon  OFF", "Beacon Interval  10 min")
    home()
    tick(epoch)
    set_auto(True)
    deadline = epoch + 600_000
    tick(deadline-1)
    write(AUDIO_GATE, 1, 1)
    tick(deadline)
    write(AUDIO_GATE, 0, 1)
    tick(deadline+1)

    timing_page()
    screen("auto-beacon-settings", "Beacon Interval  10 min", "Auto Beacon  ON")
    require({"1 min", "3 min", "5 min", "10 min"} <= set(click(135, 177)), "interval presets missing")
    require("30 min" in click(394, 165), "last interval preset missing")
    click(135, 55)
    screen("auto-beacon-30-min", "Beacon Interval  30 min", "Auto Beacon  ON")
    require("30 min" in click(135, 177), "interval picker did not reopen at the selected page")
    click(394, 68)
    click(135, 55)
    screen("auto-beacon-1-min", "Beacon Interval  1 min", "Auto Beacon  ON")
    home()

    minute = 60_000
    deadline += 1 + minute
    scheduled("16-auto-first", deadline)
    skipped = ["busy on default interval"]
    for label, address, blocked_value, size in (
        ("off frequency", ACTIVE_HZ, FM_HZ+5000, 4),
        ("GPS disabled", GPS_MODE, 0, 1),
        ("remote PTT", FLAGS, read(FLAGS, 1) | 0x20, 1),
        ("mic PTT", PTT, read(PTT, 1) | 1, 1),
    ):
        deadline += minute
        saved = read(address, size)
        write(address, blocked_value, size)
        tick(deadline)
        write(address, saved, size)
        tick(deadline+1)
        tick(deadline+minute-1)
        skipped.append(label)

    deadline += minute
    timing_page()
    tick(deadline)
    home()
    tick(deadline+1)
    skipped.append("menu open")
    deadline += minute
    scheduled("17-auto-after-skips", deadline)
    mode(1)
    deadline += 3*minute
    tick(deadline)
    skipped.append("RX Only")
    wrap = 0xffff8000
    tick(wrap)
    mode(2)
    scheduled("18-auto-wrap", wrap+minute)
    set_auto(False)
    tick(wrap+2*minute)
    tick(wrap+3*minute)

    require(bytes(cpu.mem_read(0x203E2499, 12)) == identity and not read(0x203EAAC8, 2),
            "APRS modified native callsign or modulation preferences")
    require(bytes(cpu.mem_read(DPRS_COMMENTS, 43*4)) == dprs_comments, "APRS edited the native D-PRS presets")
    require(bytes(cpu.mem_read(DPRS_SYMBOLS, 8)) == dprs_symbols, "APRS edited the native D-PRS symbols")
    mode(1)
    quick("14-back-to-rx-only", enabled=True)
    guest.press_exit()
    home()
    mode(0)
    quick("15-back-to-off", enabled=False)
    guest.press_exit()
    report = dict(region="E140" if european else "J140", image_sha256=sha256(images[0]).hexdigest(),
                  screens=proof, transmissions=transmissions, grant_timeout_release=True, remote_ptt_preserved=True,
                  automatic=automatic, skipped_automatic_cycles=skipped,
                  default_comment=DEFAULT_COMMENT, edited_comment=EDITED_COMMENT, dprs_comments_preserved=True,
                  beacon_symbol_count=163, beacon_symbol_codes_hidden=True, dprs_symbols_preserved=True)
    (output / "beacon.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--atest", type=Path, default=ATEST)
    options = parser.parse_args()
    images, european = load_aprs_panel(options.dat.read_bytes())
    replay(images, options.output, european, atest=options.atest)
