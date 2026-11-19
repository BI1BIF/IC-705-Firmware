"""Inspect the two TrueType records in an original IC-705 J132/J140 DAT (read only)."""

import argparse
import json
from pathlib import Path
import struct

from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_a_range, decode_boot
from tools.firmware_scan import identify


DEFAULT_CHARS = "\u8868\u793a\u8a00\u8a9eA7\u4e2d\u6587\u9891\u8bbe\u84dd\u7b80\u0378"


def u16(data, offset):
    return struct.unpack_from(">H", data, offset)[0]


def glyph4(cmap, codepoint):
    """Map one BMP code point using a TrueType format 4 Unicode subtable."""
    if len(cmap) < 16 or u16(cmap, 0) != 4 or u16(cmap, 2) != len(cmap):
        raise ValueError("invalid format 4 cmap length")
    twice = u16(cmap, 6)
    if not twice or twice % 2 or 16 + 4 * twice > len(cmap):
        raise ValueError("invalid format 4 cmap segment count")
    for i in range(0, twice, 2):
        end = u16(cmap, 14 + i)
        if codepoint > end:
            continue
        start = u16(cmap, 16 + twice + i)
        if codepoint < start:
            return 0
        delta = u16(cmap, 16 + 2 * twice + i)
        pos = 16 + 3 * twice + i
        advance = u16(cmap, pos)
        if not advance:
            return (codepoint + delta) & 0xFFFF
        idx = pos + advance + 2 * (codepoint - start)
        if idx < 16 + 4 * twice or idx + 2 > len(cmap):
            raise ValueError("format 4 glyph index array exceeds bounds")
        raw = u16(cmap, idx)
        return (raw + delta) & 0xFFFF if raw else 0
    return 0


def inspect_font(font, chars):
    """Validate the observed TrueType directory and report Unicode glyph indices."""
    if len(font) < 12 or font[:4] != b"\0\1\0\0":
        raise ValueError("font record is not TrueType")
    count = u16(font, 4)
    directory_end = 12 + count * 16
    if directory_end > len(font):
        raise ValueError("truncated TrueType directory")
    tables = {}
    for tag, _, offset, size in struct.iter_unpack(">4sIII", font[12:directory_end]):
        if tag in tables or offset < directory_end or offset + size > len(font):
            raise ValueError("invalid TrueType directory entry")
        tables[tag] = font[offset:offset + size]
    if (len(tables.get(b"head", b"")) < 54 or tables[b"head"][12:16] != b"\x5f\x0f\x3c\xf5"
            or len(tables.get(b"maxp", b"")) < 6 or len(tables.get(b"cmap", b"")) < 4
            or not {b"glyf", b"loca"} <= tables.keys()):
        raise ValueError("missing or invalid TrueType outline tables")
    check = sum(n for (n,) in struct.iter_unpack(">I", font + b"\0" * (-len(font) % 4))) & 0xFFFFFFFF
    if check != 0xB1B0AFBA:
        raise ValueError("invalid TrueType checksum")

    glyph_count = u16(tables[b"maxp"], 4)
    cmap = tables[b"cmap"]
    dir_end = 4 + 8 * u16(cmap, 2)
    if dir_end > len(cmap):
        raise ValueError("truncated cmap directory")
    subtables = {}
    for platform, encoding, offset in struct.iter_unpack(">HHI", cmap[4:dir_end]):
        if (platform, encoding) not in {(0, 3), (3, 1)}:
            continue
        if offset < dir_end or offset + 4 > len(cmap):
            raise ValueError("invalid Unicode cmap offset")
        if u16(cmap, offset) == 4:
            end = offset + u16(cmap, offset + 2)
            if end > len(cmap):
                raise ValueError("truncated Unicode cmap")
            subtables[f"{platform}/{encoding}"] = cmap[offset:end]
    if not subtables:
        raise ValueError("no BMP Unicode format 4 cmap")

    glyphs = {}
    for c in dict.fromkeys(chars):
        cp = ord(c)
        ids = {glyph4(sub, cp) for sub in subtables.values()}
        if len(ids) != 1 or max(ids) >= glyph_count:
            raise ValueError(f"invalid or conflicting glyph indices for U+{cp:04X}")
        glyphs[f"U+{cp:04X}"] = {"character": c, "glyph_id": ids.pop()}
    return {"table_count": count, "glyph_count": glyph_count,
            "unicode_cmaps": list(subtables), "glyphs": glyphs}


def probe(data, chars=DEFAULT_CHARS):
    if any(ord(c) > 0xFFFF for c in chars):
        raise ValueError("this probe supports BMP characters only")
    info, group = checked_group_a(data)
    boot, _ = decode_boot(data, group)
    end = group["end_exclusive"]
    tail_size = struct.unpack_from("<I", data, 0x40)[0]
    tail_offset = end - tail_size
    if tail_size != 0x3C0000 or tail_offset - group["offset"] != 0x600000:
        raise ValueError("unrecognized J132/J140 group A tail layout")
    start = group["offset"] + BOOT_SIZE
    tail = bytes(decode_a_range(data, start, end - start, boot[-1])[-tail_size:])

    pos, fonts, entries = 0, [], []
    for _ in range(2):
        if pos + 4 > len(tail):
            raise ValueError("truncated font record header")
        size = struct.unpack_from("<I", tail, pos)[0]
        stop = pos + 4 + size
        if not size or stop > len(tail):
            raise ValueError("font record exceeds group A tail")
        font = tail[pos + 4:stop]
        entries.append({"header_file_offset": tail_offset + pos,
                        "font_file_offset": tail_offset + pos + 4,
                        **identify(font), **inspect_font(font, chars)})
        fonts.append(font)
        pos = stop
    marker = tail[-16:]
    padding = tail[pos:-16]
    if pos > len(tail) - 16 or padding.strip(b"\xff") or marker != b"SX4075 V1.00-000":
        raise ValueError("unexpected data after the two font records")
    return {"input": {"bytes": info["bytes"], "sha256": info["sha256"]},
            "decoded_tail": {"file_offset": tail_offset, **identify(tail),
                             "ff_padding_bytes": len(padding),
                             "marker_file_offset": end - 16, "marker": marker.decode("ascii")},
            "fonts": entries}, fonts


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("--chars", default=DEFAULT_CHARS, help="BMP characters to look up")
    parser.add_argument("--extract-to", type=Path, help="new local directory for fonts (use .analysis/)")
    args = parser.parse_args()
    try:
        report, fonts = probe(args.dat.read_bytes(), args.chars)
        if args.extract_to:
            args.extract_to.mkdir(parents=True, exist_ok=False)
            for i, font in enumerate(fonts):
                (args.extract_to / f"font-{i}.ttf").write_bytes(font)
    except (OSError, ValueError, struct.error) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    cli()
