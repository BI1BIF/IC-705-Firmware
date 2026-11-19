"""Build and exercise the standalone CW ARM decoder; never writes a firmware image."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import random
import struct
import subprocess
import wave

from tools.emulate_705 import call, machine, uc
from tools.make_cw_fixtures import TEXT, render
from tools.probe_705_rx_audio import LAYOUTS, replay_wav
from tools.render_705_display import load
from tools.replay_705_cw_display import REFERENCE, replay_display
from tools.score_arrl_cw import body, edit_distance


CODE, STATE, PCM = 0x20005000, 0x20010000, 0x20011000
STATE_BYTES = 88
SOURCE = Path(__file__).resolve().parents[1] / "samples" / "cw-arm.c"
BLOCK_BYTES = 160


def build(output, *, address=CODE, filter_trial=False):
    elf, raw = output / "cw-test.elf", output / "cw-test.bin"
    subprocess.run(["arm-none-eabi-gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Os",
                    "-mcpu=cortex-a9", "-marm", "-ffreestanding", "-nostdlib",
                    f"-Wl,-Ttext={address:#x},-e,cw_feed,--build-id=none", "-fstack-usage",
                    *(["-DCW_FILTER_TRIAL"] if filter_trial else []), str(SOURCE), "-o", str(elf)], check=True)
    symbols = subprocess.check_output(["arm-none-eabi-nm", str(elf)], text=True)
    entry = next(int(line.split()[0], 16) for line in symbols.splitlines() if line.endswith(" T cw_feed"))
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", str(elf), str(raw)], check=True)
    if filter_trial:
        filtered = next(int(line.split()[0], 16) for line in symbols.splitlines() if line.endswith(" T cw_filtered"))
        return raw.read_bytes(), entry, filtered
    return raw.read_bytes(), entry


def wav_bytes(path):
    with wave.open(str(path)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 8000):
            raise ValueError(f"{path}: expected 8 kHz mono signed 16-bit PCM")
        return wav.readframes(wav.getnframes())


def replay(code, entry, pcm):
    cpu = machine(code)
    guard = b"\xa5" * 16
    cpu.mem_write(STATE + STATE_BYTES, guard)
    # Count executed instructions in translated basic blocks; these are not hardware cycles.
    costs, peak, peak_start = {}, 0, 0
    current = 0

    def block(_cpu, address, length, _data):
        nonlocal current
        current += length // 4

    cpu.hook_add(uc.UC_HOOK_BLOCK, block)
    chunks = []
    for start in range(0, len(pcm), BLOCK_BYTES):
        current = 0
        cpu.mem_write(PCM, bytes(pcm[start:start+BLOCK_BYTES]).ljust(BLOCK_BYTES, b"\x00"))
        count = call(cpu, entry, STATE, PCM, instruction_limit=25000)
        if count > 16:
            raise ValueError("decoder output exceeds its bounded buffer")
        if count:
            chunks.append((start // BLOCK_BYTES * 10, bytes(cpu.mem_read(STATE + 72, count)).decode("ascii")))
        costs[current] = 1 + costs.get(current, 0)
        if current > peak:
            peak, peak_start = current, start // BLOCK_BYTES
    if cpu.mem_read(STATE + STATE_BYTES, 16) != guard:
        raise ValueError("decoder wrote beyond its state")
    dot, = struct.unpack("<I", cpu.mem_read(STATE, 4))
    dropped, = struct.unpack("<I", cpu.mem_read(STATE + 32, 4))
    return dict(text="".join(s for _, s in chunks), chunks=chunks,
                first_output_ms=chunks[0][0] if chunks else None,
                blocks=sum(costs.values()), max_instructions_per_block=peak, peak_block=peak_start,
                dot_ms=dot * 10, wpm=round(120 / dot, 2) if dot else None, dropped=dropped)


def run(dat, output, arrl_wav=None, arrl_reference=None):
    output.mkdir(parents=True)
    code, entry = build(output)
    cases = [(f"{wpm}wpm-{hz}hz-{snr}", render(TEXT, wpm, hz, snr), TEXT, wpm)
             for wpm, hz, snr in [(12, 500, None), (20, 600, None), (20, 600, 6), (28, 750, None)]]
    cases.append(("silence", bytes(16000), "", None))
    rng = random.Random(705)
    noise = struct.pack("<16000h", *(rng.randrange(-11000, 11001) for _ in range(16000)))
    cases.append(("noise-only", noise, "", None))
    raw_demo = output / "reference.wav"
    with wave.open(str(raw_demo), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(render(REFERENCE, 20, 600, None))
    main, font, graphics, main_hash, small = load(dat.read_bytes())
    staged = output / "j140-recorder.wav"
    audio_path = replay_wav(main, LAYOUTS["705J140"], raw_demo, staged)
    cases.append(("j140-recorder", wav_bytes(staged), REFERENCE, 20))
    report = {}
    for name, pcm, expected, declared in cases:
        result = replay(code, entry, pcm + bytes(8000))
        result.update(expected=expected, declared_wpm=declared, char_errors=edit_distance(expected, result["text"]))
        report[name] = result
    frames = []
    if report["j140-recorder"]["char_errors"] == 0:
        frames = replay_display(main, font, graphics, small, report["j140-recorder"]["text"], output)
    if arrl_wav is not None:
        ref = body(arrl_reference.read_text(encoding="utf-8-sig"))
        if not ref:
            raise ValueError("missing ARRL reference boundaries")
        trial = replay(code, entry, wav_bytes(arrl_wav) + bytes(8000))
        rendered = body(trial["text"])
        trial.update(reference_chars=len(ref), comparable=rendered is not None,
                     char_errors=edit_distance(ref, rendered) if rendered is not None else None,
                     wav_sha256=sha256(arrl_wav.read_bytes()).hexdigest())
        report["arrl-20wpm"] = trial
    evidence = dict(test_only=True, machine="Unicorn / Cortex-A9", code_bytes=len(code),
                    code_sha256=sha256(code).hexdigest(), decoder_state_bytes=STATE_BYTES,
                    input_bytes=BLOCK_BYTES, original_main_sha256=main_hash,
                    original_audio_path=audio_path, cases=report, stock_frames=frames)
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: val for key, val in sample.items() if key not in ("text", "chunks")}
                      for name, sample in report.items()}, indent=2))
    if any(item["dropped"] for item in report.values()) or any(
        report[name]["char_errors"] or abs((report[name]["wpm"] or 0) - report[name]["declared_wpm"]) > 3
        for name in ("12wpm-500hz-None", "20wpm-600hz-None", "28wpm-750hz-None", "j140-recorder")
    ) or report["20wpm-600hz-6"]["char_errors"] or report["silence"]["text"] or report["noise-only"]["text"]:
        raise SystemExit("CW ARM baseline failed; see evidence.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path, help="new evidence directory")
    parser.add_argument("--arrl-wav", type=Path)
    parser.add_argument("--arrl-reference", type=Path)
    args = parser.parse_args()
    if (args.arrl_wav is None) != (args.arrl_reference is None):
        parser.error("supply both ARRL inputs or omit both")
    run(args.dat, args.output, args.arrl_wav, args.arrl_reference)
