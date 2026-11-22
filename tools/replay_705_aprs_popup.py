"""Render the four APRS reference layouts from audio on either 1.40 ARM panel."""

import argparse
from hashlib import sha256
import json
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path
from struct import pack
from subprocess import run

from PIL import Image

from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_feedback import BEEP, BEEP_ENABLE, SEQUENCER
from tools.replay_705_aprs_fm import GUARD, ax25_burst, capture, load_aprs_panel, original_fm, require
from tools.replay_705_aprs_panel import Panel
from tools.replay_705_aprs_task import build_task, e140_rom
from tools.replay_705_gps_inputs import GPS_EXPIRE, GPS_MODE, NO_FIX, POSITION_AGE
from tools.replay_705_settings import GRID_PAGE, TOUCH_POLL


HERE = (39 + 50/60, 116 + 36/60)
FIX = "GPRMC,120000.00,A,3950.0000,N,11636.0000,E,0.0,0.0,211126,,,A"
REPEATER_COMMENT = "PHG1324 145.500 MHz T100 QSO via NORTH RIDGE"
MOBILE_COMMENT = " QSO AT THE NORTH GATE AFTER SUNSET"
LONG_WORD = "W" * 96
CASES = (
    ("01-position-beacon", "BI1BIF-9", "!3955.00N/11630.00E>085/033", "POSITION BEACON",
     ("LAT", "39ﾟ55.00'N", "LON", "116ﾟ30.00'E", "SPEED", "61 km/h", "COURSE", "085ﾟ")),
    ("02-weather-station", "BI1WX-1", "@211230z3953.30N/11631.80E_315/008g010t054h48b10180wRSW", "WEATHER STATION",
     ("TEMP", "12ﾟC", "HUM", "48%", "WIND", "NW 13 km/h", "PRESS", "1018 hPa")),
    ("03-aprs-igate", "BI1GAT-10", "!3952.30NR11632.70E&RF ONLY UPLINK THROUGH THE SUMMIT RELAY", "APRS IGATE",
     ("MODE", "RX ONLY", "LAT", "39ﾟ52.30'N", "LON", "116ﾟ32.70'E")),
    ("04-personal-station", "BI1BIF-7", "=3950.60N/11635.10E[WALKING", "PERSONAL STATION",
     ("LAT", "39ﾟ50.60'N", "LON", "116ﾟ35.10'E", "COMMENT", "WALKING")),
    ("08-position-symbol-r", "BG1ESR-2", "!3955.12N/11625.25Er" + REPEATER_COMMENT, "POSITION BEACON",
     ("LAT", "39ﾟ55.12'N", "LON", "116ﾟ25.25'E", "COMMENT")),
    ("09-mobile-comment", "BI1BIF-9", "!3955.00N/11630.00E>085/033" + MOBILE_COMMENT, "POSITION BEACON",
     ("SPEED", "61 km/h", "COURSE", "085ﾟ", "COMMENT")),
    ("10-unbroken-comment", "BG1ESR-2", "!3955.12N/11625.25Er" + LONG_WORD, "POSITION BEACON", ("COMMENT",)),
)


