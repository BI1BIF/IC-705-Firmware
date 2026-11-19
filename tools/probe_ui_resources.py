"""Find exact menu labels, font magic and CI-V language patterns in an unmodified DAT."""

import argparse
import json
from pathlib import Path
import re


LABELS = (
    "表示言語", "システム言語", "ディスプレイ設定", "バージョン情報", "ファームアップ",
    "Display Language", "System Language", "Screen Capture", "Firmware Update", "Version Information",
)
ENCODINGS = ("utf-8", "utf-16le", "utf-16be", "cp932")
FONT_MAGIC = (b"OTTO", b"ttcf", b"wOFF", b"wOF2")


def hits(data, probes):
    results = {}
    for name, probe in probes:
        count, first = 0, []
        for match in re.finditer(re.escape(probe), data):
            count += 1
            if len(first) < 8:
                first.append(match.start())
        if count:
            results[name] = {"count": count, "first_file_offsets": first}
    return results


def language_id_probes():
    # Icom CI-V 1A/05: display language 0163, system language 0164.
    for selector in ("0163", "0164"):
        yield f"civ_prefix_{selector}", bytes.fromhex("1a05" + selector)
        yield f"bcd_pair_{selector}", bytes.fromhex(selector)
    # Adjacent official selectors 0161/0162 (units) and 0163/0164 (language).
    # These are layout hypotheses, not an assertion about the internal table.
    for kind, ids in (("bcd", range(0x0161, 0x0165)), ("decimal", range(161, 165))):
        for size in (2, 4):
            for order in ("big", "little"):
                yield f"adjacent_{kind}_{size}_{order}", b"".join(i.to_bytes(size, order) for i in ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="+", type=Path)
    args = parser.parse_args()
    report = {}
    for path in args.path:
        data = path.read_bytes()
        report[str(path)] = {
            "exact_labels": {
                encoding: hits(data, [(label, label.encode(encoding)) for label in LABELS])
                for encoding in ENCODINGS
            },
            "font_magic_candidates": hits(data, [(magic.decode(), magic) for magic in FONT_MAGIC]),
            "language_id_candidates": hits(data, language_id_probes()),
        }
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
