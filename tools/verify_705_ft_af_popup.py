"""Replay native AF level and menu rectangles against the FT compositor on J/E."""
import argparse
import json
from pathlib import Path
from struct import pack

from PIL import Image, ImageChops

from tools.build_705_e140_log_test import BASE, ROOT, decode_main, digest, load_a
from tools.probe_705_sstv_picture import frame
from tools.render_705_display import load
from tools.replay_705_settings import SettingsGuest
from tools.verify_705_e140_station import E_MAIN, EuropeanReplay
from tools.verify_705_ftx_rx import OUT, call, map_atlas, menu_init, symbols


def replay(path, out, old):
    dat = path.read_bytes()
    stock = (ROOT / "firmware" / path.name).read_bytes()
    image = bytes(decode_main(dat)[1])
    if path.name == "705E140.dat":
        original, flash = load_a(stock, E_MAIN)
        guest, _ = EuropeanReplay(original, flash, digest(image)).station_guest(dat)
    else:
        guest = SettingsGuest(load(stock), front_panel=True)
        guest.cpu.mem_write(BASE, image)
        guest.cpu.ctl_remove_cache(BASE, BASE+len(image))
        menu_init(guest.cpu, image)
        map_atlas(guest.cpu, dat)
    cpu, surface = guest.cpu, guest.surface
    sy = symbols(OUT / "rx.elf")
    guest.render()
    cpu.mem_write(guest.language_address, bytes(2))
    assert call(cpu, sy["ft_data_ready"])
    cpu.mem_write(sy["state"], pack("<I", 2))
    out.mkdir(parents=True, exist_ok=True)

    def lcd():
        surface.select_target()
        return Image.frombytes("RGBA", (480,272), bytes(surface.pixels)).convert("RGB")

    def touch(x, y):
        cpu.mem_write(0x203e1f23, bytes([1]))
        call(cpu, sy["ftx_touch"])
        cpu.mem_write(0x203e1f23, pack(">BHH", 0, x, y))
        return call(cpu, sy["ftx_touch"])

    results = []
    for label, active, kind, suppressed, expected_top in (
        ("closed",0,0,0,272), ("volume",1,1,0,214), ("volume-held",1,1,0,214),
        ("af-menu",1,2,0,157), ("suppressed",1,1,1,272), ("restored",0,1,0,272),
    ):
        cpu.mem_write(0x204bd19e, bytes((active,kind)))
        cpu.mem_write(0x204bd68d, bytes((suppressed,)))
        frame(guest)
        native = lcd()
        native_rects = [w["rect"] for w in surface.pixel_writes if w["target"] is None]
        assert bytes(cpu.mem_read(0x204bd19e, 2)) == bytes((active,kind))
        if expected_top < 272:
            assert [0,0,118,272-expected_top] in native_rects, (label,native_rects)
        surface.pixel_writes.clear()
        call(cpu, sy["ftx_frame"], instruction_limit=12000000, timeout_us=10000000)
        ft = lcd()
        rects = [w["rect"] for w in surface.pixel_writes if w["target"] is None]
        mask = Image.new("1", (480,272))
        for x,y,w,h in rects:
            mask.paste(1,(x,272-y-h,x+w,272-y))
        visible_top = 272 if old and kind == 1 else expected_top
        expected = Image.new("1",(480,272))
        expected.paste(1,(0,84,480,272))
        if visible_top < 272:
            expected.paste(0,(0,visible_top,118,272))
        assert mask.tobytes() == expected.tobytes(), (label,rects)
        if expected_top < 272:
            box = (0,expected_top,118,272)
            preserved = not ImageChops.difference(native.crop(box),ft.crop(box)).getbbox()
            assert preserved == (visible_top < 272), (label,preserved)
        if label == "closed":
            baseline = ft
        if label == "restored":
            assert ft.crop((0,214,118,272)).tobytes() == baseline.crop((0,214,118,272)).tobytes()
        # A new press within the window must never select the hidden FT row.
        assert touch(117,214) == int(visible_top > 214)
        assert touch(118,214) == 1
        ft.save(out/(label+".png"))
        results.append(dict(state=label,ft_visible_left_to_y_exclusive=visible_top,
                            lcd_blits=rects))
    (out/"replay.json").write_text(json.dumps(dict(dat_sha256=digest(dat),states=results),indent=2))
    print(path, "passed", len(results), "frames")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dat", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--old", action="store_true")
    args = p.parse_args()
    replay(args.dat, args.out, args.old)
