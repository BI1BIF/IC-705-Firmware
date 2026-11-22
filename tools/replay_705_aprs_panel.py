"""Replay the ARM modem into separate APRS records and native FM panel controls."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from struct import calcsize, pack, unpack

from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.replay_705_aprs_fm import AUDIO_GATE, capture, load_aprs_panel, original_fm, read_wav, require
from tools.replay_705_aprs_rx import FRAME_MAX, FRAME_STRIDE, monitor
from tools.replay_705_aprs_task import FM_HZ, build_task, e140_rom, install_task
from tools.replay_705_dv_panel import (CLOSE, DRAW_POSITION, DRAW_STRIP, DRAW_WINDOW, DV_STRIP, GPS_REQUEST, GPS_WORK,
                                     LIVE_WINDOW, OPEN, PREFERENCES, PREPARE, REOPEN, RX_POSITION, RX_TASK, WINDOW_AGE,
                                     attach_position_graphics)
from tools.replay_705_gps_inputs import BYTE_RX, GPS_INIT, GPS_MODE, RMC, nmea
from tools.replay_705_language_storage import WRITE as EEPROM_WRITE
from tools.replay_705_settings import KEY_EVENT, KEY_SCAN, TOUCH_RECT


POSITION_REQUEST = 0x20048510
ALERT_SHOW, ALERT_STATE, DUPLICATE_CALLSIGN = 0x20047B28, 0x20392FE0, 472
GPS_VALID = 0x20074650
DV_VIEW, DV_NEW_POSITION, DV_MESSAGE_VALID = 0x20392F7C, 0x203800AA, 0x203800A8
DV_CALLS, DV_MESSAGE, DV_POSITION_VALID = 0x203E23C1, 0x203E24A5, 0x203813EE
WATCH_RANGES = {
    "dv_strip_and_view": (DV_VIEW, DV_STRIP + 2 * 0xCA - DV_VIEW),
    "dv_call_addresses": (DV_CALLS, 96),
    "dv_messages": (DV_MESSAGE, 40),
    "dv_remote_positions": (RX_POSITION, 2 * 112),
    "dv_remote_position_valid": (DV_POSITION_VALID, 2),
    "dv_record_and_position_events": (DV_MESSAGE_VALID, 4),
    "stock_position_task": (0x203D9E24, 60),
    "stock_position_result": (0x20380400, 5),
}
DV_CALL, DV_TEXT = b"JA1ABC", b"DV CONTROL RECORD"
DV_COORDS = b"35300000N139310000E"
POSITION = re.compile(rb"(?:[!=]|[/@]\d{6}[hz/])(\d{4}\.\d\d[NS])([/\\A-Z0-9])(\d{5}\.\d\d[EW])([!-~])(.*)\Z")


def position(info):
    match = POSITION.fullmatch(info)
    if not match:
        return None
    lat, table, lon, symbol, comment = match.groups()
    for value, width, limit in ((lat, 2, 90), (lon, 3, 180)):
        degree = int(value[:width])
        minutes = int(value[width:width+2]) * 100 + int(value[-3:-1])
        if minutes >= 6000 or degree > limit or (degree == limit and minutes):
            return None
    coords = [value.decode() for value in (lat, lon)]
    return dict(coordinates=coords, table=table.decode(), symbol=symbol.decode(), comment=comment.decode("ascii", "replace"))


def record(event):
    data = bytes.fromhex(event["octets"])
    calls = []
    for offset in range(0, min(len(data) - 8, 70), 7):
        block = data[offset:offset+7]
        call = bytes(byte >> 1 for byte in block[:6]).rstrip(b" ").decode("ascii")
        flags = block[6]
        ssid = flags >> 1 & 15
        calls.append(call + (f"-{ssid}" if ssid else ""))
        if flags & 1:
            break
    require(len(calls) >= 2 and flags & 1 and data[offset+7] & 0xEF == 3 and data[offset+8] == 0xF0,
            "invalid UI frame from ARM queue")
    for i in range(len(calls) - 1, 1, -1):
        if data[7*i+6] & 0x80:
            calls[i] += "*"
            break
    raw = data[offset+9:]
    # Keep every octet in the record. The Dire Wolf generator adds LF to most test payloads.
    info = raw.rstrip(b"\r\n")
    point = position(info)
    kind = "position" if point else {b":": "message", b">": "status"}.get(info[:1], "other")
    return dict(**event, source=calls[1], destination=calls[0], path=calls[2:], kind=kind,
                info_hex=raw.hex(), position=point)


class Panel:
    def __init__(self, guest, output, task, *, channel=FM_HZ, european=False):
        self.guest, self.cpu, self.output = guest, guest.cpu, output
        code, self.symbols = task
        if code is not None:
            install_task(self.cpu, code, self.symbols, european=european)
        if channel:
            self.cpu.mem_write(self.symbols["aprs_channel_hz"], pack("<I", channel))
        self.popup_entry = self.symbols["aprs_j140_popup_body"]
        self.records, self.latest_position = [], None
        self.trace, self.frames, self.dv_writes, self.eeprom_writes = [], [], [], []
        self.check_writes = False
        attach_position_graphics(guest)
        self.install()
        self.cpu.mem_write(GPS_MODE, b"\x01")
        call(self.cpu, guest.rom(GPS_INIT))
        self.feed_gps(RMC.format(time="120000"))
        require(call(self.cpu, guest.rom(GPS_VALID)) == 1, "stock GPS did not publish the NMEA fixture")

    def feed_gps(self, sentence):
        for byte in nmea(sentence):
            call(self.cpu, self.guest.rom(BYTE_RX), byte)

    def mode(self, mode):
        for address in (MODE_UI_A, MODE_VFO_A):
            self.cpu.mem_write(address, bytes((mode << 4,)))

    def window(self):
        return list(self.cpu.mem_read(LIVE_WINDOW, 2))

    def count(self, key):
        return int.from_bytes(self.cpu.mem_read(self.symbols["aprs_" + key], 4), "little")

    def popup(self):
        fields = f"104s10s9s10s3s{FRAME_MAX}s"
        values = unpack(fields, self.cpu.mem_read(self.symbols["aprs_popup_packet"], calcsize(fields)))
        return tuple(value.split(b"\0")[0].decode("ascii") for value in values)

    def refresh(self):
        call(self.cpu, self.symbols["aprs_update_panel"])

    def originals(self):
        return {name: sha256(self.cpu.mem_read(address, size)).hexdigest() for name, (address, size) in WATCH_RANGES.items()}

    def install(self):
        cpu = self.cpu

        def hook(address, callback):
            cpu.hook_add(uc.UC_HOOK_CODE, callback, begin=address, end=address)

        def trace(c, address, _size, _user):
            self.trace.append([hex(address), hex(c.reg_read(arm.UC_ARM_REG_LR)), c.reg_read(arm.UC_ARM_REG_R0)])

        def memory_write(c, _access, address, size, _value, _):
            if self.check_writes:
                self.dv_writes.append([hex(c.reg_read(arm.UC_ARM_REG_PC)), hex(c.reg_read(arm.UC_ARM_REG_LR)), hex(address), size])

        def storage_write(c, *_):
            if self.check_writes:
                self.eeprom_writes.append([hex(c.reg_read(arm.UC_ARM_REG_R0)), c.reg_read(arm.UC_ARM_REG_R2)])

        for address in (KEY_SCAN, KEY_EVENT, TOUCH_RECT, REOPEN, POSITION_REQUEST, OPEN, CLOSE, PREPARE, DRAW_POSITION,
                        DRAW_STRIP, 0x2004B7F4, 0x20188E30):
            hook(self.guest.rom(address), trace)
        hook(self.popup_entry, trace)
        for address, size in WATCH_RANGES.values():
            cpu.hook_add(uc.UC_HOOK_MEM_WRITE, memory_write, begin=address, end=address+size-1)
        hook(self.guest.rom(EEPROM_WRITE), storage_write)

    def observe_poll(self, _, sample, *, frames=False):
        require(self.count("rx_samples") == sample and self.count("rx_overrun") == 0,
                "native task lost undecimated audio or overran")
        end = self.count("record_count")
        first = end and not self.records
        for index in range(len(self.records), end):
            address = self.count("records") + index % 64 * FRAME_STRIDE
            time, length = unpack("<II", self.cpu.mem_read(address, 8))
            raw = bytes(self.cpu.mem_read(address + 8, length))
            item = record(dict(text=monitor(raw), octets=raw[:-2].hex(), fcs_wire=raw[-2:].hex(), end_sample=time,
                               gate=self.cpu.mem_read(AUDIO_GATE, 1)[0]))
            self.records.append(item)
            if item["position"]:
                self.latest_position = item
        if first and frames:
            self.frame("02-fm-aprs-callsign", "FM", words=("RX:", self.records[0]["source"]))
            require(hex(self.guest.rom(DRAW_STRIP)) in {entry[0] for entry in self.frames[-1]["draw_calls"]},
                    "short line bypassed stock draw")
        self.refresh()
        if first and frames:
            expected = {(hex(self.guest.rom(POSITION_REQUEST)), 3), (hex(self.guest.rom(OPEN)), 13)}
            require(expected <= {(e[0], e[2]) for e in self.trace},
                    "position bypassed the original automatic open path")
            self.frame("03-fm-aprs-position", "FM", item=self.records[0], action="ARM receive record")

    def frame(self, name, mode, *, item=None, words=(), action=None):
        input_calls = self.trace.copy()
        self.trace.clear()
        labels, png = self.guest.render()
        titles = ("POSITION BEACON", "WEATHER STATION", "APRS IGATE", "PERSONAL STATION")
        opened = "RX POSITION DISPLAY" in labels or any(title in labels for title in titles)
        require(mode in labels and all(word in "".join(labels) for word in words), f"{name}: {labels}")
        require(opened == (self.window() == [13, 0]), f"{name}: wrong native position window")
        if item:
            point = item["position"]
            symbol = point["table"] + point["symbol"]
            require(item["source"] in labels and self.popup()[4] == symbol and any(title in labels for title in titles),
                    f"{name}: wrong APRS position {labels}")
            require(not {"RX POSITION DISPLAY", "DST:", "MSG:"} & set(labels), f"{name}: D-PRS content leaked")
            expected = {hex(self.guest.rom(address)) for address in (PREPARE, DRAW_POSITION, 0x20188E30)}
            require(expected | {hex(self.popup_entry)} <= {entry[0] for entry in self.trace},
                    "position bypassed the stock window or Back button")
        if mode == "FM" and self.check_writes:
            require(DV_CALL.decode() not in labels and DV_TEXT.decode() not in labels, "DV content appeared on the APRS panel")
        (self.output / f"{name}.png").write_bytes(png)
        self.frames.append(dict(name=name, text=labels, window=self.window(), draw_window=list(self.cpu.mem_read(DRAW_WINDOW, 2)),
                                action=action, input_calls=input_calls, draw_calls=self.trace.copy(), png_sha256=sha256(png).hexdigest()))
        self.trace.clear()
        return labels

    def tap_position(self, *, aprs):
        address = lambda entry: hex(self.guest.rom(entry))
        hit = self.guest.click(401, 101)
        require(hit == 0x15 and any(e[0] == address(REOPEN) for e in self.trace), f"wrong original icon path: {hit:#x}")
        if aprs:
            require(self.popup()[-1] == self.latest_position["position"]["comment"] and
                    {(address(POSITION_REQUEST), 2), (address(OPEN), 13)} <= {(e[0], e[2]) for e in self.trace},
                    "original tap dispatcher did not select the APRS position")
        else:
            self.stock_gps_work()
        return hit

    def exit(self):
        self.guest.press_exit()
        expected = {hex(self.guest.rom(address)) for address in (KEY_SCAN, KEY_EVENT, CLOSE)}
        close = [hex(self.guest.rom(CLOSE)), hex(self.guest.rom(0x20089C1C)), 1]
        require(self.window() == [0, 0] and expected <= {e[0] for e in self.trace} and
                close in self.trace, f"physical EXIT did not run the original path: {self.window()}, {self.trace[-16:]}")
        self.refresh()

    def stock_gps_work(self):
        call(self.cpu, self.guest.rom(GPS_REQUEST))
        call(self.cpu, self.guest.rom(GPS_WORK))

    def seed_dv(self):
        """Start with the previous replay's DV inputs and a distinct position."""
        cpu = self.cpu
        self.mode(9)
        cpu.mem_write(DV_STRIP+2, b"\x01\x02")
        cpu.mem_write(DV_STRIP+6, b"\x04")
        cpu.mem_write(DV_STRIP+0x0A, DV_CALL.ljust(13) + bytes((len(DV_CALL),)))
        cpu.mem_write(DV_STRIP+0x76, DV_TEXT.ljust(20) + bytes((len(DV_TEXT),)))
        cpu.mem_write(PREFERENCES+0x3E8, b"\x01\x01\x01\x00")
        cpu.mem_write(RX_POSITION, b"\x01\x00")
        cpu.mem_write(RX_POSITION+4, DV_CALL.ljust(9))
        cpu.mem_write(RX_POSITION+0x0D, DV_COORDS)
        cpu.mem_write(RX_POSITION+0x24, b"\x02")
        cpu.mem_write(RX_POSITION+0x22, b"\xff\xff")
        cpu.mem_write(DV_POSITION_VALID, b"\x01")
        cpu.mem_write(DV_MESSAGE_VALID, b"\x01")
        cpu.mem_write(DV_NEW_POSITION, b"\x01")
        cpu.mem_write(DV_CALLS, DV_CALL.ljust(12))
        cpu.mem_write(DV_MESSAGE, DV_TEXT.ljust(20))
        call(cpu, self.guest.rom(RX_TASK))
        self.stock_gps_work()


