"""Generate offline CW WAV fixtures and reference text. No decoder or device I/O."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import wave


RATE = 8000
TEXT = "CQ TEST 123"
MORSE = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                 ".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- "
                 ".--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. "
                 "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.".split()))
CASES = [("slow-clean", 12, 500, None), ("medium-noise", 20, 600, 6), ("fast-clean", 28, 750, None)]
PAD_FRAMES = 2400


def spans(message):
    for wi, word in enumerate(message.split()):
        if wi:
            yield False, 7
        for ci, letter in enumerate(word):
            if ci:
                yield False, 3
            for mi, mark in enumerate(MORSE[letter]):
                if mi:
                    yield False, 1
                yield True, 1 if mark == "." else 3


def render(message, wpm, tone_hz, snr_db):
    rng = random.Random(705)
    amplitude = 0.35
    noise_sigma = 0 if snr_db is None else amplitude / math.sqrt(2) * 10 ** (-snr_db / 20)
    pcm = bytearray()

    def append(value):
        value += rng.gauss(0, noise_sigma) if noise_sigma else 0
        pcm.extend(struct.pack("<h", max(-32768, min(32767, round(value * 32767)))))

    for _ in range(PAD_FRAMES):
        append(0)
    elapsed_units = 0
    for mark, units in spans(message):
        start = round(elapsed_units * RATE * 1.2 / wpm)
        elapsed_units += units
        end = round(elapsed_units * RATE * 1.2 / wpm)
        for i in range(end - start):
            ramp = min(1.0, i / 32, (end - start - 1 - i) / 32)
            append(amplitude * ramp * math.sin(math.tau * tone_hz * i / RATE) if mark else 0)
    for _ in range(PAD_FRAMES):
        append(0)
    return pcm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new directory for WAV files and manifest")
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    manifest = []
    for name, wpm, tone_hz, snr_db in CASES:
        path = args.output / (name + ".wav")
        pcm = render(TEXT, wpm, tone_hz, snr_db)
        with path.open("xb") as file, wave.open(file, "wb") as wav:
            wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        manifest.append({"file": path.name, "expected_text": TEXT, "wpm": wpm, "tone_hz": tone_hz,
                         "nominal_mark_snr_db": snr_db, "frames": len(pcm) // 2, "sample_rate": RATE,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