def replay_symbol_atlas(images, output, european, symbols):
    output.mkdir(parents=True, exist_ok=True)
    guest = original_fm(images, output, rom=e140_rom if european else None)
    surface = guest.surface
    surface.pixels[:] = b"\0\0\0\xff" * (surface.width * surface.height)

    def draw(code, x, y):
        icon = int.from_bytes(code.encode(), "big")
        before = len(surface.pixel_writes)
        call(guest.cpu, symbols["aprs_draw_icon"], icon, x, y, 0)
        require(len(surface.pixel_writes) == before+1, f"symbol did not use the bitmap path: {code}")
        cell = b"".join(surface.pixels[4*(row*surface.width+x):4*(row*surface.width+x+24)]
                        for row in range(y, y+24))
        require(any(value for i, value in enumerate(cell) if i % 4 != 3), f"blank icon: {code}")
        return sha256(cell).hexdigest()

    base = {}
    for table, expected in (("/", 86), ("\\", 77)):
        count = 0
        for code in range(33, 127):
            if call(guest.cpu, symbols["aprs_symbol_label"], ord(table)*256+code):
                index = len(base)
                base[table+chr(code)] = draw(table+chr(code), index % 18 * 26, index // 18 * 26)
                count += 1
        require(count == expected, f"catalog coverage changed for table {table}")
    Image.frombytes("RGBA", (surface.width, surface.height), bytes(surface.pixels)).save(output/"base-icons.png")
    overlay = {ch: draw(ch+"&", 0, 0) for ch in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    require(len(set(overlay.values())) == 36, "overlay digits or letters are visually identical")
    report = dict(base_art=base, overlay_igate=overlay, application_sha256=sha256(images[0]).hexdigest())
    (output/"atlas.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")


def replay_compact_positions(images, output, european, symbols, decoder):
    cases = (
        ("compressed-car", "APDW16", "=/5L!!<*e7>7P[Trip", "/>",
         ("4930.00N", "07245.00W"), ("67 km/h", "088ﾟ", "Trip")),
        ("compressed-igate", "APDW16", "@092345zR5L!!<*e7& sTClimb", "R&",
         ("4930.00N", "07245.00W"), ("RX ONLY", "Climb")),
        ("compressed-number", "APDW16", "!c5L!!<*e7& sT", "2&",
         ("4930.00N", "07245.00W"), ()),
        ("mice", "TRSW1R", "`c0ol!O[/HIKING", "/[",
         ("4237.12N", "07120.83W"), ("HIKING",)),
        ("mice-old", "3351Q0", "'O(>\x22\x1eX>5SOUTH EAST", "5>",
         ("3351.10S", "15112.34E"), ("111 km/h", "260ﾟ", "SOUTH EAST")),
        ("mice-ambiguity", "3351ZL", "'O(>\x22\x1eX>5APPROXIMATE", "5>",
         ("3351.50S", "15112.50E"), ("~33ﾟ51.50'S", "APPROXIMATE")),
        ("uncompressed-ambiguity", "APDW16", "!3955.  N/11630.  E$PHONE", "/$",
         ("3955.50N", "11630.50E"), ("~39ﾟ55.50'N", "PHONE")),
        ("uncompressed-lat-ambiguity", "APDW16", "!3955.  N/11630.75E$PHONE", "/$",
         ("3955.50N", "11630.50E"), ("~116ﾟ30.50'E", "PHONE")),
        ("extra-symbol", "APDW16", "!3955.00N/11630.00E$PHONE", "/$",
         ("3955.00N", "11630.00E"), ("PHONE",)),
        ("tx-igate", "APDW16", "!3955.00NT11630.00E&TEST", "T&",
         ("3955.00N", "11630.00E"), ("TX IGATE",)),
        ("invalid-base91", "APDW16", "!/5L~!<*e7>7P[Bad", None, None, ()),
        ("invalid-mice", "APDWD6", "`c0ol!O[/Bad", None, None, ()),
    )
    reference_frames = [f"WB2OSZ>{dest}:{info}" for _, dest, info, icon, _, _ in cases if icon]
    ref = run([str(decoder.resolve(strict=True))], cwd=decoder.resolve().parent,
              input=("\n".join(reference_frames)+"\n").encode(), capture_output=True, check=True)
    log = ref.stdout.decode(errors="replace")
    output.mkdir(parents=True, exist_ok=True)
    (output / "dire-wolf-decode.txt").write_text(log, encoding="utf-8")
    for expected in ("N 49 30.0000, W 072 45.0002, 67 km/h", "course 88",
                     "N 42 37.1200, W 071 20.8300", "S 33 51.1000, E 151 12.3400"):
        require(expected in log, f"Dire Wolf did not find the reference {expected}")

    results, icon_pixels = {}, {}
    for name, dest, info, icon, coords, labels in cases:
        guest = original_fm(images, output, rom=e140_rom if european else None)
        panel = Panel(guest, output, (None, symbols), european=european)
        baseline = panel.originals()
        panel.check_writes = True
        stream = GUARD + ax25_burst(info, 22, source="WB2OSZ", destination=dest) + GUARD
        capture(guest, stream, {}, task=symbols["aprs_j140_record_step"], after_poll=panel.observe_poll)
        require(len(panel.records) == 1 and panel.records[0]["info_hex"] == info.encode().hex(),
                f"lost or changed RF record {name}")
        if icon:
            panel.frame(f"{name}-popup", "FM", words=("WB2OSZ", *labels))
            require(panel.window() == [13, 0] and panel.popup()[2:5] == (*coords, icon),
                    f"wrong decoded position {name}: {panel.popup()}")
            with Image.open(output / f"{name}-popup.png") as frame:
                icon_pixels[name] = sha256(frame.crop((185, 70, 209, 94)).tobytes()).hexdigest()
            panel.exit()
        else:
            require(panel.window() == [0, 0], f"malformed position opened a popup: {name}")
        guest.render()
        guest._press_key(1, 1)
        guest.render()
        guest.click(128, 55)
        history, png = guest.render()
        require("APRS RX List" in history and "WB2OSZ" in history, f"missing history {name}")
        (output / f"{name}-history.png").write_bytes(png)
        guest.click(128, 55)
        guest.render()
        require(panel.window() == [13, 0] and (not icon or panel.popup()[2:5] == (*coords, icon)),
                f"history did not reopen {name}")
        panel.exit()
        require("APRS RX List" in guest.render()[0], f"EXIT did not return to the history for {name}")
        require(baseline == panel.originals() and not panel.dv_writes and not panel.eeprom_writes,
                f"DV or EEPROM changed for {name}")
        results[name] = dict(raw=panel.records[0]["info_hex"], coordinates=coords, symbol=icon,
                             image=icon_pixels.get(name), history_reopened=True)
    require(len({icon_pixels[name] for name in ("compressed-igate", "compressed-number", "tx-igate")}) == 3,
            "distinct iGate overlays rendered identically")
    (output / "positions.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")


def reference_geometry(position, here=HERE):
    latitude, longitude = position["coordinates"]
    lat, lon = map(radians, here)
    other = radians(int(latitude[:2]) + float(latitude[2:-1])/60)
    delta = radians(int(longitude[:3]) + float(longitude[3:-1])/60) - lon
    east = sin(delta) * cos(other)
    north = cos(lat)*sin(other) - sin(lat)*cos(other)*cos(delta)
    dot = sin(lat)*sin(other) + cos(lat)*cos(other)*cos(delta)
    return 6371.0088 * atan2(hypot(east, north), dot), degrees(atan2(east, north)) % 360


def badge_layout(path):
    with Image.open(path) as png:
        frame = png.convert("RGB")
    pixel = frame.getpixel
    left, top, right, bottom = 346, 29, 413, 48
    require(all(pixel((x, y)) == (0, 0, 0) for x in (left, right) for y in (top, bottom)),
            f"{path.name}: square badge corner")
    edge = pixel((380, top))
    require(min(edge) >= 75 and all(pixel(point) == edge for point in
            ((380, bottom), (left, 38), (right, 38))), f"{path.name}: missing badge outline")
    rows = [y for y in range(top+1, bottom)
            if any(min(pixel((x, y))) > 110 for x in range(left+4, right-3))]
    require(rows and abs(min(rows) + max(rows) - top - bottom) <= 1,
            f"{path.name}: badge label is not vertically centered")
    return dict(outline_y=[top, bottom], title_y=[26, 51], label_y=[min(rows), max(rows)], radius_px=5)


def compass_images(guest, count, *, filtered=False):
    masks = [item for item in guest.surface.image_draws if item["size"] == [91, 91]]
    require([list(map(abs, image["matrix"][:2])) for image in masks] == [[1, 1]] * count,
            f"unexpected native compass or needle transform: {masks}")
    if filtered:
        require(int(masks[0]["source"], 16) < 0x20000000 <= int(masks[1]["source"], 16),
                "needle must use the filtered mask at native resolution")
    return masks


def replay_manual(panel, item):
    guest, cpu = panel.guest, panel.cpu
    # Seed the stock Manual Position fields as loaded from settings.
    cpu.mem_write(0x203EA85D, pack(">BHcBHc", 39, 47125, b"N", 116, 37476, b"E"))
    cpu.mem_write(POSITION_AGE, b"\0")
    call(cpu, guest.rom(GPS_EXPIRE))
    require(not call(cpu, guest.rom(0x20074650)), "live GPS was still valid")
    results = {}

    def choose(source, choice, *, check_manual_position=False):
        # Use the original settings page and touch action for GPS Select.
        panel.check_writes = False
        guest.press_menu()
        guest.render()
        if cpu.mem_read(GRID_PAGE, 1)[0] != 2:
            guest.click(274, 251)
            guest.render()
        for index, (x, y) in enumerate(((145, 178), (130, 54), (130, 54), (130, 55 + 61*choice))):
            guest.click(x, y)
            labels, _ = guest.render()
            if index == 2:
                require({"GPS Select", "OFF", "ON", "Manual"} <= set(labels), "original GPS source picker missing")
        require("GPS SET" in labels and source in labels and cpu.mem_read(GPS_MODE, 1)[0] == choice,
                f"original GPS Select did not apply {source}: {labels}")
        if check_manual_position:
            guest.click(130, 177)
            labels, png = guest.render()
            require({"MANUAL POSITION", " 39ﾟ47.12'N", "116ﾟ37.47'E"} <= set(labels),
                    f"original Manual Position showed unexpected coordinates: {labels}")
            (panel.output / "11-original-manual-position.png").write_bytes(png)
        for _ in range(5):
            if "FM" in labels:
                break
            guest.press_exit()
            labels, _ = guest.render()
        require("FM" in labels, "could not leave the original GPS settings")
        panel.check_writes = True
        panel.refresh()
        return panel.originals()

    manual_stock = choose("Manual", 2, check_manual_position=True)
    panel.tap_position(aprs=True)
    labels = panel.frame("12-manual-position", "FM", item=item, words=("MANUAL", "WALKING"))
    km = float(next(label[:-3] for label in labels if label.endswith(" km")))
    bearing = int(next(label[:3] for label in labels if "ﾟ " in label))
    reference = reference_geometry(item["position"], (39 + 47.125/60, 116 + 37.476/60))
    require(abs(km-reference[0]) < 0.02 and abs(bearing-reference[1]) < 0.6,
            f"APRS did not use the original manual coordinates: {(km, bearing)} vs {reference}")
    require(cpu.mem_read(POSITION_AGE, 1)[0] == 0, "manual position depended on a live GPS fix")
    results["manual"] = dict(frame=panel.frames[-1], shown_km=km, bearing=bearing,
                             badge=badge_layout(panel.output / "12-manual-position.png"))
    panel.exit()

    # Keep a fresh satellite position alongside the manual position in the replay.
    panel.feed_gps(FIX)
    require(call(cpu, guest.rom(0x20212BC8)) and cpu.mem_read(POSITION_AGE, 1)[0] == 120,
            "fixture did not publish a separate live position")
    guest._press_key(1, 1)
    require("APRS RX List" in guest.render()[0], "FM QUICK history entry missing")
    guest.click(128, 55)
    require(item["source"] in guest.render()[0], "received position missing from history")
    guest.click(128, 55)
    labels = panel.frame("12b-manual-from-history", "FM", item=item, words=("MANUAL", f"{km:.2f} km", "WALKING"))
    require("GPS" not in labels, "a fresh satellite position overrode GPS Select = Manual")
    results["manual_with_fresh_live_cache"] = panel.frames[-1]
    panel.exit()
    require("APRS RX List" in guest.render()[0], "EXIT did not return to the history")
    guest.press_exit()
    guest.render()
    require(manual_stock == panel.originals(), "manual APRS detail changed stock GPS/DV state")

    off_stock = choose("OFF", 0)
    panel.tap_position(aprs=True)
    labels = panel.frame("13-manual-position-off", "FM", item=item, words=("NO FIX", "-- km", "WALKING"))
    require("MANUAL" not in labels and not any("ﾟ " in label for label in labels), "GPS OFF used the old manual position")
    results["off"] = panel.frames[-1]
    panel.exit()
    require(off_stock == panel.originals(), "GPS OFF APRS detail changed stock GPS/DV state")

    live_stock = choose("ON", 1)
    panel.tap_position(aprs=True)
    labels = panel.frame("14-gps-on-waits-for-fix", "FM", item=item, words=("NO FIX", "-- km", "WALKING"))
    require("MANUAL" not in labels, "GPS ON fell back to the manual position")
    panel.feed_gps(FIX)
    panel.refresh()
    labels = panel.frame("15-gps-on-reacquired", "FM", item=item, words=("GPS", "WALKING"))
    require(next(label for label in labels if label.endswith(" km")) != f"{km:.2f} km",
            "GPS ON did not replace the manual geometry")
    results["live"] = panel.frames[-1]
    panel.exit()
    require(live_stock == panel.originals() and not panel.dv_writes and not panel.eeprom_writes,
            "APRS position reads modified GPS/DV or EEPROM")
    return results


def replay(images, output, european=False, *, installed_symbols=None):
    output.mkdir(parents=True)
    task = build_task(output, european=european) if installed_symbols is None else (None, installed_symbols)
    region_rom = e140_rom if european else None

    def trace_beep(guest):
        events = []
        address = guest.rom(BEEP)
        guest.cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: events.append(
            (c.reg_read(arm.UC_ARM_REG_LR), c.reg_read(arm.UC_ARM_REG_R0))), begin=address, end=address)
        return events

    def finish_short_beep(guest):
        # Advance the original sequencer before a second simulated action.
        duration = guest.cpu.mem_read(SEQUENCER + 8, 1)
        guest.cpu.mem_write(0x20401FBD, bytes(duration))
        call(guest.cpu, 0x2000E868 - (244 if european else 0))
        require(not guest.cpu.mem_read(SEQUENCER, 1)[0], "stock one-shot did not end")
        # EXIT has its own confirmation and its release may be deferred until the tone ends.
        for _ in range(7):
            call(guest.cpu, guest.rom(TOUCH_POLL))

    # Feed a received position at the native DV record boundary with confirmation Beep enabled.
    control = original_fm(images, output, rom=region_rom)
    dv = Panel(control, output, task, channel=0, european=european)
    control.cpu.mem_write(BEEP_ENABLE, b"\1")
    dv_beeps = trace_beep(control)
    dv.seed_dv()
    require(dv.window() == [13, 0] and not dv_beeps and not control.cpu.mem_read(SEQUENCER, 1)[0],
            "stock D-PRS position opened with an audible confirmation")
    _, stock_png = control.render()
    (output / "00-stock-dprs-position.png").write_bytes(stock_png)
    dv_baseline = dict(position_popup=True, beep_requests=dv_beeps.copy(), compass=compass_images(control, 2))
    results = []
    for name, station, info, title, fields in CASES:
        guest = original_fm(images, output, rom=region_rom)
        panel = Panel(guest, output, task, european=european)
        panel.feed_gps(FIX)
        beep_enabled = name != "03-aprs-igate"
        guest.cpu.mem_write(BEEP_ENABLE, bytes((beep_enabled,)))
        beeps = trace_beep(guest)
        baseline = panel.originals()
        panel.check_writes = True
        samples = GUARD + ax25_burst(info, 22, source=station) + GUARD
        capture(guest, samples, {}, task=panel.symbols["aprs_j140_record_step"], after_poll=panel.observe_poll)
        item = panel.latest_position
        require(len(panel.records) == 1 and item and item["info_hex"] == info.encode().hex(), "incorrect RF record")
        effective = bool(guest.cpu.mem_read(SEQUENCER, 1)[0])
        require(len(beeps) == 1 and beeps[0][1] == 8 and effective == beep_enabled,
                f"{name}: expected one native notification request and Beep preference, {beeps=} {effective=}")
        auto_beep = beeps[0]
        labels = panel.frame(name, "FM", item=item, words=(title, "GPS", *fields))
        require(panel.popup()[4] not in labels, f"{name}: icon code was drawn")
        comment_rows = []
        if "COMMENT" in labels:
            comment_rows = labels[labels.index("COMMENT") + 1:-1]
            expected = item["position"]["comment"]
            if name == "09-mobile-comment":
                expected = MOBILE_COMMENT
            require(panel.popup()[-1] == expected, f"{name}: stored comment changed")
            displayed = "".join("".join(comment_rows).split())
            compact = "".join(expected.split())
            if name == "10-unbroken-comment":
                require(len(comment_rows) == 4 and displayed.endswith("...") and compact.startswith(displayed[:-3])
                        and len(displayed) > 43, "a long unbroken word did not fill the available lines")
            else:
                require(displayed == compact, f"{name}: display lost comment text: {comment_rows}")
                if name != "04-personal-station":
                    require(len(comment_rows) >= 2, f"{name}: long comment did not wrap")
        with Image.open(output / f"{name}.png") as image:
            frame = image.convert("RGB")
        icon_rows, call_rows = [], []
        for y in range(68, 94):
            for x in range(185, 209):
                r, g, b = frame.getpixel((x, y))
                if max(r, g, b) > 64:
                    icon_rows.append(y)
            for x in range(217, 355):
                if min(frame.getpixel((x, y))) > 130:
                    call_rows.append(y)
        centre_offset = (min(icon_rows) + max(icon_rows) - min(call_rows) - max(call_rows)) / 2
        require(abs(centre_offset) <= 2, f"{name}: icon is away from the callsign centre: {centre_offset}")
        km = float(next(label[:-3] for label in labels if label.endswith(" km")))
        bearing = int(next(label[:3] for label in labels if "ﾟ " in label))
        expected_km, expected_bearing = reference_geometry(item["position"])
        require(abs(km-expected_km) < 0.06 and abs(bearing-expected_bearing) < 1.5,
                f"unexpected GPS geometry: {(km, bearing)} relative to {(expected_km, expected_bearing)}")
        results.append(dict(source=station, wire=info, shown_km=km, bearing=bearing, frame=panel.frames[-1],
                            comment_lines=comment_rows,
                            gps_badge=badge_layout(output / f"{name}.png"),
                            compass=compass_images(guest, 2, filtered=True),
                            icon_centre_offset_px=centre_offset,
                            beep_enabled=beep_enabled, beep_requested=auto_beep[1], stock_sequencer_active=effective))
        panel.exit()
        if name == "04-personal-station":
            finish_short_beep(guest)
            # Isolate the APRS reopen from the separate native touch confirmation.
            guest.cpu.mem_write(BEEP_ENABLE, b"\0")
            guest.render()
            guest.cpu.mem_write(POSITION_AGE, b"\x74")
            panel.feed_gps(NO_FIX)
            require(guest.cpu.mem_read(POSITION_AGE, 1)[0] == 116 and call(guest.cpu, guest.rom(0x20074650)),
                    "void NMEA unexpectedly refreshed or invalidated the retained fix")
            panel.tap_position(aprs=True)
            current = panel.frame("05-fix-current", "FM", item=item, words=("GPS", "WALKING"))
            distance = next(label for label in current if label.endswith(" km"))
            guest.cpu.mem_write(POSITION_AGE, b"\x73")
            panel.refresh()
            panel.frame("06-fix-last", "FM", item=item, words=("LAST FIX", distance, "WALKING"))
            results[-1]["last_fix"] = panel.frames[-1]

            guest.cpu.mem_write(POSITION_AGE, b"\0")
            require(call(guest.cpu, guest.rom(0x20074650)), "stock fix expired before its periodic expiry call")
            panel.refresh()
            labels = panel.frame("05-position-without-fix", "FM", item=item, words=("NO FIX", "-- km", "WALKING"))
            require(not any("ﾟ " in label for label in labels), "old bearing remained visible with expired GPS")
            compass_images(guest, 1)
            results[-1]["no_fix"] = panel.frames[-1]
            call(guest.cpu, guest.rom(GPS_EXPIRE))
            require(not call(guest.cpu, guest.rom(0x20074650)), "stock expiry left the valid flag set")
            panel.feed_gps(FIX.replace("3950.0000", "3949.0000"))
            require(guest.cpu.mem_read(POSITION_AGE, 1)[0] == 120, "fresh NMEA did not reload the fix age")
            panel.refresh()
            updated = panel.frame("07-fix-reacquired", "FM", item=item, words=("GPS", "WALKING"))
            require(next(label for label in updated if label.endswith(" km")) != distance,
                    "fresh local fix did not update the open window")
            results[-1]["reacquired_fix"] = panel.frames[-1]
            panel.exit()
        require(beeps.count(auto_beep) == 1, "manual position reopen repeated the automatic notification tone")
        require(baseline == panel.originals() and not panel.dv_writes and not panel.eeprom_writes,
                f"{name}: APRS affected native DV or EEPROM")
        if name == "04-personal-station":
            results[-1]["manual_position"] = replay_manual(panel, item)

    combined = Image.new("RGB", (984, 568), (17, 22, 28))
    for i, (name, *_rest) in enumerate(CASES[:4]):
        with Image.open(output / f"{name}.png") as frame:
            require(frame.size == (480, 272), "not a native 480 × 272 frame")
            combined.paste(frame, (8 + 488*(i % 2), 8 + 280*(i // 2)))
    combined.save(output / "aprs-popup-baseline.png")
    report = dict(region="E140" if european else "J140", image_sha256=sha256(images[0]).hexdigest(),
                  arm_sha256=None if task[0] is None else sha256(task[0]).hexdigest(),
                  stock_dprs_control=dv_baseline, cases=results,
                  last_fix_badge=badge_layout(output / "06-fix-last.png"),
                  no_fix_badge=badge_layout(output / "05-position-without-fix.png"))
    (output / "popup.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    images, european = load_aprs_panel(args.dat.read_bytes())
    replay(images, args.output, european)
