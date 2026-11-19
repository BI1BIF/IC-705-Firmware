"""Score the 2026-01-06 ARRL 20 WPM body in a multimon-ng log, and measure PCM timing."""

import argparse
from array import array
from itertools import groupby
import json
from math import sqrt
from pathlib import Path
import re
from statistics import median
import sys
import wave


def body(text):
    # The archive includes a speed announcement and an end prosign outside the passage.
    match = re.search(r"PAGE\s+44\s*=\s*(.*?)\s*=\s*END\s+OF\s+20\s+WPM\s+TEXT",
                      text.upper(), re.DOTALL)
    if not match:
        return None
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "�", match[1]))


def edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j-1] + (x != y)))
        row = next_row
    return row[-1]


def measure(path):
    with wave.open(str(path)) as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 8000):
            raise ValueError("expected 8000 Hz mono signed 16-bit PCM")
        x = array("h")
        x.frombytes(stream.readframes(stream.getnframes()))
    if sys.byteorder != "little":
        x.byteswap()
    blocks = [sqrt(sum(v*v for v in x[i:i+40]) / 40) for i in range(0, len(x)-39, 40)]
    results = []
    for threshold in (4000, 8000):
        marks = [len(list(run))*5 for high, run in groupby(v >= threshold for v in blocks) if high]
        dits = [n for n in marks if 35 <= n <= 100]
        dahs = [n for n in marks if 130 <= n <= 250]
        if not dits or not dahs:
            raise ValueError(f"expected both short and long tones at RMS {threshold}")
        dit, dah = median(dits), median(dahs)
        results.append({"rms_threshold": threshold, "dit_count": len(dits), "dah_count": len(dahs),
                        "dit_ms": dit, "dah_ms": dah, "estimated_wpm": 2400 / (dah - dit)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("multimon_log", type=Path)
    parser.add_argument("pcm_wav", type=Path)
    args = parser.parse_args()
    try:
        ref = body(args.reference.read_text(encoding="utf-8-sig"))
        log = args.multimon_log.read_text(encoding="utf-8-sig")
        out = body(log)
        dit = re.findall(r"TIMING_DIT:\s*(\d+)", log)
        if not ref or not out or not dit or int(dit[-1]) <= 0:
            raise ValueError("missing passage boundaries or a positive TIMING_DIT in this log")
        print(json.dumps({"reference_chars": len(ref), "decoded_chars": len(out),
                          "char_errors": edit_distance(ref, out), "final_multimon_dit_ms": int(dit[-1]),
                          "final_multimon_wpm": 1200 / int(dit[-1]), "pcm_measurements": measure(args.pcm_wav)},
                         indent=2))
    except (OSError, ValueError, wave.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
