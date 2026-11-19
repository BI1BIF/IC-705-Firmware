"""Check inferred MK2 and 7760 stored payload boundaries; print JSON, write no firmware."""

import argparse
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
from struct import unpack_from

from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_boot, lzss


def digest(data):
    return sha256(data).hexdigest()


def records(data):
    if data[:4] == b"DU3\0":
        first, limit, _, _, second, second_limit = unpack_from("<6I", data, 0x20)
        offset, lengths = 0x38, [(first, limit), (second, second_limit)]
    elif data[:4] == b"DDDV":
        words = unpack_from("<16I", data, 0x30)
        offset, lengths = 0x70, list(zip(words[::2], words[1::2], strict=True))
    else:
        raise ValueError("unexpected container magic")
    # This is a framing hypothesis; the purpose of the opaque 256-byte blocks is unknown.
    if offset + sum(length + 256 for length, _ in lengths) + 256 + 2 != len(data):
        raise ValueError("candidate records do not account for file")
    result = []
    for length, limit in lengths:
        if not 0 < length <= len(data) - offset or limit == 0:
            raise ValueError("invalid candidate record size")
        end = offset + length
        result.append((offset, data[offset:end], limit, data[end:end + 256]))
        offset = end + 256
    return result, data[offset:-2]


def compare(left, right):
    offset = best_start = best_size = 0
    for equal, group in groupby(a == b for a, b in zip(left, right)):
        size = sum(1 for _ in group)
        if equal and size > best_size:
            best_start, best_size = offset, size
        offset += size
    return {"identical": left == right, "identical_after_first_byte": left[1:] == right[1:],
            "longest_aligned_run_offset": best_start,
            "longest_aligned_run_bytes": best_size}


def test_705_decoder(stored, declared):
    """Check the published IC-705 payload interpretation as a format control."""
    prior = (stored[0] ^ 0xFF) - 0x4B
    expanded_input = bytearray(len(stored))
    for i, value in enumerate(stored):
        prior = value ^ ((prior + 0x4B + i) & 0xFF)
        expanded_input[i] = prior
    try:
        decoded, consumed = lzss(expanded_input, declared)
    except ValueError as exc:
        return {"matches": False, "reason": str(exc)}
    if consumed != len(stored):
        return {"matches": False, "reason": "unconsumed input", "consumed": consumed}
    return {"matches": True, "consumed": consumed, "output_bytes": len(decoded),
            "output_sha256": digest(decoded)}


def boot_test(stored):
    """Measure the erased suffix under the IC-705 bootstrap hypothesis."""
    if len(stored) < BOOT_SIZE:
        return {"reason": "stored region shorter than the IC-705 bootstrap"}
    candidate = bytearray(BOOT_SIZE)
    prior = 0xFF
    for i in range(BOOT_SIZE - 1, -1, -1):
        candidate[i] = prior
        prior = ((stored[i] ^ prior) - i - 0x4B) & 0xFF
    return {"sha256": digest(candidate), "erased_suffix_bytes": BOOT_SIZE - len(candidate.rstrip(b"\xff"))}


def scan(paths):
    files, by_record = [], []
    for path in paths:
        data = path.read_bytes()
        segments, terminal_block = records(data)
        entry = {"file": path.name, "bytes": len(data), "sha256": digest(data),
                 "magic": data[:4].hex(), "candidate_records": [],
                 "terminal_opaque_block_sha256": digest(terminal_block), "trailer": data[-2:].hex()}
        for offset, stored, limit, gap in segments:
            entry["candidate_records"].append({"offset": offset, "bytes": len(stored),
                "other_header_word": limit, "sha256": digest(stored),
                "following_256_bytes_sha256": digest(gap)})
        if data[:4] == b"DU3\0":
            entry["record_1_ic705_boot_assumption"] = boot_test(segments[0][1])
            _, stored, limit, _ = segments[1]
            entry["record_2_ic705_decoder"] = test_705_decoder(stored, limit)
        files.append(entry)
        by_record.append([stored for _, stored, _, _ in segments])

    changes = []
    for left, right, first, second in zip(files, files[1:], by_record, by_record[1:]):
        if left["magic"] == right["magic"]:
            changes.append({"versions": [left["file"], right["file"]], "records": [
                compare(a, b) for a, b in zip(first, second, strict=True)]})
    return files, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ic705-control", type=Path, required=True)
    parser.add_argument("packages", type=Path, nargs="+", help="group official DAT files by model, then version")
    args = parser.parse_args()
    control = args.ic705_control.read_bytes()
    info, boot_group = checked_group_a(control)
    group = info["groups"][2]
    bootstrap, _ = decode_boot(control, boot_group)
    boot_positive = boot_test(control[boot_group["offset"]:boot_group["end_exclusive"]])
    if boot_positive["sha256"] != digest(bootstrap):
        parser.error("IC-705 bootstrap positive control failed")
    positive = test_705_decoder(control[group["offset"]:group["end_exclusive"]], 0x200000)
    if not positive["matches"]:
        parser.error("IC-705 decoder positive control failed")
    files, changes = scan(args.packages)
    print(json.dumps({"ic705_decoder_control": {"file": args.ic705_control.name,
                       "dat_sha256": digest(control), "bootstrap": boot_positive, **positive},
                      "files": files, "comparisons": changes}, indent=2))


if __name__ == "__main__":
    main()
