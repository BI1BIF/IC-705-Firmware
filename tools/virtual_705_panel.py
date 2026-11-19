"""Run the J140 home, MENU and settings screens offline, or save a reproducible input replay."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tools.emulate_705 import call, uc
from tools.render_705_display import DAT_HASH, PAGE, load
from tools.render_705_stock_row import FONT_HASH, SMALL_FONT_HASH, require
from tools.replay_705_settings import GRID_PAGE, KEY_EVENT, KEY_SCAN, OPEN_MENU, ROW_INPUT, TOUCH_RECT, SettingsGuest
from tools.zh_705_row import AUTO_LABEL, AUTO_SOURCE, ChineseLabel, DISPLAY_PAGE, STOCK_LABEL, ZH_LABEL


JA_PAGE = ["ディスプレイ設定", "1/6", "LCDバックライト", "  0%",
           "スクリーンセーバー (バッテリーパック)", "OFF", "スクリーンセーバー (外部電源)", "OFF",
           "画面消灯 [POWER]キー", "OFF"]
ZH_PAGE = ["显示设置", "1/6", "LCD 背光", "  0%",
           "屏幕保护（电池供电）", "关闭", "屏幕保护（外部供电）", "关闭",
           "屏幕熄灭 [POWER] 键", "关闭"]
EN_PAGE = ["DISPLAY", "1/6", "LCD Backlight", "  0%", "Screen Saver (Battery Pack)", "OFF",
           "Screen Saver (DC 13.8 V)", "OFF", "Screen OFF [POWER] Switch", "OFF"]


def localized_words(words):
    expected = [ZH_LABEL] if ZH_LABEL in words else []
    if words[0] == "显示设置":
        expected = [words[i] for i in (0, 2, 4, 5, 6, 7, 8, 9)]
    elif words[0] in DISPLAY_PAGE.values():
        expected = [w for w in words if w in DISPLAY_PAGE.values() or w == AUTO_LABEL or w.endswith(" 分钟")]
    return expected


def check_chinese(guest, name, words):
    lab = guest.chinese.glyphs["lab"]
    runs = guest.chinese.runs
    drawn = [run["text"] for run in runs if run["stage"] == "draw"]
    require(guest.chinese.active is None and drawn == localized_words(words)
            and all(list(dict.fromkeys(run["indices"])) == [lab[ch] for ch in dict.fromkeys(run["text"])]
                    for run in runs),
            f"{name}: unexpected Chinese glyph lookup: {runs}")
    for event in guest.surface.events:
        glyphs = event["glyphs"]
        if "".join(chr(g["key"]) for g in glyphs) in drawn:
            require(all(g["segments"] for g in glyphs if g["key"] != ord(" ")),
                    f"{name}: Chinese glyph missing its original draw path")


def start(images, *, front_panel=True, zh_font=None, arm_build=None, arm_table=None, arm_font_sha=None,
          third_language=False):
    guest = SettingsGuest(images, front_panel=front_panel)
    guest.chinese = ChineseLabel(guest, zh_font) if zh_font is not None and arm_build is None else None
    guest.display_arm = None
    if arm_build is not None:
        from tools.arm_705_display import DisplayArm
        options = {} if arm_font_sha is None else {"font_sha": arm_font_sha}
        guest.display_arm = DisplayArm(guest, zh_font, arm_build, arm_table, third_language=third_language, **options)
    if not front_panel:
        call(guest.cpu, OPEN_MENU, 22)
    return guest


def touch_replay(images, output, *, front_panel=False, zh_font=None, display_check=False, arm_build=None, arm_table=None):
    guest = start(images, front_panel=front_panel, zh_font=zh_font, arm_build=arm_build, arm_table=arm_table)
    arm_localized = guest.display_arm is not None and guest.display_arm.evidence["table_rows"] > 0
    output.mkdir(parents=True, exist_ok=True)
    steps = []

    def step(name, xy, words, *, menu, first, hit=None, event=None, highlight=None, language=(1, 1), grid=None,
             seed=None, prefs=None):
        if seed:
            for address, value in seed.items():
                guest.cpu.mem_write(address, bytes((value,)))
        before, language_before = guest.state(), guest.language()
        guest.writes.clear()
        guest.visits.clear()
        if xy == "MENU":
            guest.press_menu()
            require(all(hex(entry) in guest.visits for entry in (KEY_SCAN, KEY_EVENT)), "missing original key scan")
        elif xy is not None:
            region = guest.click(*xy)
            require(region == hit, f"{name}: unexpected touch region {region:#x}, expected {hit:#x}")
            require(hex(TOUCH_RECT) in guest.visits, f"{name}: missing original hit test")
        after, language_after = guest.state(), guest.language()
        writes, calls = guest.writes.copy(), guest.visits.copy()
        events = [w["value"] for w in writes if w["address"] == hex(ROW_INPUT+18) and w["value"]]
        require(events == ([] if event is None else [event]), f"{name}: unexpected guest events {events}")
        require((after["menu"], after["first"]) == (menu, first), f"{name}: unexpected guest state {after}")
        require(language_after == list(language), f"{name}: unexpected languages {language_after}")
        language_writes = [w for w in writes if int(w["address"], 16) in range(guest.language_address, guest.language_address+2)]
        expected_writes = [] if language_after == language_before else [(hex(guest.language_address), 1, language[0])]
        require([(w["address"], w["size"], w["value"]) for w in language_writes] == expected_writes,
                f"{name}: unexpected preference writes {language_writes}")
        if guest.chinese:
            guest.chinese.runs.clear()
        arm_before = guest.display_arm.counts() if guest.display_arm else 0
        text, image = guest.render()
        require(text[:len(words)] == words, f"{name}: unexpected original text {text}")
        require(guest.language() == list(language) and not any(
            int(w["address"], 16) in range(guest.language_address, guest.language_address+2)
            for w in guest.writes[len(writes):]), f"{name}: render wrote a language preference")
        row = guest.cpu.mem_read(PAGE+898, 1)[0]
        require(highlight is None or highlight == row, f"{name}: unexpected highlight")
        image_hash = sha256(image).hexdigest()
        if xy is not None and hit == 0:
            require(before == after and image_hash == steps[-1]["png_sha256"], f"{name}: miss altered screen")
        (output / f"{name}.png").write_bytes(image)
        record = {"frame": name, "xy": None if xy == "MENU" else xy, "touch_region": hit, "events": events,
                  "before": before, "after": after, "language_before": language_before,
                  "language_after": language_after, "highlight_row_one_based": row,
                  "input_calls": calls, "input_writes": writes, "draw_calls": guest.visits.copy(),
                  "text": text, "png_sha256": image_hash}
        if front_panel:
            mode = guest.cpu.mem_read(PAGE+1, 1)[0]
            grid_page = guest.cpu.mem_read(GRID_PAGE, 1)[0] if mode == 2 else None
            require(grid_page == grid, f"{name}: unexpected MENU page {grid_page}")
            require(any(entry["target"] is None and entry["source_target"] == (11 if mode == 1 else 18)
                        for entry in guest.surface.pixel_writes), f"{name}: missing original LCD composition")
            record.update(key="MENU" if xy == "MENU" else None, ui_mode=mode, grid_page=grid_page,
                          pixel_writes=guest.surface.pixel_writes.copy(), image_draw_count=len(guest.surface.image_draws))
        if guest.chinese:
            runs = guest.chinese.runs.copy()
            check_chinese(guest, name, words)
            record["chinese_runs"] = runs
        if guest.display_arm:
            applied = guest.display_arm.counts() - arm_before
            expected = localized_words(words)
            require((not expected and applied == 0) or (bool(expected) and applied >= len(expected)),
                    f"{name}: unexpected ARM translation count {applied}")
            record["arm_translations"] = applied
        if seed:
            record["ram_seed"] = {hex(address): value for address, value in seed.items()}
        if display_check:
            prefs_after = [*guest.cpu.mem_read(0x203EAE26, 2), *guest.cpu.mem_read(0x203EAE37, 3)]
            require(prefs is None or prefs_after == list(prefs), f"{name}: unexpected display preferences {prefs_after}")
            record["display_preferences"] = prefs_after
            record["display_item"] = int.from_bytes(guest.cpu.mem_read(PAGE+348, 2), "little") if menu == 286 else None
        steps.append(record)

    display = "ディスプレイ設定"
    display_lang = ZH_LABEL if guest.chinese or arm_localized else STOCK_LABEL
    system_lang = "システム言語"
    down, up, back, first_row, second_row = (449, 163), (449, 69), (449, 244), (120, 54), (120, 119)
    home_words = [" 0", ":", "00", "kHz"]
    if front_panel:
        step("panel-00-home", None, home_words, menu=0, first=0)
        step("panel-01-menu-1", "MENU", ["MENU"], menu=0, first=0, event=0x44, grid=1)
        step("panel-02-menu-2", (274, 251), ["MENU"], menu=0, first=0, hit=0x1BB, event=0x46, grid=2)
        step("panel-03-menu-1", (186, 251), ["MENU"], menu=0, first=0, hit=0x1BA, event=0x46, grid=1)
        require(steps[1]["png_sha256"] == steps[3]["png_sha256"] != steps[2]["png_sha256"], "MENU page pixel mismatch")
        step("panel-04-open-set", (429, 182), ["セット", "1/4"], menu=22, first=0, hit=0x1B9, event=0x45)
    step("00-set", None, ["セット", "1/4"], menu=22, first=0)
    step("01-set-page2", down, ["セット", "2/4"], menu=22, first=4, hit=0x23, event=0x17E)
    localized = arm_localized or (guest.chinese is not None and guest.chinese.full_page)
    page1 = ZH_PAGE if localized else JA_PAGE
    step("02-display-page1", (120, 230), page1, menu=67, first=0, hit=0x21, event=0x17C)
    for page, label in enumerate(("受信LED", "受信コールサイン表示", "自動応答位置表示", "スクロール速度", display_lang), 2):
        step(f"0{page+1}-display-page{page}", down, [display, f"{page}/6", label],
             menu=67, first=(page-1)*4, hit=0x23, event=0x17E)
    step("08-title-miss", (22, 8), [display, "6/6", display_lang], menu=67, first=20, hit=0)
    step("09-system-language", second_row, [system_lang, "1/1", "英語", "日本語"], menu=286, first=0, hit=0x1F, event=0x17C)
    step("10-system-back", back, [display, "6/6", display_lang], menu=67, first=20, hit=0x44, event=0x38, highlight=2)
    step("11-display-language", first_row, [display_lang, "1/1", "英語", "日本語"], menu=286, first=0, hit=0x1E, event=0x17C)
    step("12-switch-to-english", first_row, ["DISPLAY", "6/6", "Display Language", "English", "System Language", "Japanese"],
         menu=67, first=20, hit=0x3E, event=0x184, language=(0, 1))
    if display_check:
        for page in range(5, 0, -1):
            step(f"english-display-page{page}", up, EN_PAGE if page == 1 else ["DISPLAY", f"{page}/6"],
                 menu=67, first=(page-1)*4, hit=0x22, event=0x17D, language=(0, 1))
        for page in range(2, 7):
            step(f"english-return-page{page}", down, ["DISPLAY", f"{page}/6"],
                 menu=67, first=(page-1)*4, hit=0x23, event=0x17E, language=(0, 1))
    step("13-open-english-picker", first_row, ["Display Language", "1/1", "English", "Japanese"],
         menu=286, first=0, hit=0x1E, event=0x17C, language=(0, 1))
    step("14-switch-back-to-japanese", second_row, [display, "6/6", display_lang, "日本語", system_lang, "日本語"],
         menu=67, first=20, hit=0x3F, event=0x184)
    if display_check:
        for page in range(5, 0, -1):
            step(f"japanese-return-page{page}", up, page1 if page == 1 else [display, f"{page}/6"],
                 menu=67, first=(page-1)*4, hit=0x22, event=0x17D)
        check_display_values(step, page1, localized)
        for page in range(2, 7):
            words = [display, f"{page}/6"] + ([display_lang] if page == 6 else [])
            step(f"display-check-exit-page{page}", down, words,
                 menu=67, first=(page-1)*4, hit=0x23, event=0x17E)
    step("15-display-page5", up, [display, "5/6"], menu=67, first=16, hit=0x22, event=0x17D)
    step("16-return-to-set", back, ["セット", "2/4"], menu=22, first=4, hit=0x24, event=0x38, highlight=4)
    if front_panel:
        step("panel-17-return-home", back, home_words, menu=0, first=4, hit=0x24, event=0x38)
        step("panel-18-reopen-menu", "MENU", ["MENU"], menu=0, first=4, event=0x44, grid=1)
        step("panel-19-menu-back", (440, 250), home_words, menu=0, first=4, hit=0x1BC, event=0x38)
        require(steps[0]["png_sha256"] == steps[-3]["png_sha256"] == steps[-1]["png_sha256"], "home pixels changed")
    report = {"input_sha256": DAT_HASH, "main_sha256": guest.main_hash, "font_sha256": FONT_HASH,
              "engine": f"Unicorn {uc.__version__}", "steps": steps}
    if front_panel:
        report["small_font_sha256"] = SMALL_FONT_HASH
    if guest.chinese:
        report.update(chinese_font_sha256=guest.chinese.font_sha, chinese_glyphs=guest.chinese.glyphs)
    if guest.display_arm:
        report["arm_localization"] = guest.display_arm.evidence
    (output / "trace.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def check_display_values(step, page1, localized):
    off, on, unit = ("关闭", "开启", " 分钟") if localized else ("OFF", "ON", "分")

    def values(battery, external, power, percent=0, auto=False):
        words = page1.copy()
        if auto:
            words[2] = "LCD 背光（自动调节中）" if localized else "LCDバックライト (自動調整中)"
        words[3] = f"{percent:3d}%"
        if battery:
            words[5] = str(battery) + unit
        if external:
            words[7] = str(external) + unit
        if power:
            words[9] = on
        return words

    def editor(percent, auto=False):
        title = values(0, 0, False, auto=auto)[2]
        digits = list(str(percent).rjust(3, " ").replace(" ", "\0"))
        return [title, *(digit.strip("\0") for digit in digits), "%", "＋", "－", AUTO_LABEL if localized else AUTO_SOURCE]

    step("brightness-editor", (120, 54), editor(49), menu=286, first=0, hit=0x1E, event=0x17C,
         seed={0x203EAE26: 127}, prefs=(127, 0, 0, 0, 0))
    step("brightness-plus", (392, 114), editor(50), menu=286, first=0, hit=0x46, event=0x185,
         prefs=(128, 0, 0, 0, 0))
    step("brightness-minus", (88, 114), editor(49), menu=286, first=0, hit=0x47, event=0x186,
         prefs=(127, 0, 0, 0, 0))
    step("brightness-auto", (240, 195), editor(0, auto=True), menu=286, first=0, hit=0x4E, event=0x187,
         prefs=(127, 1, 0, 0, 0))
    step("brightness-manual", (240, 195), editor(0), menu=286, first=0, hit=0x4E, event=0x187,
         prefs=(1, 0, 0, 0, 0))
    step("brightness-return", (449, 244), values(0, 0, False), menu=67, first=0, hit=0x50, event=0x38,
         prefs=(1, 0, 0, 0, 0))

    # Use the original option pickers and touch dispatcher to set both timers and the power-key option.
    step("battery-picker", (120, 100), [page1[4], "1/2", off, *(n+unit for n in ("1", "2", "5"))],
         menu=286, first=0, hit=0x1F, event=0x17C)
    step("battery-five", (120, 217), values(5, 0, False), menu=67, first=0, hit=0x41, event=0x184)
    step("external-picker", (120, 154), [page1[6], "1/2", off, *(n+unit for n in ("1", "2", "5"))],
         menu=286, first=0, hit=0x20, event=0x17C)
    step("external-picker-next", (449, 163), [page1[6], "2/2", *(n+unit for n in ("15", "30", "60"))],
         menu=286, first=4, hit=0x43, event=0x17E)
    step("external-sixty", (120, 157), values(5, 60, False), menu=67, first=0, hit=0x40, event=0x184)
    step("power-picker", (120, 221), [page1[8], "1/1", off, on],
         menu=286, first=0, hit=0x21, event=0x17C)
    step("power-on", (120, 100), values(5, 60, True), menu=67, first=0, hit=0x3F, event=0x184,
         prefs=(1, 0, 3, 6, 1))
    # Feed edge cases to the original list builder after verifying actual editor input.
    for name, raw, auto, pct, timers, mins in (
        ("9-percent", 23, 0, 9, (1, 2), (1, 2)),
        ("50-percent", 128, 0, 50, (4, 5), (15, 30)),
        ("100-percent", 255, 0, 100, (3, 6), (5, 60)),
        ("auto-backlight", 255, 1, 0, (3, 6), (5, 60)),
    ):
        seed = {0x203EAE26: raw, 0x203EAE27: auto, 0x203EAE37: timers[0], 0x203EAE38: timers[1]}
        step(name, None, values(*mins, True, pct, auto=bool(auto)), menu=67, first=0, seed=seed)


def make_window(images, *, storage=None, storage_path=None, **settings):
    import tkinter as tk

    root = tk.Tk()
    root.title("IC-705 日版 1.40 · " + ("离线面板（简体实验）" if settings.get("zh_font") is not None else "离线面板"))
    root.resizable(False, False)
    lcd = tk.Label(root, borderwidth=0, highlightthickness=0, width=480, height=272)
    lcd.pack()
    footer = tk.Frame(root)
    footer.pack(fill="x")
    status = tk.Label(footer, anchor="w", text="")
    status.pack(side="left", padx=8, fill="x", expand=True)
    guest, stopped = None, False

    def draw():
        if guest.chinese:
            guest.chinese.runs.clear()
        _, frame = guest.render()
        if guest.display_arm:
            guest.display_arm.counts()
        image = tk.PhotoImage(master=root, data=frame, format="png")
        lcd.configure(image=image)
        lcd.image = image
        if settings.get("third_language"):
            menu_button.configure(text="菜单" if guest.language() == [2, 1] else "MENU")

    def reset():
        nonlocal guest, stopped
        guest = start(images, **settings)
        if storage is not None:
            storage.restore(guest)
            # The stored block also contains menu bookkeeping; start the preview at Home.
            call(guest.cpu, OPEN_MENU, 0)
        draw()
        stopped = False
        status.configure(text=("点 菜单 → 设置" if menu_button.cget("text") == "菜单" else "点 MENU → SET")
                         + " · 只在模拟内存运行")

    def save():
        if stopped:
            return
        try:
            storage.flush(guest)
            if storage_path is not None:
                storage.write_file(storage_path)
        except (OSError, ValueError, uc.UcError) as exc:
            status.configure(text="模拟保存失败")
            print(f"Original settings flush failed: {exc}")
        else:
            status.configure(text="已保存到电脑，下次打开仍有效" if storage_path is not None else "已保存到模拟存储，可重载")

    def handle(action):
        nonlocal stopped
        if stopped:
            return
        try:
            if action == "MENU":
                guest.press_menu()
                draw()
                status.configure(text="MENU · 原厂键盘扫描")
            else:
                hit = guest.click(*action)
                if hit:
                    draw()
                status.configure(text=f"触摸 {action} · " + (f"原厂触区 {hit:#x}" if hit else "未命中"))
        except (ValueError, uc.UcError) as exc:
            stopped = True
            status.configure(text="当前分支未建模；可重置面板")
            print(f"Original guest paused: {exc}")

    tk.Button(footer, text="重载" if storage is not None else "重置", command=reset).pack(side="right", padx=6, pady=5)
    if storage is not None:
        tk.Button(footer, text="保存", command=save).pack(side="right", padx=2, pady=5)
    menu_button = tk.Button(footer, text="MENU", command=lambda: handle("MENU"))
    menu_button.pack(side="right", padx=2, pady=5)
    lcd.bind("<Button-1>", lambda event: handle((event.x, event.y)))
    reset()
    return root, lcd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="original Japanese 705J140.dat")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--replay", type=Path, metavar="OUTPUT", help="save the settings-only regression")
    modes.add_argument("--panel-replay", type=Path, metavar="OUTPUT", help="save the full home → MENU → settings regression")
    parser.add_argument("--display-check", action="store_true", help="extend the panel replay with language and display-value checks")
    parser.add_argument("--zh-font", type=Path, help="enable the offline Chinese experiment with a verified font subset")
    parser.add_argument("--arm-zh", type=Path, metavar="BUILD", help="build and run localization on the emulated ARM CPU")
    args = parser.parse_args()
    if args.zh_font and args.replay:
        parser.error("--zh-font requires the interactive front panel or --panel-replay")
    if args.display_check and args.panel_replay is None:
        parser.error("--display-check requires --panel-replay")
    if args.arm_zh and args.zh_font is None:
        parser.error("--arm-zh requires --zh-font")
    zh_font = args.zh_font.read_bytes() if args.zh_font else None
    images = load(args.dat.read_bytes())
    arm_build = None
    if args.arm_zh:
        from tools.arm_705_display import build
        arm_build = build(args.arm_zh)
    if args.panel_replay is not None:
        touch_replay(images, args.panel_replay, front_panel=True, zh_font=zh_font, display_check=args.display_check,
                     arm_build=arm_build)
    elif args.replay is not None:
        touch_replay(images, args.replay)
    else:
        root, _ = make_window(images, zh_font=zh_font, arm_build=arm_build)
        root.mainloop()


if __name__ == "__main__":
    main()
