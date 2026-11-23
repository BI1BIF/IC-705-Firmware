"""Replay captured IQ through a modeled FM audio path, SD decoder and installed playback DMA."""
import argparse
import json
from pathlib import Path
import sys
import wave

import numpy as np
from scipy.signal import butter, resample_poly, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.verify_705_dmr_multimode import UP, discriminator, replay
from tools.verify_705_dmr_station_air import bench


def verify(package, region, cutoff):
    output = package / region
    cases = (
        ("p25p1_c4fm_vc", 3, 14400, "GRP NAC 293 ID 1 TG 1"),
        ("ysf", 2, 45600, "DN DG-ID 00 RX N8KDR-TERY"),
    )
    for name, mode, count, caller in cases:
        raw = discriminator(UP / "tests/fixtures/iq" / (name + ".iq")).astype(float)
        # Synthetic channel, independent of the fixture. These are not measured IC-705 filters.
        pcm = sosfilt(butter(1, 300, btype="highpass", fs=48000, output="sos"), raw)
        pcm = sosfilt(butter(2, 3000, fs=48000, output="sos"), pcm)
        pcm = resample_poly(resample_poly(pcm, 1, 6), 6, 1)
        pcm = sosfilt(butter(1, cutoff, fs=48000, output="sos"), pcm)
        pcm = np.rint(pcm).clip(-32768, 32767).astype("<i2")
        label = f"{name}-deemphasis-{cutoff}"
        result = replay(label, mode, pcm, package_dir=package, output_dir=output)
        assert caller in result["rows"] and result["samples"] == count, result
        with wave.open(str(output / (label + ".wav")), "rb") as audio:
            expected = audio.readframes(audio.getnframes())
        # Exclude the call alert at the beginning when checking for audible output.
        assert np.max(np.abs(np.frombuffer(expected, "<i2")[1600:].astype(int))) > 200
        pcm = np.pad(pcm, (0, 24012 + (-len(pcm)) % 36))
        bench(region, pcm, None, digital=(mode, label, expected), package_dir=package)
        (output / (label + ".json")).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("region", choices=("J", "E"))
    parser.add_argument("--cutoff", choices=(400, 750), type=int, default=750)
    args = parser.parse_args()
    verify(args.package.resolve(), args.region, args.cutoff)
