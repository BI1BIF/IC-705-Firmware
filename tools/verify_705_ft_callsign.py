"""Save a callsign through the FT panel and read it back on a fresh radio."""
import argparse
import json
from hashlib import sha256
from pathlib import Path

from tools.decode_705_main import decode_main
from tools.verify_705_e140_station import E_MAIN, OUT, ROOT, EuropeanReplay, load_a, symbols
from tools.verify_705_ftx_rx import BASE, SettingsGuest, load, map_atlas, menu_init
from tools.verify_705_ftx_tx import call, mount_station_card, val


def exercise(dat, raw_state, region):
    stock_dat = (ROOT / f"firmware/705{region}140.dat").read_bytes()
    image = bytes(decode_main(dat)[1])
    if region == "E":
        stock, flash = load_a(stock_dat, E_MAIN)
        board = EuropeanReplay(stock, flash, sha256(image).hexdigest())
    sy = symbols(OUT / "rx.elf")

    def boot(saved_files):
        if region == "E":
            guest, _ = board.station_guest(dat)
        else:
            guest = SettingsGuest(load(stock_dat), front_panel=True)
            guest.cpu.mem_write(BASE, image)
            guest.cpu.ctl_remove_cache(BASE, BASE + len(image))
            menu_init(guest.cpu, image)
            map_atlas(guest.cpu, dat)
        cpu = guest.cpu
        files, _, _ = mount_station_card(cpu, sy, rom=guest.rom)
        files.update(saved_files)
        cpu.mem_write(0x20380172, bytes([raw_state]))
        call(cpu, sy["ft_data_ready"])
        call(cpu, sy["ft_station_open"])
        return cpu, files

    cpu, files = boot({})

    def tap(x, y):
        assert call(cpu, sy["ft_panel_touch"], x, y) == 1

    tap(440, 249)  # FT menu
    tap(100, 184)  # Station settings
    tap(90, 130)   # Callsign keyboard
    for letter in "K1ABC":
        pos = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".index(letter)
        tap(18 + 39 * (pos % 9), 140 + 33 * (pos // 9))
    tap(442, 173)  # Accept keyboard entry
    assert not files
    tap(441, 246)  # Save station settings
    notice = bytes(cpu.mem_read(val(cpu, sy["notice"]), 32)).split(b"\0")[0].decode()
    fresh, _ = boot(files)
    restored = bytes(fresh.mem_read(sy["pref"], 12)).split(b"\0")[0].decode()
    return dict(region=region, card_state=raw_state, notice=notice, files=sorted(files), reopened_call=restored)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("--region", choices=["J", "E"], required=True)
    parser.add_argument("--before-fix", action="store_true")
    args = parser.parse_args()
    data = args.dat.read_bytes()
    results = []
    for state in (3, 4, 0):
        result = exercise(data, state, args.region)
        saved = state == 3 or (state == 4 and not args.before_fix)
        assert result["reopened_call"] == ("K1ABC" if saved else ""), result
        assert result["notice"] == ("Saved on SD" if saved else "Applied for this session"), result
        results.append(result)
    print(json.dumps(results, indent=2))
