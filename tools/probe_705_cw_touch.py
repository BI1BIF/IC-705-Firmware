"""Check the exact delivered CW application's touch path using two offline sample sequences."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory

from tools.build_705_cw_sim import load_image, pack_image
from tools.decode_705_main import decode_main
from tools.emulate_705 import BASE, call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_cw_session import read_session
from tools.render_705_display import PAGE, load, require
from tools.replay_705_settings import TOUCH_POLL, TOUCH_SAMPLE, UPDATE
from tools.virtual_705_panel import start


def open_cw(images, main, anchor, release):
    guest = start(images)
    cpu = guest.cpu
    cpu.mem_write(BASE, bytes(main))
    state = 0x209EE000  # Preallocated, empty session in the isolated CPU fixture.
    cpu.mem_write(anchor, pack("<I", state))
    for addr in (MODE_UI_A, MODE_VFO_A):
        cpu.mem_write(addr, b"\x20")
    guest.render()
    guest.press_menu()
    guest.render()

    def tap(x, y):
        for sample in (pack(">BHH", 0, x, y), release):
            cpu.mem_write(TOUCH_SAMPLE, sample)
            call(cpu, TOUCH_POLL)

    tap(80, 247)
    require(read_session(cpu, state)["active"], "The original MENU did not open CW")
    return guest, state, tap


def trace(images, main, anchor, release):
    guest, state, tap = open_cw(images, main, anchor, release)
    cpu = guest.cpu
    observed = []
    addr = 0x2007D6C0  # The stock poll's immediate key/touch dispatch, not all redraw sources.
    cpu.hook_add(uc.UC_HOOK_CODE, lambda *_: observed.append(addr), begin=addr, end=addr)
    presses = []
    for name, x, y, field in (("SET open", 430, 254, "color_open"), ("SET close", 430, 254, "color_open"),
                              ("AUTO/WPM", 430, 157, "speed_picker"), ("< 1 >", 48, 254, "menu_two")):
        observed.clear()
        before = read_session(cpu, state)[field]
        tap(x, y)
        after = read_session(cpu, state)[field]
        presses.append(dict(button=name, before=before, after=after, stock_dispatches=len(observed)))
    guest.press_exit()
    return dict(sample_after_each_down=release.hex(), cw_opened=True, presses=presses,
                physical_exit_closed_cw=not read_session(cpu, state)["active"])


def navigation(images, main, anchor):
    cases = []
    for button, bank, bit, mode, popup in (("MENU", 0, 3, 2, False), ("QUICK", 1, 1, 1, True),
                                           ("FUNCTION", 0, 7, 3, False), ("EXIT", 1, 2, 1, False)):
        guest, state, _ = open_cw(images, main, anchor, b"\1\0\0\0\0")
        call(guest.cpu, UPDATE, instruction_limit=2_000_000)  # Let the original GUI leave the grid.
        require(guest.cpu.mem_read(PAGE+1, 1)[0] == 1, "opening CW did not restore HOME")
        guest._press_key(bank, bit)
        call(guest.cpu, UPDATE, instruction_limit=2_000_000)
        base = guest.cpu.mem_read(PAGE+1, 1)[0]
        overlay = bool(guest.cpu.mem_read(0x204BD0F4, 1)[0])
        require((base, overlay) == (mode, popup), f"stock {button} selected screen/overlay {base}/{overlay}")
        cases.append(dict(button=button, stock_page=int(base), stock_popup=overlay,
                          cw_active=bool(read_session(guest.cpu, state)["active"])))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path, help="original Japanese 1.40 DAT")
    parser.add_argument("candidate", type=Path, help="already delivered CW DAT; read-only")
    parser.add_argument("pc_image", type=Path, help="matching PC image providing the session anchor address")
    parser.add_argument("--check-navigation", action="store_true",
                        help="compare physical MENU, QUICK, FUNCTION and EXIT in the delivered and current PC builds")
    args = parser.parse_args()
    _, app, metadata = decode_main(args.candidate.read_bytes())
    bundle, index = load_image(args.pc_image)
    require(app == bundle[0], "candidate does not contain the PC image's exact application")
    stock_dat = args.stock.read_bytes()
    stock = load(stock_dat)
    anchor = index["symbols"]["cw_state_anchor"]
    normal = trace(stock, app, anchor, b"\1\0\0\0\0")
    no_release_flag = trace(stock, app, anchor, bytes(5))
    require([p["after"] for p in normal["presses"]] == [True, False, True, True]
            and all(not p["after"] for p in no_release_flag["presses"])
            and normal["physical_exit_closed_cw"] and no_release_flag["physical_exit_closed_cw"],
            "touch controls differ from the delivered build's expected response")
    result = dict(candidate_sha256=metadata["input"]["sha256"], application_sha256=sha256(app).hexdigest(),
                  scope="isolated original input poll with synthetic samples; no physical or LCD refresh trace",
                  normal_release=normal, no_release_flag=no_release_flag)
    if args.check_navigation:
        delivered_nav = navigation(stock, app, anchor)
        with TemporaryDirectory() as folder:
            pc_only = Path(folder)/"test.ic705sim"
            pack_image(stock_dat, pc_only)
            fixed, index = load_image(pc_only)
        fixed_anchor = index["symbols"]["cw_state_anchor"]
        fixed_nav = navigation(stock, fixed[0], fixed_anchor)
        require([c["cw_active"] for c in delivered_nav] == [True, True, False, False]
                and not any(c["cw_active"] for c in fixed_nav), "CW did not yield to original navigation")
        require(trace(stock, fixed[0], fixed_anchor, b"\1\0\0\0\0") == normal,
                "navigation fix changed the normal CW touch controls")
        result.update(delivered_navigation=delivered_nav, fixed_navigation=fixed_nav,
                      pc_fixed_application_sha256=sha256(fixed[0]).hexdigest())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
