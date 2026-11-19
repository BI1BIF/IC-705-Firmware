"""Extract the IC-705 bootstrap and main image from a local, original DAT for static analysis."""

import argparse
import json
from pathlib import Path
import struct

from tools.firmware_scan import identify, layout


BOOT_SIZE = 0x10000
MAX_MAIN_SIZE = 10 * 1024 * 1024
J140_DAT_SHA = "2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45"
J140_MAIN_SHA = "d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9"


def lzss(stream, size, *, max_size=MAX_MAIN_SIZE, original_7300=False):
    """Decode a bounded Okumura stream and return its input consumption.

    The initial IC-7300 loader caps the last match and leaves 18 history bytes
    uninitialized. The default IC-705 interpretation is unchanged.
    """
    ring = bytearray(4096)
    head = 0xFEE
    pos = 0
    out = bytearray()
    if not 0 < size <= max_size:
        raise ValueError("invalid LZSS output size")
    try:
        while len(out) < size:
            flags = stream[pos]
            pos += 1
            for bit in range(8):
                first = stream[pos]
                pos += 1
                if flags & (1 << bit):
                    out.append(first)
                    ring[head] = first
                    head = (head + 1) & 0xFFF
                else:
                    second = stream[pos]
                    pos += 1
                    index = first | ((second & 0xF0) << 4)
                    count = (second & 15) + 3
                    if len(out) + count > size:
                        if not original_7300:
                            raise ValueError("LZSS token exceeds the declared output size")
                        count = size - len(out)
                    for _ in range(count):
                        if original_7300 and index >= 0xFEE + len(out):
                            raise ValueError("LZSS references uninitialized history")
                        value = ring[index]
                        out.append(value)
                        ring[head] = value
                        index = (index + 1) & 0xFFF
                        head = (head + 1) & 0xFFF
                if len(out) == size:
                    break
    except IndexError as exc:
        raise ValueError("truncated LZSS stream") from exc
    return out, pos


def checked_group_a(data):
    info = layout(data)
    if not info["all_records_valid"] or info["trailer_hex"] != "4075":
        raise ValueError("IC-705 envelope verification failed")
    return info, info["groups"][0]


def decode_boot(data, group):
    # Read-only interpretation of SQ6EMM's published IC705_DAT_FORMAT.md.
    start = group["offset"]
    end = start + BOOT_SIZE
    if end + 8 > group["end_exclusive"]:
        raise ValueError("group A is too short for the bootstrap and main header")

    boot = bytearray(BOOT_SIZE)
    previous = 0xFF  # Erased byte at the end of the bootstrap.
    for offset in range(end - 1, start - 1, -1):
        boot[offset - start] = previous
        previous = ((data[offset] ^ previous) - offset + 0x19) & 255
    padding = BOOT_SIZE - len(boot.rstrip(b"\xff"))
    if padding < 256:
        raise ValueError("bootstrap does not end in the expected padding")
    return boot, padding


def decode_a_range(data, offset, length, previous):
    out = bytearray(length)
    for i in range(length):
        pos = offset + i
        previous = data[pos] ^ ((previous + pos - 0x19) & 255)
        out[i] = previous
    return out


def decode_main(data):
    info, group = checked_group_a(data)
    boot, padding = decode_boot(data, group)
    start = group["offset"]
    end = start + BOOT_SIZE
    header = decode_a_range(data, end, 8, boot[-1])
    stored, size = struct.unpack("<II", header)
    if not (0 < stored <= group["end_exclusive"] - (end + 8) and 0 < size <= MAX_MAIN_SIZE):
        raise ValueError("decoded main lengths are outside bounds")
    stream = decode_a_range(data, end + 8, stored, header[-1])
    main, consumed = lzss(stream, size)
    if stream[consumed:].strip(b"\xff"):
        raise ValueError("main stream has unexpected trailing bytes")
    return boot, main, {
        "input": {"bytes": info["bytes"], "sha256": info["sha256"]},
        "bootstrap": {"file_offset": start, "ff_suffix_bytes": padding, **identify(boot)},
        "main": {"header_file_offset": end, "stream_file_offset": end + 8,
                 "stored_bytes": stored, "consumed_bytes": consumed,
                 "ff_suffix_bytes": stored - consumed, **identify(main)},
    }


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path, help="new directory for two raw analysis images and JSON")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("output directory already exists")
        boot, main, manifest = decode_main(args.dat.read_bytes())
        args.output.mkdir(parents=True)
        (args.output / "bootstrap.bin").write_bytes(boot)
        (args.output / "main.bin").write_bytes(main)
        report = json.dumps(manifest, indent=2)
        (args.output / "manifest.json").write_text(report + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(report)


if __name__ == "__main__":
    cli()
