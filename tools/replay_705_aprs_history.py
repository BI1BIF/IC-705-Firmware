"""Replay FM QUICK, native history paging, packet details and both EXITs."""

import argparse
import json
from pathlib import Path
from struct import pack

from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_feedback import BEEP
from tools.probe_705_rx_audio import DMAC, FRAMES, completed
from tools.replay_705_aprs_fm import GUARD, LAYOUT, ax25_burst, load_aprs_panel, original_fm, require
from tools.replay_705_aprs_panel import Panel
from tools.replay_705_aprs_rx import FRAME_STRIDE
from tools.replay_705_aprs_task import APRS_HISTORY, build_task, e140_rom
from tools.replay_705_gps_inputs import GPS_MODE, POSITION_AGE, RMC
from tools.replay_705_vfo_split import ACTIVE_HZ


SELECTOR, RTC = 0x203e1a28, 0x2038079a


def replay(images, output, european, *, installed_symbols=None):
    output.mkdir(parents=True, exist_ok=True)
    task = build_task(output, european=european) if installed_symbols is None else (None, installed_symbols)
    guest = original_fm(images, output, rom=e140_rom if european else None)
    panel = Panel(guest, output, task, european=european)
    cpu, rom = guest.cpu, guest.rom
    block = 0
    proof = {}
    taps = []
    beep = rom(BEEP)
    cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: taps.append(c.reg_read(arm.UC_ARM_REG_R0)),
                 begin=beep, end=beep)

    def picker():
        return int.from_bytes(cpu.mem_read(SELECTOR, 2), "little")

    def screen(name, *words):
        labels, png = guest.render()
        require(set(words) <= set(labels), f"{name} missing {words}: {labels}")
        (output / f"{name}.png").write_bytes(png)
        proof[name] = dict(labels=labels, picker=picker(), window=panel.window())
        return labels

    def exit_to(selector=0):
        guest.press_exit()
        panel.refresh()
        require(picker() == selector and panel.window() == [0, 0],
                f"physical EXIT did not reach picker {selector}: {picker()} {panel.window()}")

    def quick_to_list(name):
        guest._press_key(1, 1)
        require(picker() == 1, "physical QUICK did not open the stock picker")
        screen(name, "QUICK MENU", "APRS RX List", "Group Select")
        taps.clear()
        require(guest.click(128, 55) == 0x221 and picker() == APRS_HISTORY and [n for n in taps if n] == [1],
                f"native QUICK history action or confirmation failed: {picker()}, {taps}")

    def receive(info, source, clock, *, date="26123104", bad_fcs=False):
        nonlocal block
        cpu.mem_write(RTC, bytes.fromhex(date + clock))
        data = GUARD + ax25_burst(info, 22, source=source, bad_fcs=bad_fcs) + GUARD
        data += (0,) * (-len(data) % FRAMES)
        before = panel.count("record_count")
        for start in range(0, len(data), FRAMES):
            completed(cpu, rom(LAYOUT["rec_dma"]), DMAC + 0xE4, LAYOUT["rec_bank"], block,
                      data[start:start+FRAMES], (0,) * FRAMES, timeout_us=0)
            block += 1
            if block % 6 == 0 or start + FRAMES == len(data):
                call(cpu, panel.symbols["aprs_j140_record_step"], timeout_us=0)
                panel.refresh()
        require(panel.count("record_count") - before == int(not bad_fcs),
                "history disagrees with the native receive counter")
        if panel.window() == [13, 0]:
            exit_to()

    originals = panel.originals()
    quick_to_list("01-quick")
    screen("02-empty", "APRS RX List", "1/1", "No APRS packets")
    guest.click(128, 55)
    require(picker() == APRS_HISTORY and panel.window() == [0, 0], "empty row opened a detail")
    exit_to()
    receive("!3531.00N/13930.00E>EARLIEST", "N0CAR-9", "235956")
    cpu.mem_write(GPS_MODE, b"\0")
    receive("!3531.00N/13930.00E_315/012t054h48b10180", "N0WX-1", "235957")
    cpu.mem_write(GPS_MODE, b"\1")
    receive(">AT THE TRAILHEAD", "N0HIK-7", "235958")
    receive("!3531.00NR13930.00E&IGATE", "N0GAT-10", "235959")
    receive("!3531.00N/13930.00E[WALKING", "N0PED-7", "000000", date="27010105")
    receive(":N0CAR-9  :MEET AT NOON{12", "N0MSG-2", "000001", date="27010105")
    receive(">BAD FCS", "N0BAD", "000002", date="27010105", bad_fcs=True)
    # This fix arrives after all six records. The older distances are immutable.
    panel.feed_gps("GPRMC,130000.00,A,3950.0000,N,11636.0000,E,0.0,0.0,211126,,,A")

    # Change both the native clock and the FM channel after reception.
    cpu.mem_write(RTC, bytes.fromhex("27010206120030"))
    for address in (ACTIVE_HZ, 0x203EBC2F):
        cpu.mem_write(address, pack("<I", 145_000_000))
    panel.refresh()
    quick_to_list("03-quick-away")
    expected = ["N0MSG-2", "00:00:01", "2027-01-01", "N0PED-7", "00:00:00", "2027-01-01",
                "N0GAT-10", "23:59:59", "2026-12-31", "N0HIK-7", "23:59:58", "2026-12-31"]
    labels = screen("04-newest-first", "APRS RX List", "1/2", *expected)
    require(labels.count("1.85 km")==2 and labels[labels.index("N0PED-7")+1]=="1.85 km" and
            labels[labels.index("N0GAT-10")+1]=="1.85 km", f"reception distances or station rows changed: {labels}")
    require([label for label in labels if label in expected] == expected, "RX order or captured timestamps changed")
    clock_rows = [(text, event["glyphs"][0]["offset"][1]) for text, event in zip(labels, guest.surface.events)
                  if text in expected and (":" in text or text[:2] == "20")]
    require(len(clock_rows) == 8 and all(clock_rows[i][1] > clock_rows[i+1][1] for i in range(0, 8, 2)),
            f"date must be below the time in each row: {clock_rows}")
    require("N0BAD" not in labels, "bad FCS reached the native list")
    require(len(guest.surface.pixel_writes) >= 4, "list did not draw its four station icons")
    taps.clear()
    guest.click(128, 55)
    require([n for n in taps if n] == [1], f"history selection used the wrong confirmation: {taps}")
    screen("05-message-detail", "APRS MESSAGE", "N0MSG-2", "TO", "N0CAR-9", "MEET AT NOON", "ID", "12")
    require(panel.window() == [13, 0], "message did not open the native detail window")
    exit_to(APRS_HISTORY)
    screen("06-exit-to-list", "APRS RX List", *expected)

    guest.click(394, 165)
    older=screen("07-older-page", "2/2", "N0WX-1", "23:59:57", "N0CAR-9", "23:59:56", "2026-12-31")
    require(older.count("1.85 km")==1 and older[older.index("N0CAR-9")+1]=="1.85 km" and
            older[older.index("N0WX-1")+1]=="23:59:57","no-fix record acquired a later distance")
    guest.click(128, 118)
    screen("08-position-detail", "POSITION BEACON", "N0CAR-9", "EARLIEST")
    require(panel.window() == [13, 0], "older row did not open its own native detail")
    exit_to(APRS_HISTORY)
    screen("09-exit-to-older-page", "2/2", "N0WX-1", "N0CAR-9")
    exit_to()
    require("APRS RX List" not in screen("10-exit-to-fm", "FM"), "second EXIT left the history on screen")
    require(panel.originals() == originals, "APRS history touched the DV records")

    # Replay already validated decoder output to fill and wrap the native ring.
    symbols = panel.symbols
    valid = bytes(cpu.mem_read(panel.count("records") + 2*FRAME_STRIDE, FRAME_STRIDE))
    for i in range(60):
        written = int.from_bytes(cpu.mem_read(symbols["aprs_rx_written"], 4), "little")
        cpu.mem_write(symbols["aprs_rx_frames"] + written % 4 * FRAME_STRIDE, valid)
        cpu.mem_write(symbols["aprs_rx_written"], pack("<I", written+1))
        date = bytes.fromhex("27000206" if i == 59 else "27010206")
        cpu.mem_write(RTC, date + bytes((0x12, 0x10, (i//10 << 4) | (i % 10))))
        call(cpu, symbols["aprs_record_receive"])
    require(panel.count("record_count") == 66, "receive history did not wrap")
    quick_to_list("11-quick-after-wrap")
    screen("12-wrapped-newest", "1/16", "N0HIK-7", "12:10:59", "12:10:56", "-"*10, "2027-01-02")
    for _ in range(15):
        guest.click(394, 165)
    labels = screen("13-wrapped-oldest", "16/16", "N0MSG-2", "N0PED-7", "N0GAT-10", "N0HIK-7", "23:59:58", "2026-12-31")
    require("N0CAR-9" not in labels and "N0WX-1" not in labels, "overwritten entries stayed visible")
    guest.click(128, 241)
    screen("14-status-detail", "APRS STATUS", "N0HIK-7", "AT THE TRAILHEAD")
    guest.click(373, 241)
    panel.refresh()
    screen("15-back-to-last-page", "16/16", "N0HIK-7")
    guest.click(394, 245)
    require(picker() == 0 and panel.window() == [0, 0], "screen Back did not leave the list")

    for address in (ACTIVE_HZ, 0x203EBC2F):
        cpu.mem_write(address, pack("<I", panel.count("channel_hz")))
    cpu.mem_write(GPS_MODE, b"\x02")
    cpu.mem_write(0x203ea85d, pack(">BHcBHc", 35, 31000, b"N", 139, 30000, b"E"))
    receive("!3531.00N/13930.00E>MANUAL", "N0SAME-9", "180000")
    cpu.mem_write(GPS_MODE, b"\x01")
    panel.feed_gps(RMC.format(time="181000"))
    cpu.mem_write(POSITION_AGE, b"\x30")
    receive("!3531.00N/13930.00E>LAST", "N0SAME-9", "181000")
    cpu.mem_write(GPS_MODE, b"\0")
    quick_to_list("16a-same-station-quick")
    recent = screen("16b-same-station-distances", "~1.85 km", "0.00 km", "18:00:00", "18:10:00")
    recent = recent[recent.index("APRS RX List")+1:]
    require([recent[i+1] for i, name in enumerate(recent) if name == "N0SAME-9"] == ["~1.85 km", "0.00 km"],
            f"same callsign lost its per-frame distances: {recent}")
    exit_to()

    panel.mode(9)
    guest._press_key(1, 1)
    require("APRS RX List" not in screen("16-dv-original-quick", "DV", "QUICK MENU"), "APRS row appeared in DV")
    exit_to()
    (output / "history.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    images, european = load_aprs_panel(args.source.read_bytes())
    replay(images, args.output, european)
