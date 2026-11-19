"""Read-only firmware triage. Run this script with --help for usage."""

import argparse
from collections import Counter
from hashlib import md5, sha256
from itertools import islice
import json
from math import log2
from pathlib import Path
import re
import struct


MAGIC = {
    "elf": b"\x7fELF", "zip": b"PK\x03\x04", "gzip": b"\x1f\x8b\x08",
    "xz": b"\xfd7zXZ\x00", "zstd": b"\x28\xb5\x2f\xfd", "7zip": b"7z\xbc\xaf\x27\x1c",
    "png": b"\x89PNG\r\n\x1a\n", "uimage": b"\x27\x05\x19\x56", "dtb_fit": b"\xd0\x0d\xfe\xed",
    "squashfs_le": b"hsqs", "ubifs": b"\x31\x18\x10\x06", "ubi": b"UBI#",
}


def identify(data):
    return {"bytes": len(data), "sha256": sha256(data).hexdigest()}


def entropy(data):
    return -sum((n / len(data)) * log2(n / len(data)) for n in Counter(data).values()) or 0.0


def scan(data, block):
    signatures = {}
    for name, magic in MAGIC.items():
        hits = [m.start() for m in re.finditer(re.escape(magic), data)]
        if hits:
            signatures[name] = {"count": len(hits), "first_offsets": hits[:12]}
    words = data[: min(104, len(data) // 4 * 4)]
    return {
        **identify(data), "header_hex": data[:104].hex(" "),
        "header_u32le": [n for (n,) in struct.iter_unpack("<I", words)],
        "file_entropy": round(entropy(data), 6), "signature_candidates": signatures,
        "blocks": [
            {"offset": off, "size": len(chunk), "entropy": round(entropy(chunk), 6),
             "lag_256_equal_fraction": round(sum(a == b for a, b in zip(chunk, chunk[256:])) / (len(chunk) - 256), 6)
             if len(chunk) > 256 else None}
            for off in range(0, len(data), block) if (chunk := data[off:off + block])
        ],
    }


def strings(data, minimum, limit):
    patterns = [("ascii", rb"[ -~]"), ("utf-16le", rb"(?:[ -~]\x00)")]
    return {
        label: [{"offset": m.start(), "text": m[0].decode(label)[:160]}
                for m in islice(re.finditer(unit + rb"{%d,}" % minimum, data), limit)]
        for label, unit in patterns
    }


def layout(data):
    """Validate the observed 705E and 705J envelopes without decoding payloads."""
    if len(data) < 0x64 or data[:4] != b"\x44\x00\x77\x55":
        raise ValueError("unrecognized IC-705 header")
    lengths = [struct.unpack_from("<I", data, p)[0] for p in (0x38, 0x44, 0x4C, 0x54, 0x5C)]
    if not all(lengths[i] for i in (0, 3, 4)) or 0x64 + sum(lengths) + 4 * 16 + 2 != len(data):
        raise ValueError("payload lengths do not account for the file")
    if bool(lengths[1]) != bool(lengths[2]):
        raise ValueError("unverified mixed zero/nonzero B lengths")
    offset = 0x64
    groups = []
    for name, size in zip(("A", "B", "C", "D"), (lengths[0], sum(lengths[1:3]), *lengths[3:])):
        end = offset + size
        content = data[offset:end]
        stored = data[end:end + 16].hex()
        computed = md5(content, usedforsecurity=False).hexdigest() if size else None
        valid = stored == (computed if size else "0" * 32)
        groups.append({"name": name, "offset": offset, "end_exclusive": end,
                       **identify(content), "record_offset": end,
                       "digest_offset": end if size else None,
                       "record_kind": "md5" if size else "empty_placeholder",
                       "record_hex": stored, "stored_md5": stored if size else None,
                       "computed_md5": computed, "match": valid if size else None,
                       "record_valid": valid})
        offset = end + 16
    # The neighboring words are observations; their interpretation needs decoded images.
    size_pairs = [
        {"name": name, "stored_size_field": field, "stored_size": size,
         "neighbor_field": field + 4, "neighbor_value": struct.unpack_from("<I", data, field + 4)[0]}
        for name, field, size in zip(("B1", "B2", "C", "D"), (0x44, 0x4C, 0x54, 0x5C), lengths[1:])
    ]
    return {**identify(data), "header_bytes": 0x64, "groups": groups,
            "size_pairs": size_pairs,
            "group_b_candidate_split": groups[1]["offset"] + lengths[1] if lengths[1] else None,
            "trailer_offset": offset, "trailer_hex": data[offset:].hex(),
            "all_md5_match": all(group["match"] for group in groups if group["record_kind"] == "md5"),
            "all_records_valid": all(group["record_valid"] for group in groups)}


def compare(left, right, block):
    shared = min(len(left), len(right))
    identical_ranges, changed = [], []
    for off in range(0, shared, block):
        end = min(off + block, shared)
        a, b = left[off:end], right[off:end]
        if a == b:
            if identical_ranges and identical_ranges[-1][1] == off:
                identical_ranges[-1][1] = end
            else:
                identical_ranges.append([off, end])
            continue
        first = last = None
        count = 0
        for i, (x, y) in enumerate(zip(a, b), off):
            if x != y:
                first = i if first is None else first
                last = i
                count += 1
        changed.append({"block_offset": off, "different_bytes": count, "first": first, "last": last})
    return {"left": identify(left), "right": identify(right),
            "different_overlap_bytes": sum(b["different_bytes"] for b in changed),
            "unpaired_tail_bytes": abs(len(left) - len(right)), "identical_block_ranges": identical_ranges,
            "changed_blocks": changed}


def compare_groups(left, right, block):
    first, second = layout(left), layout(right)
    if not first["all_records_valid"] or not second["all_records_valid"]:
        raise ValueError("cannot align groups with invalid layout records")
    groups = []
    for a, b in zip(first["groups"], second["groups"]):
        same = a["sha256"] == b["sha256"]
        delta = None
        if not same and a["bytes"] and b["bytes"]:
            delta = compare(left[a["offset"]:a["end_exclusive"]],
                            right[b["offset"]:b["end_exclusive"]], block)
        groups.append({"name": a["name"], "identical": same, "left": a, "right": b,
                       "difference_group_relative": delta})
    return {"left_sha256": first["sha256"], "right_sha256": second["sha256"], "groups": groups}


def arm(data, start, end):
    # A32 little-endian branch and vector-load encodings; no Thumb or CFG recovery.
    result = []
    count = 0
    for offset in range(start, end - 3, 4):
        word, = struct.unpack_from("<I", data, offset)
        if word >> 28 == 15:
            continue
        if word & 0x0E000000 == 0x0A000000:
            immediate = word & 0xFFFFFF
            displacement = (immediate - ((immediate & 0x800000) << 1)) * 4
            target = offset + 8 + displacement
            if start <= target < end:
                count += 1
                if len(result) < 64:
                    result.append({"offset": offset, "kind": "BL" if word & 0x1000000 else "B", "target_offset": target})
        elif word & 0x0F7FF000 == 0x051FF000:
            target = offset + 8 + (word & 0xFFF) * (1 if word & 0x800000 else -1)
            if start <= target <= end - 4:
                count += 1
                if len(result) < 64:
                    result.append({"offset": offset, "kind": "LDR_PC_literal", "literal_offset": target})
    return {"candidates": count, "first_matches": result, "range": [start, end],
            "meaning": "Unverified instruction patterns; targets are file offsets under a linear mapping."}


def number(value):
    return int(value, 0)


def positive(value):
    n = number(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, summary in [("scan", "Header, signatures, entropy and periodicity by block"),
                          ("layout", "Verify observed 705E/705J layouts and payload MD5 records"),
                          ("compare", "Compare bytes at the same offsets across files"),
                          ("compare-groups", "Align checked 705E/705J groups before comparing"),
                          ("strings", "Find ASCII and ASCII-range UTF-16LE strings"),
                          ("arm", "List potential A32 branch/vector encodings in a chosen interval")]:
        command = sub.add_parser(name, help=summary, description=summary)
        command.add_argument("path", type=Path)
        if name in ("scan", "compare", "compare-groups"):
            command.add_argument("--block", type=positive, default=65536)
        if name in ("compare", "compare-groups"):
            command.add_argument("other", type=Path)
        if name == "strings":
            command.add_argument("--minimum", type=positive, default=12)
            command.add_argument("--limit", type=positive, default=30)
        if name == "arm":
            command.add_argument("--start", required=True, type=number)
            command.add_argument("--end", required=True, type=number)
    args = parser.parse_args()
    try:
        data = args.path.read_bytes()
        if args.command == "scan":
            output = scan(data, args.block)
        elif args.command == "layout":
            output = layout(data)
        elif args.command == "compare":
            output = compare(data, args.other.read_bytes(), args.block)
        elif args.command == "compare-groups":
            output = compare_groups(data, args.other.read_bytes(), args.block)
        elif args.command == "strings":
            output = {**identify(data), "strings": strings(data, args.minimum, args.limit)}
        else:
            if not 0 <= args.start < args.end <= len(data):
                parser.error("expected 0 <= start < end <= file size")
            output = {**identify(data), **arm(data, args.start, args.end)}
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(output, indent=2))
    if args.command == "layout" and not output["all_records_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
