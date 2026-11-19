"""Drive the actual Tk controls with both historical reports and save a local trace."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from tools.virtual_705_satellite import INITIAL, J140_DAT, REPLAY_DIR, load_reports, open_panel


def check(root, panel, output, screenshots):
    from tkinter import ttk

    def walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from walk(child)

    widgets = list(walk(root))
    commands = {w.cget("text"): w for w in widgets if isinstance(w, (ttk.Button, ttk.Checkbutton))}
    stars, roles, gps, fault = [w for w in widgets if isinstance(w, ttk.Combobox)]
    scale, = [w for w in widgets if isinstance(w, ttk.Scale)]
    trace = []
    arm = hasattr(panel.vfo, "legs")
    leg_cursor = 0

    def click(text):
        commands[text].invoke()
        root.update()

    def choose(widget, index):
        widget.current(index)
        widget.event_generate("<<ComboboxSelected>>")
        root.update()

    def go(index):
        scale.set(index)
        root.update()
        assert panel.index == index

    def check_status(expected, name=None):
        nonlocal leg_cursor
        assert panel.status == expected, (expected, panel.status)
        trace.append({"name": name or expected, "satellite": panel.report["satellite_id"], "role": panel.role,
                      "sample_utc": panel.sample["utc"], "status": panel.status, "ptt_held": panel.ptt,
                      "vfo": asdict(panel.vfo.read()), "write_count": len(panel.vfo.writes),
                      "last_write": panel.vfo.writes[-1] if panel.vfo.writes else None})
        if arm:
            trace[-1].update(stock_tx_readback=panel.vfo.tx_readback(), stock_legs=panel.vfo.legs[leg_cursor:])
            leg_cursor = len(panel.vfo.legs)
        if name and screenshots:
            from PIL import ImageGrab

            root.update()
            ImageGrab.grab(window=root.winfo_id()).save(output / f"{name}.png")

    root.update()
    click("播放回放")
    root.after(700, root.quit)
    root.mainloop()
    click("播放回放")
    assert panel.index >= 1 and not panel.vfo.writes

    first = next(i for i, row in enumerate(panel.report["samples"]) if row["targets"])
    go(first)
    check_status("preview", "01-preview")
    assert not panel.vfo.writes and panel.vfo.read() == INITIAL
    click("启用补偿")
    check_status("tracking", "02-tracking")
    frozen, count = panel.vfo.read(), len(panel.vfo.writes)
    click("模拟按住 PTT")
    go(first + 2)
    check_status("ptt_hold", "03-ptt-hold")
    assert (panel.vfo.read(), len(panel.vfo.writes)) == (frozen, count)
    click("模拟按住 PTT")
    check_status("tracking")
    assert panel.vfo.read().a_hz == panel.target["rx_target_hz"] and panel.vfo.read() != frozen

    for n, flag in enumerate(("position_expired", "utc_expired"), 1):
        count = len(panel.vfo.writes)
        choose(gps, n)
        go(first + 2 + n)
        check_status(flag, "04-utc-expired" if n == 2 else None)
        assert len(panel.vfo.writes) == count
        choose(gps, 0)
        check_status("tracking")
        assert len(panel.vfo.writes) == count + 1
    click("手动接管")
    click("手动 +1 kHz")
    manual = panel.vfo.read()
    go(first + 5)
    check_status("manual", "05-manual")
    assert panel.vfo.read() == manual
    click("退出并恢复")
    check_status("restored", "06-restored")
    assert panel.vfo.read() == INITIAL

    choose(stars, 1)
    choose(roles, 1)
    assert panel.report["satellite_id"] == "00005" and panel.role == "B"
    first = next(i for i, row in enumerate(panel.report["samples"]) if row["targets"])
    go(first)
    click("启用补偿")
    check_status("tracking")
    assert panel.vfo.read().b_hz == panel.target["rx_target_hz"]
    click("模拟按住 PTT")
    click("退出并恢复")
    check_status("exit_pending")
    click("模拟按住 PTT")
    check_status("restored")
    assert panel.vfo.read() == INITIAL

    choose(fault, 1)
    click("启用补偿")
    check_status("tune_rejected")
    click("退出并恢复")
    check_status("restored")
    choose(fault, 2)
    click("启用补偿")
    check_status("tune_mismatch", "07-readback-mismatch")
    count = len(panel.vfo.writes)
    go(first + 1)
    assert len(panel.vfo.writes) == count
    choose(fault, 1)
    click("退出并恢复")
    check_status("restore_rejected")
    click("退出并恢复")
    check_status("restored")
    assert panel.vfo.read() == INITIAL

    if arm:
        for direction in ("B", "A"):
            assert panel.role == direction
            checkpoint = len(panel.vfo.legs)
            choose(fault, 3)
            click("启用补偿")
            check_status("tune_rejected", f"08-second-rejected-{direction}")
            first_leg, second_leg = panel.vfo.legs[checkpoint:]
            assert first_leg["relative_vfo"] == 0 and first_leg["reply"] == "FB" and first_leg["record_commit"]
            assert second_leg["relative_vfo"] == 1 and second_leg["reply"] == "FA" and not second_leg["record_commit"]
            partial = panel.vfo.read()
            assert getattr(partial, direction.lower() + "_hz") == panel.target["rx_target_hz"]
            other_hz = ("b" if direction == "A" else "a") + "_hz"
            assert getattr(partial, other_hz) == getattr(INITIAL, other_hz)
            go(panel.index + 1)
            assert panel.vfo.read() == partial and len(panel.vfo.legs) == checkpoint + 2
            click("退出并恢复")
            check_status("restored")
            assert panel.vfo.read() == INITIAL and panel.snapshot is None

            checkpoint = len(panel.vfo.legs)
            choose(fault, 4)
            click("启用补偿")
            check_status("ptt_hold", f"09-hold-between-{direction}")
            assert panel.ptt and panel.vfo.tx_readback() is True and len(panel.vfo.legs) == checkpoint + 1
            partial = panel.vfo.read()
            old_target = panel.target
            go(panel.index + 2)
            click("模拟按住 PTT")
            check_status("ptt_hold", f"10-request-cleared-{direction}")
            assert not panel.ptt and panel.vfo.tx_readback() is True
            assert len(panel.vfo.legs) == checkpoint + 1 and panel.vfo.read() == partial
            if direction == "A":
                click("退出并恢复")
                check_status("exit_pending")
                assert len(panel.vfo.legs) == checkpoint + 1 and panel.snapshot == INITIAL
                click("模拟发射状态输入")
                check_status("restored", "11-restore-after-rx-A")
                assert {row["action"] for row in panel.vfo.legs[checkpoint + 1:]} == {"restore"}
            else:
                assert panel.target != old_target
                click("模拟发射状态输入")
                check_status("tracking", "11-resume-latest-after-rx-B")
                assert panel.vfo.read().b_hz == panel.target["rx_target_hz"]
                assert panel.vfo.read().a_hz == panel.target["tx_target_hz"]
                click("退出并恢复")
                check_status("restored")
            assert panel.vfo.read() == INITIAL and panel.snapshot is None
            if direction == "B":
                choose(stars, 0)
                go(next(i for i, row in enumerate(panel.report["samples"]) if row["targets"]))

    click("启用补偿")
    click("模拟按住 PTT")
    root.tk.eval(root.protocol("WM_DELETE_WINDOW"))
    check_status("exit_pending", None)
    click("模拟按住 PTT")
    check_status("restored", None)
    assert panel.vfo.read() == INITIAL and not root.tk.call("info", "commands", ".")
    return trace


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new local trace directory")
    parser.add_argument("--replays", type=Path, default=REPLAY_DIR)
    parser.add_argument("--arm", action="store_true", help="use the original J140 ARM backend")
    parser.add_argument("--dat", type=Path, default=J140_DAT)
    parser.add_argument("--screenshots", action="store_true", help="save window captures with Pillow on Windows")
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    root, panel, _ = open_panel(load_reports(args.replays), args.dat if args.arm else None)
    try:
        trace = check(root, panel, args.output, args.screenshots)
    finally:
        if root.tk.call("info", "commands", "."):
            root.destroy()
    (args.output / "trace.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    print(f"Satellite panel: {len(trace)} UI checkpoints passed")


if __name__ == "__main__":
    cli()
