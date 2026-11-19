"""Robot 36 audio reference for the IC-705 project (mono PCM in, ordered RGB rows out)."""
from array import array
import argparse
from collections import deque
from math import acos, pi
from pathlib import Path
from statistics import median
import sys
import wave

from PIL import Image
from tools.make_sstv_fixtures import HEIGHT, WIDTH, robot36, write_wav


def frequencies(samples, rate):
    """Fit the sinusoidal three-sample recurrence across a short moving window."""
    a = b = 0
    count = max(3, round(rate * 0.0005))
    terms = deque([(0, 0)] * count)
    numerator = energy = 0
    for c in samples:
        old_num, old_energy = terms.popleft()
        num, power = b * (a+c), b*b
        terms.append((num, power))
        numerator += num - old_num
        energy += power - old_energy
        a, b = b, c
        if energy < count * 32**2:
            yield 0
        else:
            cosine = max(-1, min(1, numerator/(2*energy)))
            yield round(acos(cosine) * rate / (2*pi))


def valid_vis(history, rate):
    """The last sample belongs to the first 1500 Hz porch after stop + first sync."""
    def tone(start_ms, end_ms, expected):
        start = len(history) + round((start_ms-9)*rate/1000)
        end = len(history) + round((end_ms-9)*rate/1000)
        return start >= 0 and abs(median(history[start:end])-expected) < 55

    if not all(tone(a,b,f) for a,b,f in ((-890,-650,1900),(-608,-602,1200),(-570,-330,1900),
                                          (-295,-275,1200),(-55,-35,1100),(-26,-4,1200))):
        return False
    for bit in range(7):
        start = -270 + bit*30
        if not tone(start+6,start+24,1100 if 8 & (1<<bit) else 1300):
            return False
    return True


def component(values, count):
    # Sample at pixel centers. A chroma scan has half the horizontal resolution.
    return [max(0, min(255, (values[(2*i+1)*len(values)//(2*count)]-1500)*255/800))
            for i in range(count)]


def decode_rows(samples, rate):
    """Yield (first row index, two RGB888 rows) only after VIS 8 and alternating chroma."""
    if rate not in (8000, 48000):
        raise ValueError("expected 8 or 48 kHz PCM")

    def ms(duration):
        return round(rate * duration / 1000)

    scan_length = ms(141)
    line_period = ms(150)
    tolerance = ms(2)
    last_sync = 0
    recent = deque(maxlen=rate)
    sync = 0
    line = None
    line_index = None
    previous_y = cr = None
    for index, freq in enumerate(frequencies(samples, rate)):
        recent.append(freq)
        if line_index is not None and index-last_sync > line_period+tolerance:
            return
        # Complete the current scan even if the next line's sync is starting.
        if line is not None:
            line.append(freq)
            if len(line) == scan_length:
                sep = median(line[ms(92):ms(94)])
                expected = 1500 if line_index % 2 == 0 else 2300
                if abs(sep - expected) > 140:
                    return
                else:
                    luminance = component(line[ms(3):ms(91)], WIDTH)
                    chroma = component(line[ms(97):ms(141)], WIDTH//2)
                    if line_index % 2 == 0:
                        previous_y, cr = luminance, chroma
                    else:
                        rgb = bytearray()
                        for row in (previous_y, luminance):
                            for x, y in enumerate(row):
                                red, blue = cr[x//2]-127.5, chroma[x//2]-127.5
                                for v in (y+1.402*red, y-0.714136*red-0.344136*blue, y+1.772*blue):
                                    rgb.append(max(0,min(255,round(v))))
                        yield line_index-1, bytes(rgb)
                    line_index += 1
                    if line_index == HEIGHT:
                        return
                line = None
        if 1140 <= freq <= 1260:
            sync += 1
            continue
        if line_index is None and ms(35) <= sync <= ms(44) and valid_vis(list(recent), rate):
            line_index = 0
            line = [freq]
            last_sync = index
        elif (line_index is not None and line is None and ms(7) <= sync <= ms(11)
              and abs(index-last_sync-line_period) <= tolerance):
            line = [freq]
            last_sync = index
        sync = 0


def wav_pairs(path):
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise ValueError("expected mono 16-bit PCM")

        def samples():
            while block := wav.readframes(1024):
                values = array("h")
                values.frombytes(block)
                if sys.byteorder != "little":
                    values.byteswap()
                yield from values

        yield from decode_rows(samples(), wav.getframerate())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["encode", "decode"])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.operation == "encode":
        with Image.open(args.source) as image:
            if image.size != (WIDTH, HEIGHT):
                parser.error("Robot 36 input must be 320 by 240 pixels")
            pixels = list(image.convert("RGB").get_flattened_data())
        rows = [pixels[start:start+WIDTH] for start in range(0, len(pixels), WIDTH)]
        write_wav(args.output, robot36(rows))
    else:
        rgb = bytearray()
        for y, pair in wav_pairs(args.source):
            if len(rgb) != y*WIDTH*3:
                raise ValueError("line sequence interrupted")
            rgb.extend(pair)
        if len(rgb) != WIDTH*HEIGHT*3:
            raise ValueError(f"incomplete Robot 36 frame ({len(rgb)//(3*WIDTH)} rows)")
        with args.output.open("xb") as out:
            Image.frombytes("RGB", (WIDTH, HEIGHT), bytes(rgb)).save(out, format="PNG")


if __name__ == "__main__":
    main()

