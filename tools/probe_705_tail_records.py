"""Read-only repeat, index and format checks for the aligned IC-705 tail window."""

import argparse
from collections import Counter
from hashlib import md5
from itertools import chain
import json
from pathlib import Path
import re
from struct import Struct, unpack_from
from zlib import crc32

from tools.firmware_scan import MAGIC, identify
from tools.probe_705_a import PERIOD
from tools.probe_icom_comparators import PAGE, probe
from tools.probe_ui_resources import ENCODINGS, FONT_MAGIC, LABELS, hits, language_id_probes

FOCUS_START, FOCUS_END = 0x3A2589, 0x3A89B1  # Relative to each model's tail.
MATCH_RUN = re.compile(rb"\x01{16,}")
FORMATS = {
    **MAGIC, **{tag.decode(): tag for tag in FONT_MAGIC},
    "sfnt_1": b"\x00\x01\x00\x00", "psf1": b"\x36\x04", "psf2": b"\x72\xb5\x4a\x86",
    "pcf": b"\x01fcp", "bdf": b"STARTFONT ", "fnt2": b"\x00\x02", "fnt3": b"\x00\x03",
    "bmp": b"BM", "gif87a": b"GIF87a", "gif89a": b"GIF89a", "jpeg": b"\xff\xd8\xff",
}


def phase_repeats(data, start, end):
    """Maximal exact runs at 256-byte multiple lags, excluding local periodic copies."""
    found = []
    for lag in range(PERIOD, end - start - 15, PERIOD):
        matches = bytes(x == y for x, y in zip(data[start:end - lag], data[start + lag:end]))
        for m in MATCH_RUN.finditer(matches):
            a, b = start + m.start(), start + m.end()
            if any(data[x:y] == data[x + p:y + p] for x, y in ((a, b), (a + lag, b + lag))
                   for p in (-PERIOD, PERIOD)):
                continue
            found.append((a - start, lag, b - a))
    return sorted(found, key=lambda r: (-r[2], r[0], r[1]))


def offset_tables(data, landmarks=()):
    """Look for runs of eight increasing 16/32-bit offsets bounded by this window."""
    for form in ("<H", ">H", "<I", ">I"):
        entry = Struct(form)
        for phase in range(entry.size):
            end = len(data) - (len(data) - phase) % entry.size
            run = []
            for i, (value,) in enumerate(chain(entry.iter_unpack(data[phase:end]), [(len(data),)])):
                if run and (value >= len(data) or value <= run[-1]):
                    if len(run) >= 8:
                        step, count = Counter(b - a for a, b in zip(run, run[1:])).most_common(1)[0]
                        yield {"format": form, "window_offset": phase + (i - len(run)) * entry.size,
                               "entries": len(run), "most_common_step": [step, count],
                               "landmarks_referenced": [v for v in run if v in landmarks]}
                    run = []
                if value < len(data):
                    run.append(value)


def header_rejection(data, pos, kind):
    """Only reject clear contradictions. A surviving magic is still a candidate."""
    available = len(data) - pos
    if kind == "bmp" and available >= 18:
        size, r1, r2, pixels, dib = unpack_from("<IHHII", data, pos + 2)
        if r1 or r2 or not 14 + dib <= pixels < size <= available:
            return "reserved fields or declared BMP bounds fail"
    if kind in ("fnt2", "fnt3") and available >= 6:
        size, = unpack_from("<I", data, pos + 2)
        if not (118 if kind == "fnt2" else 148) <= size <= available:
            return "dfSize cannot fit a FNT header and file extent"
    if kind == "psf1" and available >= 4:
        mode, size = data[pos + 2:pos + 4]
        if mode > 5 or not 0 < size <= (available - 4) // (512 if mode & 1 else 256):
            return "mode or glyph extent fails PSF1 bounds"
    return None


