"""Select and replay historical satellite passes in an offline IC-705 desktop panel."""

import argparse
import json
from pathlib import Path

from tools.decode_705_main import J140_DAT_SHA, J140_MAIN_SHA
from tools.satellite_panel_state import SatellitePanel, VfoState, VirtualVfo


ROOT = Path(__file__).resolve().parents[1]
REPLAY_DIR = ROOT / ".analysis" / "satellite-pass"
J140_DAT = ROOT / "firmware" / "705J140.dat"
REPLAY_FILES = {"25544": "iss-release.json", "00005": "vanguard-release.json"}
INITIAL = VfoState(145_500_000, 433_500_000, "FM", "USB", "B")
ROLE_LABELS = ("A · 145 MHz 段接收，430 MHz 段上行", "B · 430 MHz 段接收，145 MHz 段上行")
GPS_LABELS = {"正常": None, "定位失效": "position_expired", "UTC 失效": "utc_expired"}
FAILURE_LABELS = {"正常": None, "拒绝写入": "reject", "写后回读不一致": "mismatch"}
ARM_FAILURES = {"第二路被原厂拒绝": "reject_second", "两路之间按下 PTT": "hold_between"}
STATUS_TEXT = {
    "preview": "预览 · 尚未启用补偿",
    "waiting": "等待第一个可用采样",
    "tracking": "补偿已启用 · 两路频率已核对",
    "below_horizon": "暂停补偿 · 卫星在地平线以下",
    "position_expired": "暂停补偿 · 定位失效",
    "utc_expired": "暂停补偿 · UTC 失效",
    "ptt_hold": "补偿冻结 · 等待 PTT 请求解除并回读接收",
    "manual": "手动接管 · 自动补偿已停止",
    "exit_pending": "已请求退出 · 等待确认接收后恢复设置",
    "tune_rejected": "自动补偿已停止 · 调谐被拒，需退出恢复",
    "tune_mismatch": "自动补偿已停止 · 调谐后回读不一致，需退出恢复",
    "unexpected_readback": "自动补偿已停止 · 当前设置与预期不一致，需退出恢复",
    "restore_rejected": "恢复被拒 · 请再次点「退出并恢复」",
    "restore_mismatch": "恢复后回读不一致 · 请再次点「退出并恢复」",
    "restored": "已退出 · 进入前的虚拟 VFO 设置已恢复",
}


def load_reports(directory=REPLAY_DIR):
    catalog = json.loads((ROOT / "samples" / "satellite-pass.json").read_text(encoding="utf-8"))["satellites"]
    reports = {}
    for id_, filename in REPLAY_FILES.items():
        path = directory / filename
        report = json.loads(path.read_text(encoding="utf-8"))
        if (report["dat_sha256"] != J140_DAT_SHA or report["main_sha256"] != J140_MAIN_SHA or
                report["satellite_id"] != id_ or report["satellite"] != catalog[id_] or
                len(report["samples"]) < 2 or {x["selected"] for x in report["stock_vfo"]} != {"A", "B"}):
            raise ValueError(f"回放文件与预期历史样本不一致：{path}")
        label = f"{id_}  {catalog[id_]['name'].split(' (')[0]}  ·  {catalog[id_]['window_utc'][0][:10]}"
        reports[label] = report
    return reports


def mhz(hz):
    return f"{hz / 1e6:.6f} MHz"


