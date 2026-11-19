"""Compare two local IC-705 board readbacks. Reads files only; reports JSON to stdout."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import unpack_from

from tools.decode_705_main import BOOT_SIZE, J140_DAT_SHA, checked_group_a, decode_a_range, decode_main, lzss


SIZES = {"IC704": 0x1000000, "IC705": 0x20000, "IC706": 0x20000}
SELECTOR, FIRST, SECOND, SHARED = 0xBF0000, 0x10000, 0x600000, 0xC00000
# Per-chip physical offsets, evidenced in the stock startup and ICF restore replays.
STARTUP = {"IC705": ((0x1FFC0, 16),),
           "IC706": ((0x1FE40, 16), (0x1FF90, 30), (0x1FFB0, 16), (0x1FFC0, 16))}


def read_reference(path):
    dat = path.read_bytes()
    if sha256(dat).hexdigest() != J140_DAT_SHA:
        raise ValueError("reference must be the unchanged official Japanese 705J140.dat")
    boot, main, manifest = decode_main(dat)
    _, group = checked_group_a(dat)
    split = SECOND - BOOT_SIZE  # The first 96 NOR sectors include the 64 KiB bootstrap.
    start = group["offset"] + split + BOOT_SIZE
    before = decode_a_range(dat, group["offset"] + BOOT_SIZE, split, boot[-1])
    tail = decode_a_range(dat, start, group["end_exclusive"] - start, before[-1])
    return bytes(boot), (len(main), manifest["main"]["sha256"]), bytes(tail)


def pair(first, second, size):
    report = {"expected_bytes": size, "sha256": [], "issues": []}
    found = [file.stat().st_size if file.is_file() else None for file in (first, second)]
    report["bytes"] = found
    if found != [size, size]:
        report["issues"].append("missing_or_wrong_size")
        return report, None
    if first.samefile(second):
        report["issues"].append("same_file")
        return report, None
    files = []
    for path in (first, second):
        with path.open("rb") as stream:
            files.append(stream.read(size + 1))
    if any(len(data) != size for data in files):
        report["issues"].append("size_changed_while_reading")
        return report, None
    report["sha256"] = [sha256(data).hexdigest() for data in files]
    if files[0] != files[1]:
        report["issues"].append("readbacks_differ")
        report["first_difference"] = hex(next(i for i, (a, b) in enumerate(zip(*files)) if a != b))
        return report, None
    data = files[0]
    if data.count(data[:1]) == size:
        report["issues"].append("blank_or_uniform")
        return report, None
    if data[:size//2] == data[size//2:]:
        report["issues"].append("repeated_halves_review_addressing")
    return report, data


def inspect_nor(data, reference):
    bootstrap, (stock_size, stock_digest), tail = reference
    marker = bootstrap[0x47E8:0x47F8]
    marked = data[SELECTOR:SELECTOR+16] == marker
    selected = SECOND if marked else FIRST
    stored, length = unpack_from("<II", data, selected)
    end = selected + 8 + stored
    decoded_sha = None
    if length == stock_size and 0 < stored and end <= (SELECTOR if marked else SECOND):
        try:
            main, _ = lzss(memoryview(data)[selected+8:end], length)
        except ValueError:
            pass
        else:
            decoded_sha = sha256(main).hexdigest()
    return {"bootstrap_matches_j140": data[:BOOT_SIZE] == bootstrap,
            "selected_main_offset_using_stock_rule": hex(selected),
            "selected_decoded_sha256": decoded_sha, "selected_main_matches_j140": decoded_sha == stock_digest,
            "shared_tail_matches_j140": data[SHARED:SHARED+len(tail)] == tail}


def verify(first, second, reference):
    components, copies = {}, {}
    for chip, size in SIZES.items():
        name = f"{chip}.bin"
        components[chip], copies[chip] = pair(first / name, second / name, size)
    findings = []
    nor = inspect_nor(copies["IC704"], reference) if copies["IC704"] is not None else None
    if nor and not all(nor[k] for k in ("bootstrap_matches_j140", "selected_main_matches_j140",
                                        "shared_tail_matches_j140")):
        findings.append("nor_does_not_match_all_known_j140_anchors")
    if copies["IC705"] is not None and copies["IC705"] == copies["IC706"]:
        findings.append("eeprom_files_identical_verify_chip_selection")
    startup = {}
    for chip, ranges in STARTUP.items():
        if copies[chip] is not None:
            startup[chip] = [
                {"offset": hex(offset), "bytes": size,
                 "all_ff_or_00": copies[chip][offset:offset+size] in (b"\xff"*size, b"\x00"*size)}
                for offset, size in ranges
            ]
    return {
        "reference": "stock comparator for Japanese 705J140",
        "file_check": "fail" if any(data is None for data in copies.values()) else
                      "review" if findings or any(item["issues"] for item in components.values()) else "pass",
        "components": components, "nor": nor, "eeprom_known_startup_ranges": startup, "findings": findings,
        "scope": "File evidence only: chip provenance, independent acquisition, NOR status, other components, "
                 "calibration and recovery still require separate proof.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("read1", type=Path, help="first independent read; directory with IC704/5/6 .bin files")
    parser.add_argument("read2", type=Path, help="second independent read of the same board")
    parser.add_argument("--reference", type=Path, default=Path("firmware/705J140.dat"))
    args = parser.parse_args()
    try:
        result = verify(args.read1, args.read2, read_reference(args.reference))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return {"pass": 0, "fail": 1, "review": 2}[result["file_check"]]


if __name__ == "__main__":
    raise SystemExit(main())