def replay(dat, fixture, reference, output, *, installed=None):
    package = dat.read_bytes()
    images, european = load_aprs_panel(package)
    region_rom = e140_rom if european else None
    baseline = json.loads((fixture / "replay.json").read_text(encoding="utf-8"))
    previous = json.loads((reference / "replay.json").read_text(encoding="utf-8"))
    require(baseline["stock_main_sha256"] == previous["stock_main_sha256"] and
            (european or images[3] == baseline["stock_main_sha256"]), "wrong replay inputs")
    output.mkdir(parents=True)
    if installed is None:
        task = build_task(output, european=european)
    else:
        image, symbols = installed
        images = (image, *images[1:])
        task = (None, symbols)
    cases = {}
    for key, prior in previous["cases"].items():
        guest = original_fm(images, output, rom=region_rom)
        rom = guest.rom
        panel = Panel(guest, output, task, european=european)
        main_case = key == "continuous"
        panel.seed_dv()
        if main_case:
            labels = panel.frame("00-dv-before", "DV", words=(DV_CALL.decode(), DV_TEXT.decode(), "35ﾟ30.00'N139ﾟ31.00'E"))
            require("RX POSITION DISPLAY" in labels, "DV position control did not open")
        else:
            guest.render()
        panel.exit()
        before = panel.originals()
        panel.mode(7)
        panel.check_writes = True
        if main_case:
            labels = panel.frame("01-fm-before-aprs", "FM")
            require("RX:" not in labels and guest.click(401, 101) != 0x15, "DV history leaked into FM before APRS")
            panel.trace.clear()
        wav = (reference if key == "recovery" else fixture) / prior["fixture"]
        source = read_wav(wav)
        if key in baseline:
            pcm_hash = sha256(pack(f"<{len(source)}h", *source)).hexdigest()
            require(pcm_hash == baseline[key]["streams"]["source48"]["pcm_sha256"], "prior WAV changed")
        gates = {item["sample"]: item["gate"] for item in prior["native"]["gate_changes"]}
        _, _, _, native = capture(guest, source, gates, right_only=key == "second_slot",
                                  task=panel.symbols["aprs_j140_record_step"],
                                  after_poll=lambda cpu, sample: panel.observe_poll(cpu, sample, frames=main_case))
        events = [{name: item[name] for name in ("text", "octets", "fcs_wire", "end_sample", "gate")} for item in panel.records]
        require(events == prior["frames"], f"{key}: ARM/RX record mismatch")
        require(panel.count("rx_read") == panel.count("rx_written") == len(panel.records) and
                panel.count("lost_pcm_blocks") == panel.count("uncertain_pcm_blocks") == 0,
                "native task did not hand off the complete input")
        if main_case:
            require(panel.popup()[-1] == "J140-000" and
                    panel.latest_position["position"]["comment"] == "J140-027" and panel.records[-1]["kind"] == "status",
                    "later frames changed the open position or did not update independent history")
            timeout, = unpack("<H", guest.cpu.mem_read(rom(0x202DE59A), 2))
            for age in (timeout, timeout+1):
                guest.cpu.mem_write(WINDOW_AGE, pack("<H", age))
                panel.refresh()
                require(panel.window() == ([13, 0] if age == timeout else [0, 0]), "wrong native timer boundary")
            require([hex(rom(CLOSE)), hex(rom(0x20048648)), 1] in panel.trace, "APRS timer bypassed the native close")
            panel.refresh()
            panel.frame("04-fm-aprs-timeout", "FM", action={"elapsed_ticks": timeout+1})
            hit = panel.tap_position(aprs=True)
            panel.frame("05-fm-aprs-icon-reopen", "FM", item=panel.latest_position, action={"touch": [401, 101], "hit": hit})
            panel.exit()
            panel.frame("06-fm-aprs-physical-exit", "FM", action="EXIT")
            panel.tap_position(aprs=True)
            require(guest.click(375, 244) == 0x21A and
                    [hex(rom(CLOSE)), hex(rom(0x20089DE0)), 1] in panel.trace,
                    "original screen return failed")
            panel.refresh()
            panel.frame("07-fm-aprs-screen-return", "FM", action={"touch": [375, 244], "hit": 0x21A})
        elif not events:
            require(panel.latest_position is None and panel.window() == [0, 0] and
                    not any(guest.cpu.mem_read(panel.symbols["aprs_strip"], 24)),
                    "invalid frame showed a notification")
        after = panel.originals()
        require(before == after and not panel.dv_writes and not panel.eeprom_writes,
                f"{key}: DV record or EEPROM write {panel.dv_writes[:10]}, {panel.eeprom_writes}, {before == after}")
        panel.check_writes = False
        if main_case:
            panel.mode(9)
            panel.tap_position(aprs=False)
            labels = panel.frame("08-dv-after", "DV", words=(DV_CALL.decode(), DV_TEXT.decode(), "35ﾟ30.00'N139ﾟ31.00'E"))
            require("N0CALL-7" not in labels and panel.frames[0]["png_sha256"] == panel.frames[-1]["png_sha256"],
                    "original DV popup changed after APRS")
        cases[key] = dict(wav=str(wav), records=list(panel.records), latest_position=panel.latest_position,
                          dv_before=before, dv_after=after, dv_guest_writes=panel.dv_writes,
                          eeprom_writes=panel.eeprom_writes, frames=panel.frames,
                          audio_dma_blocks=native["blocks"], bad_fcs_candidates=panel.count("rx_bad_fcs"))
        print(f"{key}: {len(panel.records)} APRS records, no DV writes", flush=True)
    guest = original_fm(images, output, rom=region_rom)
    panel = Panel(guest, output, task, european=european)
    call(guest.cpu, guest.rom(ALERT_SHOW), DUPLICATE_CALLSIGN, 0, 0)
    alarm = "Duplicate Call Sign."
    labels = panel.frame("09-fm-stock-alarm", "FM", words=(alarm,))
    require(panel.window() == [0, 0], "wrong stock alert fixture")
    prior = previous["cases"]["continuous"]["frames"][0]
    source = read_wav(fixture / "continuous-source48.wav")[:prior["end_sample"] + 144]
    capture(guest, source, {}, task=panel.symbols["aprs_j140_record_step"], after_poll=panel.observe_poll)
    labels = panel.frame("10-fm-alarm-keeps-priority", "FM", words=(alarm,))
    require(panel.count("record_count") == 1 and panel.window() == [0, 0],
            "position packet preempted the original warning or was lost")
    guest.press_exit()
    panel.refresh()
    require(not int.from_bytes(guest.cpu.mem_read(ALERT_STATE, 2), "little") and panel.window() == [0, 0],
            "EXIT did not dismiss the original warning first")
    panel.tap_position(aprs=True)
    panel.frame("11-fm-position-after-alarm", "FM", item=panel.latest_position)
    report = dict(scope="SSIF0 and native ARM task bodies, original panel; host paces calls and reads evidence",
                  region="E140" if european else "J140", dat_sha256=sha256(package).hexdigest(),
                  main_sha256=sha256(images[0]).hexdigest(),
                  arm_sha256=None if task[0] is None else sha256(task[0]).hexdigest(),
                  protected_dv_ranges={name: {"address": hex(address), "bytes": size}
                                       for name, (address, size) in WATCH_RANGES.items()}, cases=cases,
                  stock_alert_priority=dict(original_warning=alarm, frames=panel.frames))
    (output / "replay.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("dat", "fixture", "reference", "output"):
        parser.add_argument(option, type=Path)
    args = parser.parse_args()
    replay(args.dat, args.fixture, args.reference, args.output)
