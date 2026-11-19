"""Check the independent J140 display language through original touch, save and read paths."""

from hashlib import sha256
from io import BytesIO
import json

from PIL import Image, ImageChops

from tools.arm_705_display import DISPLAY_DESC, ORIGINAL_CHOICES, SET_CAPTION_RECT, THIRD_LABEL, THIRD_TOKEN
from tools.emulate_705 import call
from tools.render_705_display import DAT_HASH, PAGE
from tools.render_705_stock_row import require
from tools.replay_705_language_storage import DISPLAY, EN, JA, ROWS, SYSTEM, LogicalStorage
from tools.replay_705_settings import OPEN_MENU
from tools.verify_705_display_catalog import expected_words
from tools.virtual_705_panel import EN_PAGE, JA_PAGE, start


ZH = ["显示设置", "6/6", "显示语言", THIRD_LABEL, "システム言語", "日本語"]
JA_PICK = ["表示言語", "1/1", "英語", "日本語"]
EN_PICK = ["Display Language", "1/1", "English", "Japanese"]
ZH_PICK = ["显示语言", "1/1", "英语", "日语", THIRD_LABEL]
SYSTEM_PICK = ["システム言語", "1/1", "英語", "日本語"]
SET_FIRST = ["设置", "1/4", "音调控制/发射带宽", "功能设置", "本机设置", "DV 设置"]
SET_SECOND = ["设置", "2/4", "DV 中继监听设置", "通联/接收记录", "外部接口", "显示设置"]
MISSING_GLYPHS = "显简设"


