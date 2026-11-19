"""Replay the J140 display catalogue against original firmware with identical input."""

from hashlib import sha256
import json

from tools.render_705_display import DAT_HASH, PAGE
from tools.render_705_stock_row import require
from tools.virtual_705_panel import JA_PAGE, check_display_values, start
from tools.virtual_705_display_catalog import DISPLAY, LANGUAGE, TIME, UNITS
from tools.zh_705_row import AUTO_LABEL, AUTO_SOURCE, DISPLAY_PAGE, STOCK_LABEL, TIMEOUTS, ZH_LABEL

UP, DOWN, BACK = (449, 69), (449, 163), (449, 244)
ROWS = ((120, 54), (120, 100), (120, 157), (120, 217))
SWITCH = ("OFF", "ON")
# The value shown in the first stock frame, followed by the picker's choices, in order.
PAGES = (
    (("受信LED", SWITCH), ("メーターピークホールド", SWITCH),
     ("メモリーネーム", SWITCH), ("グループネームポップアップ", SWITCH)),
    (("受信コールサイン表示", ("OFF", "ノーマル", "受信ホールド", "ホールド")),
     ("受信位置インジケーター", SWITCH), ("受信位置表示", SWITCH),
     ("受信位置表示時間", ("5秒", "10秒", "15秒", "30秒", "ホールド"))),
    (("自動応答位置表示", SWITCH), ("受信画像インジケーター", SWITCH),
     ("DV受信バックライト", SWITCH), ("送信コールサイン表示", ("OFF", "相手局", "自局"))),
    (("スクロール速度", ("遅い", "速い")), ("オープニングメッセージ", SWITCH),
     ("パワーオンチェック", SWITCH), ("表示単位", ())),
)
UNIT_PAGES = (
    (("緯度/経度", ("dddﾟmm.mm'", "dddﾟmm'ss\"", "ddd.ddddﾟ")), ("高度/距離", ("m", "ft/mi")),
     ("速度", ("km/h", "mph", "knots")), ("気温", ("ﾟC", "ﾟF"))),
    (("気圧", ("hPa", "mb", "mmHg", "inHg")), ("雨量", ("mm", "inch")),
     ("風速", ("m/s", "km/h", "mph", "knots"))),
)
ON_OFF = {word: DISPLAY_PAGE[word] for word in SWITCH}
TIMERS = {n + "分": n + " 分钟" for n in TIMEOUTS}


def expected_words(menu, first, item, language, words):
    if language != [1, 1]:
        return words
    if menu == 67 and first == 0 or menu == 286 and item in (0x8C, 0x8E, 0x8F, 0x90):
        terms = DISPLAY_PAGE | TIMERS | {AUTO_SOURCE: AUTO_LABEL}
    elif menu == 67 or menu == 286 and 0x91 <= item <= 0x9F:
        terms = DISPLAY | ON_OFF | {STOCK_LABEL: ZH_LABEL}
    elif menu == 68 or menu == 286 and 0xA0 <= item <= 0xA6:
        terms = UNITS
    elif menu == 286 and item == 0xA7:
        terms = LANGUAGE | {STOCK_LABEL: ZH_LABEL}
    elif menu in (69, 70) or menu == 286 and item == 0xAE:
        terms = TIME | ON_OFF
    else:
        return words
    return [terms.get(word, word) for word in words]


def item_of(guest):
    return int.from_bytes(guest.cpu.mem_read(PAGE+348, 2), "little")


