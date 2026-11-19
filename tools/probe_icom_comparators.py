"""Compare the first payload and candidate tail in local 705, 905 and 9700 DATs."""

import argparse
from hashlib import md5
import json
from pathlib import Path
from struct import unpack_from

from tools.firmware_scan import identify, layout
from tools.probe_705_a import PERIOD, periodic_spans

PAGE = 4096
# Observed file offsets, not a general Icom format detector or a memory map.
FORMATS = {
    b"\x44\x00\x77\x55": ("IC-705", 0x64, 0x38, 0x40),
    b"\x44\x22\x00\x99": ("IC-905", 0x88, 0x3C, 0x44),
    b"\x33\x99\x11\x33": ("IC-9700", 0x38, 0x1C, None),
}


def adjacent_md5(data, start, end):
    return md5(memoryview(data)[start:end], usedforsecurity=False).digest() == data[end:end + 16]


def probe(data):
    if data[:4] not in FORMATS:
        raise ValueError("unknown comparator magic")
    model, start, size_field, tail_field = FORMATS[data[:4]]
    if len(data) < start:
        raise ValueError("truncated comparator header")
    size, = unpack_from("<I", data, size_field)
    tail_length = unpack_from("<I", data, tail_field)[0] if tail_field is not None else size - 0x400000
    end, cut = start + size, start + size - tail_length
    if not (start < cut < end <= len(data) - 16):
        raise ValueError("candidate first payload or tail is out of bounds")
    if model == "IC-705" and not layout(data)["all_records_valid"]:
        raise ValueError("invalid IC-705 layout records")
    spans = list(periodic_spans(data[start:end]))
    tail = data[cut:end]
    result = {
        "model": model, "magic": data[:4].hex(), "trailer": data[-2:].hex(), **identify(data),
        "first_payload": {"start": start, "end_exclusive": end, "size_field": size_field,
                          "adjacent_md5_matches": adjacent_md5(data, start, end)},
        "tail_length_field": tail_field,
        "field_between_size_and_tail": unpack_from("<I", data, size_field + 4)[0]
        if tail_field is not None else None,
        "front": identify(data[start:cut]),
        "tail": {"start": cut, "relative_start": cut - start, **identify(tail)},
        "period_256_stops_at_split": any(s["end_exclusive"] == cut - start for s in spans),
        "periodic_spans_payload_relative": spans,
    }
    if model == "IC-9700":
        second = end + 32
        second_end = second + unpack_from("<I", data, 0x30)[0]
        if not second < second_end == len(data) - 34:
            raise ValueError("IC-9700 second length does not account for the file")
        result["second_payload"] = {"start": second, "end_exclusive": second_end,
                                    "empty_record_before": data[end + 16:second] == bytes(16),
                                    "adjacent_md5_matches": adjacent_md5(data, second, second_end)}
    return result, tail


def compare_tail(left, right, shift=0):
    """Measure only aggregate byte statistics, without returning difference bytes."""
    count = min(len(left), max(0, len(right) - shift)) // PAGE
    kinds, wide = set(), []
    equal = nonperiodic = narrow = 0
    for off in range(0, count * PAGE, PAGE):
        a = left[off:off + PAGE]
        b = right[off + shift:off + shift + PAGE]
        values = {x ^ y for x, y in zip(a, b)}
        kinds.update(values)
        equal += sum(x == y for x, y in zip(a, b))
        if a[:-PERIOD] != a[PERIOD:] and b[:-PERIOD] != b[PERIOD:]:
            nonperiodic += 1
            narrow += len(values) <= 16
        if len(values) > 32:
            wide.append(off)
    return {"right_shift": shift, "bytes_compared": count * PAGE, "equal_bytes": equal,
            "distinct_xor_values": len(kinds), "nonperiodic_pages": nonperiodic,
            "nonperiodic_pages_at_most_16_xor_values": narrow,
            "pages_over_32_xor_values": len(wide),
            "first_and_last_wide_page_offsets": [wide[0], wide[-1]] if wide else []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="reference DAT for all pairwise comparisons")
    parser.add_argument("comparators", nargs="+", type=Path, help="official DATs to compare")
    args = parser.parse_args()
    images, tails = [], []
    for path in [args.baseline, *args.comparators]:
        try:
            info, tail = probe(path.read_bytes())
        except (OSError, ValueError) as error:
            parser.error(f"{path}: {error}")
        images.append({"file": path.name, **info})
        tails.append(tail)
    print(json.dumps({
        "images": images,
        "baseline": args.baseline.name,
        "tail_comparisons": [{"file": path.name, "aligned": compare_tail(tails[0], tail),
                              "shifted": compare_tail(tails[0], tail, PAGE)}
                             for path, tail in zip(args.comparators, tails[1:])],
    }, indent=2))


if __name__ == "__main__":
    main()
