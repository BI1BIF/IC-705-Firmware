"""Compare candidate Icom CPU records and look for untransformed A32 vectors."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from struct import unpack_from

from tools.probe_7300_family import original_layout
from tools.probe_icom_payload_boundaries import records


FIRST = 0xF87
SPAN = 983
STEP = 17 * 128
VECTOR = rb"(?:[\x00-\xff][\xf0-\xff][\x1f\x9f]\xe5|[\x00-\xff]{3}\xea)"
# A32 B or LDR PC,[PC,+/-imm] in the first five and last two exception slots.
# The architectural reserved slot may hold any word.
VECTOR_TABLE = re.compile(b"(?=(" + VECTOR + b"{5}[\\x00-\\xff]{4}" + VECTOR + b"{2}))")


def signature(payload):
    x, y, z = (payload[base:base + SPAN] for base in (FIRST, FIRST + STEP, FIRST + 2 * STEP))
    if len(z) != SPAN:
        return {"matches": False, "reason": "short record"}
    flips = [(i, a ^ b) for i, (a, b) in enumerate(zip(x, y)) if a != b]
    return {"matches": x == z and flips == [(i, 128) for i in range(15, SPAN, 17)],
            "period_4352_exact": x == z, "differences_at_2176": len(flips),
            "sha256_first_window": sha256(x).hexdigest()}


def vector_tables(payload):
    """Report compatible shapes, not confirmed entry points. Scan at any byte alignment."""
    hits = []
    for match in VECTOR_TABLE.finditer(payload):
        offset = match.start()
        first = unpack_from("<I", payload, offset)[0]
        if first >> 24 == 0xEA:
            imm = first & 0xFFFFFF
            if imm & 0x800000:
                imm -= 0x1000000
            target = offset + 8 + imm * 4
            if not 0 <= target <= len(payload) - 4:
                continue
            hits.append({"offset": offset, "relative_branch_target": target})
        else:
            target = offset + 8 + (first & 0xFFF) * (1 if first & (1 << 23) else -1)
            if not 0 <= target <= len(payload) - 4:
                continue
            hits.append({"offset": offset, "first_literal": hex(unpack_from("<I", payload, target)[0])})
    return hits


def inspect(path):
    contents = path.read_bytes()
    parts, _ = records(contents)
    return {"file": path.name, "sha256": sha256(contents).hexdigest(), "parts": [
        {"file_offset": off, "bytes_checked": len(payload), "sha256": sha256(payload).hexdigest(),
         "record_pattern": signature(payload),
         "raw_a32_table_candidates": vector_tables(payload)} for off, payload, _, _ in parts]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-7300", type=Path, required=True)
    parser.add_argument("--mapped-705-boot", type=Path, required=True)
    parser.add_argument("packages", nargs="+", type=Path)
    args = parser.parse_args()
    old = args.original_7300.read_bytes()
    if not original_layout(old)["matches"]:
        parser.error("unverified initial IC-7300 package")
    size = unpack_from("<I", old, 0x10)[0]
    controls = [vector_tables(old[0x2C:0x2C + size]), vector_tables(args.mapped_705_boot.read_bytes())]
    if not all({"offset": 0, "first_literal": "0x1800008c"} in table for table in controls):
        parser.error("positive vector controls failed")
    print(json.dumps({"vector_controls": {"7300_142_stored_main": controls[0],
                      "705J140_decoded_bootstrap": controls[1]},
                      "files": [inspect(path) for path in args.packages]}, indent=2))


if __name__ == "__main__":
    main()
