"""Generate an offline Robot 36 color card and a 6.1 kHz alias control at 48 kHz."""

import argparse
from array import array
from math import pi, sin
from pathlib import Path
import sys
import wave


RATE = 48000
WIDTH, HEIGHT = 320, 240
COLORS = [(235, 235, 235), (224, 195, 35), (30, 175, 188), (32, 162, 60),
          (195, 44, 166), (197, 50, 43), (36, 67, 188), (31, 31, 31)]


def card():
    # Two different bar orders expose a wrong line order or swapped chroma.
    return [[COLORS[(x // 40 + 3 * (y // 120)) % 8] for x in range(WIDTH)] for y in range(HEIGHT)]


def components(rgb):
    r, g, b = rgb
    y = 0.299 * r + 0.587 * g + 0.114 * b
    return (y, 127.5 + (r - y) / 1.402, 127.5 + (b - y) / 1.772)


def robot36(rows):
    pcm = array('h', [0]) * (RATE // 4)
    phase = 0.0

    def tone(hz, samples):
        nonlocal phase
        step = 2 * pi * hz / RATE
        pcm.extend(round(14000 * sin(phase + i * step)) for i in range(samples))
        phase = (phase + samples * step) % (2 * pi)

    for hz, ms in [(1900, 300), (1200, 10), (1900, 300), (1200, 30),
                   *((1100 if (8 >> bit) & 1 else 1300, 30) for bit in range(7)),
                   (1100, 30), (1200, 30)]:
        tone(hz, ms * 48)
    for y, row in enumerate(rows):
        values = [components(rgb) for rgb in row]
        tone(1200, 432)
        tone(1500, 144)
        for channel, length in [(0, 4224), (1 + y % 2, 2112)]:
            if channel:
                tone(1500 if channel == 1 else 2300, 216)
                tone(1900, 72)
            for x, value in enumerate(values):
                count = round((x + 1) * length / WIDTH) - round(x * length / WIDTH)
                tone(1500 + value[channel] * 800 / 255, count)
    pcm.extend(array('h', [0]) * RATE)
    return pcm


def write_wav(path, pcm):
    if sys.byteorder != 'little':
        pcm.byteswap()
    with path.open('xb') as handle, wave.open(handle, 'wb') as wav:
        wav.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        wav.writeframes(pcm.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='new directory for synthetic fixtures')
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=False)
    rows = card()
    (out / 'reference.ppm').write_bytes(f'P6\n{WIDTH} {HEIGHT}\n255\n'.encode() +
                                         bytes(v for row in rows for rgb in row for v in rgb))
    clean = robot36(rows)
    assert len(clean) == 38160 * (RATE // 1000)
    write_wav(out / 'robot36.wav', clean)
    tone = array('h', (round(8000 * sin(2 * pi * 6100 * i / RATE)) for i in range(RATE)))
    write_wav(out / 'alias6100.wav', tone)


if __name__ == '__main__':
    main()
