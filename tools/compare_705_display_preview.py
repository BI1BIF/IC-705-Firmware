"""Compare stock and localized --display-check replays, including unchanged pixels."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops


# Stock LCD coordinates (top-left origin): title, four row labels, three option values.
TEXT_BOXES = ((150, 0, 331, 24), (0, 25, 365, 61), (0, 86, 365, 123),
              (0, 148, 365, 185), (0, 210, 365, 248), (342, 118, 413, 148),
              (342, 180, 413, 210), (342, 242, 413, 272))


def compare(stock, chinese, arm=None, empty=None):
    def read(directory):
        trace = json.loads((directory / "trace.json").read_text(encoding="utf-8"))
        return [s["frame"] for s in trace["steps"]], {s["frame"]: s for s in trace["steps"]}

    stock_order, baseline = read(stock)
    order, translated = read(chinese)
    if order != stock_order or "auto-backlight" not in order:
        raise ValueError("expected matching --display-check replays")

    page, legacy, subpages = [], [], []
    for name in order:
        a, b = baseline[name], translated[name]
        if any(a[k] != b[k] for k in a.keys() - {"png_sha256", "text", "draw_calls"}):
            raise ValueError(f"{name}: input, preferences or drawing setup changed")
        with Image.open(stock / f"{name}.png") as x, Image.open(chinese / f"{name}.png") as y:
            diff = ImageChops.difference(x.convert("RGB"), y.convert("RGB"))
        if not diff.getbbox():
            if b["chinese_runs"]:
                raise ValueError(f"{name}: localized text produced no pixel change")
        elif (b["after"]["menu"], b["after"]["first"], b["language_after"]) == (67, 0, [1, 1]):
            page.append(name)
            for box in TEXT_BOXES:
                diff.paste((0, 0, 0), box)
            if diff.getbbox() or not b["chinese_runs"]:
                raise ValueError(f"{name}: unexpected localized pixels {diff.getbbox()}")
        elif b.get("display_item") in (0x8C, 0x8E, 0x8F, 0x90) and b["chinese_runs"]:
            subpages.append(name)
            boxes = ((120, 0, 360, 24), (175, 175, 305, 218)) if b["display_item"] == 0x8C else (
                (0, 0, 415, 24), (0, 24, 415, 272))
            for box in boxes:
                diff.paste((0, 0, 0), box)
            if diff.getbbox():
                raise ValueError(f"{name}: pixels changed outside the subpage text area")
        elif b["chinese_runs"] and all(run["text"] == "显示语言" for run in b["chinese_runs"]):
            legacy.append(name)
        else:
            raise ValueError(f"{name}: unexpected pixel changes {diff.getbbox()}")

    counts = (len(page), len(subpages), len(legacy))
    if counts != ((10, 9, 6) if "brightness-editor" in order else (9, 0, 6)):
        raise ValueError(f"unexpected first-page, subpage and legacy change counts: {counts}")
    report = {"frames": len(order), "first_page_changed": page, "subpage_changed": subpages,
              "legacy_label_changed": legacy, "identical_frames": len(order) - sum(counts)}
    for path, reference, frames in ((arm, chinese, translated), (empty, stock, baseline)):
        if path is None:
            continue
        control_order, control = read(path)
        if control_order != order:
            raise ValueError(f"{path}: unexpected replay order")
        for name in order:
            actual, expected = control[name], frames[name]
            if ("chinese_runs" in actual or "arm_translations" not in actual
                    or any(actual[k] != v for k, v in expected.items() if k != "chinese_runs")
                    or (path / f"{name}.png").read_bytes() != (reference / f"{name}.png").read_bytes()):
                raise ValueError(f"{name}: ARM replay differs from the reference")
        total = sum(record["arm_translations"] for record in control.values())
        if (path == arm) != bool(total):
            raise ValueError(f"{path}: unexpected ARM translation count {total}")
        report["arm_matches_chinese" if path == arm else "empty_table_matches_stock"] = len(order)
        if path == arm:
            report["arm_translations"] = total
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("chinese", type=Path)
    parser.add_argument("--arm", type=Path)
    parser.add_argument("--empty-table", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.stock, args.chinese, args.arm, args.empty_table), ensure_ascii=False, indent=2))
