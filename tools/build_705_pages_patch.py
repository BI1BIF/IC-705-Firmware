"""Publish a browser patch for a verified same-size IC-705 1.40 build."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

STOCK_SHA256 = "2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-sha256", required=True, help="From the verified release build")
    args = parser.parse_args()
    stock, target = args.stock.read_bytes(), args.target.read_bytes()
    digest = hashlib.sha256(target).hexdigest()
    stock_hash = hashlib.sha256(stock).hexdigest()
    manifests = {STOCK_SHA256:"latest.json",
                 "132383f8388641d02d0fadaccf9878d01a1960fa77a028328f0eb33dcfbc147b":"e140.json"}
    if stock_hash not in manifests or len(stock) != len(target):
        parser.error("Expected E140 or J140 stock and a same-length target")
    if digest != args.expected_sha256 or stock == target:
        parser.error("Target does not match the verified modified firmware")
    payload = gzip.compress(bytes(a ^ b for a, b in zip(stock, target)), mtime=0)
    patch_hash = hashlib.sha256(payload).hexdigest()
    root = Path(__file__).resolve().parents[1] / "docs/converter"
    notes = json.loads((root / "release-notes.json").read_text(encoding="utf-8-sig"))
    if not notes["history"] or args.version not in [row["version"] for row in notes["history"]]:
        parser.error("Add the new version to release-notes.json before publishing")
    for lang in ("zh", "en"):
        if not notes["features"].get(lang) or not all(row.get(lang) for row in notes["history"]):
            parser.error("Supply current features and release notes in both languages")
    filename = f"{patch_hash}.xor.gz"
    (root / filename).write_bytes(payload)
    manifest = dict(version=args.version, size=len(stock), stock=stock_hash, target=digest,
                    patch=filename, patchHash=patch_hash, notes=notes)
    (root / manifests[stock_hash]).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
