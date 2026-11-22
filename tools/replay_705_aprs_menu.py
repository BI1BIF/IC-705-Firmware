"""Drive the native GPS/APRS menu, FM encoder and receive on J140 or E140."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack

from PIL import Image

from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_feedback import BEEP
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_rx_audio import DMAC, FRAMES, completed
from tools.render_705_display import PAGE
from tools.replay_705_aprs_fm import GUARD, LAYOUT, ax25_burst, load_aprs_panel, original_fm, require
from tools.replay_705_aprs_panel import Panel
from tools.replay_705_aprs_task import FM_HZ, build_task, e140_rom
from tools.replay_705_ptt_tune import INIT_RANGES
from tools.replay_705_settings import GRID_PAGE
from tools.replay_705_vfo_split import ACTIVE_HZ, SELECT_VFO, seed_vfos


ENCODER_STATUS, ENCODER_COUNT = 0xFCFF0385, 0xFCFF0386
ENCODER_SAMPLE, APPLY_DIAL = 0x2008D484, 0x20045DD4
GPS_TX_MENU, DV_TX_MODE, SELECTOR = 286, 0x203EB172, 0x203E1A28


def replay(images, output, european, *, installed_symbols=None):
    output.mkdir(parents=True, exist_ok=True)
    task = build_task(output, european=european) if installed_symbols is None else (None, installed_symbols)
    guest = original_fm(images, output, rom=e140_rom if european else None)
    rom = guest.rom
    cpu = guest.cpu
    panel = Panel(guest, output, task, channel=0, european=european)
    seed_vfos(cpu, pair=(FM_HZ, 145_000_000))
    call(cpu, rom(INIT_RANGES))
    call(cpu, rom(SELECT_VFO[0]))
    panel.mode(7)
    cpu.mem_map(ENCODER_COUNT & ~4095, 4096)
    cpu.mem_write(ENCODER_STATUS, b"\xc0")
    steps, tuning = {}, []
    block = 0
    tones = []
    beep = rom(BEEP)
    cpu.hook_add(uc.UC_HOOK_CODE, lambda c,*_:tones.append(c.reg_read(arm.UC_ARM_REG_R0)),
                 begin=beep, end=beep)

    def read(address, size):
        return int.from_bytes(cpu.mem_read(address, size), "little")

    def trace(c, _, _address, size, value, _data):
        tuning.append(dict(pc=hex(c.reg_read(arm.UC_ARM_REG_PC)), size=size, hz=value))

    cpu.hook_add(uc.UC_HOOK_MEM_WRITE, trace, begin=ACTIVE_HZ, end=ACTIVE_HZ+3)

    def snapshot(name, *words):
        labels, screen = guest.render()
        require(set(words) <= set(labels), f"{name}: missing native labels: {labels}")
        steps[name] = dict(labels=labels, frequency=read(ACTIVE_HZ, 4), configured=panel.count("channel_hz"),
                           page=read(PAGE+1, 1), grid=read(GRID_PAGE, 1), window=panel.window(),
                           frames=panel.count("record_count"), pcm_samples=panel.count("rx_samples"),
                           sha256=sha256(screen).hexdigest())
        (output / f"{name}.png").write_bytes(screen)
        return labels

    def grid(page):
        guest.press_menu()
        guest.render()
        require(read(PAGE+1, 1) == 2, "physical MENU did not open the grid")
        if read(GRID_PAGE, 1) != page:
            key = ((182, 247), 0x1BA) if page == 1 else ((274, 251), 0x1BB)
            require(guest.click(*key[0]) == key[1],
                    "page control did not use the native touch rectangle")
            guest.render()
        require(read(GRID_PAGE, 1) == page, "wrong original grid page")

    def open_gps():
        grid(2)
        require(guest.click(145, 178) == 0x1B6 and guest.state()["menu"] == 218, "original GPS tile changed")
        guest.render()

    def aprs_from_gps():
        require(guest.click(160, 165) == 0x20 and guest.state()["menu"] == 218,
                "APRS failed to open from the GPS list")
        guest.render()

    def open_aprs():
        open_gps()
        aprs_from_gps()

    def mode_screen(name, selected):
        snapshot(name, "APRS Mode", "RX Only", "RX & TX")
        highlighted = ["".join(chr(g["key"]) for g in event["glyphs"]) for event in guest.surface.events
                       if event["rgba"] == "000000ff"]
        require(selected in highlighted, f"{name}: selected option not highlighted: {highlighted}")

    def open_tx_mode():
        open_gps()
        tones.clear()
        require(guest.click(160, 104) == 0x1F and guest.state()["menu"] == GPS_TX_MENU,
                "original GPS TX Mode touch changed")
        guest.render()
        require([n for n in tones if n] == [1], f"unexpected stock GPS selection tone: {tones}")

    def open_mode(name, selected):
        require(guest.click(150, 240) == 0x41, "APRS did not open in GPS TX Mode")
        mode_screen(name, selected)

    def chosen_mode(name, option):
        tones.clear()
        require(guest.click(115, 55 + 61*option) == 0x221 + option and panel.count("channel_hz") == FM_HZ,
                "APRS mode did not enable on the configured channel")
        labels = snapshot(name, "GPS TX Mode", "APRS")
        require("APRS Mode" not in labels and [n for n in tones if n] == [1],
                f"mode selection must close and use the stock confirmation tone: {tones}, {labels}")
        steps[name]["beep_requests"] = tones.copy()
        require(guest.state()["selection"] == 3 and not read(SELECTOR, 2) and
                read(panel.symbols["aprs_tx_enabled"], 1) == option and not read(DV_TX_MODE, 1),
                "APRS submode did not return to the native selected row")

    def disable_mode(name):
        require(guest.click(150, 55) == 0x3e and not panel.count("channel_hz"), "native OFF failed")
        snapshot(name, "GPS Set", "OFF")
        require(guest.state()["menu"] == 218, "OFF did not return to GPS")

    def home():
        for _ in range(4):
            if read(PAGE+1, 1) == 1:
                return
            guest.press_exit()
            guest.render()
        raise ValueError("physical EXIT did not return to standby")

    def deliver(data):
        nonlocal block
        require(len(data) % FRAMES == 0, "incomplete SSIF0 block")
        for start in range(0, len(data), FRAMES):
            completed(cpu, rom(LAYOUT["rec_dma"]), DMAC + 0xE4, LAYOUT["rec_bank"], block,
                      data[start:start+FRAMES], (0,) * FRAMES, timeout_us=0)
            block += 1

    def poll():
        call(cpu, panel.symbols["aprs_j140_record_step"], timeout_us=0)
        panel.refresh()

    def packet(note):
        data = GUARD + ax25_burst("!3531.00N/13930.00E>" + note, 22) + GUARD
        data += (0,) * (-len(data) % FRAMES)
        before = panel.count("record_count"), panel.count("rx_samples")
        for start in range(0, len(data), 6 * FRAMES):
            deliver(data[start:start+6*FRAMES])
            poll()
        return tuple(panel.count(field) - prior for field, prior in zip(("record_count", "rx_samples"), before)), len(data)

    def dial(counts):
        for count in counts:
            cpu.mem_write(ENCODER_COUNT, pack("<H", count))
            call(cpu, rom(ENCODER_SAMPLE))
            call(cpu, rom(APPLY_DIAL))
            panel.refresh()

    require(packet("OFF-AT-START")[0] == (0, 0), "APRS listened before being enabled")
    for page in (1, 2):
        grid(page)
        require("APRS" not in snapshot(f"01-menu-page-{page}", "MENU"), "APRS covered the original grid")
        require(guest.click(430, 178) == 0x1B9 and guest.state()["menu"] == 22, f"page-{page} SET changed")
        snapshot(f"02-original-set-{page}", "SET", "My Station")
        home()

    open_gps()
    labels = snapshot("03-gps-list", "GPS", "GPS Set", "GPS TX Mode", "APRS", "GPS Information")
    require(labels.index("GPS TX Mode") < labels.index("APRS") < labels.index("GPS Information"),
            "APRS did not follow GPS TX Mode")
    baselines = {"".join(chr(g["key"]) for g in event["glyphs"]): event["glyphs"][0]["offset"][1]
                 for event in guest.surface.events}
    require(baselines["GPS TX Mode"] == baselines["OFF"] == baselines["GPS Set"] - 62,
            f"GPS TX Mode label and value are not centered: {baselines}")
    steps["03-gps-list"]["row2_baseline"] = baselines["GPS TX Mode"]
    require(guest.click(447, 166) == 0x23, "GPS list page-down failed")
    snapshot("03-gps-list-page-2", "2/3", "GPS Position", "GPS Memory", "GPS Alarm", "GPS Logger")
    require(guest.click(447, 166) == 0x23, "GPS list did not reach its last stock row")
    snapshot("03-gps-list-page-3", "3/3", "GPS Auto TX", "OFF")
    home()
    open_tx_mode()
    require(snapshot("03b-gps-tx-mode", "GPS TX Mode", "OFF", "D-PRS", "NMEA", "APRS") ==
            ["GPS TX Mode", "1/1", "OFF", "D-PRS", "NMEA", "APRS"], "GPS TX Mode choices changed")
    guest.press_exit()
    guest.render()
    require(guest.state()["menu"] == 218, "GPS TX Mode did not exit to GPS")
    aprs_from_gps()
    require("APRS Mode" not in snapshot("04-aprs-off", "FM Channel  Use current FM", "Beacon SSID  0"),
            "parameter page still contains a second mode switch")
    guest.press_exit()
    snapshot("05-cancel-with-exit", "GPS")
    require(guest.state()["menu"] == 218 and not panel.count("channel_hz"), "EXIT changed the APRS channel")

    aprs_from_gps()
    require(guest.click(115, 54) == 0x221 and not panel.count("channel_hz"),
            "selecting the FM channel enabled APRS by itself")
    snapshot("05b-aprs-frequency", "FM Channel  144.390 MHz", "Beacon SSID  0")
    require(guest.click(115, 114) == 0x222, "SSID did not open from APRS settings")
    snapshot("05b-ssid-picker", "Beacon SSID", "1/4")
    guest.click(394, 165)
    snapshot("05b-ssid-page-2", "2/4", "5")
    tones.clear()
    guest.click(115, 114)
    snapshot("05b-ssid-5", "Beacon SSID  5", "TX Path  Direct")
    require([n for n in tones if n] == [1], f"SSID used the wrong confirmation: {tones}")
    steps["05b-ssid-5"]["beep_requests"] = tones.copy()
    require(read(SELECTOR, 2) == 277 and read(panel.symbols["aprs_beacon_ssid"], 1) == 5,
            "SSID did not apply and return to APRS")
    guest.click(115, 114)
    guest.render()
    guest.press_exit()
    snapshot("05b-ssid-canceled", "Beacon SSID  5")
    home()

    open_tx_mode()
    open_mode("05c-mode-choices", "RX Only")
    require(not panel.count("channel_hz"), "opening APRS Mode modified the setting")
    chosen_mode("05d-mode-rx-selected", 0)
    open_mode("05d-reopen-rx", "RX Only")
    chosen_mode("05e-mode-tx-selected", 1)
    open_mode("05e-reopen-tx", "RX & TX")
    chosen_mode("05e-mode-back-to-rx", 0)
    open_mode("05f-mode-reopen", "RX Only")
    require(guest.click(394, 243) == 0x227, "the mode screen Back did not use its native rectangle")
    snapshot("05g-back-to-tx-mode", "GPS TX Mode", "APRS")
    require(not read(SELECTOR, 2) and guest.state()["menu"] == GPS_TX_MENU and panel.count("channel_hz") == FM_HZ,
            "Back from APRS Mode altered the setting or skipped GPS TX Mode")
    home()
    result, size = packet("BEFORE DIAL")
    require(result == (1, size) and panel.popup()[-1] == "BEFORE DIAL", "enabled RX did not show the first position")
    snapshot("06-enabled-packet", "POSITION BEACON", "BEFORE DIAL")
    dial((4, 0))
    require(read(ACTIVE_HZ, 4) == FM_HZ and panel.window() == [13, 0], "stock modal dial behavior changed")
    panel.exit()
    guest.render()

    dial((4, 8, 12, 16, 20))
    away = read(ACTIVE_HZ, 4)
    require(away > FM_HZ and panel.count("channel_hz") == FM_HZ and panel.window() == [0, 0],
            f"physical dial did not pause the APRS channel: {away=}, window={panel.window()}, {tuning=}")
    snapshot("07-turned-away", "FM")
    open_gps()
    snapshot("08-aprs-paused", "GPS TX Mode", "APRS (Paused)")
    home()
    require(packet("OFF-CHANNEL")[0] == (0, 0), "off-channel PCM reached the APRS decoder")
    deliver((330,) * (6 * FRAMES))  # Already in the stock ring before returning.
    before = panel.count("rx_samples")
    dial((16, 12, 8, 4, 0))
    poll()
    require(read(ACTIVE_HZ, 4) == FM_HZ and panel.count("rx_samples") == before,
            "the native dial return accepted blocks captured off channel")
    result, size = packet("AFTER DIAL")
    require(result == (1, size) and panel.popup()[-1] == "AFTER DIAL", "RX did not resume on return")
    snapshot("09-resumed-packet", "POSITION BEACON", "AFTER DIAL")
    panel.exit()

    open_aprs()
    snapshot("10-aprs-on", "FM Channel  144.390 MHz", "Beacon SSID  5")
    result, size = packet("WHILE MENU")
    require(result == (1, size) and panel.window() == [0, 0], "incoming packet stole focus from the selector")
    snapshot("11-selector-keeps-focus", "FM Channel  144.390 MHz")
    home()
    panel.refresh()
    require("RX:" not in snapshot("11b-return-to-receive", "FM"), "an empty receive caption was drawn")
    with Image.open(output / "11b-return-to-receive.png") as image:
        colors = image.convert("RGB").crop((390, 90, 413, 114)).getcolors(maxcolors=552)
        require(any(r > 130 and g < 60 and b < 60 for _, (r, g, b) in colors),
                "the original position icon is not visible after leaving the menu")
    hit = guest.click(401, 101)
    require(hit == 0x15 and panel.popup()[-1] == "WHILE MENU",
            f"icon failed after the selector: hit={hit:#x}, window={panel.window()}, popup={panel.popup()}, "
            f"strip={cpu.mem_read(panel.symbols['aprs_strip'], 8).hex()}")
    panel.exit()

    deliver((330,) * (6 * FRAMES))
    open_tx_mode()
    disable_mode("11d-mode-off-selected")
    guest.click(160, 104)
    guest.render()
    open_mode("11c-mode-off-on", "RX Only")
    chosen_mode("11e-mode-rx-reselected", 0)
    home()
    before = panel.count("rx_samples")
    poll()
    require(panel.count("rx_samples") == before, "PCM from the old receive session crossed an OFF/ON cycle")

    for stock, selected, y in (("D-PRS", 1, 116), ("NMEA", 2, 179)):
        open_tx_mode()
        guest.click(150, y)
        snapshot(f"11f-stock-{stock}", stock + " SET")
        require(not panel.count("channel_hz") and read(DV_TX_MODE, 1) == selected,
                f"selecting {stock} did not disable APRS and apply the original mode")
        guest.press_exit()
        snapshot(f"11f-return-{stock}", "GPS TX Mode", "APRS")
        open_mode(f"11f-cancel-aprs-from-{stock}", "RX Only")
        guest.press_exit()
        guest.render()
        require(read(DV_TX_MODE, 1) == selected and not panel.count("channel_hz"), "browsing APRS changed native mode")
        open_mode(f"11f-aprs-from-{stock}", "RX Only")
        chosen_mode(f"11f-aprs-enabled-from-{stock}", 0)
        home()

    open_tx_mode()
    disable_mode("11g-mode-disabled")
    home()
    require(packet("DISABLED")[0] == (0, 0), "OFF accepted PCM despite remaining on frequency")
    snapshot("12-disabled", "FM")

    for mode, label in ((9, "DV"), (1, "USB")):
        for address in (MODE_UI_A, MODE_VFO_A):
            cpu.mem_write(address, bytes((mode << 4,)))
        require(label in guest.render()[0], f"test receiver did not enter {label}")
        grid(2)
        require("APRS" not in snapshot(f"13-{label.lower()}-grid", "MENU"), "non-FM menu page changed")
        require(guest.click(430, 178) == 0x1B9 and guest.state()["menu"] == 22, "non-FM SET changed")
        home()
        open_aprs()
        snapshot(f"14-{label.lower()}-aprs", "FM Channel  144.390 MHz", "Beacon SSID  5")
        require(guest.click(115, 54) == 0x221 and not panel.count("channel_hz"), "non-FM bind enabled APRS")
        home()

    require(tuning and all(e["pc"] == hex(rom(0x201034F4)) for e in tuning) and tuning[-1]["hz"] == FM_HZ,
            f"frequency changes bypassed the native VFO writer: {tuning}")
    report = dict(region="E140" if european else "J140",
                  image_sha256=sha256(images[0]).hexdigest(),
                  arm_sha256=None if task[0] is None else sha256(task[0]).hexdigest(),
                  tuned=away, return_frequency=read(ACTIVE_HZ, 4),
                  stock_tuning_writes=tuning, rejected_off_channel_blocks=6, rejected_previous_session_blocks=6,
                  steps=steps)
    (output / "menu.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    images, european = load_aprs_panel(args.dat.read_bytes())
    replay(images, args.output, european)
