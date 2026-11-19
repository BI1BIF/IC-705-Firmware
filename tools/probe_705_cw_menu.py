"""Compare the stock J140 MENU tile and touch route across CW and RTTY modes."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tools.emulate_705 import call, uc
from tools.render_705_display import PAGE, load
from tools.render_705_stock_row import require
from tools.replay_705_settings import GRID_PAGE, KEY_EVENT, KEY_SCAN, UPDATE
from tools.virtual_705_panel import start

MODE_VFO_A, MODE_UI_A = 0x203EBC33, 0x203E2128
GRID_VARIANT, MODE_READER = 0x204BD240, 0x2007D140
CASES = (
    ("LSB", 0, 0, 11, 0x0A, 0x20087988),
    ("USB", 1, 0, 11, 0x0A, 0x20087988),
    ("CW", 2, 1, 13, 0x0E, 0x20087990),
    ("CW-R", 3, 1, 13, 0x0E, 0x20087990),
    ("RTTY", 4, 2, 14, 0x0C, 0x20087998),
    ("RTTY-R", 5, 2, 14, 0x0C, 0x20087998),
    ("FM", 7, 4, 11, 0x0A, 0x20087988),
)


def probe(images, output):
    result = {}
    for name, raw, variant, menu, page, handler in CASES:
        guest = start(images)
        cpu = guest.cpu
        for address in (MODE_VFO_A, MODE_UI_A):
            # Set the two mode fields already maintained by the radio tasks.
            cpu.mem_write(address, bytes((raw << 4,)))
        home, _ = guest.render()
        require(name in home, f"mode marker missing from stock home: {home!r}")
        require(call(cpu, MODE_READER, 0) == variant, "stock mode family differs")
        guest.press_menu()
        require(all(hex(x) in guest.visits for x in (KEY_SCAN, KEY_EVENT)), "stock key path not reached")
        labels, frame = guest.render()
        require(labels == ["MENU"] and cpu.mem_read(GRID_PAGE, 1)[0] == 1, "stock MENU did not open")
        tile_variant = variant if variant in (1, 2) else 0
        require(cpu.mem_read(GRID_VARIANT, 1)[0] == tile_variant, "stock tile variant differs")
        (output / f"menu-{name.lower()}.png").write_bytes(frame)
        record = dict(active_mode=name, mode_family=variant, tile_variant=tile_variant,
                      frame_sha256=sha256(frame).hexdigest())

        require(guest.click(274, 251) == 0x1BB, "page 2 selector not reached")
        _, second_frame = guest.render()
        require(cpu.mem_read(GRID_PAGE, 1)[0] == 2, "MENU page 2 did not open")
        if name == "CW":
            (output / "menu-cw-page2.png").write_bytes(second_frame)
        require(guest.click(186, 251) == 0x1BA, "page 1 selector not reached")
        guest.render()
        if name == "CW":
            blank = start(images)
            for address in (MODE_VFO_A, MODE_UI_A):
                blank.cpu.mem_write(address, bytes((raw << 4,)))
            blank.render()
            blank.press_menu()
            blank.render()
            require(blank.click(274, 251) == 0x1BB, "blank tile test missed page 2")
            blank.render()
            empty_hit = blank.click(430, 178)
            record.update(second_page_blank_hit=hex(empty_hit), second_page_blank_menu=blank.state()["menu"])
        called = []
        cpu.hook_add(uc.UC_HOOK_CODE, lambda _c, addr, _s, _d: called.append(hex(addr)), begin=handler, end=handler)
        hit = guest.click(240, 77)
        require(hit == 0x1B2 and called == [hex(handler)], f"unexpected stock tile dispatch for {name}")
        require(guest.state()["menu"] == menu, f"wrong stock menu destination for {name}")
        call(cpu, UPDATE, instruction_limit=2_000_000)
        require(cpu.mem_read(PAGE+2, 1)[0] == page, f"wrong stock subpanel for {name}")
        record.update(stock_hit=hex(hit), handler=hex(handler), menu_id=menu, subpanel=hex(page))
        result[name] = record
    require(result["CW"]["frame_sha256"] == result["CW-R"]["frame_sha256"]
            != result["RTTY"]["frame_sha256"] == result["RTTY-R"]["frame_sha256"],
            "stock mode variants did not render different tiles")
    (output / "stock-menu-evidence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    probe(load(args.dat.read_bytes()), args.output)


if __name__ == "__main__":
    main()