def open_panel(reports, arm_dat=None):
    import tkinter as tk
    from tkinter import ttk

    if arm_dat is not None:
        from tools.satellite_arm_vfo import ArmVfo

        vfo = ArmVfo(arm_dat, INITIAL)
    else:
        vfo = VirtualVfo(INITIAL)
    root = tk.Tk()
    root.title("IC-705 卫星跟踪 · 离线回放")
    root.minsize(690, 545)
    body = ttk.Frame(root, padding=18)
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)
    ttk.Label(body, text="卫星跟踪", font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
    description = ("日版 1.40 原厂 ARM · 历史过境 · 模式标签和 PTT 输入为模拟"
                   if arm_dat else "虚拟 VFO · 历史过境")
    ttk.Label(body, text=description).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))

    panel = SatellitePanel(vfo)
    panel.select(next(iter(reports.values())))
    star, role = tk.StringVar(value=next(iter(reports))), tk.StringVar(value=ROLE_LABELS[0])
    gps, error = tk.StringVar(value="正常"), tk.StringVar(value="正常")
    ptt, tx_input, cursor = tk.BooleanVar(), tk.BooleanVar(), tk.DoubleVar()
    failures = FAILURE_LABELS | ARM_FAILURES if arm_dat else FAILURE_LABELS
    pass_text, sample_text, mode_text, status = [tk.StringVar() for _ in range(4)]
    readouts = [tk.StringVar() for _ in range(4)]
    timer, closing = None, False

    def combo(parent, variable, choices, width, callback):
        widget = ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly", width=width)
        widget.bind("<<ComboboxSelected>>", callback)
        return widget

    def button(parent, label, callback, column):
        widget = ttk.Button(parent, text=label, command=callback)
        widget.grid(row=0, column=column, padx=(0, 6), sticky="w")
        return widget

    def draw():
        sample, events, actual = panel.sample, panel.report["events"], panel.vfo.read()
        target = panel.target
        tx = panel.vfo.tx_readback()
        ptt.set(panel.ptt)
        tx_input.set(tx is True)
        blocked = panel.ptt or tx is not False
        tx_text = {True: "发射（模拟状态）", False: "接收", None: "未知"}[tx]
        if panel.failure is None:
            error.set("正常")
        def stamp(value):
            return value.split("T")[1][:8]
        pass_text.set("升起 " + stamp(events["rise"]["utc"]) + "   ·   最高 " + stamp(events["peak"]["utc"]) +
                      f" / {events['peak']['elevation_deg']:.1f}°   ·   落下 " + stamp(events["set"]["utc"]) + " UTC")
        sample_text.set(f"回放 {sample['utc'][:19].replace('T', ' ')} UTC   ·   仰角 {sample['elevation_deg']:+.1f}°   ·   "
                        f"定位{'有效' if panel.gps['position_valid'] else '失效'} / "
                        f"UTC{'有效' if panel.gps['utc_valid'] else '失效'}")
        selection = f"选中 VFO {actual.selected}   ·   Split {'开' if actual.split else '关'}" if actual else "VFO/Split 回读不可用"
        mode_text.set(selection +
                      f"   ·   PTT 请求{'有' if panel.ptt else '无'} / {'原厂' if arm_dat else '虚拟'}回读 {tx_text}"
                      f"   ·   跟踪及恢复尝试 {sum(a != 'manual' for a, _ in panel.vfo.writes)} 次")
        for label, lane, physical in zip(readouts[:2], ("rx", "tx"), (panel.role, "B" if panel.role == "A" else "A")):
            label.set(f"VFO {physical}  {mhz(target[lane + '_target_hz'])}  ({target[lane + '_delta_hz']:+,} Hz)"
                      if target else "—")
        readouts[2].set(f"{mhz(actual.a_hz)}  {actual.a_mode}" if actual else "—")
        readouts[3].set(f"{mhz(actual.b_hz)}  {actual.b_mode}" if actual else "—")
        status.set(STATUS_TEXT[panel.status])
        cursor.set(panel.index)
        at_end = panel.index + 1 == len(panel.report["samples"])
        start_button.state(["!disabled" if (panel.snapshot is None and not blocked and
                                            panel.blocked in (None, "below_horizon") and not at_end) else "disabled"])
        exit_button.state(["!disabled" if panel.snapshot is not None else "disabled"])
        take_button.state(["!disabled" if panel.active else "disabled"])
        tune_button.state(["!disabled" if panel.status == "manual" and not blocked else "disabled"])
        next_button.state(["disabled" if at_end else "!disabled"])
        play_button.state(["disabled" if at_end else "!disabled"])
        play_button.configure(text="暂停回放" if timer is not None else "播放回放")
        for widget in (star_picker, role_picker):
            widget.configure(state="disabled" if panel.snapshot is not None or blocked else "readonly")

    def stop():
        nonlocal timer
        if timer is not None:
            root.after_cancel(timer)
            timer = None

    def advance():
        nonlocal timer
        panel.step(panel.index + 1)
        timer = root.after(550, advance) if panel.index + 1 < len(panel.report["samples"]) else None
        draw()

    def play():
        nonlocal timer
        if timer is None:
            timer = root.after(550, advance)
        else:
            stop()
        draw()

    def act(callback, *args):
        callback(*args)
        if closing and panel.snapshot is None:
            root.destroy()
        else:
            draw()

    def select(_event):
        stop()
        panel.select(reports[star.get()])
        role.set(ROLE_LABELS[0])
        gps.set("正常")
        timeline.configure(to=len(panel.report["samples"])-1)
        draw()

    def seek(index):
        stop()
        act(panel.step, round(float(index)))

    def end_session():
        stop()
        act(panel.restore)

    ttk.Label(body, text="卫星").grid(row=2, column=0, sticky="w", padx=(0, 12))
    star_picker = combo(body, star, tuple(reports), 38, select)
    star_picker.grid(row=2, column=1, sticky="w")
    ttk.Label(body, text="收发方向").grid(row=3, column=0, sticky="w")
    role_picker = combo(body, role, ROLE_LABELS, 38, lambda _: act(panel.choose_role, role.get()[0]))
    role_picker.grid(row=3, column=1, sticky="w", pady=4)
    ttk.Label(body, textvariable=pass_text).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 2))
    ttk.Label(body, textvariable=sample_text).grid(row=5, column=0, columnspan=2, sticky="w")

    timeline = ttk.Scale(body, variable=cursor, from_=0, to=len(panel.report["samples"])-1, command=seek)
    timeline.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 3))
    controls = ttk.Frame(body)
    controls.grid(row=7, column=0, columnspan=2, sticky="w")
    play_button = button(controls, "播放回放", play, 0)
    next_button = button(controls, "下一采样", lambda: seek(panel.index + 1), 1)
    start_button = button(controls, "启用补偿", lambda: act(panel.enable), 2)
    take_button = button(controls, "手动接管", lambda: act(panel.take_over), 3)
    exit_button = button(controls, "退出并恢复", end_session, 4)

    info = ttk.LabelFrame(body, text="频率", padding=(10, 6))
    info.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(13, 6))
    for number, label in enumerate(("建议下行 RX", "建议上行 TX", "当前 VFO A", "当前 VFO B")):
        ttk.Label(info, text=label, width=16).grid(row=number % 2, column=number // 2 * 2, sticky="w")
        ttk.Label(info, textvariable=readouts[number], width=34 if number < 2 else 23).grid(
            row=number % 2, column=number // 2 * 2 + 1, sticky="w")
    ttk.Label(body, textvariable=mode_text).grid(row=9, column=0, columnspan=2, sticky="w")
    ttk.Label(body, textvariable=status, font=("Microsoft YaHei UI", 11, "bold")).grid(
        row=10, column=0, columnspan=2, sticky="w", pady=(8, 6))

    faults = ttk.LabelFrame(body, text="模拟操作与失效注入", padding=(9, 5))
    faults.grid(row=11, column=0, columnspan=2, sticky="ew")
    ttk.Checkbutton(faults, text="模拟按住 PTT", variable=ptt,
                    command=lambda: act(panel.set_ptt, ptt.get())).grid(row=0, column=0, sticky="w")
    tune_button = button(faults, "手动 +1 kHz", lambda: act(panel.manual_tune), 1)
    if arm_dat:
        ttk.Checkbutton(faults, text="模拟发射状态输入", variable=tx_input,
                        command=lambda: act(panel.set_tx_status, tx_input.get())).grid(
                            row=0, column=2, columnspan=2, sticky="w")
    ttk.Label(faults, text="GPS").grid(row=1, column=0, sticky="w", pady=4)
    combo(faults, gps, tuple(GPS_LABELS), 13, lambda _: act(panel.set_gps, GPS_LABELS[gps.get()])).grid(
        row=1, column=1, sticky="w", padx=(0, 12))
    ttk.Label(faults, text="下次写入").grid(row=1, column=2, sticky="w", padx=(0, 6))
    combo(faults, error, tuple(failures), 20,
          lambda _: setattr(panel, "failure", failures[error.get()])).grid(row=1, column=3)

    def close():
        nonlocal closing
        closing = True
        end_session()

    root.protocol("WM_DELETE_WINDOW", close)
    draw()
    return root, panel, draw


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", type=Path, default=REPLAY_DIR, help="directory containing the historical JSON replays")
    parser.add_argument("--dat", type=Path, default=J140_DAT, help="original Japanese 1.40 DAT")
    parser.add_argument("--virtual", action="store_true", help="use the desktop-only VFO instead of J140 ARM")
    args = parser.parse_args()
    try:
        reports = load_reports(args.replays)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"{exc}\n请按 docs/IC705_SATELLITE_PANEL.md 生成两份原厂回放 JSON。\n")
    try:
        root, _, _ = open_panel(reports, None if args.virtual else args.dat)
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(2, f"原厂 ARM 回放无法启动：{exc}\n参见 docs/IC705_SATELLITE_PANEL.md，或用 --virtual。\n")
    root.mainloop()


if __name__ == "__main__":
    cli()
