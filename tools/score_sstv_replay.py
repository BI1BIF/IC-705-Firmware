"""Compare QSSTV Robot 36 output against the generated card (requires Pillow)."""

import argparse
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixtures', type=Path, help='directory containing reference.ppm and qsstv/*.png')
    path = parser.parse_args().fixtures

    def pixels(file):
        with Image.open(file) as image:
            if image.size != (320, 240):
                raise ValueError(f'{file}: unexpected image size {image.size}')
            return image.convert('RGB').tobytes()

    ref = pixels(path / 'reference.ppm')
    base = pixels(path / 'qsstv/robot36_1_R36.png')
    centers = [i for i in range(len(ref)) if 8 <= (i // 3) // 320 < 232 and 9 <= (i // 3) % 40 < 31]
    print('image\tRGB MAE\tbar center MAE\tMAE vs direct')
    for path in sorted((path / 'qsstv').glob('*_1_R36.png')):
        out = pixels(path)
        err = [abs(x-y) for x, y in zip(out, ref)]
        direct = sum(abs(x-y) for x, y in zip(out, base)) / len(out)
        print(f'{path.name}\t{sum(err)/len(err):.3f}\t{sum(err[i] for i in centers)/len(centers):.3f}\t{direct:.3f}')


if __name__ == '__main__':
    main()
