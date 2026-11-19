"""Measure direct ARM CW quality offline, with optional annotated 8 kHz mono WAV."""

import argparse
from hashlib import sha256
import json
from math import sin, tau
from pathlib import Path
import re
import struct

from tools.emulate_705 import call, machine
from tools.make_cw_fixtures import PAD_FRAMES, RATE, render
from tools.score_arrl_cw import edit_distance
from tools.verify_705_cw_arm import BLOCK_BYTES, PCM, SOURCE, STATE, STATE_BYTES, build, wav_bytes


WORDS = ("CQ DE TEST", "CW MODE TEST", "73 DE TEST")
OTHER_WORDS = ("W9XYZ DE N0ABC", "RIG CW TEST", "TU AND 73")
CHARS = re.compile(r"[^A-Z0-9~]")


def replay(code, entry, audio, *feed_args, extra_state=None):
    cpu = machine(code)
    guard = b"\xa5" * 16
    cpu.mem_write(STATE + STATE_BYTES, guard)
    if extra_state is not None:
        cpu.mem_write(extra_state, guard)
    chunks, changes = [], []
    previous = None
    for start in range(0, len(audio), BLOCK_BYTES):
        at = (start // BLOCK_BYTES + 1) * 10
        cpu.mem_write(PCM, bytes(audio[start:start + BLOCK_BYTES]).ljust(BLOCK_BYTES, b"\0"))
        n = call(cpu, entry, STATE, PCM, *feed_args, instruction_limit=25_000, timeout_us=0)
        if not 0 <= n <= 16:
            raise ValueError(f"invalid decoder output size: {n}")
        if n:
            chunks.append((at, bytes(cpu.mem_read(STATE + 72, n)).decode("ascii")))
        dot, = struct.unpack("<I", cpu.mem_read(STATE, 4))
        if dot != previous:
            changes.append((at, round(120 / dot, 2) if dot else None))
            previous = dot
    if cpu.mem_read(STATE + STATE_BYTES, 16) != guard:
        raise ValueError("decoder wrote beyond its state")
    if extra_state is not None and cpu.mem_read(extra_state, len(guard)) != guard:
        raise ValueError("filter wrote beyond its state")
    dropped, = struct.unpack("<I", cpu.mem_read(STATE + 32, 4))
    return chunks, changes, dropped


def score(expected, observed, *, compact=False):
    if compact:
        expected, observed = (CHARS.sub("", s.upper()) for s in (expected, observed))
    return dict(reference_chars=len(expected), observed_chars=len(observed),
                edit_errors=edit_distance(expected, observed))


def pcm_ms(ms):
    return round(ms * RATE / 1000) * 2


def synthetic(code, entry, rates, words):
    audio = bytearray(PAD_FRAMES * 2)
    segments = []
    for i, (rate, text) in enumerate(zip(rates, words, strict=True)):
        first = len(audio) * 500 / RATE
        audio.extend(render(text, rate, 600, None)[PAD_FRAMES * 2:-PAD_FRAMES * 2])
        last = len(audio) * 500 / RATE
        segments.append(dict(start_ms=first, end_last_mark_ms=last, true_wpm=rate))
        # Word gap at the preceding speed, and exactly one continuous decoder instance.
        audio.extend(bytes(pcm_ms(600 if i == len(rates) - 1 else 7 * 1200 / rate)))
    chunks, changes, dropped = replay(code, entry, audio)
    expected = " ".join(words)
    observed = "".join(text for _, text in chunks)
    for i, item in enumerate(segments):
        end = segments[i + 1]["start_ms"] if i + 1 < len(segments) else len(audio) * 500 / RATE + 10
        output = [(at, text) for at, text in chunks if item["start_ms"] <= at < end]
        estimate = next((wpm for at, wpm in reversed(changes) if at < end), None)
        item.update(first_output_delay_ms=round(output[0][0] - item["start_ms"], 2) if output else None,
                    observed_at_last_mark_wpm=next((wpm for at, wpm in reversed(changes)
                                                  if at <= item["end_last_mark_ms"] + 10), None),
                    observed_wpm_by_segment_end=estimate,
                    within_3_wpm=estimate is not None and abs(estimate - item["true_wpm"]) <= 3)
    errors = score(expected, observed)
    return dict(expected=expected, observed=observed, score=errors,
                alphanumeric_score=score(expected, observed, compact=True),
                passed=not errors["edit_errors"] and not dropped and all(s["within_3_wpm"] for s in segments),
                pcm_sha256=sha256(audio).hexdigest(), segments=segments, estimates=changes, outputs=chunks,
                dropped_output_counter=dropped)


def tight_letters(code, entry):
    """A 24 WPM sender leaves 90 ms between some letters instead of 150 ms."""
    pad = PAD_FRAMES * 2

    def body(text):
        return render(text, 24, 600, None)[pad:-pad]

    audio = bytearray(pad) + body("CQ DE TEST") + bytes(pcm_ms(350))
    for pair in ("TH", "AS", "TI", "OR"):
        audio.extend(body(pair[0]) + bytes(pcm_ms(90)) + body(pair[1]) + bytes(pcm_ms(350)))
    audio.extend(bytes(pcm_ms(250)))
    chunks, changes, dropped = replay(code, entry, audio)
    expected = "CQ DE TEST TH AS TI OR"
    observed = "".join(text for _, text in chunks)
    errors = score(expected, observed)
    return dict(expected=expected, observed=observed, score=errors, passed=not errors["edit_errors"] and not dropped,
                pcm_sha256=sha256(audio).hexdigest(), estimates=changes, outputs=chunks, dropped_output_counter=dropped)


def wide_letter_gaps(code, entry):
    """Normal 20 WPM marks, with training-style pauses between letters and words."""
    pad = 2 * PAD_FRAMES
    warmup, words = ("TEST", "DE", "IC705"), ("RADIO", "MORSE")
    audio = render("CQ", 20, 600, None)[:-pad]
    for index, word in enumerate(warmup + words):
        audio.extend(bytes(pcm_ms(2600)))
        if index == len(warmup):
            score_from_ms = len(audio) * 500 / RATE
        for i, ch in enumerate(word):
            if i:
                audio.extend(bytes(pcm_ms(1400)))
            audio.extend(render(ch, 20, 600, None)[pad:-pad])
    audio.extend(bytes(pcm_ms(600)))
    chunks, estimates, dropped = replay(code, entry, audio)
    expected = "CQ " + " ".join(warmup + words)
    observed = "".join(text for _, text in chunks)
    # Give the decoder the first three words to learn this cadence, then require both kinds of gaps.
    suffix = " " + " ".join(words)
    scored = "".join(text for at, text in chunks if at >= score_from_ms)
    errors = score(suffix, scored)
    passed = not errors["edit_errors"] and not score(expected, observed, compact=True)["edit_errors"]
    return dict(expected=expected, observed=observed, scored_expected=suffix, scored_observed=scored,
                score=errors, passed=passed and not dropped,
                pcm_sha256=sha256(audio).hexdigest(), estimates=estimates, outputs=chunks, dropped_output_counter=dropped)


def recover_after_short_pause(code, entry):
    """A pause shorter than a slow word gap precedes a faster sender."""
    pad = 2 * PAD_FRAMES
    head, tail = "CQ DE TEST", "THE QUICK BROWN FOX"
    audio = render(head, 12, 710, None)[:-pad] + bytes(pcm_ms(310))
    audio += render(tail, 24, 710, None)[pad:] + bytes(pcm_ms(600))
    chunks, estimates, dropped = replay(code, entry, audio)
    observed = "".join(text for _, text in chunks)
    expected = f"{head} {tail}"
    # The first fast word can still be damaged; recovery must preserve what follows.
    passed = bool(estimates and observed.startswith(head) and observed.endswith(" BROWN FOX")
                  and estimates[-1][1] == 24)
    return dict(expected=expected, observed=observed, score=score(expected, observed, compact=True),
                passed=passed and not dropped, estimates=estimates, outputs=chunks, dropped_output_counter=dropped)


def similar_dots_after_pause(code, entry):
    """Four unequal hand-key dots should not train the decoder to read a C."""
    audio = render("CQ", 20, 600, None)[:-2*PAD_FRAMES] + bytes(pcm_ms(400))
    for on, ms in ((True, 100), (False, 10), (True, 60), (False, 20),
                   (True, 90), (False, 20), (True, 60), (False, 600)):
        count = pcm_ms(ms)//2
        audio.extend(struct.pack(f"<{count}h", *(round(14000*sin(tau*600*i/RATE)) if on else 0
                                                 for i in range(count))))
    chunks, estimates, dropped = replay(code, entry, audio)
    expected = "CQ H"
    observed = "".join(text for _, text in chunks)
    errors = score(expected, observed)
    passed = not errors["edit_errors"] and 15 <= estimates[-1][1] <= 23 and not dropped
    return dict(expected=expected, observed=observed, score=errors, passed=passed,
                pcm_sha256=sha256(audio).hexdigest(), estimates=estimates, outputs=chunks,
                dropped_output_counter=dropped)


def manual(code, entry, wav, ref, window, lead_in, first_mark, *feed_args, extra_state=None):
    low, high = window
    audio = wav_bytes(wav)
    if not 0 <= lead_in <= low < high <= len(audio) * 500 / RATE:
        raise ValueError("manual scoring window or replay start lies outside WAV")
    if first_mark is not None and not low <= first_mark < high:
        raise ValueError("manual first mark must be inside the scoring window")
    expected = ref.read_text(encoding="utf-8-sig")
    if not score(expected, "", compact=True)["reference_chars"]:
        raise ValueError("manual body reference is empty")
    chunks, changes, dropped = replay(code, entry, audio[pcm_ms(lead_in):], *feed_args, extra_state=extra_state)
    outputs = [(at + lead_in, text) for at, text in chunks if low <= at + lead_in < high]
    observed = "".join(text for _, text in outputs)
    errors = score(expected, observed, compact=True)
    return dict(wav_sha256=sha256(wav.read_bytes()).hexdigest(), reference_sha256=sha256(ref.read_bytes()).hexdigest(),
                replay_start_ms=lead_in, score_window_ms=window, first_mark_ms=first_mark,
                first_output_at_ms=outputs[0][0] if outputs else None,
                first_output_delay_ms=outputs[0][0] - first_mark if outputs and first_mark is not None else None,
                score=errors, passed=not errors["edit_errors"] and not dropped, observed=observed,
                estimates=[(at + lead_in, wpm) for at, wpm in changes], outputs=outputs, dropped_output_counter=dropped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new local evidence directory")
    parser.add_argument("--manual-wav", type=Path)
    parser.add_argument("--manual-reference", type=Path, help="UTF-8 reference text for the scoring window")
    parser.add_argument("--manual-window-ms", nargs=2, type=int, metavar=("START", "END"))
    parser.add_argument("--manual-replay-start-ms", type=int, default=0, help="start before scoring to include lead-in")
    parser.add_argument("--manual-first-mark-ms", type=int, help="optional premarked onset in original WAV")
    parser.add_argument("--check", action="store_true", help="exit 1 when any measured quality criterion fails")
    args = parser.parse_args()
    manual_inputs = (args.manual_wav, args.manual_reference, args.manual_window_ms)
    if any(manual_inputs) != all(manual_inputs) or (not all(manual_inputs) and
            (args.manual_replay_start_ms or args.manual_first_mark_ms is not None)):
        parser.error("supply --manual-wav, --manual-reference and --manual-window-ms together")

    args.output.mkdir(parents=True)
    code, entry = build(args.output)
    cases = {}
    for rates in ((12, 12, 12), (20, 20, 20), (28, 28, 28), (12, 28, 12), (28, 12, 28), (20, 24, 16)):
        cases["wpm-" + "-".join(map(str, rates))] = synthetic(code, entry, rates, WORDS)
    cases["wpm-18-30-15-other-text"] = synthetic(code, entry, (18, 30, 15), OTHER_WORDS)
    cases["tight-letter-gaps-24wpm"] = tight_letters(code, entry)
    cases["wide-letter-gaps-20wpm"] = wide_letter_gaps(code, entry)
    cases["recover-12-24-after-310ms"] = recover_after_short_pause(code, entry)
    cases["similar-dots-after-pause"] = similar_dots_after_pause(code, entry)
    for text in ("E", "T", "5", "0", "CQ"):
        cases["first-" + text] = synthetic(code, entry, (20,), (text,))
    for rate in (15, 25):
        for text in ("0", "5"):
            cases[f"first-{text}-{rate}wpm"] = synthetic(code, entry, (rate,), (text,))
    cases["first-5-same-mark-length-as-20wpm-0"] = synthetic(code, entry, (20 / 3,), ("5",))
    dash, dot = (render(text, rate, 600, None) for text, rate in (("T", 20), ("E", 20 / 3)))
    if dash != dot:
        raise ValueError("one-tone ambiguity fixture no longer has identical PCM")
    if args.manual_wav:
        cases["manual"] = manual(code, entry, *manual_inputs, args.manual_replay_start_ms, args.manual_first_mark_ms)

    quality = all(case["passed"] for case in cases.values())
    evidence = dict(test_only=True, path="8 kHz PCM directly to cw_feed on emulated Cortex-A9; no stock DMA or RTX",
                    source_sha256=sha256(SOURCE.read_bytes()).hexdigest(), code_sha256=sha256(code).hexdigest(),
                    quality_passed=quality, cases=cases,
                    single_tone_ambiguity=dict(same_pcm_for=["T at 20 WPM", "E at 20/3 WPM"],
                                               pcm_sha256=sha256(dash).hexdigest()))
    output = args.output / "evidence.json"
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    for name, case in cases.items():
        row = case["score"]
        print(f"{name}: {'PASS' if case['passed'] else 'FAIL'}; {row['edit_errors']}/{row['reference_chars']} edits")
    print(f"Accuracy criteria {'passed' if quality else 'failed'}; see {output}")
    return int(args.check and not quality)


if __name__ == "__main__":
    raise SystemExit(main())
