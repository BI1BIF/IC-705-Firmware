"""Read-only comparison of the first IC-7300MK2 stored region with public decoder formats."""

import argparse
import bz2
import json
import lzma
from pathlib import Path
from struct import unpack_from
from zipfile import ZipFile
import zlib

from tools.decode_705_main import BOOT_SIZE, J140_MAIN_SHA, decode_a_range, decode_main, lzss
from tools.probe_7300_family import original_layout
from tools.probe_icom_cpu_record import FIRST, SPAN, STEP, vector_tables
from tools.probe_icom_payload_boundaries import digest, records


LIMIT = 16 * 1024 * 1024
ORIGINAL_APP_SHA = "4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4"
STARTS = (0, 1, 4, 8, BOOT_SIZE, BOOT_SIZE + 4, BOOT_SIZE + 8)


def assess(out, consumed, stream, expected, suffix=b""):
    ending = stream[consumed:]
    result = {"output_bytes": len(out), "output_sha256": digest(out),
              "consumed_bytes": consumed, "unused_bytes": len(ending),
              "matches_full_lengths": len(out) == expected and not ending.strip(suffix)}
    if len(out) == expected:
        result["a32_vector_candidates"] = vector_tables(out)
    return result


def probe_lzss(data, start, size, dialect, suffix=b""):
    stream = data[start:]
    result = {"start": start, "requested_output_bytes": size, "format": dialect}
    try:
        out, consumed = lzss(stream, size, max_size=LIMIT, original_7300=dialect == "stock-7300")
    except ValueError as exc:
        return {**result, "reason": str(exc)}
    return {**result, **assess(out, consumed, stream, size, suffix)}


def probe_standard(stream, expected, kind):
    try:
        if kind == "xz":
            decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=4 * LIMIT)
        elif kind == "bzip2":
            decoder = bz2.BZ2Decompressor()
        else:
            decoder = zlib.decompressobj({"zlib": 15, "gzip": 31, "raw-deflate": -15}[kind])
        out = decoder.decompress(stream, expected + 1)
        if not decoder.eof:
            return {"reason": "output limit or incomplete member", "output_bytes": len(out)}
        return assess(out, len(stream) - len(decoder.unused_data), stream, expected)
    except (OSError, EOFError, zlib.error, lzma.LZMAError) as exc:
        return {"reason": str(exc)}


def check_zip(path, dat):
    with ZipFile(path) as archive:
        members = archive.infolist()
        if (len(members) != 1 or members[0].file_size != len(dat)
                or archive.read(members[0]) != dat):  # read() also verifies the member CRC-32.
            raise ValueError(f"{path}: unexpected ZIP or ZIP member bytes")
    return {"file": path.name, "sha256": digest(path.read_bytes()),
            "members": [{"path": item.filename, "bytes": item.file_size,
                         "crc32": f"{item.CRC:08x}"} for item in members]}


def inspect(path):
    data = path.read_bytes()
    if data[:4] != b"DU3\0":
        raise ValueError(f"{path}: not a DU3 package")
    offset, raw, declared, _ = records(data)[0][0]
    if not 0 < declared <= LIMIT:
        raise ValueError(f"{path}: outside the read-only output cap")
    if len(raw) <= max(STARTS):
        raise ValueError(f"{path}: short first region")
    # Exactly the published IC-705 whole-region byte interpretation previously
    # used for record 2; do not infer or search new parameters for this test.
    transformed = decode_a_range(data, offset, len(raw), (raw[0] ^ 0xFF) - 0x4B)
    views = {"stored": raw, "ic705-region-interpretation": transformed}
    cases = []
    for name, view in views.items():
        # A complete region compressed with either documented LZSS dialect.
        for dialect in ("stock-7300", "ic705"):
            cases.append({"view": name, **probe_lzss(view, 0, declared, dialect)})
        # The standalone application header locations in the older families.
        stored_size, output_size = unpack_from("<II", view, BOOT_SIZE)
        if 0 < stored_size <= len(view) - (BOOT_SIZE + 8) and 0 < output_size <= declared:
            body = view[:BOOT_SIZE + 8 + stored_size]
            result = probe_lzss(body, BOOT_SIZE + 8, output_size, "ic705", b"\xff")
            result["bytes_after_stream_record"] = len(view) - len(body)
        else:
            result = {"format": "ic705", "start": BOOT_SIZE + 8,
                      "reason": "implausible nested header lengths"}
        cases.append({"view": name, "nested_header": [stored_size, output_size], **result})
        result = probe_lzss(view, BOOT_SIZE + 4, stored_size, "stock-7300")
        cases.append({"view": name, "nested_header": [stored_size], **result})

    # The known periodic region cannot be a fixed sequence of complete raw
    # 17-byte LSB-first flag groups unless the flags have no literal bits.
    flag_values = raw[FIRST + 15:FIRST + SPAN:17]
    shifted_values = raw[FIRST + STEP + 15:FIRST + STEP + SPAN:17]
    return {"file": path.name, "sha256": digest(data), "zip": check_zip(path.with_suffix(".zip"), data),
            "first_payload": {"offset": offset, "stored_bytes": len(raw),
                              "declared_word": declared, "sha256": digest(raw)},
            "hypothetical_flags_at_periodic_flip": {
                "count": len(flag_values), "nonzero": sum(bool(n) for n in flag_values),
                "shifted_nonzero": sum(bool(n) for n in shifted_values)},
            "lzss": cases,
            "standard": [{"start": start, "format": kind,
                          **probe_standard(raw[start:], declared, kind)}
                         for start in STARTS for kind in ("zlib", "gzip", "raw-deflate", "xz", "bzip2")]}


def controls(original, ic705):
    old = original.read_bytes()
    if not original_layout(old)["matches"]:
        raise ValueError("initial IC-7300 container/MD5 positive control failed")
    length = unpack_from("<I", old, 0x10)[0]
    raw = old[0x2C:0x2C + length]
    size = unpack_from("<I", raw, BOOT_SIZE)[0]
    start = BOOT_SIZE + 4
    old_app, consumed = lzss(raw[start:], size, max_size=LIMIT, original_7300=True)
    boot, app, report = decode_main(ic705.read_bytes())
    entry = {"offset": 0, "first_literal": "0x1800008c"}
    if (digest(old_app) != ORIGINAL_APP_SHA or digest(app) != J140_MAIN_SHA
            or any(entry not in vector_tables(raw_boot) for raw_boot in (raw[:BOOT_SIZE], boot))):
        raise ValueError("positive decoding or vector control failed")
    return {"original_ic7300_142": {"input_sha256": digest(old), "entry": entry,
                                    "output_bytes": len(old_app), "output_sha256": digest(old_app),
                                    "consumed_bytes": consumed, "start": start,
                                    "application_vectors_in_first_64k": vector_tables(old_app[:BOOT_SIZE]),
                                    "bytes_beyond_application_stream": len(raw) - (start + consumed)},
            "ic705_j140": {"input_sha256": report["input"]["sha256"], "output_bytes": len(app),
                           "output_sha256": digest(app), "entry": entry}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-7300", required=True, type=Path)
    parser.add_argument("--ic705-control", required=True, type=Path)
    parser.add_argument("packages", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps({"controls": controls(args.original_7300, args.ic705_control),
                          "mk2": [inspect(path) for path in args.packages]}, indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
