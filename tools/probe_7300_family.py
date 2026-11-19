"""Compare official IC-7300 and IC-7300MK2 DAT layouts; print evidence only."""

import argparse
from hashlib import md5, sha256
from itertools import groupby
import json
from pathlib import Path
from struct import unpack_from


ORIGINAL_MAGIC = bytes.fromhex("33 77 66 55")


def original_layout(data):
    """Check the initial 7300 framing described in zarthur's research/container.md."""
    if data[:4] != ORIGINAL_MAGIC:
        return {"matches": False, "reason": "different magic"}
    main, dsp, _, tables, _, fpga, _ = unpack_from("<7I", data, 0x10)
    end = 0x2C + main + dsp + tables + fpga + 4 * 16 + 2
    if end != len(data):
        return {"matches": False, "reason": "stored lengths do not cover file"}
    offset = 0x2C
    digests = []
    for length in (main, dsp, tables, fpga):
        stop = offset + length
        digests.append(md5(data[offset:stop]).digest() == data[stop:stop + 16])
        offset = stop + 16
    return {"matches": all(digests), "component_md5_matches": digests}


def describe(path):
    data = path.read_bytes()
    result = {"file": path.name, "bytes": len(data), "sha256": sha256(data).hexdigest(),
              "magic": data[:4].hex(" "), "original_7300_layout": original_layout(data)}
    if data[:4] == b"DU3\0":
        fields = unpack_from("<6I", data, 0x20)
        result["du3_fields_at_0x20"] = [hex(field) for field in fields]
        result["length_minus_0x20_and_0x30_words"] = len(data) - fields[0] - fields[4]
    return data, result


def first_shared_run(old, new, stop=0x40000):
    """Find the longest same-offset region in the first 256 KiB; no role inferred."""
    offset = best_start = best_length = 0
    for equal, run in groupby(a == b for a, b in zip(old[:stop], new[:stop])):
        length = sum(1 for _ in run)
        if equal and length > best_length:
            best_start, best_length = offset, length
        offset += length
    end = best_start + best_length
    return {"scan_end_exclusive": hex(stop), "start": hex(best_start),
            "end_exclusive": hex(end), "bytes": best_length,
            "sha256": sha256(old[best_start:end]).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original_142", "mk2_102", "mk2_103"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    _, original = describe(args.original_142)
    old, mk2_old = describe(args.mk2_102)
    new, mk2_new = describe(args.mk2_103)
    if not original["original_7300_layout"]["matches"] or not old.startswith(b"DU3\0") or not new.startswith(b"DU3\0"):
        parser.error("expected a positive IC-7300 1.42 control and two DU3 MK2 update files")
    print(json.dumps({"files": [original, mk2_old, mk2_new],
                      "longest_same_offset_mk2_prefix_run": first_shared_run(old, new)}, indent=2))


if __name__ == "__main__":
    main()
