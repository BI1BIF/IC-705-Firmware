"""Read IC-705 ICF settings and compare their plain byte patterns against DAT files."""

import argparse
from bisect import bisect_left, bisect_right
from hashlib import sha256
import json
from pathlib import Path
import re

from tools.firmware_scan import identify, layout
from tools.probe_cs705_menu import data_range


# CS-705 x86 menu handlers use clone buffer base + 0x392C0.
SETTINGS = {
    "display_language": 0x396BB,
    "system_language": 0x396BC,
    "digital_repeater_set": 0x399BB,
    "repeater_monitor_timer": 0x399C0,
}
PAIRS = {
    "language": ("display_language", "system_language"),
    "repeater": ("digital_repeater_set", "repeater_monitor_timer"),
}
SELECTORS = ("Misc_OnOff", "Common_DigiRpt", "Common_RepeaterMonitorTimer", "Common_Language")
CHOICE = re.compile(rb"\{S\(%Flex0\[(\d+)\](?::[^)]*)?\)\}(.*)")
ICF_RECORD = re.compile(rb"([0-9A-Fa-f]{8})([0-9A-Fa-f]{2})([0-9A-Fa-f]+)")


def parse_icf(raw):
    """Decode the observed contiguous IC-705 settings format; do not verify #CD."""
    lines = raw.splitlines()
    if len(lines) < 4 or lines[0] != b"40750001":
        raise ValueError("unrecognized IC-705 ICF model header")
    if not re.fullmatch(rb"#CD=[0-9A-Fa-f]{32}", lines[-1]):
        raise ValueError("missing or malformed ICF trailer")
    revision, records, data = None, 0, bytearray()
    for number, line in enumerate(lines[1:-1], 2):
        if not records and line.startswith(b"#"):
            if line.startswith(b"#MapRev="):
                match = re.fullmatch(rb"#MapRev=(\d+)", line)
                if not match or revision is not None:
                    raise ValueError("invalid or duplicate ICF MapRev")
                revision = int(match[1])
            continue
        match = ICF_RECORD.fullmatch(line)
        if not match or int(match[1], 16) != len(data) or len(match[3]) != 2 * int(match[2], 16):
            raise ValueError(f"invalid length or non-contiguous ICF record at line {number}")
        data.extend(bytes.fromhex(match[3].decode("ascii")))
        records += 1
    if revision is None or not records:
        raise ValueError("missing ICF MapRev or data records")
    return revision, records, bytes(data)


def offsets(data, pattern, base=0):
    start = data.find(pattern)
    while start >= 0:
        yield base + start
        start = data.find(pattern, start + 1)


def cell_tables(data, start, end):
    """Find null-delimited selector tables and return decoded Flex0 options."""
    tables = {}
    section = data[start:end]
    for selector in SELECTORS:
        marker = f"#GI_Sheet_Sel_{selector}_Cells".encode("ascii") + b"\0"
        tables[selector] = []
        for pos in offsets(section, marker):
            stop = section.find(b"\0#\0", pos + len(marker), pos + len(marker) + 1024)
            if stop < 0:
                raise ValueError(f"missing CS-705 selector terminator for {selector}")
            options = {}
            for raw in section[pos + len(marker):stop].split(b"\0"):
                choice = CHOICE.fullmatch(raw)
                if not choice:
                    raise ValueError(f"unrecognized CS-705 selector entry for {selector}")
                options[int(choice[1])] = choice[2].decode("cp932").removesuffix(r"\_").strip()
            tables[selector].append({"file_offset": start + pos, "choices": options})
    return tables


def setting_contexts(data):
    """Try windows containing both fields; omit low-variety byte sequences."""
    for pair, (left, right) in PAIRS.items():
        center = (SETTINGS[left] + SETTINGS[right]) // 2
        for size in (16, 32, 64):
            start = center - size // 2
            window = data[start:start + size]
            if len(window) != size:
                raise ValueError("ICF does not cover the expected settings windows")
            if len(set(window)) >= 4:
                yield pair, start, window


