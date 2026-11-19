"""Score real 8 kHz mono PCM on the ARM decoder, using timed reference excerpts."""

import argparse
from difflib import SequenceMatcher
from hashlib import sha256
import json
from pathlib import Path

from tools.probe_705_cw_quality import CHARS, pcm_ms, replay, score
from tools.verify_705_cw_arm import SOURCE, STATE, build, wav_bytes


def read_windows(path, duration_ms):
    # Rows are [start_ms, end_ms, transcript]; empty transcript marks a no-CW control.
    windows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(windows, list) or not windows:
        raise ValueError("expected a list of scoring windows")
    last = 0
    for row in windows:
        if (not isinstance(row, list) or len(row) != 3 or type(row[0]) is not int or type(row[1]) is not int
                or not isinstance(row[2], str) or not last <= row[0] < row[1] <= duration_ms
                or (row[2] and not CHARS.sub("", row[2].upper()))):
            raise ValueError(f"invalid or overlapping scoring window: {row!r}")
        last = row[1]
    return windows


def measure(chunks, windows):
    rows = []
    for start, end, reference in windows:
        observed = "".join(text for at, text in chunks if start <= at < end)
        rows.append(dict(window_ms=[start, end], observed=observed, control=not reference,
                         **score(reference, observed, compact=True), **score_spaces(reference, observed)))
    spaces = {key: sum(row[key] for row in rows) for key in ("matched_boundaries", "extra_spaces", "missing_spaces")}
    return dict(reference_chars=sum(row["reference_chars"] for row in rows),
                edit_errors=sum(row["edit_errors"] for row in rows if not row["control"]),
                extra_chars_in_controls=sum(row["edit_errors"] for row in rows if row["control"]), windows=rows,
                **spaces)


def score_spaces(reference, observed):
    def split(text):
        chars, spaces = "", set()
        for token in text.upper().split():
            word = CHARS.sub("", token)
            if word:
                if chars:
                    spaces.add(len(chars))
                chars += word
        return chars, spaces

    expected, expected_spaces = split(reference)
    actual, actual_spaces = split(observed)
    matched = extra = missing = 0
    # A gap spanning a changed, inserted or missing character cannot be attributed to spacing.
    for base, heard, size in SequenceMatcher(None, expected, actual, autojunk=False).get_matching_blocks():
        for offset in range(1, size):
            want, got = base + offset in expected_spaces, heard + offset in actual_spaces
            extra += got and not want
            missing += want and not got
            matched += 1
    return dict(matched_boundaries=matched, extra_spaces=extra, missing_spaces=missing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("windows", type=Path, help='JSON rows: [start_ms, end_ms, "reference"]; "" means no CW')
    parser.add_argument("output", type=Path, help="new evidence directory")
    parser.add_argument("--pitch", required=True, type=int, help="measured pitch in Hz (300–1250)")
    parser.add_argument("--threshold", action="append", type=int, help="adaptive minimum in PCM units (default: 350)")
    args = parser.parse_args()
    thresholds = list(dict.fromkeys(args.threshold or [350]))
    if not 300 <= args.pitch <= 1250 or any(not 1 <= t <= 32767 for t in thresholds):
        parser.error("invalid pitch or threshold")
    pcm = wav_bytes(args.wav)
    windows = read_windows(args.windows, len(pcm) // 16)
    args.output.mkdir(parents=True)
    code, wide, fixed = build(args.output, filter_trial=True)
    results = {}
    for threshold in (None, *thresholds):
        setting = (STATE + 0x200, (threshold << 16) | 32768 | args.pitch) if threshold else ()
        chunks, speeds, dropped = replay(code, fixed if setting else wide, pcm + bytes(pcm_ms(1000)),
                                         *setting, extra_state=STATE + 0x200 + 336 if setting else None)
        mode = f"fix-{threshold}-adaptive" if threshold else "wide"
        results[mode] = dict(**measure(chunks, windows), outputs=chunks, speeds=speeds, dropped=dropped)
        row = results[mode]
        print(f'{mode}: {row["edit_errors"]}/{row["reference_chars"]} edits; '
              f'{row["extra_chars_in_controls"]} extra characters in control windows; '
              f'{row["extra_spaces"]} extra/{row["missing_spaces"]} missing spaces '
              f'across {row["matched_boundaries"]} matched boundaries; {dropped} dropped')
    report = dict(path="8 kHz PCM directly to emulated ARM; no stock DMA", pitch_hz=args.pitch,
                  wav_sha256=sha256(args.wav.read_bytes()).hexdigest(),
                  windows_sha256=sha256(args.windows.read_bytes()).hexdigest(),
                  source_sha256=sha256(SOURCE.read_bytes()).hexdigest(), code_sha256=sha256(code).hexdigest(),
                  modes=results)
    (args.output / "evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return int(any(row["dropped"] for row in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
