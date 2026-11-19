"""Replay the stock Display Language label and inspect the J132/J140 menu character map."""

import argparse
import json
from pathlib import Path
import struct

from tools.decode_705_main import decode_main
from tools.firmware_scan import identify
from tools.probe_705_fonts import DEFAULT_CHARS


MAIN_BASE = 0x20005000
# Decoded main SHA-256 -> (Display Language row, decoder literals, renderer literals).
SAMPLES = {
    "d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9":
        (0x202F0DFC, 0x201DF15C, 0x20144EF4),
    "e2367bf67ec7969ef42cf74a4d0da22d3b75b825377c223ccc131f1ba217617f":
        (0x20304D2C, 0x201DAE90, 0x201417D8),
}


def inspect(main, chars):
    """Read known tables at their observed addresses; do not execute firmware."""
    identity = identify(main)
    try:
        row, decoder_pool, render_pool = SAMPLES[identity["sha256"]]
    except KeyError as exc:
        raise ValueError("menu tables are verified only for stock 705J132 and 705J140") from exc

    def read(fmt, addr):
        return struct.unpack_from("<" + fmt, main, addr - MAIN_BASE)

    special, low1, high1, low2, skips2, high2 = read("6I", decoder_pool)
    override, _, kana = read("3I", render_pool)
    overlay = {}
    while (key := read("H", override)[0]):
        overlay[key] = read("I", override + 4)[0] & 0xFFFF
        override += 8

    def lookup(key, index, table, skips):
        while (span := read("H", skips + 2)[0]):
            start, _, remove = read("HHH", skips)
            if key < start:
                break
            if key < start + span:
                return 0
            index -= remove
            skips += 6
        return read("H", table + 2 * index)[0]

    def decode_unit(lead, trail):
        key = 256 * lead + trail
        if key in overlay:
            return overlay[key]
        if lead < 0x80:
            return lead
        if 0xA1 <= lead <= 0xDF:
            return lead + 0xFEC0
        short = 0x40 <= trail <= 0x7E
        long = 0x80 <= trail <= 0xFC
        if 0x8240 <= key < 0x8480:
            for i in range(16):
                start, cp = read("HH", special - 64 + 4 * i)
                if start <= key < start + read("B", special + i)[0]:
                    return cp + key - start if cp else 0
            return 0
        if not (short or long):
            return 0
        if 0x81 <= lead <= 0x9F:
            if short:
                return lookup(key, (lead - 0x81) * 63 + trail - 0x40, low1, low1 - 18)
            return lookup(key, (lead - 0x81) * 125 + trail - 0x80, high1, high1 - 30)
        if 0xE0 <= lead <= 0xEA:
            if short:
                return lookup(key, (lead - 0xE0) * 63 + trail - 0x40, low2, skips2)
            return lookup(key, (lead - 0xE0) * 125 + trail - 0x80, high2, high2 - 12)
        if 0xF0 <= lead <= 0xF9:
            return 0xE000 + (lead - 0xF0) * 188 + trail - (0x40 if short else 0x41)
        return 0

    label_offset = read("I", row + 0x30)[0] - MAIN_BASE
    label = main[label_offset:main.index(0, label_offset)]
    # This exact label contains only two-byte characters. This is not a general string decoder.
    decoded = [decode_unit(a, b) for a, b in zip(label[::2], label[1::2], strict=True)]
    stock_text = "".join(map(chr, decoded))
    if stock_text != "\u8868\u793a\u8a00\u8a9e" or stock_text != label.decode("cp932"):
        raise ValueError("stock Display Language label did not match the control")

    # Include both optional backslash/kana output paths to overapproximate reachability.
    possible = {decode_unit(a, b) for a in range(256) for b in range(256)}
    possible.difference_update((0, 0x0D, 0x2212))
    possible.update((0x21B5, 0xFF0D, 0xA5))
    possible.update(cp & 0xFFFF for cp in read("56I", kana))
    queried = dict.fromkeys(chars)
    return {"main": identity, "display_row": f"0x{row:08X}", "stock_bytes": label.hex(" "),
            "stock_text": stock_text, "stock_unicode": [f"U+{cp:04X}" for cp in decoded],
            "queried_count": len(queried),
            "unmapped": [c for c in queried if ord(c) not in possible]}


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("--chars", default=DEFAULT_CHARS, help="characters to check against the menu map")
    args = parser.parse_args()
    try:
        _, main, _ = decode_main(args.dat.read_bytes())
        print(json.dumps(inspect(main, args.chars), indent=2))
    except (OSError, ValueError, struct.error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    cli()
