"""Locate stable regions, periodic spans and conservative A32 vector candidates in group A."""

import argparse
from collections import Counter
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
import re
import struct

from tools.firmware_scan import layout

PERIOD = 256
MIN_SPAN = 4096
VECTOR_SLOTS = (0, 4, 8, 12, 16, 24, 28)


def periodic_spans(data):
    page = PERIOD
    while page + PERIOD <= len(data):
        if data[page:page + PERIOD] != data[page - PERIOD:page]:
            page += PERIOD
            continue
        start, end = page - PERIOD, page + PERIOD
        while end + PERIOD <= len(data) and data[end:end + PERIOD] == data[end - PERIOD:end]:
            end += PERIOD
        page = end + PERIOD
        while start > 0 and data[start - 1] == data[start - 1 + PERIOD]:
            start -= 1
        while end < len(data) and data[end] == data[end - PERIOD]:
            end += 1
        if end - start >= MIN_SPAN:
            motif = data[start:start + PERIOD]
            rotated = min(motif[i:] + motif[:i] for i in range(PERIOD))
            yield {"start": start, "end_exclusive": end, "bytes": end - start,
                   "distinct_bytes_in_motif": len(set(motif)), "motif_sha256": sha256(rotated).hexdigest()}


def stable_spans(images):
    first, *others = images
    start = None
    for off in range(0, len(first), MIN_SPAN):
        chunk = first[off:off + MIN_SPAN]
        if len(chunk) == MIN_SPAN and all(img[off:off + MIN_SPAN] == chunk for img in others):
            if start is None:
                start = off
        elif start is not None:
            yield {"start": start, "end_exclusive": off}
            start = None
    if start is not None:
        yield {"start": start, "end_exclusive": len(first)}


def shifted_markers(left, right, left_spans, right_spans):
    def signature(span):
        return span["bytes"], span["motif_sha256"]

    left_counts = Counter(map(signature, left_spans))
    right_counts = Counter(map(signature, right_spans))
    right_by_signature = {signature(span): span for span in right_spans}
    matches = ((s, right_by_signature[signature(s)]) for s in left_spans
               if left_counts[signature(s)] == right_counts[signature(s)] == 1)
    for shift, items in groupby(matches, key=lambda pair: pair[1]["start"] - pair[0]["start"]):
        spans = [a for a, _ in items]
        if not shift or len(spans) < 2:
            continue
        gaps = [(a["end_exclusive"], b["start"]) for a, b in zip(spans, spans[1:])]
        gap_bytes = sum(end - start for start, end in gaps)
        aligned = sum(sum(a == b for a, b in zip(left[start:end], right[start + shift:end + shift]))
                      for start, end in gaps)
        unshifted = sum(sum(a == b for a, b in zip(left[start:end], right[start:end]))
                        for start, end in gaps)
        yield {"markers": len(spans), "shift_bytes": shift, "start": spans[0]["start"],
               "end_exclusive": spans[-1]["end_exclusive"], "gap_bytes": gap_bytes,
               "equal_gap_bytes_shifted": aligned, "equal_gap_bytes_unshifted": unshifted}


def a32_target(data, off):
    word, = struct.unpack_from("<I", data, off)
    if word & 0xFE000000 == 0xEA000000:  # A32 B/BL, unconditional.
        imm = word & 0xFFFFFF
        target = off + 8 + ((imm ^ 0x800000) - 0x800000) * 4
        return ("branch", target) if 0 <= target <= len(data) - 4 else None
    if word & 0xFF7FF000 == 0xE51FF000:  # A32 LDR pc, [pc, +/-imm12].
        literal = off + 8 + (word & 0xFFF) * (1 if word & 0x800000 else -1)
        return ("literal", literal) if 0 <= literal <= len(data) - 4 and literal % 4 == off % 4 else None
    return None


def a32_vectors(data):
    # The high byte of the first instruction narrows the search at all byte alignments.
    for hit in re.compile(rb"[\xea\xeb\xe5]").finditer(data, 3):
        off = hit.start() - 3
        if off + 32 > len(data):
            break
        targets = [a32_target(data, off + rel) for rel in VECTOR_SLOTS]
        if all(target is not None for target in targets):
            yield {"offset": off, "slots": [{"offset": off + slot, "kind": kind, "target": target}
                                             for slot, (kind, target) in zip(VECTOR_SLOTS, targets)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    images, results = [], []
    for path in args.paths:
        data = path.read_bytes()
        info = layout(data)
        if not info["all_records_valid"]:
            parser.error(f"invalid payload records: {path}")
        group = info["groups"][0]
        content = data[group["offset"]:group["end_exclusive"]]
        images.append(content)
        results.append({"file": path.name, "group_offset": group["offset"], "bytes": len(content),
                        "group_sha256": group["sha256"], "periodic_spans": list(periodic_spans(content)),
                        "a32_vector_candidates": list(a32_vectors(content))})
    if len({len(img) for img in images}) != 1:
        parser.error("group A sizes differ; cannot compare at the same offsets")
    comparisons = [
        {"left": a["file"], "right": b["file"],
         "groups": list(shifted_markers(x, y, a["periodic_spans"], b["periodic_spans"]))}
        for x, y, a, b in zip(images, images[1:], results, results[1:])
    ]
    print(json.dumps({"offset_space": "relative to group A", "images": results,
                      "stable_block_bytes": MIN_SPAN, "all_identical_spans": list(stable_spans(images)),
                      "consecutive_shifted_markers": comparisons}, indent=2))


if __name__ == "__main__":
    main()
