"""Replay stock IC-705 receive audio routines on two known Japanese main.bin images."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from struct import pack, pack_into, unpack
import wave

if __package__:
    from tools.emulate_705 import PROFILES, SCRATCH, call, machine
else:
    from emulate_705 import PROFILES, SCRATCH, call, machine


# Each row is tied to the SHA-256 profile in emulate_705.py.
LAYOUTS = {
    "705J132": dict(rec_dma=0x200FC658, rec_bank=0x20400760, rec_ring=0x20401402,
                    rec_right=0x20401888, rec_consume=0x2010C7C8,
                    rec_enable=0x203809F2, rec_stage=0x204036A0,
                    riff=0x20110414, fmt=0x2010E190, data=0x20110438,
                    lan_dma=0x200FCA10, lan_bank=0x20400E20, lan_ring=0x204E9158,
                    lan_ramp=0x20380872, lan_slot=0x203EA9C1, lan_read=0x201F159C),
    "705J140": dict(rec_dma=0x200FFC70, rec_bank=0x20400800, rec_ring=0x204014A2,
                    rec_right=0x20401928, rec_consume=0x2010FE04,
                    rec_enable=0x203809FA, rec_stage=0x20403740,
                    riff=0x20113A50, fmt=0x201117CC, data=0x20113A74,
                    lan_dma=0x20100028, lan_bank=0x20400EC0, lan_ring=0x204E91F8,
                    lan_ramp=0x20380876, lan_slot=0x203EAA49, lan_read=0x201F5834),
}
DMAC = 0xE8200000
FRAMES = 36
RING_SLOTS = 8
RECORD_BLOCKS = 18
RECORD_SAMPLES = 108
DECIMATION = 6
PRERECORD_SLOTS = 1914
AUDIO_GATE = 0x2038026C


def require(condition, message):
    if not condition:
        raise ValueError(message)


def samples(block):
    left = tuple((block * 8191 + i * 1949) % 65536 - 32768 for i in range(FRAMES))
    right = tuple(32767 - (block * 3943 + i * 977) % 65536 for i in range(FRAMES))
    return left, right


def completed(cpu, entry, status, bank, block, left, right, **call_options):
    # Both banks get used; deliberately nonzero low halfwords distinguish sample alignment.
    bank_number = block % 2
    words = ((sample & 0xFFFF) << 16 | (0x1357 + i) for i, sample in enumerate(
        value for pair in zip(left, right) for value in pair))
    cpu.mem_write(bank + bank_number * 0x120, pack("<72I", *words))
    cpu.mem_write(status, pack("<I", 0x41 if bank_number else 0xC1))
    call(cpu, entry, **call_options)


def start_recorder(cpu, layout):
    cpu.mem_write(layout["rec_enable"], b"\x01")
    cpu.mem_write(AUDIO_GATE, b"\x01")


def replay_recorder(cpu, layout):
    ring = layout["rec_ring"]
    right_ring = layout["rec_right"]
    start_recorder(cpu, layout)
    expected = []
    for block in range(18):
        left, right = samples(block)
        completed(cpu, layout["rec_dma"], DMAC + 0xE4, layout["rec_bank"], block, left, right)
        slot = block % RING_SLOTS * FRAMES * 2
        require(unpack("<36h", cpu.mem_read(ring + slot, 72)) == left, "first SSI0 slot lost samples")
        require(unpack("<36h", cpu.mem_read(right_ring + slot, 72)) == right, "second SSI0 slot lost samples")
        expected.extend(left[::6])
        call(cpu, layout["rec_consume"])
    staged = unpack("<108h", cpu.mem_read(layout["rec_stage"] + 0x271C8, 216))
    require(staged == tuple(expected), "stock recorder staging PCM differs from SSI0 / 6")
    require(cpu.mem_read(ring + 0x240, 2) == b"\x02\x02", "SSI0 ring did not wrap twice")
    return staged


def stock_wav(cpu, layout, pcm, channels):
    require(call(cpu, layout["riff"], SCRATCH) == 12, "RIFF size")
    require(call(cpu, layout["fmt"], SCRATCH + 12, channels) == 24, "fmt size")
    require(call(cpu, layout["data"], SCRATCH + 36) == 8, "data size")
    header = bytearray(cpu.mem_read(SCRATCH, 44))
    # Size fields belong to the host fixture; no SD or file writer is emulated.
    pack_into("<I", header, 4, len(pcm) + 36)
    pack_into("<I", header, 40, len(pcm))
    return header + pcm


def verify_wav(cpu, layout, samples):
    formats = []
    for channels in (1, 2):
        pcm = pack("<" + "h" * (len(samples) * channels),
                   *(value for value in samples for _ in range(channels)))
        with wave.open(BytesIO(stock_wav(cpu, layout, pcm, channels)), "rb") as wav:
            fmt = wav.getnchannels(), wav.getframerate(), wav.getsampwidth()
            require(fmt == (channels, 8000, 2), "unexpected WAV format")
            require(wav.readframes(len(samples)) == pcm, "WAV fixture did not round-trip")
            formats.append(dict(channels=channels, hz=fmt[1], bits=fmt[2] * 8))
    return formats


def recorder_backlog(main, layout):
    results = []
    for burst in (7, 8, 9):
        cpu = machine(main)
        cpu.mem_map(DMAC, 0x1000)
        start_recorder(cpu, layout)
        cursors = layout["rec_ring"] + 0x240
        first_kept = (burst // RING_SLOTS) * RING_SLOTS
        for block in range(first_kept + RECORD_BLOCKS):
            left, right = samples(block)
            completed(cpu, layout["rec_dma"], DMAC + 0xE4, layout["rec_bank"], block, left, right)
            if block == burst - 1:
                before = list(cpu.mem_read(cursors, 2))
            if block >= burst - 1:
                call(cpu, layout["rec_consume"])
            if block == burst - 1:
                after = list(cpu.mem_read(cursors, 2))
        expected = pack("<108h", *(value for block in range(first_kept, first_kept + RECORD_BLOCKS)
                                   for value in samples(block)[0][::6]))
        require(before == [burst % RING_SLOTS, 0] and after == [burst % RING_SLOTS] * 2,
                f"unexpected DMA cursors after deferred consumer: {burst}")
        require(cpu.mem_read(layout["rec_stage"] + 0x271C8, 216) == expected,
                f"unexpected PCM after deferred consumer: {burst}")
        results.append(dict(dma_blocks_before_first_consume=burst, write_read_before=before,
                            write_read_after=after, first_recorded_block_zero_based=first_kept))
    return results


def record_group(cpu, layout, group, values):
    right = (0,) * FRAMES
    for offset in range(RECORD_BLOCKS):
        left = values[offset * FRAMES:(offset + 1) * FRAMES]
        block = group * RECORD_BLOCKS + offset
        # These fixed firmware images run under the same per-call instruction cap as the short probe.
        completed(cpu, layout["rec_dma"], DMAC + 0xE4, layout["rec_bank"], block, left, right,
                  timeout_us=0)
        call(cpu, layout["rec_consume"], timeout_us=0)
    ring_index = ((group + 1) * RECORD_BLOCKS) % RING_SLOTS
    require(cpu.mem_read(layout["rec_ring"] + 0x240, 2) == bytes([ring_index] * 2), f"DMA cursors after group {group}")
    stage = layout["rec_stage"]
    cursor = unpack("<H", cpu.mem_read(stage + 0x8DE9E, 2))[0]
    require(cursor == (group + 1) % PRERECORD_SLOTS, f"pre-record cursor after group {group}")
    return bytes(cpu.mem_read(stage + 0x271C8 + (group % PRERECORD_SLOTS) * 220, RECORD_SAMPLES * 2))


def replay_wav(main, layout, path, output):
    with wave.open(str(path), "rb") as wav:
        hz = wav.getframerate()
        require((wav.getnchannels(), wav.getsampwidth()) == (1, 2) and hz in (8000, 48000),
                f"expected mono 16-bit WAV at 8000 or 48000 Hz: {path}")
        frames = wav.getnframes()
        pcm = wav.readframes(frames)
    require(frames > 0 and len(pcm) == 2 * frames, f"empty or truncated PCM: {path}")
    cpu = machine(main)
    cpu.mem_map(DMAC, 0x1000)
    start_recorder(cpu, layout)
    received = bytearray()
    stride = hz // 8000
    size = RECORD_SAMPLES * stride * 2
    kept = (frames + stride - 1) // stride
    groups = (len(pcm) + size - 1) // size
    expected_stream = bytearray()
    for group, offset in enumerate(range(0, len(pcm), size)):
        chunk = pcm[offset:offset + size].ljust(size, b"\0")
        values = unpack(f"<{size // 2}h", chunk)
        if stride == 1:
            values = tuple(value for value in values for _ in range(DECIMATION))
        expected = pack("<108h", *values[::DECIMATION])
        observed = record_group(cpu, layout, group, values)
        require(observed == expected, f"first PCM mismatch in group {group} (sample {offset // 2}): {path}")
        received.extend(observed)
        expected_stream.extend(expected)
    del received[kept * 2:]
    del expected_stream[kept * 2:]

    # Nonzero input through both gate states, in the same CPU and queue, after the measured stream.
    control = tuple(range(1, RECORD_SAMPLES * DECIMATION + 1))
    cpu.mem_write(AUDIO_GATE, b"\x00")
    require(record_group(cpu, layout, groups, control) == bytes(RECORD_SAMPLES * 2), "muted group must be silent")
    cpu.mem_write(AUDIO_GATE, b"\x01")
    require(record_group(cpu, layout, groups + 1, control) == pack("<108h", *control[::DECIMATION]),
            "audio did not resume after unmute")

    wav_bytes = stock_wav(cpu, layout, received, 1)
    with wave.open(BytesIO(wav_bytes), "rb") as wav:
        require((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes())
                == (1, 2, 8000, kept), "unexpected recorder WAV fixture format")
        require(wav.readframes(kept) == received, "recorder WAV fixture changed captured PCM")
    with output.open("xb") as handle:
        handle.write(wav_bytes)
    return dict(source=str(path), output=str(output), input_hz=hz, input_samples=frames,
                samples=kept, seconds=kept / 8000,
                dma_blocks=groups * RECORD_BLOCKS, dma_ring_wraps=groups * RECORD_BLOCKS // RING_SLOTS,
                prerecord_groups=groups, prerecord_wraps=groups // PRERECORD_SLOTS,
                tail_padding_samples=groups * RECORD_SAMPLES - kept, input_pcm_sha256=sha256(pcm).hexdigest(),
                expected_pcm_sha256=sha256(expected_stream).hexdigest(), staged_pcm_sha256=sha256(received).hexdigest(),
                output_wav_sha256=sha256(wav_bytes).hexdigest(), mute_and_resume_verified=True)


def replay_lan(cpu, layout):
    cpu.mem_write(0x2038026D, b"\x01")
    cpu.mem_write(layout["lan_ramp"] + 2, pack("<H", 480))
    results = []
    stream = bytearray()
    ring = layout["lan_ring"]
    for i, block in enumerate(range(4, 31)):
        slot = i % 2
        left, right = samples(block)
        cpu.mem_write(layout["lan_slot"] + 0x7B, bytes([slot]))
        completed(cpu, layout["lan_dma"], DMAC + 0x524, layout["lan_bank"], block, left, right)
        expected = pack("<72h", *(sample for sample in (left, right)[slot] for _ in range(2)))
        require(cpu.mem_read(ring + i * 144, 144) == expected, f"WLAN ring slot selection {slot} failed")
        stream.extend(expected)
        if i < 2:
            results.append(dict(serial_slot=slot, samples=FRAMES, sha256=sha256(expected).hexdigest()))
    require(cpu.mem_read(ring + 0x1C200, 2) == pack("<H", 972), "WLAN write cursor")
    out = SCRATCH - 0x2000
    call(cpu, layout["lan_read"], ring, out, 960)
    frame = bytes(cpu.mem_read(out, 3840))
    require(frame == stream[:3840], "stock WLAN reader changed PCM")
    require(cpu.mem_read(ring + 0x1C202, 2) == pack("<H", 960), "WLAN read cursor")
    call(cpu, layout["lan_read"], ring, out, 960)
    require(cpu.mem_read(out, 3840) == bytes(3840), "short WLAN read did not return silence")
    require(cpu.mem_read(ring + 0x1C202, 2) == pack("<H", 960), "short WLAN read advanced cursor")
    return dict(first_blocks=results, written_frames=972, read_frames=960,
                pcm_sha256=sha256(frame).hexdigest(), short_read_silence=True)


def probe(path, wavs=(), out_dir=None):
    main = path.read_bytes()
    digest = sha256(main).hexdigest()
    profile = PROFILES.get(digest)
    require(profile is not None, f"unrecognized main CPU image: {path} ({digest})")
    layout = LAYOUTS[profile.name]
    if wavs:
        return dict(sample=profile.name, main_sha256=digest, recorder_wav=[
            replay_wav(main, layout, wav, out_dir / f"{profile.name}-{wav.stem}.wav") for wav in wavs])
    cpu = machine(main)
    cpu.mem_map(DMAC, 0x1000)
    staged = replay_recorder(cpu, layout)
    return dict(sample=profile.name, main_sha256=digest, dma_blocks=18, dma_frames_per_block=FRAMES,
                recorder_staged_samples=len(staged),
                recorder_sha256=sha256(pack("<108h", *staged)).hexdigest(),
                wav=verify_wav(cpu, layout, staged), recorder_backlog=recorder_backlog(main, layout),
                wlan_ring=replay_lan(cpu, layout))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="decoded main.bin images")
    parser.add_argument("--wav", action="append", default=[], type=Path,
                        help="replay a mono signed 16-bit 8000 or 48000 Hz WAV (repeatable)")
    parser.add_argument("--out-dir", type=Path, help="new directory for replay WAV fixtures")
    args = parser.parse_args()
    if bool(args.wav) != bool(args.out_dir):
        parser.error("--wav and --out-dir must be used together")
    if len({wav.stem.casefold() for wav in args.wav}) != len(args.wav):
        parser.error("input WAV filenames must have distinct stems")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=False)
    print(json.dumps([probe(path, args.wav, args.out_dir) for path in args.images], indent=2))