def replay(images, settings, output):
    original, localized = start(images), start(images, **settings)
    require(localized.chinese is None, "host text replacement must stay disabled")
    for branch in ("stock", "zh"):
        (output / branch).mkdir(parents=True, exist_ok=True)
    log = []

    def step(name, touch=None, *, menu=None, item=None, first=None, hit=None, stock=None, language=(1, 1),
             seed=None, prefs=None):
        runs = []
        for guest in (original, localized):
            for address, value in (seed or {}).items():
                guest.cpu.mem_write(address, bytes([value]))
            guest.writes.clear()
            region = None
            if touch == "MENU":
                guest.press_menu()
            elif touch is not None:
                region = guest.click(*touch)
            after_input = guest.language()
            words, frame = guest.render()
            require(guest.language() == after_input == list(language), f"{name}: incorrect language preferences")
            if prefs is not None:
                actual = tuple(guest.cpu.mem_read(0x203EAE26, 2)) + tuple(guest.cpu.mem_read(0x203EAE37, 3))
                require(actual == prefs, f"{name}: original display preferences changed: {actual}")
            runs.append((region, guest.state(), item_of(guest), list(guest.writes), words, frame))
        a, b = runs
        require(a[:4] == b[:4], f"{name}: ARM module changed touch, navigation or preference writes")
        region, state, active_item, writes, original_words, original_frame = a
        require(hit is None or hit == region, f"{name}: hit {region!r}, expected {hit!r}")
        require(menu is None or state["menu"] == menu, f"{name}: menu {state}")
        require(first is None or state["first"] == first, f"{name}: page {state}")
        if item is not None:
            require(active_item == item, f"{name}: got item {active_item:#x}, expected {item:#x}")
        require(stock is None or original_words == stock, f"{name}: original shows {original_words!r}, expected {stock!r}")
        translated, frame = b[4:]
        expected = expected_words(state["menu"], state["first"], active_item, list(language), original_words)
        require(translated == expected, f"{name}: Chinese shows {translated!r}, expected {expected!r}")
        changed = original_words != translated
        require((original_frame != frame) == changed, f"{name}: unexpected pixel equality")
        if changed:
            for i, (before, after) in enumerate(zip(original_words, translated)):
                stock_event = original.surface.events[i]
                event = localized.surface.events[i]
                if before == after:
                    require(event == stock_event, f"{name}: unmodified text changed: {before}")
                else:
                    require(event["translation"][1] == stock_event["translation"][1] and
                            all(g["segments"] for g in event["glyphs"] if g["key"] != ord(" ")),
                            f"{name}: Chinese text moved to a different row or has a missing glyph: {after}")
        previous = log[-1]["arm_applies"] if log else 0
        applied = localized.display_arm.counts()
        require((applied > previous) == changed, f"{name}: ARM processing did not match its scope")
        for branch, data in (("stock", original_frame), ("zh", frame)):
            (output / branch / (name+".png")).write_bytes(data)
        log.append(dict(frame=name, touch=touch, hit=region, state=state, item=hex(active_item), writes=writes, seed=seed,
                        language=language, stock=original_words, zh=translated, arm_applies=applied,
                        stock_png=sha256(original_frame).hexdigest(), zh_png=sha256(frame).hexdigest()))
        return original_words

    step("home")
    step("menu", "MENU")
    step("set", (429, 182), menu=22, first=0, hit=0x1B9)
    step("set-2", DOWN, menu=22, first=4, hit=0x23)
    step("display-1", (120, 230), menu=67, first=0, hit=0x21, stock=JA_PAGE)

    def page_one(name, xy, words, *, event=None, **kwargs):
        step(name, xy, stock=words, **kwargs)

    check_display_values(page_one, JA_PAGE, localized=False)

    def visit(page, title, pager, rows, item_start, selections, values, menu, first):
        def listing():
            return [title, pager, *(word for (label, choices), value in zip(rows, values)
                                    for word in ((label, value) if choices else (label,)))]

        for index, (label, choices) in enumerate(rows):
            if not choices:
                continue
            item = item_start + index
            case = f"{page}-{item:02x}"
            for choice_page, start in enumerate(range(0, len(choices), 4), 1):
                xy = ROWS[index] if choice_page == 1 else DOWN
                step(f"{case}-options-{choice_page}", xy, menu=286, item=item, first=start,
                     hit=0x1E+index if choice_page == 1 else 0x43,
                     stock=[label, f"{choice_page}/{(len(choices)+3)//4}", *choices[start:start+4]])
                if item == 0x98 and choice_page == 1:
                    values[index] = "30秒"
                    step(f"{case}-30-seconds", ROWS[3], menu=menu, first=first, hit=0x41, stock=listing())
                    step(f"{case}-reopen", ROWS[index], menu=286, item=item, first=0, hit=0x21,
                         stock=[label, "1/2", *choices[:4]])
            if item in selections:
                choice = selections[item]
                values[index] = choices[choice]
                select = ROWS[choice % 4]
                step(f"{case}-select", select, menu=menu, first=first, hit=0x3E+choice % 4, stock=listing())
            else:
                step(f"{case}-back", BACK, menu=menu, first=first, hit=0x44, stock=listing())

    display_title = "ディスプレイ設定"
    for number, rows in enumerate(PAGES, 2):
        pager, first, name = f"{number}/6", (number-1)*4, f"display-{number}"
        values = [choices[0] if choices else None for _, choices in rows]
        step(name, DOWN, menu=67, first=first, hit=0x23,
             stock=[display_title, pager, *(word for (label, choices), value in zip(rows, values)
                                             for word in ((label, value) if choices else (label,)))])
        visit(name, display_title, pager, rows, 0x91+(number-2)*4,
              {0x91: 1, 0x95: 2, 0x98: 4, 0x9C: 2, 0x9D: 1}, values, 67, first)

    for number, rows in enumerate(UNIT_PAGES, 1):
        name, title, pager, first = f"units-{number}", "表示単位", f"{number}/2", (number-1)*4
        values = [choices[0] for _, choices in rows]
        step(name, (120, 230) if number == 1 else DOWN, menu=68, first=first, hit=0x21 if number == 1 else 0x23,
             stock=[title, pager, *(word for (label, _), value in zip(rows, values) for word in (label, value))])
        visit(name, title, pager, rows, 0xA0+(number-1)*4,
              {0xA0: 2, 0xA2: 2, 0xA3: 1, 0xA5: 1, 0xA6: 3}, values, 68, first)

    step("units-return", BACK, menu=67, first=16, hit=0x24)
    japanese = [display_title, "6/6", STOCK_LABEL, "日本語", "システム言語", "日本語"]
    step("display-6", DOWN, menu=67, first=20, hit=0x23, stock=japanese)
    step("system-language", (120, 119), menu=286, item=0xA8, hit=0x1F,
         stock=["システム言語", "1/1", "英語", "日本語"])
    step("system-back", BACK, menu=67, first=20, hit=0x44, stock=japanese)
    step("display-language", ROWS[0], menu=286, item=0xA7, hit=0x1E, stock=[STOCK_LABEL, "1/1", "英語", "日本語"])
    step("english", ROWS[0], menu=67, first=20, hit=0x3E, language=(0, 1),
         stock=["DISPLAY", "6/6", "Display Language", "English", "System Language", "Japanese"])
    for number in range(5, 0, -1):
        words = step(f"english-{number}", UP, menu=67, first=(number-1)*4, hit=0x22, language=(0, 1))
        require(words[:2] == ["DISPLAY", f"{number}/6"], f"page {number}: incorrect English title")
    for number in range(2, 7):
        step(f"english-return-{number}", DOWN, menu=67, first=(number-1)*4, hit=0x23, language=(0, 1))
    step("english-picker", ROWS[0], menu=286, item=0xA7, hit=0x1E, language=(0, 1),
         stock=["Display Language", "1/1", "English", "Japanese"])
    step("japanese-return", (120, 119), menu=67, first=20, hit=0x3F, stock=japanese)
    step("set-return", BACK, menu=22, first=4, hit=0x24)
    step("set-3", DOWN, menu=22, first=8, hit=0x23)
    step("time", ROWS[0], menu=69, first=0, hit=0x1E, stock=["時間設定", "1/1", "日時設定", "UTCオフセット", "± 0:00"])
    step("date-1", ROWS[0], menu=70, first=0, hit=0x1E,
         stock=["日時設定", "1/2", "日付", "2000/00/00()", "時間", " 0:00:00", "<<ネットワーク時刻補正>>", "NTP機能", "OFF"])
    step("ntp", ROWS[3], menu=286, item=0xAE, hit=0x21, stock=["NTP機能", "1/1", "OFF", "ON"])
    step("ntp-back", BACK, menu=70, first=0, hit=0x44)
    step("date-2", DOWN, menu=70, first=4, hit=0x23,
         stock=["日時設定", "2/2", "NTPサーバーアドレス", "GPS時刻補正", "OFF"])
    step("date-return", BACK, menu=69, first=0, hit=0x24)
    step("time-return", BACK, menu=22, first=8, hit=0x24)
    step("home-return", BACK, menu=0, hit=0x24)
    require(log[0]["stock_png"] == log[-1]["stock_png"], "home pixels changed after returning")

    pref = hex(original.language_address)
    system_pref = hex(original.language_address+1)
    require(not any(w["address"] == system_pref for row in log for w in row["writes"]),
            "system-language preference was written")
    require([(row["frame"], w["value"]) for row in log for w in row["writes"] if w["address"] == pref]
            == [("english", 0), ("japanese-return", 1)], "unexpected display-language preference writes")
    changed = sum(row["stock_png"] != row["zh_png"] for row in log)
    report = dict(input_sha256=DAT_HASH, main_sha256=original.main_hash, arm=localized.display_arm.evidence,
                  frames=len(log), translated_frames=changed, paired_arm_calls=localized.display_arm.counts(), steps=log)
    (output / "trace.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"{len(log)} frames, {changed} translated, {localized.display_arm.counts()} paired ARM calls")
