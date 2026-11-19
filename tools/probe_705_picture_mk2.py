"""Replay four J140 Picture page entries and compare two official MK2 update headers."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from math import log2
from pathlib import Path
from struct import unpack_from

from tools.emulate_705 import BASE, call, machine
from tools.decode_705_main import J140_DAT_SHA, J140_MAIN_SHA
from tools.firmware_scan import entropy, layout


PAGES = (
    ("RX PICTURE", 0x202ECB60, 0x37),
    ("RX PICTURE HISTORY", 0x202ECB78, 0x38),
    ("TX PICTURE", 0x202ECB90, 0x39),
    ("TX/RX PICTURE VIEW", 0x202EBC60, 0x3A),
)
MK2_SHA = {
    "1.02": "a3c4b3a31593b8c69f7cfd85073a1e29ec2e2b2198e9cced957211cad249e020",
    "1.03": "96306d3c746792a77ea4efdf7745edd86eeb5df6779d2e145629679f55ad942f",
}
J132_MAIN_SHA = "e2367bf67ec7969ef42cf74a4d0da22d3b75b825377c223ccc131f1ba217617f"


def probe_picture(main):
    if sha256(main).hexdigest() != J140_MAIN_SHA:
        raise ValueError("expected the original decoded 705J140 main.bin")
    page_ram, = unpack_from("<I", main, 0x200B4100-BASE)
    results = []
    for label, record, page_id in PAGES:
        title, _, _, _, entry = unpack_from("<5I", main, record-BASE)
        if main[title-BASE:].split(b"\0", 1)[0] != label.encode("ascii"):
            raise ValueError(f"title mismatch: {label}")
        cpu = machine(main)
        call(cpu, entry)
        page = cpu.mem_read(page_ram+1, 1)[0]
        if page != page_id:
            raise ValueError(f"unexpected page selected for {label}: {page}")
        results.append({"title": label, "record": hex(record), "entry": hex(entry), "page_id": page,
                        "guest_page_state": hex(page_ram+1)})
    return results


def probe_mk2(data, version):
    digest = sha256(data).hexdigest()
    if digest != MK2_SHA[version]:
        raise ValueError(f"expected the original MK2 {version} DAT")
    words = unpack_from("<6I", data, 0x20)
    text_hits = {label: {encoding: data.find(label.encode(encoding)) for encoding in ("ascii", "utf-16le")}
                 for label in ("CW DECODE", "KEY SPEED", "RTTY DECODE")}
    return {"sha256": digest, "bytes": len(data), "magic": data[:4].hex(" "),
            "words_at_0x20": [hex(word) for word in words],
            "bytes_outside_two_candidate_lengths": len(data)-words[0]-words[4],
            "raw_dat_text_offsets_minus_one_means_absent": text_hits}


def compare_mk2(old, new, *, width=4096):
    """Find exact stored windows above and below the header's 0x20 numeric word."""
    length_old, = unpack_from("<I", old, 0x20)

    def scan(start, stop):
        shifts = Counter()
        tested = ambiguous = 0
        for offset in range(start, stop-width+1, width):
            window = old[offset:offset+width]
            if len(set(window)) < 12:
                continue
            tested += 1
            match = new.find(window, width)
            if match < 0:
                continue
            if new.find(window, match+1) >= 0:
                ambiguous += 1
                continue
            shifts[match-offset] += 1
        return {"tested": tested, "unique_matches": sum(shifts.values()), "ambiguous_matches": ambiguous,
                "new_minus_old_offsets": dict(sorted(shifts.items()))}

    old_tail = len(old)-unpack_from("<I", old, 0x30)[0]
    new_tail = len(new)-unpack_from("<I", new, 0x30)[0]
    common_start = common_end = 0
    while common_start > -min(old_tail, new_tail) and old[old_tail+common_start-1] == new[new_tail+common_start-1]:
        common_start -= 1
    while common_end < min(len(old)-old_tail, len(new)-new_tail) and old[old_tail+common_end] == new[new_tail+common_end]:
        common_end += 1
    return {"window_bytes": width, "range_note": "absolute aligned offsets; header words are not proven section boundaries",
            "below_header_word_0x20": scan(width, length_old),
            "above_header_word_0x20": scan((length_old+width-1)//width*width, len(old)),
            "common_run_around_tail_minus_word_0x30": {"anchors": [hex(old_tail), hex(new_tail)],
                  "start_offsets": [hex(old_tail+common_start), hex(new_tail+common_start)],
                  "end_offsets_exclusive": [hex(old_tail+common_end), hex(new_tail+common_end)],
                  "sha256": sha256(old[old_tail+common_start:old_tail+common_end]).hexdigest(),
                  "bytes": common_end-common_start}}


def compare_705_plaintext(main, j132, dat, old, new, common):
    """Check sampled plaintext, with the 705's own package as a packing control."""
    if sha256(dat).hexdigest() != J140_DAT_SHA or sha256(j132).hexdigest() != J132_MAIN_SHA:
        raise ValueError("expected the unmodified J140 DAT and extracted J132 main.bin")
    group = next(row for row in layout(dat)["groups"] if row["name"] == "C")
    c = dat[group["offset"]:group["end_exclusive"]]
    stable = new[int(common["start_offsets"][1], 16):int(common["end_offsets_exclusive"][1], 16)]
    targets = {"J132 extracted main": j132, "J140 raw DAT": dat,
               "MK2 1.02 raw DAT": old, "MK2 1.03 raw DAT": new, "MK2 shared range": stable}
    rows = {}
    for label, source in {"J140 extracted main": main, "J140 stored C": c}.items():
        for n in (32, 64):
            candidates = (source[i:i+n] for i in range(0, len(source)-n+1, 4096))
            windows = [w for w in candidates if entropy(w) >= log2(n)-1.5 and source.count(w) == 1]
            rows[f"{label}, {n} bytes"] = {"windows": len(windows),
                                          "matches": {name: sum(w in data for w in windows)
                                                      for name, data in targets.items()}}
    return {"method": "Sample every 4096 bytes; require one source occurrence and entropy >= log2(width)-1.5",
            "limits": "No raw match cannot rule out shared decoded code or establish porting compatibility",
            "stored_C": {"offset": hex(group["offset"]), "sha256": sha256(c).hexdigest()}, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("j140_main", type=Path)
    parser.add_argument("mk2_102", type=Path)
    parser.add_argument("mk2_103", type=Path)
    parser.add_argument("--j140-dat", type=Path)
    parser.add_argument("--j132-main", type=Path)
    args = parser.parse_args()
    if bool(args.j140_dat) != bool(args.j132_main):
        parser.error("supply --j140-dat and --j132-main together")
    old, new = args.mk2_102.read_bytes(), args.mk2_103.read_bytes()
    j140 = args.j140_main.read_bytes()
    report = {"j140_main_sha256": J140_MAIN_SHA, "isolated_picture_entries": probe_picture(j140),
              "mk2_update_headers": {"1.02": probe_mk2(old, "1.02"), "1.03": probe_mk2(new, "1.03")},
              "mk2_exact_window_comparison": compare_mk2(old, new)}
    if args.j140_dat:
        common = report["mk2_exact_window_comparison"]["common_run_around_tail_minus_word_0x30"]
        report["raw_plaintext_controls"] = compare_705_plaintext(
            j140, args.j132_main.read_bytes(), args.j140_dat.read_bytes(), old, new, common)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