def packed_pairs(data, base, distance=64):
    """Compare both byte orders and report pairs of non-overlapping literals."""
    report = {}
    for pair, fields in PAIRS.items():
        for width in (3, 4):
            for order in ("little", "big"):
                a, b = (list(offsets(data, SETTINGS[f].to_bytes(width, order), base)) for f in fields)
                count, first = 0, []
                for x in a:
                    for low, high in ((x - distance, x - width), (x + width, x + distance)):
                        left, right = bisect_left(b, low), bisect_right(b, high)
                        count += right - left
                        if len(first) < 8:
                            first.extend([x, y] for y in b[left:min(right, left + 8 - len(first))])
                report[f"{pair}_{width}_{order}"] = {
                    "literal_counts": [len(a), len(b)], "first_literal_file_offsets": [a[:8], b[:8]],
                    "pair_count": count, "first_pairs": first,
                }
    return report


def exact_matches(data, patterns, base=0):
    return {name: {"count": len(found), "first_file_offsets": found[:8]}
            for name, pattern in patterns.items() if (found := list(offsets(data, pattern, base)))}


def dat_report(data, patterns):
    envelope = layout(data)
    if not envelope["all_records_valid"]:
        raise ValueError("invalid DAT envelope records")
    a = envelope["groups"][0]
    start, end = a["offset"], a["end_exclusive"]
    cut = end - int.from_bytes(data[0x40:0x44], "little")
    if cut - start != 0x600000 or cut >= end:
        raise ValueError("unrecognized A group split")
    report = {}
    for name, (lo, hi) in (("whole", (0, len(data))), ("a_front", (start, cut)), ("a_tail", (cut, end))):
        region = data[lo:hi]
        report[name] = {"range": [lo, hi], "exact_matches": exact_matches(region, patterns, lo),
                        "packed_offsets": packed_pairs(region, lo)}
    return {**identify(data), "regions": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--icf", action="append", type=Path, required=True, help="official IC-705 .icf (repeatable)")
    parser.add_argument("--firmware", action="append", type=Path, default=[], help="raw IC-705 DAT (repeatable)")
    parser.add_argument("--cs", action="append", type=Path, default=[], help="extracted CS705.exe (repeatable)")
    args = parser.parse_args()
    report = {"settings_offsets": SETTINGS, "icf": {}, "cs705": {}, "dat": {}}
    patterns = {f"ascii:{label}": label.encode("ascii") for label in ("ON(GW)", "ON (GW)", "60min")}
    patterns.update({f"ascii:{s}": f"#GI_Sheet_Sel_{s}_Cells".encode("ascii") + b"\0" for s in SELECTORS})
    try:
        for path in args.icf:
            raw = path.read_bytes()
            revision, records, data = parse_icf(raw)
            windows = {}
            for pair, start, window in setting_contexts(data):
                name = f"{path.name}:{pair}:{len(window)}"
                patterns[name] = window
                windows[name] = {"logical_offset": start, **identify(window),
                                 "control_offsets": list(offsets(data, window))[:8]}
            report["icf"][path.as_posix()] = {
                **identify(raw), "map_rev": revision, "records": records, "logical_bytes": len(data),
                "values": {field: data[off] for field, off in SETTINGS.items()}, "windows": windows,
            }
        for path in args.cs:
            data = path.read_bytes()
            start, end = data_range(data)
            report["cs705"][path.as_posix()] = {
                **identify(data), "cell_tables": cell_tables(data, start, end),
                "plain_selector_hits": exact_matches(data[start:end], {
                    name: pattern for name, pattern in patterns.items() if name.startswith("ascii:")
                }, start),
            }
        for path in args.firmware:
            report["dat"][path.as_posix()] = dat_report(path.read_bytes(), patterns)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
