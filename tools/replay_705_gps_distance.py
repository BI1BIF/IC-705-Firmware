"""Replay the J140 GPS distance row with a scoped PC localization fixture."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from struct import iter_unpack, pack, unpack

from PIL import Image, ImageChops

from tools.emulate_705 import arm, call, machine, uc
from tools.probe_zh_cn_page import build_font
from tools.render_705_display import DAT_HASH, PAGE, load
from tools.render_705_stock_row import coverage, png, require
from tools.replay_705_language_storage import DISPLAY, SYSTEM, LogicalStorage
from tools.replay_705_menu_word import CONVERT_TABLE, STOCK_CODES, add_glyphs
from tools.replay_705_settings import UPDATE, SettingsGuest
from tools.virtual_705_display_catalog import FONT_SOURCE_SHA


DISTANCE, PREVIOUS = 0x204BACF2, 0x204BD826
FORMAT, REDRAW = 0x2021710C, 0x2018A8D0
LABEL_RECORD, DRAW, LABEL_LOOKUP = 0x2032AFBC, 0x20142698, 0x201895A0
LABEL_RETURN, VALUE_RETURN = 0x201895B4, 0x201895E4
LAB, WORD, CODES = 0x21011000, 0x21011010, 0x21011100
FIXTURE = Path(__file__).resolve().parents[1] / "samples/j140-gps-distance.json"
EXTRA = 0xF5F0
CASES = ((50000, 1, "5000m"), (99994, 1, "9999m"), (99995, 1, "10.0km"),
         (100000, 1, "10.0km"), (0, 0, "-----km"))


def page_inputs(main):
    cpu = machine(main)
    # Synthetic GPS page inputs; the stock page builder, formatter and destination are unmodified.
    cpu.mem_write(0x203E84BF+0x42, b"\1")
    cpu.mem_write(0x203EAA49+0x723, b"\2")
    cpu.mem_write(0x203813EE, b"\1")
    cpu.mem_write(0x205DDDCC+9, b"35300000N139300000E")
    calls, results = [], []

    def capture(_cpu, _pc, _size, _data):
        calls.append(tuple(cpu.reg_read(reg) for reg in (
            arm.UC_ARM_REG_LR, arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)))

    cpu.hook_add(uc.UC_HOOK_CODE, capture, begin=FORMAT, end=FORMAT)
    for dm, valid, expected in CASES:
        cpu.mem_write(0x203813EE, bytes((valid,)))
        cpu.mem_write(0x203D9E30, pack("<I", dm))
        call(cpu, 0x200B34B0)
        value = bytes(cpu.mem_read(DISTANCE, 7)).decode("ascii")
        require(calls.pop() == (0x200B2D14, DISTANCE, dm if valid else 0xFFFFFFFF, valid, 0)
                and not calls and value.rstrip() == expected, "unexpected GPS page formatter inputs")
        results.append({"distance_dm": dm, "record_valid": bool(valid), "page_distance": value})
    return results


def resource(guest, label, usable):
    cpu, surface = guest.cpu, guest.surface
    data = b"".join(EXTRA.to_bytes(2, "big") if ch == "离" else ch.encode("cp932") for ch in label)
    base = bytes(cpu.mem_read(STOCK_CODES, 79*8))
    require(cpu.mem_read(STOCK_CODES+len(base), 8) == bytes(8) and
            all(key != EXTRA for key, _ in iter_unpack("<II", base)), "unexpected stock character table")
    cpu.mem_map(LAB, 0x1000, uc.UC_PROT_READ)
    cpu.mem_write(LAB, pack("<III", 1, WORD, len(data)))
    cpu.mem_write(WORD, data+b"\0")
    cpu.mem_write(CODES, base+pack("<II", EXTRA, ord("离"))+bytes(8))
    sources = []

    def choose(_cpu, _pc, _size, _data):
        if guest.language() != [2, 1]:
            return
        require(surface.reg("R0") == LABEL_RECORD+12, "stock did not select Japanese compatibility record")
        # Scope this resource to the GPS label. Missing subset keeps the original Japanese fallback.
        if usable:
            cpu.reg_write(arm.UC_ARM_REG_R0, LAB)
            sources.append(hex(WORD))

    def decode(_cpu, _pc, _size, _data):
        if surface.reg("R6") == WORD:
            require(surface.reg("SL") == STOCK_CODES and surface.reg("R7") == len(data), "unexpected decoder ABI")
            cpu.reg_write(arm.UC_ARM_REG_SL, CODES)

    for pc, hook in ((LABEL_LOOKUP, choose), (CONVERT_TABLE, decode)):
        cpu.hook_add(uc.UC_HOOK_CODE, hook, begin=pc, end=pc)
    return sources


def ink(event, surface):
    pixels = set()
    for glyph in event["glyphs"]:
        pixels.update(coverage(glyph["segments"], glyph["coordinates"], glyph["offset"], surface.width, surface.height))
    require(bool(pixels), "stock draw did not produce glyph coverage")
    xs, ys = zip(*[(i % surface.width, i // surface.width) for i in pixels])
    return min(xs), min(ys), max(xs)+1, max(ys)+1


def run(images, label, preferences, samples, *, fixture=False, usable=False):
    guest = SettingsGuest(images, front_panel=True)
    cpu, surface = guest.cpu, guest.surface
    storage = LogicalStorage()
    storage.data[DISPLAY:SYSTEM+1] = bytes(preferences)
    storage.restore(guest)
    call(cpu, UPDATE, instruction_limit=2_000_000)
    stock_bits = cpu.mem_read(PAGE+9, 1)[0] & 3
    require(stock_bits == (3 if preferences == (1, 1) else preferences[1]), "unexpected original language bits")
    if fixture and preferences == (2, 1):
        # Use the same Japanese display-bit compatibility as the existing third-language replay.
        def compatibility(_cpu, _pc, _size, _data):
            require(surface.reg("R0") == 2, "unexpected display value at the original bit pack")
            cpu.reg_write(arm.UC_ARM_REG_R0, 1)

        cpu.hook_add(uc.UC_HOOK_CODE, compatibility, begin=0x20095E94, end=0x20095E94)
        call(cpu, UPDATE, instruction_limit=2_000_000)
        require(cpu.mem_read(PAGE+9, 1)[0] & 3 == 3, "display compatibility was not applied")
    sources = resource(guest, label, usable) if fixture else []
    japanese = stock_bits == 3 or (fixture and preferences == (2, 1))
    expected_label = label if preferences == (2, 1) and usable else ("距離:" if japanese else "DST:")
    calls = []

    def capture(_cpu, _pc, _size, _data):
        lr = surface.reg("LR")
        if lr in (LABEL_RETURN, VALUE_RETURN):
            ptr, size = surface.reg("R2"), surface.reg("R3")
            calls.append((lr, ptr, bytes(cpu.mem_read(ptr, size))))

    cpu.hook_add(uc.UC_HOOK_CODE, capture, begin=DRAW, end=DRAW)
    results, frames = {}, {}
    for dm, valid, expected in samples:
        count = call(cpu, FORMAT, DISTANCE, dm, valid, 0, 1, 1, 0)
        value = bytes(cpu.mem_read(DISTANCE, 7))
        require(value[:count].decode("ascii") == expected and count == len(expected), "stock formatter mismatch")
        surface.events.clear()
        calls.clear()
        surface.pixels[:] = bytes(len(surface.pixels))
        call(cpu, REDRAW, 1, instruction_limit=5_000_000)
        require(len(calls) == 2 and calls[0][:2] == (LABEL_RETURN, {
            "距離:": 0x20364790, "DST:": 0x20364718, label: WORD}[expected_label])
            and calls[1] == (VALUE_RETURN, DISTANCE, value), "wrong label or altered distance draw input")
        texts = ["".join(chr(g["key"]) for g in event["glyphs"]) for event in surface.events]
        label_event = surface.events[texts.index(expected_label)]
        value_event = surface.events[texts.index(value.decode("ascii"))]
        require(all(g["segments"] for g in label_event["glyphs"]), "missing distance label glyph")
        label_box, value_box = ink(label_event, surface), ink(value_event, surface)
        require(0 < label_box[0] < label_box[2] < value_box[0] < value_box[2] < surface.width and
                0 < label_box[1] < label_box[3] < surface.height and 0 < value_box[1] < value_box[3] < surface.height,
                f"label/value clipped or overlapping: {label_box}, {value_box}")
        image = png(surface.width, surface.height, surface.pixels)
        cpu.mem_write(PREVIOUS, value)
        calls.clear()
        call(cpu, REDRAW, 0, instruction_limit=5_000_000)
        require(not calls, "matching previous distance still redrew")
        # Force one different previous byte and verify the original differential redraw takes the distance path.
        cpu.mem_write(PREVIOUS, bytes((value[0] ^ 1,)))
        call(cpu, REDRAW, 0, instruction_limit=5_000_000)
        require(len(calls) == 2 and calls[1] == (VALUE_RETURN, DISTANCE, value), "changed distance did not redraw")
        results[dm] = {"valid": bool(valid), "stock_draw_bytes": value.decode("ascii"), "label": expected_label,
                       "label_bbox": label_box, "value_bbox": value_box,
                       "label_origin": label_event["translation"], "value_origin": value_event["translation"],
                       "all_glyph_runs": texts, "png_sha256": sha256(image).hexdigest()}
        frames[dm] = image
    require(guest.language() == list(preferences) and len(storage.requests) == 714, "language settings changed")
    require(len(sources) == (2*len(samples) if preferences == (2, 1) and usable else 0),
            "localization was applied outside the distance redraw")
    return results, frames


def replay(dat, output, font_source):
    images = load(dat)
    output.mkdir(parents=True, exist_ok=True)
    label = json.loads(FIXTURE.read_bytes())["distance"]
    require(label == "距离:", "expected the one-character J140 GPS distance substitution")
    require(sha256(font_source.read_bytes()).hexdigest() == FONT_SOURCE_SHA, "unexpected Noto source font")
    subset = output / "gps-lab.ttf"
    build_font(font_source, subset, "离")
    main, stock, graphics, digest, small = images
    expanded = (main, add_glyphs(stock, subset, "离"), graphics, digest, small)
    report = {"dat_sha256": DAT_HASH, "main_sha256": digest, "page_inputs": page_inputs(main),
              "results": {}, "comparisons": {}}
    results, frames = report["results"], {}
    for name, prefs, fixture, usable, samples in (
        ("ja-stock", (1, 1), False, False, CASES), ("zh", (2, 1), True, True, CASES),
        ("ja", (1, 1), True, True, CASES[1:3]), ("en", (0, 1), True, True, CASES[1:3]),
        ("en-stock", (0, 1), False, False, CASES[1:3]), ("en-system", (2, 0), True, True, CASES[1:3]),
        ("en-system-stock", (0, 0), False, False, CASES[1:3]), ("missing", (2, 1), True, False, CASES[1:3]),
    ):
        results[name], frames[name] = run(expanded if usable else images, label, prefs, samples, fixture=fixture, usable=usable)
    for name, stock_name in (("ja", "ja-stock"), ("en", "en-stock"), ("en-system", "en-system-stock"),
                             ("missing", "ja-stock")):
        require(all(image == frames[stock_name][dm] for dm, image in frames[name].items()), f"{name}: stock pixels changed")
    for dm, frame in frames["zh"].items():
        with Image.open(BytesIO(frame)) as zh, Image.open(BytesIO(frames["ja-stock"][dm])) as ja:
            # Include color and alpha differences, and constrain every changed pixel to the label region.
            diff = ImageChops.difference(zh, ja).getbbox(alpha_only=False)
        left, right = results["zh"][dm], results["ja-stock"][dm]
        label_x, label_y, label_r, label_b = (min(left["label_bbox"][0], right["label_bbox"][0]),
            min(left["label_bbox"][1], right["label_bbox"][1]), max(left["label_bbox"][2], right["label_bbox"][2]),
            max(left["label_bbox"][3], right["label_bbox"][3]))
        require(diff is not None and label_x <= diff[0] < diff[2] <= label_r and label_y <= diff[1] < diff[3] <= label_b
                and left["value_bbox"] == right["value_bbox"] and left["value_origin"] == right["value_origin"],
                f"{dm}: localized pixels changed outside the label: {diff}")
        report["comparisons"][dm] = {"changed_bbox": diff, "value_pixels_identical": True}
    for name in ("ja-stock", "zh", "en-stock", "missing"):
        for dm in (99994, 99995):
            (output / f"{name}-{dm}dm.png").write_bytes(frames[name][dm])
    # A readable detail from the two real draws; the full PNGs keep the original coordinates.
    detail = Image.new("RGB", (140, 58))
    for y, dm in ((0, 99994), (30, 99995)):
        with Image.open(BytesIO(frames["zh"][dm])) as frame:
            crop = frame.crop((88, 159, 228, 187))
            detail.paste(crop, (0, y), crop)
    detail.resize((560, 232), Image.Resampling.NEAREST).save(output / "gps-distance-detail.png")
    (output / "gps-distance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"J140 GPS distance replay passed: {output / 'gps-distance.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font-source", type=Path, default=Path(".analysis/zh-cn-preview/noto/NotoSansSC-VF.ttf"))
    args = parser.parse_args()
    replay(args.dat.read_bytes(), args.output, args.font_source)
