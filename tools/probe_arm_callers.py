"""Find direct branches and literal references to even ARM-state addresses."""

import argparse
import json
from pathlib import Path
from struct import iter_unpack


def signed(value, bits):
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def probe(data, base, targets):
    if base % 4 or any(target % 4 for target in targets):
        raise ValueError("ARM base and targets must be word aligned")
    kinds = ("a32_bl", "a32_b", "t32_blx", "aligned_literals")
    hits = {target: {kind: [] for kind in kinds} for target in targets}
    for offset, (word,) in enumerate(iter_unpack("<I", data[:len(data) & ~3])):
        pc = base + offset * 4
        if word in hits:
            hits[word]["aligned_literals"].append(pc)
        if word & 0x0E000000 == 0x0A000000 and word >> 28 != 15:
            target = pc + 8 + signed(word & 0xFFFFFF, 24) * 4
            if target in hits:
                kind = "a32_bl" if word & 0x01000000 else "a32_b"
                hits[target][kind].append(pc)

    prev = 0
    for offset, (halfword,) in enumerate(iter_unpack("<H", data[:len(data) & ~1])):
        if prev & 0xF800 == 0xF000 and halfword & 0xD001 == 0xC000:
            pc = base + offset * 2 - 2
            s = (prev >> 10) & 1
            i1 = 1 ^ ((halfword >> 13) & 1) ^ s
            i2 = 1 ^ ((halfword >> 11) & 1) ^ s
            imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((prev & 0x3FF) << 12) | ((halfword & 0x7FE) << 1)
            target = ((pc + 4) & ~3) + signed(imm, 25)
            if target in hits:
                hits[target]["t32_blx"].append(pc)
        prev = halfword
    return {hex(addr): {kind: list(map(hex, refs)) for kind, refs in groups.items()}
            for addr, groups in hits.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--base", type=lambda value: int(value, 0), default=0x20005000)
    parser.add_argument("targets", nargs="+", type=lambda value: int(value, 0))
    args = parser.parse_args()
    print(json.dumps(probe(args.image.read_bytes(), args.base, args.targets), indent=2))


if __name__ == "__main__":
    main()
