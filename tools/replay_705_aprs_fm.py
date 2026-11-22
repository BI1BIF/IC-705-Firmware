"""Replay 1200-baud packets through the stock J140 FM standby PCM path."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from math import sin, tau
from pathlib import Path
from random import Random
import re
from struct import pack, unpack
from subprocess import run
import wave

from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_cw_pcm import DECIMATED, REC_TASK_STEP
from tools.probe_705_rx_audio import AUDIO_GATE, DECIMATION, DMAC, FRAMES, LAYOUTS, RING_SLOTS, completed, require
from tools.render_705_display import DAT_HASH, PAGE, load
from tools.render_705_stock_row import FONT_HASH, FONT_HEADER, SMALL_FONT_HASH, SMALL_FONT_HEADER
from tools.replay_705_settings import SettingsGuest
from tools.replay_705_stock_install import A_PREFIX, load_a


RATE = 48000
LAYOUT = LAYOUTS["705J140"]
RAW_TAP, SCOPE_CALL, SCOPE_ENABLE = 0x2010FE34, 0x2010FE48, 0x2038001E
SQL_KNOB, DSP_STATUS, DSP_NOISE = 0x203EB11B, 0x203809A1, 0x203E1E2E
SQL_SETTINGS, SQL_STEP, SQL_PUBLISH = 0x200B6B60, 0x200B47D0, 0x200623F0
SQL_STATE, GATE_STORE = 0x203806FC, 0x200622D8
HEADER = "N0CALL-7>APDW16"
DW_VERSION = "1.8.1-a231971"
GUARD = (0,) * 7200
E140_DAT_HASH = "132383f8388641d02d0fadaccf9878d01a1960fa77a028328f0eb33dcfbc147b"
E140_MAIN_HASH = "3df33f33de9b2754a86cc61608334e61364e409f5a8ce905f0fac0e42afd3b3c"


def load_aprs_panel(dat):
    if sha256(dat).hexdigest() != E140_DAT_HASH:
        return load(dat), False
    main, flash = load_a(dat, E140_MAIN_HASH)

    def font(offset, digest):
        length, = unpack("<I", flash[offset:offset+4])
        data = flash[offset+4:offset+4+length]
        require(sha256(data).hexdigest() == digest, "unexpected E140 font")
        return data

    large = font(A_PREFIX, FONT_HASH)
    small = font(A_PREFIX + SMALL_FONT_HEADER - FONT_HEADER, SMALL_FONT_HASH)
    return (main, large, flash[:A_PREFIX], E140_MAIN_HASH, small), True


def command(exe, directory, *args):
    result = run([exe, *args], cwd=directory, stdout=-1, stderr=-2, check=True, timeout=90)
    return result.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def write_wav(path, samples, rate):
    pcm = pack(f"<{len(samples)}h", *samples)
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", ""))
        out.writeframes(pcm)
    return sha256(pcm).hexdigest()


def read_wav(path):
    with wave.open(str(path), "rb") as source:
        require((source.getnchannels(), source.getsampwidth(), source.getframerate()) == (1, 2, RATE),
                "unexpected generated WAV format")
        frames = source.getnframes()
        return unpack(f"<{frames}h", source.readframes(frames))


def decode(directory, atest, wav):
    log = command(atest, directory, "-B", "1200", "-F", "0", wav)
    (directory / f"{wav}.atest.txt").write_text(log, encoding="utf-8")
    frames = re.findall(r"^\[0\] (.+)$", log, re.MULTILINE)
    summary = re.findall(r"^(\d+) packets? decoded in", log, re.MULTILINE)
    require(summary == [str(len(frames))], "could not account for every Dire Wolf frame")
    return frames


def original_fm(images, output, *, rom=None):
    guest = SettingsGuest(images, front_panel=True, language_address=0x203EAE44,
                          **({} if rom is None else {"rom": rom}))
    cpu = guest.cpu
    cpu.mem_write(guest.language_address, bytes(2))
    for address in (MODE_UI_A, MODE_VFO_A):
        cpu.mem_write(address, b"\x70")
    for address in (0x20380714, 0x203EBC2F):
        cpu.mem_write(address, pack("<I", 144_390_000))
    labels, frame = guest.render()
    require("FM" in labels and "FIL1" in labels and cpu.mem_read(PAGE + 1, 1) == b"\x01",
            f"unexpected FM standby screen: {labels}")
    (output / "stock-fm-standby.png").write_bytes(frame)
    cpu.mem_map(DMAC, 0x1000)

    # Supply the FM receive-status bit and noise metric the ARM squelch code reads.
    # The same knob value is held across all signal-present and signal-absent transitions.
    cpu.mem_write(DSP_STATUS, b"\x40")
    cpu.mem_write(SQL_KNOB, b"\x64")
    call(cpu, guest.rom(SQL_SETTINGS))
    return guest


def capture(guest, source, transitions, *, right_only=False, after_poll=None, task=REC_TASK_STEP):
    cpu = guest.cpu
    rom = guest.rom
    full, down, gated, gate_stores = bytearray(), bytearray(), bytearray(), []
    gate_changes = []
    scope_calls = 0

    def tap_raw(c, *_):
        full.extend(c.mem_read(c.reg_read(arm.UC_ARM_REG_SP) + 32, 2 * FRAMES))

    def tap_down(c, *_):
        pcm = c.mem_read(c.reg_read(arm.UC_ARM_REG_SP) + 8, 2 * (FRAMES // DECIMATION))
        down.extend(pcm)
        gated.extend(pcm if c.mem_read(AUDIO_GATE, 1)[0] else bytes(len(pcm)))

    def scope_used(*_):
        nonlocal scope_calls
        scope_calls += 1

    def gate_store(c, _kind, _address, _size, value, _):
        gate_stores.append((c.reg_read(arm.UC_ARM_REG_PC), value))

    for address, callback in ((RAW_TAP, tap_raw), (DECIMATED, tap_down), (SCOPE_CALL, scope_used)):
        cpu.hook_add(uc.UC_HOOK_CODE, callback, begin=rom(address), end=rom(address))
    cpu.hook_add(uc.UC_HOOK_MEM_WRITE, gate_store, begin=AUDIO_GATE, end=AUDIO_GATE)

    padded = source + (0,) * (-len(source) % FRAMES)
    silence = (0,) * FRAMES
    block_count = len(padded) // FRAMES
    # Exercise different ring occupancies while staying below its eight-slot wrap.
    cadence = (1, 4, 7, 2, 6, 3, 5)
    batches = Counter()
    pending = polls = 0
    for block, offset in enumerate(range(0, len(padded), FRAMES)):
        if offset in transitions:
            phase = transitions[offset]
            noise = 0 if phase else 0xFFFF
            cpu.mem_write(DSP_NOISE, pack("<H", noise))
            call(cpu, rom(SQL_STEP))
            call(cpu, rom(SQL_PUBLISH))
            require(cpu.mem_read(SQL_STATE, 1)[0] == cpu.mem_read(AUDIO_GATE, 1)[0] == phase,
                    "stock FM squelch did not follow the injected status metric")
            gate_changes.append(dict(sample=offset, noise_metric=noise, gate=phase))
        audio = padded[offset:offset + FRAMES]
        left, right = (silence, audio) if right_only else (audio, silence)
        completed(cpu, rom(LAYOUT["rec_dma"]), DMAC + 0xE4, LAYOUT["rec_bank"], block,
                  left, right, timeout_us=0)
        pending += 1
        if pending == cadence[polls % len(cadence)] or offset + FRAMES in transitions or block + 1 == block_count:
            call(cpu, task, timeout_us=0)
            if after_poll is not None:
                after_poll(cpu, offset + FRAMES)
            batches[pending] += 1
            pending = 0
            polls += 1

    require(gate_stores == [(rom(GATE_STORE), item["gate"]) for item in gate_changes],
            "gate writes did not come from stock ARM")
    require(len(gate_changes) == len(transitions), "transition must land on an SSIF0 DMA block")
    require(len(full) == 2 * len(padded) and len(down) == 2 * len(padded) // DECIMATION, "missing or repeated PCM blocks")
    raw = unpack(f"<{len(padded)}h", full)[:len(source)]
    down_8k = unpack(f"<{len(padded) // DECIMATION}h", down)[:len(source[::DECIMATION])]
    gated_8k = unpack(f"<{len(padded) // DECIMATION}h", gated)[:len(down_8k)]
    expected = (0,) * len(source) if right_only else source
    require(raw == expected and down_8k == expected[::DECIMATION], "PCM changed in stock DMA or sample copy")
    require(list(cpu.mem_read(LAYOUT["rec_ring"] + 0x240, 2)) == [block_count % RING_SLOTS] * 2,
            "DMA ring cursors diverged")
    require(cpu.mem_read(LAYOUT["rec_enable"], 1) == cpu.mem_read(SCOPE_ENABLE, 1) == b"\0" and not scope_calls,
            "recording or AUDIO SCOPE was active")
    return raw, down_8k, gated_8k, dict(blocks=block_count, ring_wraps=block_count // RING_SLOTS,
                                        host_task_calls=polls, dma_blocks_per_task=dict(sorted(batches.items())),
                                        right_slot_only=right_only, gate_changes=gate_changes,
                                        scope_calls=scope_calls, record_enabled=False)


def ax25_burst(info, flags, *, bad_fcs=False, source="N0CALL-7", destination="APDW16"):
    """Only the timing and bad-FCS fixtures need direct control of the bits on the wire."""
    require(re.fullmatch(r"[A-Z0-9]{6}", destination), "invalid fixture destination")
    address = bytes(ord(ch) << 1 for ch in destination) + b"\xe0"
    call, _, ssid = source.partition("-")
    require(re.fullmatch(r"[A-Z0-9]{1,6}", call) and 0 <= int(ssid or 0) <= 15, "invalid fixture source")
    address += bytes(ord(ch) << 1 for ch in call.ljust(6)) + bytes((0x61 | int(ssid or 0) << 1,))
    frame = address + b"\x03\xf0" + info.encode("ascii")
    crc = 0xFFFF
    for value in frame:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    fcs = crc ^ 0xFFFF ^ bad_fcs
    flag = [0, 1, 1, 1, 1, 1, 1, 0]
    bits = flag * flags
    ones = 0
    for value in frame + pack("<H", fcs):
        for i in range(8):
            bit = (value >> i) & 1
            bits.append(bit)
            ones = ones + 1 if bit else 0
            if ones == 5:
                bits.append(0)
                ones = 0
    bits.extend(flag * 3)
    phase, mark = 0, False
    pcm = []
    for bit in bits:
        mark ^= not bit
        hz = 1200 if mark else 2200
        for _ in range(RATE // 1200):
            pcm.append(round(10000 * sin(tau * phase / RATE)))
            phase = (phase + hz) % RATE
    return tuple(pcm)


def exercise(images, output, atest, name, source, transitions, *, right_only=False):
    raw, down, gated, result = capture(original_fm(images, output), source, transitions, right_only=right_only)
    streams = [("source48", source, RATE), ("stock48", raw, RATE), ("stock8", down, RATE // DECIMATION)]
    if name == "stock-squelch":
        streams.append(("with-post-tap-gate8", gated, RATE // DECIMATION))
    result["streams"] = {}
    for label, pcm, rate in streams:
        wav = f"{name}-{label}.wav"
        digest = write_wav(output / wav, pcm, rate)
        result["streams"][label] = dict(wav=wav, samples=len(pcm), rate=rate, pcm_sha256=digest,
                                         frames=decode(output, atest, wav))
    return result


def squelch_sweep(images, output, atest):
    source = GUARD
    rows = []
    for flags in (8, 16, 32):
        preamble_ms = flags * 8 * 1000 / 1200
        for cut_ms in (0, 10, 30, 50, 70, 90, 110, 150, 190, 200, 205, 210, 220, 240):
            if cut_ms > preamble_ms + 27:
                break
            case = f"{flags:02}-{cut_ms:03}"
            first, follow = f">FIRST-{case}", f">FOLLOW-{case}"
            burst = ax25_burst(first, flags)
            cut = cut_ms * (RATE // 1000)
            source += (0,) * cut + burst[cut:] + GUARD + ax25_burst(follow, 16) + GUARD
            rows.append(dict(flags=flags, preamble_ms=round(preamble_ms, 3), cut_ms=cut_ms,
                             first=f"{HEADER}:{first}", follow=f"{HEADER}:{follow}"))
    result = exercise(images, output, atest, "upstream-mute", source, {0: 1})
    for label, stream in result["streams"].items():
        frames = stream["frames"]
        require(frames == [row[key] for row in rows for key in ("first", "follow") if row[key] in frames],
                f"unexpected, duplicate, or reordered {label} frame")
        require(all(row["follow"] in frames for row in rows), f"{label}: intact follow-up lost")
        require(all((row["cut_ms"] != 0 or row["first"] in frames) and
                    (row["cut_ms"] <= row["preamble_ms"] or row["first"] not in frames) for row in rows),
                f"{label}: first-packet controls failed")
        for row in rows:
            row[label] = row["first"] in frames
    result["trials"] = rows
    return result


def replay(dat, direwolf, output):
    images = load(dat.read_bytes())
    atest, gen = (direwolf / name for name in ("atest.exe", "gen_packets.exe"))
    hashes = {exe.name: sha256(exe.read_bytes()).hexdigest() for exe in (gen, atest)}
    output.mkdir(parents=True)
    templates = ("!3531.00N/13930.00E>J140-{:03}", ":N0TEST   :offline {:03}{{{:03}", ">J140 FM {:03}")
    frames = [f"{HEADER},WIDE1-1:{templates[i % 3].format(i, i)}" for i in range(30)]
    # gen_packets includes LF in the transmitted info when a TNC2 line ends in LF.
    text_file = "direwolf-input.txt"
    (output / text_file).write_bytes("\n".join(frames).encode("ascii"))
    frames = [text + "<0x0a>" for text in frames[:-1]] + frames[-1:]
    log = command(gen, output, "-B", "1200", "-r", str(RATE), "-o", "direwolf-generated.wav", text_file)
    (output / "direwolf-generated.txt").write_text(log, encoding="utf-8")
    source = read_wav(output / "direwolf-generated.wav")
    clean = exercise(images, output, atest, "continuous", source, {0: 1})
    require(all(stream["frames"] == frames for stream in clean["streams"].values()), "baseline packet mismatch")
    print(f"Clean: {len(frames)} frames through both stock taps.", flush=True)

    rng = Random(705140)
    weak = tuple(max(-32768, min(32767, round(s / 16 + rng.gauss(0, 500)))) for s in source)
    noisy = exercise(images, output, atest, "weak-noisy", weak, {0: 1})
    for stream in noisy["streams"].values():
        decoded = stream["frames"]
        require(decoded == [frame for frame in frames if frame in decoded], "unexpected weak-signal frame")
    require(noisy["streams"]["stock48"]["frames"] == noisy["streams"]["source48"]["frames"], "48 kHz noisy replay differed")

    first = ax25_burst(">FIRST", 16)
    follow = ax25_burst(">FOLLOW", 16)
    valid = ax25_burst(">CHECK-FCS", 16)
    invalid = ax25_burst(">CHECK-FCS", 16, bad_fcs=True)
    pad = (0,) * (-(len(first) + len(follow)) % FRAMES)
    cycle = GUARD + first + GUARD + follow + GUARD + pad
    opening = (len(GUARD) + 120 * (RATE // 1000)) // FRAMES * FRAMES
    require(opening > len(GUARD) + 16 * 8 * RATE // 1200, "gate test must open after the first preamble")
    squelch = exercise(images, output, atest, "stock-squelch", cycle * 3,
                       {offset: gate for i in range(3) for offset, gate in
                        ((i * len(cycle), 0), (i * len(cycle) + opening, 1))})
    for label, stream in squelch["streams"].items():
        expected = [f"{HEADER}:>FOLLOW"] if label == "with-post-tap-gate8" else [f"{HEADER}:>FIRST", f"{HEADER}:>FOLLOW"]
        require(stream["frames"] == expected * 3, f"stock squelch transition mismatch ({label})")
    print("Stock SQL: three closes and opens, all first packets present before the gate.", flush=True)

    fcs = exercise(images, output, atest, "fcs", GUARD + invalid + GUARD + valid + GUARD, {0: 1})
    require(all(s["frames"] == [f"{HEADER}:>CHECK-FCS"] for s in fcs["streams"].values()), "bad FCS accepted or good FCS lost")
    bad_only = "bad-fcs-source48.wav"
    write_wav(output / bad_only, GUARD + invalid + GUARD, RATE)
    require(not decode(output, atest, bad_only), "bad FCS alone was accepted")
    second = exercise(images, output, atest, "second-slot", GUARD + first + GUARD, {0: 1}, right_only=True)
    require(second["streams"]["source48"]["frames"] == [f"{HEADER}:>FIRST"] and
            not second["streams"]["stock48"]["frames"] and not second["streams"]["stock8"]["frames"],
            "second-slot isolation failed")

    sweep = squelch_sweep(images, output, atest)
    report = dict(scope="offline stock J140 ARM, injected SSIF0 PCM and simulated DSP noise metric; host-paced audio task",
                  stock_dat_sha256=DAT_HASH, stock_main_sha256=images[3], dire_wolf_release=DW_VERSION,
                  dire_wolf_executables_sha256=hashes, mode="FM FIL1", baud=1200, tones_hz=[1200, 2200],
                  taps_hz={hex(RAW_TAP): RATE, hex(DECIMATED): RATE // DECIMATION},
                  stock_squelch_knob=100, stock_squelch_open_delay_ms=(opening - len(GUARD)) * 1000 / RATE,
                  weak_noisy_fixture=dict(seed=705140, amplitude_scale=1 / 16, noise_sigma=500),
                  expected_clean_frames=frames, continuous=clean, weak_noisy=noisy, stock_squelch=squelch,
                  fcs=fcs, second_slot=second, upstream_mute=sweep)
    (output / "replay.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Completed FM PCM replay: {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="stock 705J140.dat")
    parser.add_argument("direwolf", type=Path, help=f"Windows Dire Wolf {DW_VERSION} executable directory")
    parser.add_argument("output", type=Path, help="new replay evidence directory")
    args = parser.parse_args()
    replay(args.dat, args.direwolf.resolve(), args.output)
