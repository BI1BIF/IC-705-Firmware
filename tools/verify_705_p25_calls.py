"""Check unprogrammed P25 conventional receive across NACs and destinations in one session."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.verify_705_dmr_call_types import air, gen
from tools.verify_705_dmr_multimode import replay


def check(package):
    source = 7654321
    rng = np.random.default_rng(25705)
    segments = []
    expected_rows = set()
    expected_samples = 0

    def append(nac, duid, word, row, *, damaged_nid=False):
        nonlocal expected_samples
        control = gen.rs64_encode(gen.p25_hexbits(word), 12 if duid == 5 else 8)
        with patch.object(gen, "P25_NAC", nac):
            bits = gen.p25_ldu_bits(duid, control, rng, gen.p25_imbe_silent_bits())
        if damaged_nid:
            # Two information errors and four parity errors, excluding status dibits.
            for pos in (51, 56, 76, 81, 87, 100):
                bits[pos] ^= 1
        segments.extend((np.zeros(24000, dtype="<i2"), air(gen.bits_to_levels(bits * 2))))
        if row:
            expected_rows.add(row)
            expected_samples += 2880

    for nac, fmt, mfid, target, kind in (
        (0x001, 0, 0, 17, "GRP"), (0xB91, 3, 1, 9876543, "PVT"),
        (0x6AF, 0, 0, 65535, "ALL"), (0x912, 0x40, 0xA4, 3500, "GRP"),
        (0x310, 0, 0x90, 9000, "GRP"),
    ):
        lc = bytes((fmt, mfid, 0)) + target.to_bytes(3, "big") + source.to_bytes(3, "big")
        label = "TO" if kind == "PVT" else "TG"
        append(nac, 5, lc, f"{kind} NAC {nac:03X} ID {source} {label} {target}", damaged_nid=True)
    append(0x737, 10, bytes(9) + bytes((0x80, 0, 0)), "NAC 737")
    append(0x737, 10, bytes(9) + bytes((0x84, 0, 0)), None)
    append(0xA11, 5, bytes((3, 1, 64, 0, 0, 1, 0, 0, 2)), None)
    result = replay("p25-auto-calls", 3, np.concatenate(segments), package_dir=package)
    assert set(result["rows"]) == expected_rows and result["samples"] == expected_samples, result
    (package / "p25-auto-calls.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    check(parser.parse_args().package.resolve())
