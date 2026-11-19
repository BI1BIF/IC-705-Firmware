"""Compare the original broad detector and a fixed-pitch ARM trial on the same PCM."""

import argparse
from hashlib import sha256
import json
from math import cos, sin, tau
from pathlib import Path
from random import Random
from struct import iter_unpack, pack

from tools.make_cw_fixtures import RATE, render, spans
from tools.probe_705_cw_quality import manual, replay, score
from tools.score_arrl_cw import body
from tools.verify_705_cw_arm import STATE, SOURCE, build, wav_bytes


def samples(pcm):
    return [x for x, in iter_unpack("<h", pcm)]


def mix(target, neighbor=(), *, neighbor_gain=1, noise=0):
    rng = Random(705)
    size = max(len(target), len(neighbor))
    t = list(target) + [0]*(size-len(target))
    n = list(neighbor) + [0]*(size-len(neighbor))
    result = [max(-32768, min(32767, round(x+y*neighbor_gain+rng.gauss(0, noise))))
              for x, y in zip(t, n, strict=True)]
    if not all(-32768 < v < 32767 for v in result):
        raise ValueError("fixture clipped")
    return pack(f"<{size}h", *result) + bytes(RATE)


def dominant_hz(audio):
    # Use the strongest 40 ms block from the first 30 seconds to avoid measuring silence.
    data = samples(audio[:60*RATE])
    width = 320
    block = max((data[i:i+width] for i in range(0, len(data)-width+1, width)),
                key=lambda b: sum(x*x for x in b))
    return max(range(300, 1251, 10), key=lambda hz: (
        sum(x*cos(tau*i*hz/RATE) for i, x in enumerate(block))**2 +
        sum(x*sin(tau*i*hz/RATE) for i, x in enumerate(block))**2))


def adjacent_fixture(offset=100):
    text = "CQ TEST 123 DE IC705"
    target = samples(render(text, 20, 600, None))
    neighbor = samples(render("W9XYZ NR 51 CQ DE K8JZZ", 22, 600+offset, None))
    return mix(target, neighbor, neighbor_gain=1.75), text


def tracking_fixture():
    """Two separable main stations, each heard over noise and a weaker caller."""
    for hz, text, interfering_hz in ((600, "CQ TEST", 800), (900, "DE IC705", 700)):
        signal = samples(render(text, 20, hz, None))
        other = samples(render("T T T T", 20, interfering_hz, None))
        yield hz, text, mix(signal, other, neighbor_gain=0.35, noise=190)