def nearby_fields(data, start, lag, length, tail, focus):
    segment = data[start:start + length]
    found = []
    for pos in (start, start + lag):
        values = {"file_start": pos, "file_end": pos + length, "tail_start": pos - tail,
                  "tail_end": pos + length - tail, "focus_start": pos - focus,
                  "focus_end": pos + length - focus, "length": length, "lag": lag}
        probes = [(f"{name}:{size}:{order}", value.to_bytes(size, order))
                  for name, value in values.items() for size in (2, 3, 4)
                  for order in ("little", "big") if value < 1 << (size * 8)]
        probes += [(f"crc32:{order}", crc32(segment).to_bytes(4, order)) for order in ("little", "big")]
        probes.append(("md5", md5(segment, usedforsecurity=False).digest()))
        for off in (pos - 64, pos + length):
            if matches := hits(data[off:off + 64], probes):
                found.append({"search_start": off, "relative_hits": matches})
    return found


def inspect(data, tail):
    start, end = tail + FOCUS_START, tail + FOCUS_END
    width = end - start
    if not PERIOD <= start - width < end + width <= len(data) - PERIOD:
        raise ValueError("focus and control windows must fit with a 256-byte margin")
    zones = {}
    for label, first in (("left", start - width), ("focus", start), ("right", end)):
        sample = data[first:first + width]
        repeats = phase_repeats(data, first, first + width)
        edges = {v for off, lag, n in repeats for v in (off, off + n, off + lag, off + lag + n)}
        zones[label] = {"start": first, "end_exclusive": first + width, **identify(sample),
                        "lag_256_equal_bytes": sum(x == y for x, y in zip(sample, sample[PERIOD:])),
                        "repeat_runs": repeats, "packed_offset_candidates": list(offset_tables(sample, edges))}
    scan_start = start - PAGE
    format_hits = hits(data[scan_start:end + PAGE], FORMATS.items())
    for kind, summary in format_hits.items():
        summary["headers"] = [{"file_offset": (pos := scan_start + off),
                               "rejection": header_rejection(data, pos, kind)}
                              for off in summary.pop("first_file_offsets")]
    target = data[start:end]
    labels = [(f"{enc}:{label}", label.encode(enc)) for label in LABELS for enc in ENCODINGS]
    settings = [(name, raw) for name, raw in language_id_probes() if not name.startswith("bcd_pair_")]
    label_hits, civ_hits = hits(target, labels), hits(target, settings)
    for hit in [*label_hits.values(), *civ_hits.values()]:
        hit["first_file_offsets"] = [start + off for off in hit["first_file_offsets"]]
    nearby = None
    if strongest := zones["focus"]["repeat_runs"]:
        off, lag, length = strongest[0]
        nearby = nearby_fields(data, start + off, lag, length, tail, start)
    return {"zones": zones, "format_scan_range": [scan_start, end + PAGE], "format_hits": format_hits,
            "exact_label_hits": label_hits, "civ_table_hits": civ_hits, "near_longest_repeat": nearby}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="baseline DAT followed by comparator DATs")
    args = parser.parse_args()
    rows = []
    for path in args.paths:
        try:
            data = path.read_bytes()
            info, tail = probe(data)
            if info["model"] != "IC-905" and not info["first_payload"]["adjacent_md5_matches"]:
                raise ValueError("first payload digest did not match")
            if FOCUS_END + (FOCUS_END - FOCUS_START) + PERIOD > len(tail):
                raise ValueError("candidate tail is too short for the comparison windows")
            rows.append({"file": path.name, "model": info["model"], "file_sha256": info["sha256"],
                         **inspect(data, info["tail"]["start"])})
        except (OSError, ValueError) as error:
            parser.error(f"{path}: {error}")
    base = rows[0]["zones"]
    overlap = [{"file": r["file"], "shared_repeat_counts":
                {k: len(set(v["repeat_runs"]) & set(r["zones"][k]["repeat_runs"])) for k, v in base.items()}}
               for r in rows[1:]]
    print(json.dumps({"baseline": rows[0]["file"], "images": rows, "overlap": overlap}, indent=2))


if __name__ == "__main__":
    main()
