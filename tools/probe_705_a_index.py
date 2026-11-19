"""Test a header-derived A split and look for cleartext fields that track A landmarks."""

import argparse
from hashlib import md5
import json
from pathlib import Path

from tools.firmware_scan import identify, layout
from tools.probe_705_a import periodic_spans

TAIL_LENGTH_FIELD = 0x40
NEARBY = 256


def a_split(data, group, spans):
    tail_length = int.from_bytes(data[TAIL_LENGTH_FIELD:TAIL_LENGTH_FIELD + 4], "little")
    if not 16 < tail_length < group["bytes"]:
        raise ValueError("0x40 does not give an in-range candidate A tail length")
    start, end = group["offset"], group["end_exclusive"]
    cut = end - tail_length
    tail = data[cut:end]
    period_ends = {s["end_exclusive"] for s in spans}
    matching_fields = []
    for off in range(0x38, 0x64, 4):
        n = int.from_bytes(data[off:off + 4], "little")
        if 0 < n < group["bytes"] and end - start - n in period_ends:
            matching_fields.append(off)
    return {
        "header_0x3c_le32": int.from_bytes(data[0x3C:0x40], "little"),
        "header_0x40_le32": tail_length,
        "front": {"start": start, "end_exclusive": cut, **identify(data[start:cut])},
        "tail": {"start": cut, "end_exclusive": end, **identify(tail)},
        "period_256_stops_at_split": cut - start in period_ends,
        "aligned_header_fields_matching_a_tail_at_a_period_end": matching_fields,
        "tail_last_16_matches_md5_of_preceding_bytes":
            md5(tail[:-16], usedforsecurity=False).digest() == tail[-16:],
    }


def fixed_hits(data, patterns):
    """Find the same file offset encoding the predicted value in each sample."""
    offset = data[0].find(patterns[0])
    while offset >= 0:
        if all(sample.startswith(p, offset) for sample, p in zip(data[1:], patterns[1:])):
            yield offset
        offset = data[0].find(patterns[0], offset + 1)


def local_slots(edges, width):
    for side, deltas in (
        ("before_start", range(-NEARBY, -width + 1)),
        ("after_end", range(NEARBY - width + 1)),
    ):
        anchor = 0 if side == "before_start" else 1
        for delta in deltas:
            yield side, delta, [pair[anchor] + delta for pair in edges]


def plain_fields(data, edges, a_bounds, discovery_count):
    """Require all discovery matches; score any hits against the held-out inputs."""
    starts, ends = zip(*edges)
    a_starts, a_ends = zip(*a_bounds)
    values = {
        "file_start": starts, "file_end": ends,
        "a_relative_start": [s - a for s, a in zip(starts, a_starts)],
        "a_relative_end": [e - a for e, a in zip(ends, a_starts)],
        "start_to_a_end": [a - s for a, s in zip(a_ends, starts)],
        "end_to_a_end": [a - e for a, e in zip(a_ends, ends)],
        "length": [e - s for s, e in edges],
    }
    hits = []
    training = slice(0, discovery_count)
    test = slice(discovery_count, None)
    for label, numbers in values.items():
        for width in (2, 3, 4):
            if max(numbers) >= 1 << (width * 8):
                continue
            for byteorder in ("little", "big"):
                encoded = [v.to_bytes(width, byteorder) for v in numbers]
                base = {"field": label, "width": width, "endian": byteorder}
                if len(set(numbers[training])) > 1:
                    for offset in fixed_hits(data[training], encoded[training]):
                        held = [s.startswith(p, offset) for s, p in zip(data[test], encoded[test])]
                        hits.append({**base, "kind": "fixed", "file_offset": offset, "holdouts_match": held})
                for side, delta, slots in local_slots(edges, width):
                    matches = [off >= 0 and s.startswith(p, off) for s, p, off in zip(data, encoded, slots)]
                    if all(matches[training]):
                        hits.append({**base, "kind": side, "delta": delta, "holdouts_match": matches[test]})

    # Test a fixed but unknown address/offset base without guessing the memory map.
    placements = [("header", off, [off] * len(data)) for off in range(0x64 - 4 + 1)]
    placements.extend(local_slots(edges, 4))
    for endian in ("little", "big"):
        for side, delta, slots in placements:
            if any(not 0 <= off <= len(s) - 4 for s, off in zip(data, slots)):
                continue
            biases = [(int.from_bytes(s[off:off + 4], endian) - start) & 0xFFFFFFFF
                      for s, off, start in zip(data, slots, starts)]
            if len(set(biases[training])) == 1:
                hits.append({"field": "start_plus_constant", "width": 4, "endian": endian,
                             "kind": side, "delta": delta, "constant": biases[0],
                             "holdouts_match": [v == biases[0] for v in biases[test]]})
    return hits


def landmarks(spans, discovery_count):
    # Earlier changing start with a fixed right edge, plus the previously moving middle markers.
    def identify_span(span):
        if span["end_exclusive"] == 0x262000:
            return "early_period_start", span["motif_sha256"]
        if 0x2EC000 <= span["start"] < 0x5F0000 and span["end_exclusive"] <= 0x5F0000:
            return span["bytes"], span["motif_sha256"]
        return None

    for original in spans[0]:
        key = identify_span(original)
        if key is None:
            continue
        matches = [[s for s in group if identify_span(s) == key] for group in spans]
        if all(len(group) == 1 for group in matches):
            selected = [group[0] for group in matches]
            if len({s["start"] for s in selected[:discovery_count]}) >= 4:
                yield key, selected


def read_image(path):
    data = path.read_bytes()
    report = layout(data)
    if not report["all_records_valid"]:
        raise ValueError(f"invalid payload records: {path}")
    a = report["groups"][0]
    spans = list(periodic_spans(data[a["offset"]:a["end_exclusive"]]))
    return data[:a["end_exclusive"]], a, spans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("discovery", nargs="+", type=Path)
    parser.add_argument("--holdout", action="append", default=[], type=Path)
    parser.add_argument("--split-only", action="append", default=[], type=Path)
    args = parser.parse_args()
    if len(args.discovery) < 4:
        parser.error("provide at least four discovery versions")
    paths = args.discovery + args.holdout
    try:
        images = [read_image(p) for p in paths]
        splits = [{"file": p.name, **a_split(*image)} for p, image in zip(paths, images)]
        splits += [{"file": p.name, **a_split(*read_image(p))} for p in args.split_only]
    except (OSError, ValueError) as error:
        parser.error(str(error))
    data, groups, spans = zip(*images)
    a_bounds = [(a["offset"], a["end_exclusive"]) for a in groups]
    probes = []
    for key, selected in landmarks(spans, len(args.discovery)):
        edges = [(s["start"] + a["offset"], s["end_exclusive"] + a["offset"])
                 for s, a in zip(selected, groups)]
        probes.append({"landmark": key, "file_ranges": edges,
                       "fields": plain_fields(data, edges, a_bounds, len(args.discovery))})
    print(json.dumps({"discovery": [p.name for p in args.discovery], "holdout": [p.name for p in args.holdout],
                      "a_splits": splits, "landmark_probes": probes}, indent=2))


if __name__ == "__main__":
    main()
