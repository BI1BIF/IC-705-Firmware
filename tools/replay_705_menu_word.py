"""Replay one J140 menu word from a reloadable PC resource, before stock decoding."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from struct import iter_unpack, pack, unpack

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops

from tools.arm_705_display import DISPLAY_DESC, ORIGINAL_CHOICES, SITES, DisplayArm, build, word_table
from tools.emulate_705 import PROFILES, SCRATCH, arm, call, machine, uc
from tools.probe_zh_cn_page import build_font
from tools.render_705_display import DAT_HASH, PAGE, load
from tools.render_705_stock_row import require
from tools.replay_705_language_storage import DISPLAY, EN, JA, ROWS, SYSTEM, LogicalStorage
from tools.replay_705_settings import OPEN_MENU, SettingsGuest
from tools.virtual_705_display_catalog import FONT_SOURCE_SHA


PICK_POINTER, JP_POINTER, STOCK_TEXT = 0x2014B41C, DISPLAY_DESC+0x30, 0x2035CAE0
CONVERT, CONVERT_TABLE, CONVERT_DONE = 0x20144CAC, 0x20144CD4, 0x20144DE4
STOCK_CODES, WORD_RECORD = 0x202FCDC4, 0x21011000
WORD, CODES = WORD_RECORD+4, WORD_RECORD+0x100
EXTRA = {"显": 0xF5F0, "语": 0xF5F1}
FIXTURE = Path(__file__).resolve().parents[1] / "samples/j140-display-word.json"


def add_glyphs(original, subset, chars=EXTRA):
    # Preserve stock glyph IDs, instructions and metrics. Append only missing outlines in memory.
    with TTFont(BytesIO(original), recalcTimestamp=False) as stock, TTFont(subset) as font:
        source, cmap, order = font.getGlyphSet(), font.getBestCmap(), stock.getGlyphOrder()
        scale = stock["head"].unitsPerEm / font["head"].unitsPerEm
        for ch in chars:
            cp, name = ord(ch), f"lab{ord(ch):04X}"
            require(cp not in stock.getBestCmap() and name not in order, "unexpected stock glyph")
            glyph = cmap[cp]
            recording = DecomposingRecordingPen(source)
            source[glyph].draw(recording)
            pen = TTGlyphPen(None)
            recording.replay(TransformPen(pen, (scale, 0, 0, scale, 0, 0)))
            stock["glyf"][name] = pen.glyph()
            stock["hmtx"][name] = tuple(round(v*scale) for v in font["hmtx"][glyph])
            if "vmtx" in stock:
                stock["vmtx"][name] = tuple(round(v*scale) for v in font["vmtx"][glyph])
            for table in stock["cmap"].tables:
                if table.isUnicode():
                    table.cmap[cp] = name
        output = BytesIO()
        stock.save(output)
        return output.getvalue()


def convert_probe(main, address, payload):
    cpu = machine(main)
    cpu.mem_write(SCRATCH, payload+b"\0")
    count = call(cpu, address, SCRATCH, len(payload), SCRATCH+0x100)
    return bytes(cpu.mem_read(SCRATCH+0x100, count*2)).decode("utf-16-le") if count else ""


def install_word(guest, path):
    cpu, surface = guest.cpu, guest.surface
    raw = path.read_bytes()
    words = json.loads(raw)
    require(isinstance(words, dict) and words.keys() == {"0xA7"}, "expected one display-language label")
    word = words["0xA7"]
    require(isinstance(word, str) and 1 <= len(word) <= 24 and all(ch.isalpha() for ch in word), "invalid menu word")
    encoded = b"".join(EXTRA[ch].to_bytes(2, "big") if ch in EXTRA else ch.encode("cp932") for ch in word)
    require(unpack("<I", cpu.mem_read(JP_POINTER, 4))[0] == STOCK_TEXT, "unexpected stock label pointer")
    prefix = bytes(cpu.mem_read(STOCK_CODES, 79*8))
    require(bytes(cpu.mem_read(STOCK_CODES+len(prefix), 8)) == bytes(8)
            and not set(EXTRA.values()) & {key for key, _ in iter_unpack("<II", prefix)},
            "unexpected stock character table")
    table = prefix + b"".join(pack("<II", key, ord(ch)) for ch, key in EXTRA.items()) + bytes(8)
    cpu.mem_map(WORD_RECORD, 0x1000, uc.UC_PROT_READ)
    cpu.mem_write(WORD_RECORD, pack("<I", WORD))
    cpu.mem_write(WORD, encoded+b"\0")
    cpu.mem_write(CODES, table)
    evidence = {"text": word, "sha256": sha256(raw).hexdigest(), "encoded": encoded.hex(), "reads": []}
    from_pc = None

    def lookup(_cpu, _pc, _size, _data):
        if surface.reg("R0") == JP_POINTER-4 and surface.reg("R4") == 0xA7 and guest.language() == [2, 1]:
            # Redirect the stock LDR to the data record; do not touch its caller or the converter's result.
            cpu.reg_write(arm.UC_ARM_REG_R0, WORD_RECORD-4)

    def codes(_cpu, _pc, _size, _data):
        if surface.reg("R6") == WORD:
            require(surface.reg("SL") == STOCK_CODES and surface.reg("R7") == len(encoded), "unexpected conversion ABI")
            cpu.reg_write(arm.UC_ARM_REG_SL, CODES)

    def entering(_cpu, _pc, _size, _data):
        nonlocal from_pc
        if surface.reg("R0") == WORD:
            from_pc = surface.reg("LR")

    def decoded(_cpu, _pc, _size, _data):
        nonlocal from_pc
        if surface.reg("R6") == WORD:
            count = surface.reg("R5")
            result = bytes(cpu.mem_read(surface.reg("R9"), count*2)).decode("utf-16-le") if count else ""
            require(result == word and from_pc in (0x20146844, 0x20146ABC), f"unexpected stock conversion: {result!r}")
            evidence["reads"].append({"return_pc": hex(from_pc), "text": result})
            from_pc = None

    for pc, hook in ((PICK_POINTER, lookup), (CONVERT, entering), (CONVERT_TABLE, codes), (CONVERT_DONE, decoded)):
        cpu.hook_add(uc.UC_HOOK_CODE, hook, begin=pc, end=pc)
    return evidence


def page_six(guest):
    call(guest.cpu, OPEN_MENU, 22)
    for menu, first in ((22, 4), (67, 20)):
        for _ in range(6):
            state = guest.state()
            require(state["menu"] == menu, "unexpected settings page")
            guest.render()
            if state["first"] == first:
                break
            guest.click(449, 163 if state["first"] < first else 69)
        else:
            raise ValueError("could not reach display settings page 6")
        if menu == 22:
            guest.click(120, 230)


def replay(images, source, output):
    output.mkdir(parents=True, exist_ok=True)
    path = output / "word.json"
    path.write_bytes(FIXTURE.read_bytes())
    main, stock, graphics, digest, small = images
    subset = output / "lab.ttf"
    require(sha256(source.read_bytes()).hexdigest() == FONT_SOURCE_SHA, "unexpected Noto source font")
    build_font(source, subset, "".join(EXTRA))
    lab = subset.read_bytes()
    expanded = (main, add_glyphs(stock, subset), graphics, digest, small)
    arm_build = build(output)
    en_system = ["DISPLAY", "6/6", "System Language", "English"]
    jp_picker = ["表示言語", "1/1", "英語", "日本語", "Chinese"]
    en_picker = ["Display Language", "1/1", "English", "Japanese", "Chinese"]
    converter = PROFILES[digest].convert
    report = {"dat_sha256": DAT_HASH, "main_sha256": digest, "frames": {}, "resources": {}, "storage": {},
              "unmodified_decoder": {enc: convert_probe(main, converter, "显示语言".encode(enc))
                                     for enc in ("gb18030", "utf-8")}}
    report["unmodified_decoder"]["experimental-bytes"] = convert_probe(main, converter, bytes.fromhex("f5f08ea6f5f18cbe"))
    require(all(text != "显示语言" for text in report["unmodified_decoder"].values()), "unexpected stock encoding")

    def restore(store, name, expected, *, lab_guest=True):
        guest = SettingsGuest(expanded if lab_guest else images, front_panel=True)
        if lab_guest:
            guest.display_arm = DisplayArm(guest, lab, arm_build, word_table([]), font_sha=sha256(lab).hexdigest(),
                                           third_language=True, text_hooks=False)
            require(all(bytes(guest.cpu.mem_read(pc, 4)) == pack("<I", instr) for pc, (_, instr) in SITES.items()),
                    "a post-conversion branch was installed")
            report["resources"][name] = install_word(guest, path)
        store.restore(guest)
        require(guest.language() == list(expected) and len(store.requests) == 714, "stock settings did not reload")
        page_six(guest)
        return guest

    def frame(guest, name, expected):
        labels, png = guest.render()
        require(labels == expected, f"{name}: unexpected labels {labels}")
        for label, event in zip(labels, guest.surface.events, strict=True):
            if label in ("显示语言", "界面语言"):
                require(len(event["glyphs"]) == 4 and all(g["segments"] for g in event["glyphs"]), "missing glyph")
        (output / f"{name}.png").write_bytes(png)
        report["frames"][name] = {"text": labels, "language": guest.language(), "sha256": sha256(png).hexdigest()}
        return png

    def select_save(guest, store, index, picker):
        require(guest.click(*ROWS[0]) == 0x1E and guest.render()[0] == picker, "unexpected display-language picker")
        guest.writes.clear()
        require(guest.click(*ROWS[index]) == 0x3E+index and guest.language() == [index, 1], "language click failed")
        require([w for w in guest.writes if int(w["address"], 16) in (guest.language_address, guest.language_address+1)] ==
                [{"pc": "0x200a29c0", "address": hex(guest.language_address), "size": 1, "value": index}],
                "touch did not use the original display-only write")
        before, saved = len(store.requests), bytes(store.data[DISPLAY:SYSTEM+1])
        require(saved != bytes((index, 1)) and saved[1] == 1, "unexpected pre-save language")
        store.flush(guest)
        requests = [r for r in store.requests[before:] if r["offset"] <= SYSTEM and r["offset"]+r["size"] > DISPLAY]
        require(len(requests) == 1 and (requests[0]["offset"], requests[0]["size"], requests[0]["return_pc"]) ==
                (DISPLAY, 1, "0x2004e8fc") and store.data[DISPLAY:SYSTEM+1] == bytes((index, 1)),
                "stock save changed system language")
        report["storage"][str(index)] = requests[0]
        return bytes(store.data)

    def stock_compare(guest, snapshot, name, lang, expected):
        original = restore(LogicalStorage(snapshot), name+"-stock", lang, lab_guest=False)
        png = frame(guest, name, expected)
        require(png == frame(original, name+"-stock", expected), f"{name}: changed stock pixels")
        require(all(guest.cpu.mem_read(addr, size) == original.cpu.mem_read(addr, size)
                    for addr, size in ((DISPLAY_DESC+0x3C, 0x3C), (ORIGINAL_CHOICES, 24))), "system resources changed")

    store = LogicalStorage()
    guest = restore(store, "initial", (1, 1))
    stock_compare(guest, bytes(store.data), "01-japanese", (1, 1), JA)
    chinese = select_save(guest, store, 2, jp_picker)

    store = LogicalStorage(chinese)
    guest = restore(store, "chinese", (2, 1))
    png1 = frame(guest, "02-chinese", [*JA[:2], "显示语言", "Chinese", *JA[4:]])
    path.write_text(json.dumps({"0xA7": "界面语言"}, ensure_ascii=False)+"\n", encoding="utf-8")
    require(guest.render()[0][2] == "显示语言", "loaded resource unexpectedly changed on disk edit")
    guest = restore(LogicalStorage(chinese), "edited", (2, 1))
    png2 = frame(guest, "03-chinese-edited", [*JA[:2], "界面语言", "Chinese", *JA[4:]])
    with Image.open(BytesIO(png1)) as a, Image.open(BytesIO(png2)) as b:
        box = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox()
        require(box is not None and box[2] <= 160 and 30 <= box[1] < box[3] <= 80, f"word diff outside its row: {box}")
    report["edit_pixel_bbox"] = box
    require(guest.click(*ROWS[1]) == 0x1F, "system picker not reached")
    control = restore(LogicalStorage(), "system-picker-stock", (1, 1), lab_guest=False)
    require(control.click(*ROWS[1]) == 0x1F and guest.render() == control.render(), "system picker changed")
    # Continue switching with a clean instance using the saved settings and edited word file.
    store = LogicalStorage(chinese)
    guest = restore(store, "chinese-exit", (2, 1))
    english = select_save(guest, store, 0, jp_picker)
    store = LogicalStorage(english)
    guest = restore(store, "english", (0, 1))
    stock_compare(guest, english, "04-english", (0, 1), EN)
    japanese = select_save(guest, store, 1, en_picker)
    guest = restore(LogicalStorage(japanese), "japanese", (1, 1))
    stock_compare(guest, japanese, "05-japanese-reloaded", (1, 1), JA)
    control = LogicalStorage(chinese)
    control.data[SYSTEM] = 0
    guest = restore(control, "english-system", (2, 0))
    stock_compare(guest, bytes(control.data), "06-english-system", (2, 0), en_system)
    for name, entry in report["resources"].items():
        require(bool(entry["reads"]) == (name in ("chinese", "edited", "chinese-exit")), f"{name}: unexpected lookup")
    (output / "menu-word.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"J140 source-word replay passed: {output / 'menu-word.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font-source", type=Path, default=Path(".analysis/zh-cn-preview/noto/NotoSansSC-VF.ttf"))
    args = parser.parse_args()
    replay(load(args.dat.read_bytes()), args.font_source, args.output)


if __name__ == "__main__":
    main()
