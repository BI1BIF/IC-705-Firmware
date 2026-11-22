"""Run the 48 kHz RX-only ARM modem in the J140 audio task and compare exact AX.25 octets."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from struct import pack, unpack
from subprocess import check_output, run

from tools.emulate_705 import uc
from tools.probe_705_sstv_picture import branch
from tools.replay_705_aprs_fm import (AUDIO_GATE, FRAMES, GUARD, RAW_TAP, ax25_burst, capture,
                                     command, original_fm, read_wav, require, write_wav, RATE)
from tools.render_705_display import DAT_HASH, load


BASE = 0x21000000  # emulator-only mapped pages
FRAME_STRIDE, FRAME_MAX, OUT_SLOTS = 340, 330, 4
ORIGINAL_INSTRUCTION = b"\x04\x00\x9d\xe5"
SOURCES = ("samples/aprs-j140-rx.s", "samples/aprs-rx-arm.c")


def build_target(output, stem, sources, address, entry, *, float_abi="soft", includes=(), flags=()):
    elf, raw = output / f"{stem}.elf", output / f"{stem}.bin"
    run(["arm-none-eabi-gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O3",
         "-mcpu=cortex-a9", "-marm", f"-mfloat-abi={float_abi}", "-ffreestanding", "-nostdlib",
         "-fno-tree-loop-distribute-patterns", "-fstack-usage",
         f"-Wl,-Ttext={address:#x},-e,{entry},--build-id=none",
         *(f"-I{directory}" for directory in includes), *flags, *sources, "-lgcc", "-o", elf], check=True)
    lines = check_output(["arm-none-eabi-nm", "-n", elf], text=True).splitlines()
    symbols = {name: int(value, 16) for value, _, name in (line.split() for line in lines if len(line.split()) == 3)}
    run(["arm-none-eabi-objcopy", "-O", "binary", elf, raw], check=True)
    return raw.read_bytes(), symbols


def build(output):
    return build_target(output, "aprs-rx", SOURCES, BASE, "aprs_j140_rx")


def dire_wolf(atest, fixture, wav, output):
    log = command(atest, fixture, "-B", "1200", "-F", "0", "-h", wav)
    (output / f"{wav}.direwolf.txt").write_text(log, encoding="utf-8")
    raw = []
    for line in log.splitlines():
        if line.startswith("[0] "):
            raw.append(dict(text=line[4:], octets=""))
        match = re.match(r"^\s+[0-9a-f]{3}:  ((?:[0-9a-f]{2} ){1,16})", line)
        if match:
            raw[-1]["octets"] += "".join(match[1].split())
    require(all(entry["octets"] for entry in raw) and re.findall(r"^(\d+) packets? decoded in", log, re.M) == [str(len(raw))],
            "could not verify Dire Wolf packet and hex output")
    return raw


def monitor(frame):
    address = []
    for i in range(0, 70, 7):
        callsign = bytes(value >> 1 for value in frame[i:i+6]).rstrip(b" ").decode("ascii")
        flags = frame[i+6]
        ssid = (flags >> 1) & 15
        address.append(callsign + (f"-{ssid}" if ssid else ""))
        if flags & 1:
            break
    require(len(address) >= 2 and frame[i+7] & 0xEF == 3 and frame[i+8] == 0xF0, "unexpected audio decoder frame format")
    path = "," + ",".join(address[2:]) if len(address) > 2 else ""
    info = "".join(chr(byte) if 32 <= byte < 127 else f"<0x{byte:02x}>" for byte in frame[i+9:-2])
    return f"{address[1]}>{address[0]}{path}:{info}"


def arm_receive(images, output, code, symbols, source, transitions, *, right_only=False, guest=None, on_frame=None):
    if guest is None:
        guest = original_fm(images, output)
    cpu = guest.cpu
    end = (symbols["__bss_end__"] + 4095) & ~4095
    cpu.mem_map(BASE, end - BASE)
    cpu.mem_write(BASE, code)
    require(cpu.mem_read(RAW_TAP, 4) == ORIGINAL_INSTRUCTION, "unexpected J140 instruction at 48 kHz tap")
    cpu.mem_write(RAW_TAP, pack("<I", branch(RAW_TAP, symbols["aprs_j140_rx"])))
    cpu.mem_protect(BASE, (len(code) + 4095) & ~4095, uc.UC_PROT_READ | uc.UC_PROT_EXEC)

    read = 0
    output_frames = []
    gate_samples = Counter()
    previous_sample = 0

    def word(name):
        return unpack("<I", cpu.mem_read(symbols["aprs_rx_" + name], 4))[0]

    def after_poll(_, sample):
        nonlocal read, previous_sample
        require(word("samples") == sample, "ARM decoder did not consume each sample in the early tap")
        gate_samples[cpu.mem_read(AUDIO_GATE, 1)[0]] += sample - previous_sample
        previous_sample = sample
        written = word("written")
        require(read <= written <= read + OUT_SLOTS, "invalid decoder output cursors")
        while read < written:
            address = symbols["aprs_rx_frames"] + read % OUT_SLOTS * FRAME_STRIDE
            time, length = unpack("<II", cpu.mem_read(address, 8))
            require(18 <= length <= FRAME_MAX and previous_sample - 7 * FRAMES <= time <= sample, "invalid ARM output event")
            frame = bytes(cpu.mem_read(address + 8, length))
            event = dict(text=monitor(frame), octets=frame[:-2].hex(), fcs_wire=frame[-2:].hex(), end_sample=time,
                         gate=cpu.mem_read(AUDIO_GATE, 1)[0])
            output_frames.append(event)
            read += 1
            if on_frame is not None:
                on_frame(event)
        cpu.mem_write(symbols["aprs_rx_read"], pack("<I", read))

    _, _, _, native = capture(guest, source, transitions, right_only=right_only, after_poll=after_poll)
    require(word("overrun") == 0, "ARM decoder output overran")
    return dict(frames=output_frames, bad_fcs_candidates=word("bad_fcs"), output_overrun=word("overrun"),
                gate_samples=dict(gate_samples), native=native)


def compare(actual, reference):
    arm, dw = ([item["octets"] for item in stream] for stream in (actual, reference))
    arm_counts, dw_counts = map(Counter, (arm, dw))

    def unmatched(frames, counts):
        out = []
        for item in frames:
            key = item["octets"]
            if counts[key]:
                counts[key] -= 1
                out.append(item["text"])
        return out

    return dict(arm=len(arm), direwolf=len(dw), common=sum((arm_counts & dw_counts).values()),
                identical_in_order=arm == dw, arm_only=unmatched(actual, arm_counts - dw_counts),
                direwolf_only=unmatched(reference, dw_counts - arm_counts))


def verify(baseline, cases):
    for key in ("continuous", "stock_squelch", "fcs", "second_slot", "bad_fcs_only", "recovery"):
        require(cases[key]["comparison"]["identical_in_order"], f"{key}: raw frame mismatch")
    require(cases["stock_squelch"]["gate_samples"][0] == 38880, "unexpected number of samples taken with squelch closed")
    require(cases["fcs"]["frames"][0]["gate"] == 0, "valid frame did not publish during closed squelch")
    require(cases["bad_fcs_only"]["bad_fcs_candidates"] > 0 and not cases["bad_fcs_only"]["frames"],
            "isolated bad FCS did not reach the CRC check or leaked a frame")
    weak = [item["text"] for item in cases["weak_noisy"]["frames"]]
    require(weak and weak == [text for text in baseline["expected_clean_frames"] if text in weak],
            "weak signal introduced unexpected, repeated or reordered frames")
    trials = baseline["upstream_mute"]["trials"]
    observed = [item["text"] for item in cases["upstream_mute"]["frames"]]
    require(observed == [row[key] for row in trials for key in ("first", "follow") if row[key] in observed],
            "truncation sweep introduced unexpected, repeated or reordered frames")
    for row in trials:
        row["arm_first"] = row["first"] in observed
        row["arm_follow"] = row["follow"] in observed
        require(row["arm_follow"] and (row["cut_ms"] or row["arm_first"]) and
                (row["cut_ms"] <= row["preamble_ms"] or not row["arm_first"]), "failed to recover after upstream clipping")
    cases["upstream_mute"]["trials"] = trials
    require([frame["text"].split(":", 1)[1] for frame in cases["recovery"]["frames"]] == [">AFTER-BAD-FCS", ">AFTER-CUT"],
            "adjacent recovery fixtures failed")


def replay(dat, fixture, atest, output):
    images = load(dat.read_bytes())
    baseline = json.loads((fixture / "replay.json").read_text(encoding="utf-8"))
    require(baseline["stock_main_sha256"] == images[3], "previous audio corpus is from another image")
    atest_hash = sha256(atest.read_bytes()).hexdigest()
    require(atest_hash == baseline["dire_wolf_executables_sha256"]["atest.exe"], "use the same Dire Wolf build as the baseline")
    output.mkdir(parents=True)
    code, symbols = build(output)
    cases = {}
    for key in ("continuous", "weak_noisy", "stock_squelch", "fcs", "upstream_mute", "second_slot", "bad_fcs_only"):
        right_only = key == "second_slot"
        if key == "bad_fcs_only":
            wav = source_wav = "bad-fcs-source48.wav"
            gates = {0: 0}
        else:
            row = baseline[key]
            wav = row["streams"]["stock48"]["wav"]
            source_wav = row["streams"]["source48"]["wav"]
            gates = {item["sample"]: item["gate"] for item in row["gate_changes"]}
        if key == "fcs":
            gates = {0: 0}  # Also prove a complete frame can publish while SQL stays closed.
        source = read_wav(fixture / source_wav)
        if key != "bad_fcs_only":
            pcm_hash = sha256(pack(f"<{len(source)}h", *source)).hexdigest()
            require(pcm_hash == row["streams"]["source48"]["pcm_sha256"], "prior test input changed")
        reference = dire_wolf(atest, fixture, wav, output)
        if key != "bad_fcs_only":
            require([item["text"] for item in reference] == row["streams"]["stock48"]["frames"], "Dire Wolf baseline changed")
        result = arm_receive(images, output, code, symbols, source, gates, right_only=right_only)
        cases[key] = dict(fixture=source_wav, direwolf_reference=reference,
                          comparison=compare(result["frames"], reference), **result)
        stats = cases[key]["comparison"]
        print(f"{key}: ARM {stats['arm']}, Dire Wolf {stats['direwolf']}, same octets {stats['common']}", flush=True)

    cut = 112 * (RATE // 1000)
    source = (GUARD + ax25_burst(">BAD-FCS", 8, bad_fcs=True) + ax25_burst(">AFTER-BAD-FCS", 8) + GUARD +
              (0,) * cut + ax25_burst(">TRUNCATED", 16)[cut:] + ax25_burst(">AFTER-CUT", 8) + GUARD)
    wav = "adjacent-recovery.wav"
    write_wav(output / wav, source, RATE)
    reference = dire_wolf(atest, output, wav, output)
    result = arm_receive(images, output, code, symbols, source, {0: 0})
    cases["recovery"] = dict(fixture=wav, direwolf_reference=reference, comparison=compare(result["frames"], reference), **result)

    verify(baseline, cases)
    report = dict(scope="J140 FM audio task, emulator-only A32 branch, RX only, simulated DMA and SQL inputs",
                  stock_dat_sha256=DAT_HASH, stock_main_sha256=images[3], tap=hex(RAW_TAP),
                  atest_sha256=atest_hash, code_bytes=len(code), code_sha256=sha256(code).hexdigest(),
                  state_bytes=symbols["__bss_end__"] - symbols["__bss_start__"], cases=cases)
    (output / "replay.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("dat", "fixture", "atest", "output"):
        parser.add_argument(option, type=Path)
    args = parser.parse_args()
    replay(args.dat, args.fixture, args.atest.resolve(), args.output)
