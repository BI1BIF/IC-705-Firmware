"""Generate a verified SD update file from the original Japanese 1.40 DAT."""
import argparse
from hashlib import sha256
import lzma
from pathlib import Path

STOCK = "2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45"
TARGET = "5297e2581cdeb8f48af1ba6dd9b1bb33704675673c49b9448383f8d9a383c039"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("--output", type=Path, default=Path("IC-705/705J140.dat"))
    args = parser.parse_args()
    base = args.stock.read_bytes()
    if sha256(base).hexdigest() != STOCK:
        parser.error("Expected original Japanese IC-705 1.40 DAT (SHA-256 mismatch).")
    delta = lzma.decompress(Path(__file__).with_name("RX4-TX4.xor.xz").read_bytes())
    if len(delta) != len(base):
        parser.error("Incorrect patch size.")
    result = bytes(a ^ b for a, b in zip(base, delta))
    if sha256(result).hexdigest() != TARGET:
        parser.error("Generated firmware failed SHA-256 verification.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(result)
    print(args.output, TARGET)


if __name__ == "__main__":
    main()
