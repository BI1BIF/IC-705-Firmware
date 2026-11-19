"""Build and render a static TrueType subset on the PC, with stock fallback."""

import argparse
import hashlib
import json
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont, features

from tools.probe_705_fonts import inspect_font


FIXTURE = Path(__file__).resolve().parents[1] / "samples" / "zh-cn-display.json"
CONTROLS = "\u8868\u9891\u8bbe\u84dd\u7b80"
ABSENT = "\u0378"
STOCK_LABELS = {"ja": "\u8868\u793a\u8a00\u8a9e", "en": "Display Language"}


def signature(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build_font(source, target, chars):
    options = subset.Options()
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17]
    options.name_languages = [0x409]
    options.ignore_missing_unicodes = False
    sub = subset.Subsetter(options=options)
    sub.populate(text=chars)
    with TTFont(source, recalcTimestamp=False) as font:
        sub.subset(font)
        instantiateVariableFont(font, {"wght": 400}, inplace=True, static=True)
        names = font["name"]
        renamed = {1: "IC705 Lab SC", 2: "Regular", 3: "IC705LabSC-Regular",
                   4: "IC705 Lab SC Regular", 6: "IC705LabSC-Regular",
                   16: "IC705 Lab SC", 17: "Regular"}
        names.names = [rec for rec in names.names if rec.nameID not in renamed]
        for name_id, value in renamed.items():
            names.setName(value, name_id, 3, 1, 0x409)
        font.save(target)
    with TTFont(target) as font:
        if any(tag in font for tag in ("fvar", "gvar", "CFF ", "CFF2")):
            raise ValueError("subset must be a static glyf font")


def font_coverage(path, chars):
    return inspect_font(path.read_bytes(), chars)["glyphs"]


def missing(coverage, text):
    return sorted({char for char in text if not coverage[f"U+{ord(char):04X}"]["glyph_id"]})


def rows_for(fixture):
    yield "title", fixture["title"], (18, 0, 290, 44), 24, "#F2F7FC"
    yield "badge", fixture["badge"], (366, 0, 98, 44), 13, "#D3E3F3"
    yield "breadcrumb", fixture["breadcrumb"], (18, 48, 444, 24), 14, "#A7C2D8"
    for i, choice in enumerate(fixture["choices"]):
        y = 78 + 42 * i
        yield f"choice-{i}", choice["label"], (30, y, 288, 36), 20, "#F2F7FC"
        if choice["status"]:
            yield f"status-{i}", choice["status"], (365, y, 80, 36), 14, "#D3E3F3"
    yield "fallback-note", fixture["fallback_note"], (18, 205, 444, 28), 15, "#D3E3F3"
    yield "mixed", fixture["mixed_format"].format(fixture["frequency"], fixture["mode"]), (18, 233, 444, 29), 15, "#A7C2D8"


def render(rows, choices, fonts, coverage, fallback=None):
    image = Image.new("RGB", (480, 272), "#101822")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 479, 43), fill="#1D3550")
    for i, choice in enumerate(choices):
        y = 78 + 42 * i
        draw.rectangle((18, y, 461, y + 35), fill="#254F77" if choice["active"] else "#1C2B39")
    checks = []
    for id_, original, (x, y, w, h), em, color in rows:
        primary = original + ABSENT if fallback and id_ == "title" else original
        absent = missing(coverage["sc"], primary)
        role, text = (fallback, STOCK_LABELS[fallback]) if absent and fallback and id_ == "title" else ("sc", primary)
        if missing(coverage[role], text):
            raise ValueError(f"missing glyph in {id_} from {role}")
        font = ImageFont.truetype(str(fonts[role]), em, layout_engine=ImageFont.Layout.BASIC)
        mask, (left, top) = font.getmask2(text)
        ink = mask.getbbox()
        advance = font.getlength(text)
        if not ink:
            raise ValueError(f"empty ink in {id_}")
        ix, iy, right, bottom = ink
        dx = x - min(0, left + ix)
        dy = y + (h - (bottom - iy)) // 2 - top - iy
        bounds = [dx + left + ix, dy + top + iy, dx + left + right, dy + top + bottom]
        if not (0 <= x <= bounds[0] < bounds[2] <= x + w <= 480
                and 0 <= y <= bounds[1] < bounds[3] <= y + h <= 272
                and dx + advance <= x + w):
            raise ValueError(f"text exceeds box: {id_}")
        draw.text((dx, dy), text, font=font, fill=color)
        checks.append({"id": id_, "text": text, "font": role, "missing_primary": absent,
                       "advance_px": advance, "ink_bounds": bounds, "box": [x, y, w, h]})
    return image, checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("noto_vf", type=Path)
    parser.add_argument("stock_large", type=Path)
    parser.add_argument("stock_small", type=Path)
    parser.add_argument("output", type=Path, help="new directory under .analysis/")
    args = parser.parse_args()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = list(rows_for(fixture))
    page_chars = set("".join(row[1] for row in rows))
    chars = "".join(sorted(page_chars | set(CONTROLS)))
    args.output.mkdir(parents=True, exist_ok=False)
    sc = args.output / "IC705LabSC-Regular.ttf"
    build_font(args.noto_vf, sc, chars)
    fonts = {"sc": sc, "ja": args.stock_large, "en": args.stock_small}
    coverage = {role: font_coverage(path, chars + ABSENT + "".join(STOCK_LABELS.values()))
                for role, path in fonts.items()}
    if missing(coverage["sc"], chars) or missing(coverage["sc"], ABSENT) != [ABSENT]:
        raise ValueError("subset coverage or negative control failed")
    sc24 = ImageFont.truetype(str(sc), 24)
    ja24 = ImageFont.truetype(str(args.stock_large), 24)
    stock_control = [coverage["ja"][f"U+{ord(c):04X}"]["glyph_id"] for c in CONTROLS]
    ink_control = [sc24.getmask(c).getbbox() for c in CONTROLS]
    if stock_control != [3136, 0, 0, 0, 0] or not ja24.getmask(CONTROLS[0]).getbbox() or not all(ink_control):
        raise ValueError("stock or SC ink control failed")
    runs = {}
    for name, fallback in (("language-preview", None), ("fallback-ja", "ja"), ("fallback-en", "en")):
        image, checks = render(rows, fixture["choices"], fonts, coverage, fallback)
        if checks[0]["font"] != (fallback or "sc") or checks[0]["missing_primary"] != ([ABSENT] if fallback else []):
            raise ValueError("fallback control failed")
        image.save(args.output / f"{name}.png")
        runs[name] = checks
    report = {
        "canvas": [480, 272], "page_codepoints": len(page_chars), "subset_requested_codepoints": len(chars),
        "input_fonts": {"noto_vf": signature(args.noto_vf), "stock_large": signature(args.stock_large),
                        "stock_small": signature(args.stock_small)},
        "subset": signature(sc), "freetype": features.version("freetype2"),
        "controls": [{"character": c, "stock_large_glyph": gid, "sc_24px_ink": box}
                     for c, gid, box in zip(CONTROLS, stock_control, ink_control)],
        "runs": runs,
    }
    (args.output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
