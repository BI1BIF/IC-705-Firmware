"""Reproduce the degraded CQC holdout from the 8 kHz mono PCM recording."""

import argparse
import random
import struct
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_wav")
    parser.add_argument("output_wav")
    parser.add_argument("--start-ms", type=int, default=8050)
    parser.add_argument("--end-ms", type=int, default=15180)
    args = parser.parse_args()
    with wave.open(args.original_wav, "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 8000):
            parser.error("expected 8 kHz, mono, 16-bit PCM")
        if not 0 <= args.start_ms < args.end_ms or args.end_ms * 8 > source.getnframes():
            parser.error("selected interval is outside the source WAV")
        source.setpos(args.start_ms * 8)
        count = (args.end_ms - args.start_ms) * 8
        message = struct.unpack(f"<{count}h", source.readframes(count))

    rng = random.Random(705100)
    pcm = [rng.randrange(-2400, 2401) for _ in range(12000 * 8)]
    pcm.extend(sample // 3 + rng.randrange(-2400, 2401) for sample in message)
    pcm.extend(rng.randrange(-2400, 2401) for _ in range(800 * 8))
    with open(args.output_wav, "xb") as file, wave.open(file, "wb") as out:
        out.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        out.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))


if __name__ == "__main__":
    main()