def replay(images, settings, output, *, fallback):
    output.mkdir(parents=True, exist_ok=True)
    report = {"dat_sha256": DAT_HASH, "main_sha256": images[3], "frames": {}, "selections": [],
              "storage": {}, "pixel_comparisons": []}
    frames = report["frames"]
    stock = start(images)
    system_descriptor = bytes(stock.cpu.mem_read(DISPLAY_DESC+0x3C, 0x3C))
    shared_choices = bytes(stock.cpu.mem_read(ORIGINAL_CHOICES, 24))

    def frame(guest, expected=None, name=None, *, missing=False):
        language = guest.language()
        labels, image = guest.render()
        require(guest.language() == language, "render changed the language setting")
        if not missing:
            require(THIRD_TOKEN not in labels, "unexpected fallback for the third language")
        if expected is not None:
            require(labels == expected, f"{name}: unexpected labels {labels}")
        if guest.display_arm is not None:
            guest.display_arm.counts()
            for label, event in zip(labels, guest.surface.events, strict=True):
                if any("\u4e00" <= ch <= "\u9fff" for ch in label) and label in (
                    *SET_FIRST, *SET_SECOND, "菜单", THIRD_LABEL, "显示语言"
                ):
                    require(all(g["segments"] for ch, g in zip(label, event["glyphs"], strict=True) if ch != " "),
                            f"missing glyph for {label}")
        if name is not None:
            (output / f"{name}.png").write_bytes(image)
            frames[name] = {"text": labels, "png_sha256": sha256(image).hexdigest(), "language": guest.language(),
                            "menu": guest.state()["menu"], "item": int.from_bytes(guest.cpu.mem_read(PAGE+348, 2), "little")}
        return labels, image

    def click(guest, xy, hit):
        require(guest.click(*xy) == hit, f"unexpected touch region at {xy}")

    def open_display(guest, *, name=None, missing=False):
        zh = guest.display_arm is not None and guest.language() == [2, 1]
        guest.press_menu()
        grid = frame(guest, ["菜单" if zh else "MENU"], name+"-menu" if name else None)[1]
        click(guest, (429, 182), 0x1B9)
        if name and zh and not missing and guest.state()["first"] == 4:
            frame(guest, SET_SECOND)
            click(guest, (449, 69), 0x22)
        if guest.state()["first"] == 0:
            frame(guest, SET_FIRST if zh and not missing else None, name+"-set1" if name and zh and not missing else None)
            click(guest, (449, 163), 0x23)
        expected = SET_SECOND if zh and not missing else (
            ["セット", "2/4", "DVレピータモニター設定", "通联/接收记录", "外部接口", "ディスプレイ設定"] if missing else None
        )
        set2 = frame(guest, expected, name+"-set2" if name else None)[1]
        require(guest.state()["menu"] == 22 and guest.state()["first"] == 4, "did not open SET page 2")
        click(guest, (120, 230), 0x21)
        require(guest.state()["menu"] == 67, "did not open display settings")
        for _ in range(5):
            if guest.state()["first"] == 0:
                break
            frame(guest, missing=missing)
            click(guest, (449, 69), 0x22)
        require(guest.state()["first"] == 0, "did not reach display page 1")
        return grid, set2

    def sixth(guest, *, missing=False):
        for _ in range(5):
            frame(guest, missing=missing)
            click(guest, (449, 163), 0x23)
        require(guest.state()["menu"] == 67 and guest.state()["first"] == 20, "did not reach display page 6")

    def restore(store, name, expected, *, original=False, missing=False):
        guest = start(images, **({} if original else fallback if missing else settings))
        store.restore(guest)
        require(guest.language() == list(expected) and len(store.requests) == 714 and
                all(r["op"] == "read" for r in store.requests), "fresh instance did not reload original settings")
        covering = [r for r in store.requests if r["offset"] <= DISPLAY < r["offset"]+r["size"]]
        require(len(covering) == 1 and covering[0]["return_pc"] == "0x2004e78c", "missing stock read of language")
        require(bytes(guest.cpu.mem_read(DISPLAY_DESC+0x3C, 0x3C)) == system_descriptor and
                bytes(guest.cpu.mem_read(ORIGINAL_CHOICES, 24)) == shared_choices, "stock system choices changed")
        report["storage"][name] = {"language": guest.language(), "read": covering[0]}
        call(guest.cpu, OPEN_MENU, 0)
        frame(guest)
        return guest

    def choose(guest, store, index):
        guest.writes.clear()
        before = len(store.requests)
        click(guest, ROWS[index], 0x3E+index)
        writes = [w for w in guest.writes if int(w["address"], 16) in range(guest.language_address,
                                                                            guest.language_address+2)]
        require(writes == [{"pc": "0x200a29c0", "address": hex(guest.language_address), "size": 1, "value": index}]
                and guest.language() == [index, 1] and len(store.requests) == before,
                "display choice did not use the original display-only write")
        report["selections"].append(writes[0])

    def flush(guest, store, name, expected):
        before, start_index = bytes(store.data), len(store.requests)
        store.flush(guest)
        writes = store.requests[start_index:]
        covering = [r for r in writes if r["offset"] <= DISPLAY < r["offset"]+r["size"]]
        require(before[DISPLAY] != expected and store.data[DISPLAY:SYSTEM+1] == bytes((expected, 1)) and
                before[SYSTEM] == store.data[SYSTEM], "unexpected simulated storage change")
        require(len(covering) == 1 and covering[0]["offset"] == DISPLAY and covering[0]["size"] == 1 and
                covering[0]["return_pc"] == "0x2004e8fc", "missing stock single-byte flush")
        report["storage"][name] = {"language": list(store.data[DISPLAY:SYSTEM+1]), "write": covering[0]}

    def compare_stock(guest, snapshot, label, expected, first, nav):
        original = restore(LogicalStorage(snapshot), label+"-stock", tuple(guest.language()), original=True)
        require(nav == open_display(original), f"{label}: MENU grid or SET page 2 differs from stock")
        stock_words, stock_image = frame(original)
        require(stock_words[:2] == first[:2] and frame(guest, stock_words)[1] == stock_image,
                f"{label}: page 1 differs from stock")
        sixth(guest)
        sixth(original)
        require(frame(guest, expected, label)[1] == frame(original, expected)[1], f"{label}: page 6 differs from stock")
        report["pixel_comparisons"].extend((label+"-menu", label+"-set2", label+"-page1", label+"-page6"))
        return original

    def tile(png):
        with Image.open(BytesIO(png)) as lcd:
            return lcd.crop((383, 132, 473, 222)).convert("RGB")

    store = LogicalStorage()
    guest = restore(store, "initial", (1, 1))
    report["arm"] = guest.display_arm.evidence
    nav = open_display(guest)
    original = compare_stock(guest, bytes(store.data), "01-japanese-stock-match", JA, JA_PAGE, nav)
    click(original, ROWS[1], 0x1F)
    system_stock = frame(original, SYSTEM_PICK)[1]
    click(guest, ROWS[0], 0x1E)
    frame(guest, JA_PICK+[THIRD_LABEL], "02-three-display-choices")
    choose(guest, store, 2)
    frame(guest, ZH, "03-chinese-selected")
    click(guest, ROWS[1], 0x1F)
    require(frame(guest, SYSTEM_PICK, "04-system-language-unchanged")[1] == system_stock,
            "the original system picker changed under Chinese display")
    report["pixel_comparisons"].append("system-picker-japanese")
    click(guest, (449, 244), 0x44)
    frame(guest, ZH)
    restore(LogicalStorage(bytes(store.data)), "unsaved-control", (1, 1))
    flush(guest, store, "save-chinese", 2)

    store = LogicalStorage(bytes(store.data))
    guest = restore(store, "reload-chinese", (2, 1))
    chinese_snapshot = bytes(store.data)
    chinese_grid, _ = open_display(guest, name="11-chinese-nav")
    # Some fields besides language are also saved; use the Japanese rendering of this snapshot as the source oracle.
    japanese = LogicalStorage(bytes(store.data))
    japanese.data[DISPLAY] = 1
    original = restore(japanese, "chinese-page-source-stock", (1, 1), original=True)
    stock_grid, _ = open_display(original, name="12-japanese-nav")
    diff = ImageChops.difference(tile(stock_grid), tile(chinese_grid)).getbbox()
    require(diff is not None and diff[0] >= SET_CAPTION_RECT[0] and diff[1] >= SET_CAPTION_RECT[1]
            and diff[2] <= SET_CAPTION_RECT[2] and diff[3] <= SET_CAPTION_RECT[3],
            f"SET button differs outside its caption: {diff}")
    report["navigation"] = {"set_caption_diff_bbox": diff, "set_touch_region": "0x1b9",
                            "display_settings_touch_region": "0x21"}
    source = frame(original)[0]
    localized = frame(guest, name="05-chinese-reloaded-page1")[0]
    require(localized == expected_words(67, 0, 0, [1, 1], source) and localized[:2] == ["显示设置", "1/6"],
            f"unexpected page 1 content: stock {source}, Chinese {localized}")
    sixth(guest)
    frame(guest, ZH, "06-chinese-reloaded-page6")
    click(guest, ROWS[0], 0x1E)
    _, picker_image = frame(guest, ZH_PICK, "07-chinese-reloaded-picker")
    with Image.open(BytesIO(picker_image)) as lcd:
        require(guest.state()["selection"] == 2 and lcd.getpixel((380, 181)) == (93, 160, 201, 255)
                and lcd.getpixel((380, 119)) == (0, 0, 0, 255), "reloaded third choice is not highlighted")
    choose(guest, store, 0)
    frame(guest, EN)
    flush(guest, store, "save-english", 0)

    store = LogicalStorage(bytes(store.data))
    guest = restore(store, "reload-english", (0, 1))
    nav = open_display(guest)
    compare_stock(guest, bytes(store.data), "08-english-stock-match", EN, EN_PAGE, nav)
    click(guest, ROWS[0], 0x1E)
    frame(guest, EN_PICK+[THIRD_LABEL])
    choose(guest, store, 1)
    frame(guest, JA)
    flush(guest, store, "save-japanese", 1)

    guest = restore(LogicalStorage(bytes(store.data)), "reload-japanese", (1, 1))
    nav = open_display(guest)
    compare_stock(guest, bytes(store.data), "09-japanese-reloaded", JA, JA_PAGE, nav)

    control = LogicalStorage(bytes(store.data))
    control.data[DISPLAY:SYSTEM+1] = b"\x02\x00"
    guest = restore(control, "english-system", (2, 0))
    nav = open_display(guest)
    compare_stock(guest, bytes(control.data), "10-english-system-control",
                  ["DISPLAY", "6/6", "System Language", "English"], EN_PAGE, nav)
    require(guest.display_arm.counts() == 0, "system English allowed Chinese text")

    report["fallback"] = {"omitted_glyphs": MISSING_GLYPHS, "exits": {}}
    for index, language in ((0, "english"), (1, "japanese")):
        store = LogicalStorage(chinese_snapshot)
        guest = restore(store, "missing-"+language+"-initial", (2, 1), missing=True)
        prefix = "13-missing" if index == 0 else None
        missing_grid, _ = open_display(guest, name=prefix, missing=True)
        require(tile(missing_grid).tobytes() == tile(stock_grid).tobytes(), "missing glyph changed the stock SET tile")
        sixth(guest, missing=True)
        frame(guest, ["ディスプレイ設定", "6/6", "表示言語", THIRD_TOKEN, "システム言語", "日本語"],
              "13-missing-display" if prefix else None, missing=True)
        click(guest, ROWS[0], 0x1E)
        frame(guest, ["表示言語", "1/1", "英语", "日语", THIRD_TOKEN],
              "13-missing-picker" if prefix else None, missing=True)
        miss_count = guest.display_arm.missing()
        require(miss_count > 0, "ARM did not detect any missing glyphs")
        choose(guest, store, index)
        frame(guest, EN if index == 0 else JA, f"14-recovered-{language}")
        flush(guest, store, "missing-save-"+language, index)
        recovered = restore(LogicalStorage(bytes(store.data)), "missing-reload-"+language, (index, 1), missing=True)
        report["fallback"]["exits"][language] = {"missing_run_checks": miss_count, "reloaded": recovered.language()}

    (output / "third-language.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Independent J140 language replay passed: {output / 'third-language.json'}")