def drifting_fixture():
    """One continuous message from a station whose tone changes without a retune gap."""
    text = "CQ TEST DE IC705 CQ TEST DE IC705"
    spans_ms = list(spans(text))
    unit = 60 * RATE // 1000
    size = sum(n * unit for _, n in spans_ms)
    start_hz, end_hz = 600, 800
    delta = (end_hz - start_hz) / size
    signal = [0] * (RATE // 4)
    at = 0
    for mark, n in spans_ms:
        length = n * unit
        for i in range(length):
            t = at + i
            phase = tau * t * (start_hz + delta * t / 2) / RATE
            ramp = min(1, i / 32, (length - 1 - i) / 32)
            signal.append(round(4200 * ramp * sin(phase)) if mark else 0)
        at += length
    signal += [0] * (RATE // 2)
    return mix(signal, noise=190), text, start_hz, end_hz


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arrl-wav", type=Path)
    parser.add_argument("--arrl-reference", type=Path)
    parser.add_argument("--handkey-wav", type=Path, help="NW6V Vail hand-key recording, 8 kHz mono PCM")
    parser.add_argument("--handkey-reference", type=Path, help="reference for the NW6V 15,000–151,300 ms window")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if bool(args.arrl_wav) != bool(args.arrl_reference):
        parser.error("supply both ARRL inputs")
    if bool(args.handkey_wav) != bool(args.handkey_reference):
        parser.error("supply both hand-key inputs")
    args.output.mkdir(parents=True, exist_ok=True)
    code, broad, fixed = build(args.output, filter_trial=True)
    expected = "CQ TEST 123 DE IC705"
    target = samples(render(expected, 20, 600, None))
    weak = [round(x*0.065) for x in target]
    interferer = "W9XYZ NR 51 CQ DE K8JZZ"
    neighbor = samples(render(interferer, 22, 800, None))
    channel = samples(render(interferer, 22, 600, None))
    cases = {
        "clean": (mix(target), expected, 600),
        "strong-neighbor-200hz": (*adjacent_fixture(200), 600),
        "strong-neighbor-100hz": (*adjacent_fixture(), 600),
        "cochannel-control": (mix(target, channel, neighbor_gain=1.5), expected, 600),
        "neighbor-only-200hz": (mix([], neighbor, neighbor_gain=1.75), "", 600),
        "weak-and-noise": (mix(weak, noise=220), expected, 600),
        "noise-only": (mix([0]*len(target), noise=850), "", 600),
        "different-pitch-and-speed": (mix(samples(render(expected, 28, 750, None))), expected, 750),
    }
    arrl_hashes = None
    if args.arrl_wav:
        recording = wav_bytes(args.arrl_wav)
        reference = body(args.arrl_reference.read_text(encoding="utf-8-sig"))
        if not reference:
            parser.error("ARRL reference passage markers missing")
        cases["arrl-20wpm"] = (recording + bytes(RATE), reference, dominant_hz(recording))
        arrl_hashes = dict(wav=sha256(args.arrl_wav.read_bytes()).hexdigest(),
                           reference=sha256(args.arrl_reference.read_bytes()).hexdigest())
    results = {}
    for name, (pcm, ref, pitch) in cases.items():
        rows = {}
        settings = [("broad", broad, ())] + [
            (f"fix-{threshold}", fixed, (STATE+0x200, (threshold<<16)|pitch))
            for threshold in ((350, 1100) if name != "arrl-20wpm" else (350,))
        ]
        settings.append(("fix-adaptive", fixed, (STATE+0x200, (350<<16)|32768|pitch)))
        for label, entry, feed_args in settings:
            chunks, estimates, dropped = replay(code, entry, pcm, *feed_args,
                                                 extra_state=STATE+0x200+336 if feed_args else None)
            observed = "".join(text for _, text in chunks)
            passage = body(observed) if name == "arrl-20wpm" else None
            count = score(ref, (passage or "") if name == "arrl-20wpm" else observed,
                          compact=name != "arrl-20wpm")
            rows[label] = dict(score=count, dropped=dropped, first_ms=chunks[0][0] if chunks else None,
                               last_wpm=estimates[-1][1] if estimates else None,
                               observed=None if name == "arrl-20wpm" else observed,
                               passage_found=bool(passage) if name == "arrl-20wpm" else None,
                               diagnostic_edges=[observed[:100], observed[-100:]] if name == "arrl-20wpm" else None)
        results[name] = dict(pcm_sha256=sha256(pcm).hexdigest(), fixed_center_hz=pitch, results=rows)
        print(name, {label: row["score"]["edit_errors"] if row["passage_found"] is not False else "no comparable passage"
                     for label, row in rows.items()}, flush=True)
    required = ("clean", "strong-neighbor-200hz", "strong-neighbor-100hz", "neighbor-only-200hz", "weak-and-noise",
                "noise-only", "different-pitch-and-speed")
    passed = all(not results[key]["results"]["fix-adaptive"]["score"]["edit_errors"] for key in required)
    passed &= all(not row["dropped"] for case in results.values() for row in case["results"].values())
    if arrl_hashes:
        passed &= not results["arrl-20wpm"]["results"]["fix-adaptive"]["score"]["edit_errors"]
    handkey = None
    if args.handkey_wav:
        pitch = dominant_hz(wav_bytes(args.handkey_wav))
        start = [("broad", broad, ())]
        for threshold in (350, 1100, 1600, 2200):
            start.extend((label, fixed, (STATE+0x200, (threshold<<16)|mode|pitch))
                         for label, mode in ((f"fix-{threshold}", 0), (f"adaptive-{threshold}", 32768)))
        handkey = dict(fixed_center_hz=pitch, **{
            name: manual(code, entry, args.handkey_wav, args.handkey_reference, (15000, 151300), 14500, 15120,
                         *feed_args, extra_state=STATE+0x200+336 if feed_args else None)
            for name, entry, feed_args in start
        })
        print("handkey", {label: handkey[label]["score"]["edit_errors"] for label, _, _ in start})
        passed &= (handkey["adaptive-1100"]["score"]["edit_errors"] <= handkey["broad"]["score"]["edit_errors"]
                   and not any(handkey[label]["dropped_output_counter"] for label, _, _ in start))
    (args.output / "evidence.json").write_text(json.dumps(dict(
        test_only=True, source_sha256=sha256(SOURCE.read_bytes()).hexdigest(),
        code_sha256=sha256(code).hexdigest(), arrl_files_sha256=arrl_hashes,
        required_cases=required, passed=passed, cases=results, exploratory_handkey=handkey), indent=2)+"\n",
        encoding="utf-8")
    return int(args.check and not passed)


if __name__ == "__main__":
    raise SystemExit(main())
