"""Run the J140 stock DISPLAY page offline and save reference frames and draw evidence."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack

from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_a_range, decode_main
from tools.decode_705_main import J140_DAT_SHA as DAT_HASH
from tools.emulate_705 import PROFILES, SCRATCH, arm, call, uc
from tools.render_705_stock_row import FONT_HASH, SMALL_FONT_HASH, SMALL_FONT_HEADER, FONT_HEADER, make_surface, png, require


GRAPHICS_FLASH = 0x185F0000
FONT_OFFSET = 0x600000
GROUP_SELECTION, LIST_STATE, PAGE = 0x203807E8, 0x203804C8, 0x204BAB5C
LIST_ENTRIES, LIST_GROUP, TITLE_NUMBER = 0x203DAD1C, 36, 67


def load(dat):
    require(sha256(dat).hexdigest() == DAT_HASH, "expected the original Japanese IC-705 1.40 DAT")
    boot, main, manifest = decode_main(dat)
    _, group = checked_group_a(dat)
    start = group["offset"] + BOOT_SIZE
    decoded = bytes(boot) + bytes(decode_a_range(dat, start, group["end_exclusive"]-start, boot[-1]))
    length, = unpack("<I", decoded[FONT_OFFSET:FONT_OFFSET+4])
    font = decoded[FONT_OFFSET+4:FONT_OFFSET+4+length]
    require(sha256(font).hexdigest() == FONT_HASH, "unexpected original Japanese font")
    small_offset = FONT_OFFSET + SMALL_FONT_HEADER - FONT_HEADER
    length, = unpack("<I", decoded[small_offset:small_offset+4])
    small_font = decoded[small_offset+4:small_offset+4+length]
    require(sha256(small_font).hexdigest() == SMALL_FONT_HASH, "unexpected original small font")
    return bytes(main), font, decoded[:FONT_OFFSET], manifest["main"]["sha256"], small_font


def render(main, font, graphics, profile, system, display, last, cursor):
    cpu, surface = make_surface(main, font)
    cpu.mem_map(GRAPHICS_FLASH, len(graphics), uc.UC_PROT_READ)
    cpu.mem_write(GRAPHICS_FLASH, graphics)
    cpu.mem_write(profile.language_bytes, bytes((display, system)))
    # Feed the original list builder a page selection and a cursor, not synthetic row records.
    cpu.mem_write(GROUP_SELECTION+4, pack("<H", LIST_GROUP))
    cpu.mem_write(0x203E84BF+10, pack("<H", TITLE_NUMBER))
    call(cpu, 0x200A163C, 0)
    count, = unpack("<H", cpu.mem_read(LIST_STATE+22, 2))
    entries = [unpack("<BH", cpu.mem_read(LIST_ENTRIES+3*i, 3)) for i in range(count)]
    ids = [row_id for kind, row_id in entries if kind == 2]
    require((0xA7 in ids) == bool(system) and ids[-1] == 0xA8 and count == 21+system,
            "unexpected stock display item inventory")
    first = ((count-1)//4)*4 if last else 0
    require(first+cursor < count, "cursor outside stock menu")
    cpu.mem_write(LIST_STATE+16, pack("<2H", first+cursor, first))
    call(cpu, 0x200AD034)
    effective = call(cpu, profile.language)
    cpu.mem_write(PAGE+1, b"\x0c")  # State dispatched to the stock settings list renderer.
    cpu.mem_write(PAGE+9, bytes((2*effective+system,)))
    selected, = cpu.mem_read(PAGE+898, 1)
    require(selected == cursor+1, "original row builder selected a different item")
    visited = []

    def record(_cpu, addr, _size, _data):
        visited.append(hex(addr))

    def missing(_cpu, _access, address, _size, _value, _data):
        raise ValueError(f"unmodeled guest access at {address:#x} from {surface.reg('PC'):#x}")

    def graphics_boundary(_cpu, address, _size, _data):
        require(address in surface.handlers, f"unmodeled OpenVG entry at {address:#x}")

    cpu.hook_add(uc.UC_HOOK_MEM_INVALID, missing)
    cpu.hook_add(uc.UC_HOOK_CODE, graphics_boundary, begin=0x20263100, end=0x20263DFF)
    for address in (0x20153D5C, 0x2014BA80, 0x201543DC):
        cpu.hook_add(uc.UC_HOOK_CODE, record, begin=address, end=address)
    call(cpu, 0x201549B4, SCRATCH, instruction_limit=8_000_000, timeout_us=10_000_000)
    words = ["".join(chr(g["key"]) for g in event["glyphs"]).rstrip() for event in surface.events]
    require(words[:2] == ["ディスプレイ設定" if effective else "DISPLAY", "6/6" if last else "1/6"],
            f"unexpected stock page header: {words[:2]!r}")
    if last:
        expected = (["表示言語", "日本語", "システム言語", "日本語"] if effective else
                    ["Display Language", "English", "System Language", "Japanese"] if system else
                    ["System Language", "English"])
        require(words[2:] == expected, f"unexpected language text from stock page: {words!r}")
    else:
        require(len(words) == 10 and words[2] == "LCDバックライト", "first page did not draw four rows")
    require(0xFF == min(surface.pixels[3::4]) and len(surface.image_draws) >= 16,
            "stock page did not paint the full surface and its assets")
    sample = [bytes(surface.pixels[4*(y*surface.width+200):4*(y*surface.width+200)+4]).hex() for y in (40, 100)]
    require(sample[cursor] == "5da0c9ff" and sample[1-cursor] != "5da0c9ff", "missing stock selection highlight")
    image = png(surface.width, surface.height, surface.pixels)
    return image, {"system": system, "display": display, "first_item": first, "cursor": cursor,
                   "listed_items": entries, "highlight_samples_rgba": sample, "text": words,
                   "observed_functions": visited, "clears": surface.clears, "images": surface.image_draws,
                   "draws": surface.events, "png_sha256": sha256(image).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="original Japanese 705J140.dat")
    parser.add_argument("output", type=Path, help="new local directory under .analysis")
    args = parser.parse_args()
    main_image, font, graphics, main_hash, _ = load(args.dat.read_bytes())
    cases = (("01-display-first-jp", 1, 1, False, 0), ("06-display-language-jp", 1, 1, True, 0),
             ("06-system-language-jp", 1, 1, True, 1), ("06-display-english", 1, 0, True, 0),
             ("06-system-english", 0, 1, True, 0))
    args.output.mkdir(parents=True)
    report = {"input_sha256": DAT_HASH, "main_sha256": main_hash, "font_sha256": FONT_HASH,
              "graphics_slice_sha256": sha256(graphics).hexdigest(), "engine": f"Unicorn {uc.__version__}", "frames": {}}
    for name, *state in cases:
        image, evidence = render(main_image, font, graphics, PROFILES[main_hash], *state)
        (args.output / f"{name}.png").write_bytes(image)
        report["frames"][name] = evidence
    (args.output / "trace.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
