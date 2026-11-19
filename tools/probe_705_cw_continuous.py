"""Score a continuous recording through the offline J140 receive panel."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tools.emulate_705 import uc
from tools.probe_705_cw_offair import score_spaces
from tools.probe_705_cw_quality import CHARS, pcm_ms, score
from tools.probe_705_cw_session import (
    KEY_SPEED_RAW, SESSION_AUTO_DOT, SESSION_FED, SESSION_MARK, SESSION_TRACKED_HZ, TEST_STATE,
    build, seed_key_speed,
)
from tools.render_705_display import load
from tools.verify_705_cw_arm import wav_bytes
from tools.virtual_705_cw_panel import Panel


def read_segments(path, duration):
    # The whole interval is accounted for: text, verified background, or unlabelled.
    segments = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(segments, list) or not segments:
        raise ValueError("expected a nonempty segment list")
    previous = 0
    for row in segments:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError(f"invalid segment row: {row!r}")
        start, end, transcript, onset = row
        if (type(start) is not int or type(end) is not int or not previous == start < end <= duration
                or (transcript is not None and not isinstance(transcript, str))
                or (transcript and (not CHARS.sub("", transcript.upper()) or type(onset) is not int
                                    or not start <= onset < end))
                or (not transcript and onset is not None)):
            raise ValueError(f"invalid or discontinuous segment: {row!r}")
        previous = end
    return segments


def assess(events, segments):
    rows = []
    for start, end, reference, onset in segments:
        selected = [(at, ch) for at, ch in events if start <= at < end]
        observed = "".join(ch for _, ch in selected)
        row = dict(window_ms=[start, end], observed=observed, reference=reference,
                   emitted_symbols=sum(not ch.isspace() for _, ch in selected))
        if reference:
            initial = CHARS.sub("", reference.upper())[0]
            # Early or wrong output is a failure; don't search ahead for the right letter.
            first = next(((at, ch) for at, ch in selected if not CHARS.fullmatch(ch)), None)
            delay = first[0]-onset if first else None
            correct = first is not None and delay >= 0 and first[1] == initial
            row.update(**score(reference, observed, compact=True), **score_spaces(reference, observed),
                       first_mark_ms=onset, first_scored_output=first,
                       first_output_delay_ms=delay, first_char_correct=correct,
                       correct_initial_delay_ms=delay if correct else None)
        rows.append(row)
    return dict(reference_chars=sum(row.get("reference_chars", 0) for row in rows),
                edit_errors=sum(row.get("edit_errors", 0) for row in rows),
                extra_spaces=sum(row.get("extra_spaces", 0) for row in rows),
                missing_spaces=sum(row.get("missing_spaces", 0) for row in rows),
                background_ms=sum(end-start for start, end, ref, _ in segments if ref == ""),
                background_symbols=sum(row["emitted_symbols"] for row in rows if row["reference"] == ""),
                unlabelled_ms=sum(end-start for start, end, ref, _ in segments if ref is None),
                unlabelled_symbols=sum(row["emitted_symbols"] for row in rows if row["reference"] is None),
                segments=rows)


def run_panel(images, program, pcm, mode, pitch, threshold, screenshot, *, key_speed_raw=None,
              trace_demod=False):
    panel = Panel(images, program)
    if key_speed_raw is not None:
        seed_key_speed(panel.guest.cpu, key_speed_raw)
    home = panel.display().tobytes()
    panel.press_menu()
    panel.click(80, 247)
    if mode != "WIDE":
        select = [(50, 227)] if mode == "AUTO" else [(138, 227), (387 + ((pitch-300)*86+475)//950, 205)]
        for x, y in [(48, 253), (336, 253), (138, 253), *select, (50, 253)]:
            panel.click(x, y)
        for _ in range((threshold-350)//250):
            panel.click(235, 227)
        panel.click(336, 253)
        panel.click(48, 253)
    if key_speed_raw is not None:
        panel.click(430, 158)
        panel.click(235, 227)  # SPEED → MANUAL
    state = panel.lab.view()
    if (state["active"], state["filter_mode"], state["fixed_hz"], state["threshold"], state["manual_threshold"]) != (
            1, mode, pitch if mode == "FIX" else 0, threshold if mode != "WIDE" else 350, False):
        raise ValueError(f"could not configure {mode}: {state}")
    speed_mode, speed_wpm = state["speed_mode"], state["speed_wpm"]
    if key_speed_raw is not None and (speed_mode != "MANUAL" or not speed_wpm):
        raise ValueError("could not select the guest's manual key speed")

    events, speed_changes, length, text = [], [], TEST_STATE+20, TEST_STATE+344

    def audio_time():
        return round(panel.lab.blocks * 0.75, 2)

    def append(cpu, _access, address, size, value, _data):
        # A full buffer shifts indices 0–126; only its final slot is a new char.
        count = int.from_bytes(cpu.mem_read(length, 4), "little")
        if size == 1 and address == text + count - 1:
            events.append((audio_time(), chr(value)))

    def note_speed(_cpu, _access, _address, size, value, _data):
        if size == 4 and (not speed_changes or speed_changes[-1][1] != value):
            speed_changes.append((audio_time(), value))

    handle = panel.lab.cpu.hook_add(uc.UC_HOOK_MEM_WRITE, append, begin=text, end=text+127)
    speed_handle = panel.lab.cpu.hook_add(uc.UC_HOOK_MEM_WRITE, note_speed,
                                          begin=SESSION_AUTO_DOT, end=SESSION_AUTO_DOT+3)
    demod_changes = []
    first_block = state["fed"]

    def note_demod(cpu, _access, _address, size, count, _data):
        # The worker commits a 10 ms audio block after updating the detector and the selected pitch.
        if size == 4 and count > first_block:
            mark = int.from_bytes(cpu.mem_read(SESSION_MARK, 4), "little")
            hz = int.from_bytes(cpu.mem_read(SESSION_TRACKED_HZ, 4), "little") if mode == "AUTO" else (
                pitch if mode == "FIX" else 0)
            if not demod_changes or demod_changes[-1][1:] != [hz, mark]:
                demod_changes.append([(count - first_block) * 10, hz, mark])

    demod_handle = panel.lab.cpu.hook_add(uc.UC_HOOK_MEM_WRITE, note_demod,
                                         begin=SESSION_FED, end=SESSION_FED+3) if trace_demod else None
    state = panel.lab.feed(pcm + bytes(-len(pcm) % 12))
    panel.lab.cpu.hook_del(handle)
    panel.lab.cpu.hook_del(speed_handle)
    if demod_handle is not None:
        panel.lab.cpu.hook_del(demod_handle)
    if state["queued"] or state["drops"] or state["text"] != "".join(ch for _, ch in events)[-128:]:
        raise ValueError("DMA or transcript trace disagreed with session state")
    if key_speed_raw is not None and (panel.guest.cpu.mem_read(KEY_SPEED_RAW, 1) != bytes((key_speed_raw,))
                                      or state["speed_wpm"] != speed_wpm):
        raise ValueError("fixture key speed changed during receive")
    panel.display().save(screenshot)
    panel.exit()
    if panel.active or panel.display().tobytes() != home:
        raise ValueError("EXIT did not restore HOME")
    data = dict(dma_groups=panel.lab.blocks, tracked_hz=state["tracked_hz"], exit_restored_home=True,
                speed_mode=speed_mode, final_wpm=state["speed_wpm"], auto_dot_ticks=speed_changes)
    if trace_demod:
        data["demod_changes_ms_hz_mark"] = demod_changes
    return events, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("wav", type=Path)
    parser.add_argument("segments", type=Path, help='[start_ms, end_ms, transcript/null, first_mark_ms/null] rows')
    parser.add_argument("output", type=Path)
    parser.add_argument("--modes", nargs="+", choices=("AUTO", "FIX", "WIDE"), default=["AUTO", "FIX"])
    parser.add_argument("--pitch", type=int, required=True, help="fixed-frequency comparison, multiples of 10 Hz")
    parser.add_argument("--threshold", type=int, default=350, help="350 to 9850 in 250-unit increments")
    parser.add_argument("--key-speed-raw", type=int, help="seed only the guest keyer speed (0–255) and select MANUAL")
    parser.add_argument("--trace-demod", action="store_true", help="log changes in selected pitch and key state")
    args = parser.parse_args()
    if not 300 <= args.pitch <= 1250 or args.pitch % 10 or not 350 <= args.threshold <= 9850 or (args.threshold-350)%250:
        parser.error("invalid pitch or threshold")
    if args.key_speed_raw is not None and not 0 <= args.key_speed_raw <= 255:
        parser.error("invalid guest key speed")
    audio, dat = wav_bytes(args.wav), args.dat.read_bytes()
    segments = read_segments(args.segments, len(audio)//16)
    end = segments[-1][1]
    # Emulation pauses at exactly the declared endpoint; it does not infer silence beyond the recording.
    args.output.mkdir(parents=True)
    images, program = load(dat), build(args.output)
    report = dict(stock_dat_sha256=sha256(dat).hexdigest(), wav_sha256=sha256(args.wav.read_bytes()).hexdigest(),
                  segments_sha256=sha256(args.segments.read_bytes()).hexdigest(), code_sha256=sha256(program[0]).hexdigest(),
                  interval_ms=[0, end], threshold=args.threshold, fixed_hz=args.pitch,
                  key_speed_raw=args.key_speed_raw, modes={})
    for mode in dict.fromkeys(args.modes):
        events, data = run_panel(images, program, audio[:pcm_ms(end)], mode, args.pitch, args.threshold,
                                 args.output / f"{mode.lower()}-last.png", key_speed_raw=args.key_speed_raw,
                                 trace_demod=args.trace_demod)
        row = report["modes"][mode] = dict(**data, **assess(events, segments), events=events)
        print(f"{mode}: {row['edit_errors']}/{row['reference_chars']} edits, "
              f"{row['background_symbols']} background symbols, {row['unlabelled_ms']} ms unlabelled", flush=True)
    if args.dat.read_bytes() != dat:
        raise ValueError("official DAT changed during replay")
    (args.output / "evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
