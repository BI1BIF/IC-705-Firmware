"""Verify a stock J140 PCM tap with recording off, without modifying the firmware."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack
from tempfile import TemporaryDirectory

from tools.emulate_705 import arm, call, uc
from tools.make_cw_fixtures import TEXT, render
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC, LAYOUTS, completed, require
from tools.render_705_display import load
from tools.replay_705_ptt_tune import (FLAGS, PANEL_PTT, PORT_MODE, PORT_PTT, PTT_INIT,
                                       PTT_PASSES, STATUS_STORE, STATUS_TASK, byte, radio, word)
from tools.replay_705_vfo_split import exchange_in_guest, read_in_guest
from tools.verify_705_cw_arm import BLOCK_BYTES, STATE_BYTES, build


REC_TASK_STEP, DECIMATED = 0x20110384, 0x2010FEAC
TEST_CODE, TEST_STATE, TEST_PCM = 0x21000000, 0x21001000, 0x21002000
LAYOUT = LAYOUTS["705J140"]
BUILD_REQUEST, FILTER_REQUEST = 0x20109514, 0x2010A820
REQUEST, FILTERED = 0x203809AC, 0x203809B0
RAW_DSP_STATUS, DSP_STATUS, MIRROR_DSP_STATUS = 0x203E1E6C, 0x203809A1, 0x200D4A28
DSP_TX = 0x10
KEY_ACTIVITY = 0x203E1E68  # Populated by the original DSP status parser before PCM.


def feed_dsp_tx(cpu, active, mirror=MIRROR_DSP_STATUS):
    raw = word(cpu, RAW_DSP_STATUS) & ~DSP_TX
    cpu.mem_write(RAW_DSP_STATUS, pack("<I", raw | (DSP_TX if active else 0)))
    call(cpu, mirror)
    require(bool(byte(cpu, DSP_STATUS) & DSP_TX) == active, "stock DSP mirror did not update")


def probe(cpu, phases, code, entry, rec_enable, gate, *, after_first_pcm=None):
    cpu.mem_map(DMAC, 4096)
    cpu.mem_map(TEST_CODE, 0x3000)
    require(len(code) <= 4096, "lab code exceeds its page")
    cpu.mem_write(TEST_CODE, code)
    cpu.mem_protect(TEST_CODE, 4096, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
    cpu.mem_write(LAYOUT["rec_enable"], bytes((rec_enable,)))
    cpu.mem_write(AUDIO_GATE, bytes((gate,)))
    captured, pending, stages = bytearray(), bytearray(), []
    taps = decoder_calls = 0
    reception = False

    def tap(c, _addr, _size, _data):
        nonlocal taps
        pos = c.reg_read(arm.UC_ARM_REG_SP) + 8
        batch = c.mem_read(pos, 12)  # Six real samples produced by the stock 6:1 copy.
        captured.extend(batch)
        if reception:
            pending.extend(batch)
        taps += 1

    cpu.hook_add(uc.UC_HOOK_CODE, tap, begin=DECIMATED, end=DECIMATED)
    for label, chunk, transition in phases:
        if transition:
            transition(cpu)
        flags = byte(cpu, FLAGS)
        request, filtered, panel = word(cpu, REQUEST), word(cpu, FILTERED), byte(cpu, PANEL_PTT) & 1
        audio = byte(cpu, AUDIO_GATE)
        tx, = read_in_guest(cpu, "1c 00")[0]
        require(tx == flags >> 7, "stock readback differs from published status")
        dsp_tx = bool(byte(cpu, DSP_STATUS) & DSP_TX)
        key_activity = bool(byte(cpu, KEY_ACTIVITY))
        reception = not (panel or flags & 0xA0 or request or filtered or dsp_tx or key_activity) and audio == 1
        calls_before, dropped, text = decoder_calls, 0, []
        if not reception:
            dropped = len(pending) // 2
            pending.clear()
            cpu.mem_write(TEST_STATE, bytes(STATE_BYTES))
        for offset in range(0, len(chunk), 12):
            samples = unpack("<6h", chunk[offset:offset+12])
            left = tuple(x for x in samples for _ in range(6))
            completed(cpu, LAYOUT["rec_dma"], DMAC+0xE4, LAYOUT["rec_bank"], taps, left, (0,)*36,
                      timeout_us=0)
            call(cpu, REC_TASK_STEP, timeout_us=0)
            if offset == 0 and after_first_pcm is not None:
                after_first_pcm(cpu, label)
            # Only the host schedules the isolated decoder after the stock step returns.
            if len(pending) >= BLOCK_BYTES:
                cpu.mem_write(TEST_PCM, bytes(pending[:BLOCK_BYTES]))
                del pending[:BLOCK_BYTES]
                used = call(cpu, entry, TEST_STATE, TEST_PCM, timeout_us=0, instruction_limit=25000)
                require(used <= 16, "decoder buffer overflow")
                decoder_calls += 1
                if used:
                    text.append(bytes(cpu.mem_read(TEST_STATE+72, used)).decode("ascii"))
        state_clear = not any(cpu.mem_read(TEST_STATE, STATE_BYTES))
        require(reception or (state_clear and not pending and decoder_calls == calls_before),
                "decoder ran or retained audio outside reception")
        _, _, pattern, mark = unpack("<4I", cpu.mem_read(TEST_STATE, 16))
        stages.append(dict(stage=label, audio_gate=audio, rx_enabled=reception, stock_tx=tx,
                           ci_v_request=bool(flags & 0x20), panel_ptt=bool(panel), dsp_tx=dsp_tx,
                           key_activity=key_activity,
                           request=request, filtered=filtered, fed_blocks=decoder_calls-calls_before,
                           discarded_partial_samples=dropped, decoder_state_clear=state_clear,
                           mark_in_progress=bool(mark), symbol_pattern=pattern, text="".join(text)))
    pcm = b"".join(chunk for _, chunk, _ in phases)
    raw_cursors = list(cpu.mem_read(LAYOUT["rec_ring"]+0x240, 2))
    prerecord, = unpack("<H", cpu.mem_read(LAYOUT["rec_stage"]+0x8DE9E, 2))
    require(captured == pcm and taps * 12 == len(pcm), "PCM tap lost or changed samples")
    require(raw_cursors == [taps % 8]*2, "stock PCM cursors diverged")
    require(prerecord == ((taps // 18) % 1914 if rec_enable else 0), "stock prerecord behavior changed")
    require(cpu.mem_read(LAYOUT["rec_enable"], 1) == bytes((rec_enable,)), "recording flag changed")
    nonzero = None
    if len(pcm) == 216:
        slot = bytes(cpu.mem_read(LAYOUT["rec_stage"] + 0x271C8, len(pcm)))
        require(slot == (pcm if rec_enable and gate else bytes(len(pcm))), "stock gate output changed")
        nonzero = sum(value != 0 for value in unpack("<108h", slot))
    return dict(recording_enable=rec_enable, audio_gate=gate, original_blocks=taps, raw_cursors=raw_cursors,
                prerecord_cursor=prerecord, prerecord_nonzero_samples=nonzero,
                samples_sha256=sha256(captured).hexdigest(), text="".join(stage["text"] for stage in stages),
                stages=stages)


def simulated_gpio(cpu, *, extra=(), rom=lambda pc: pc):
    cpu.mem_map(0xFCFE3000, 4096)
    cpu.mem_write(PORT_MODE, pack("<H", 0x40))
    cpu.mem_write(PORT_PTT, pack("<H", 0x2000))
    accesses = set()

    def io_guard(_cpu, kind, address, size, value, _data):
        entry = (kind, address, size, value)
        expected = ((uc.UC_MEM_READ, PORT_MODE, 2, 0), (uc.UC_MEM_READ, PORT_PTT, 2, 0),
                    (uc.UC_MEM_READ, 0xFCFE3214, 2, 0), (uc.UC_MEM_WRITE, 0xFCFE3114, 4, 0x10000))
        require(entry in expected + extra, f"unexpected guest GPIO access: {kind}, {address:#x}, {size}, {value:#x}")
        accesses.add(entry)

    cpu.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, io_guard, begin=0xFCFE3000, end=0xFCFE3FFF)
    call(cpu, rom(PTT_INIT))
    return accesses


def transitions(main, pcm, code, entry):
    cpu = radio(main, 0)
    accesses = simulated_gpio(cpu)
    stores = []

    def track_status(c, *_args):
        stores.append(byte(c, FLAGS) >> 7)

    cpu.hook_add(uc.UC_HOOK_CODE, track_status, begin=STATUS_STORE+4, end=STATUS_STORE+4)

    def request(down):
        def send(c):
            response, _ = exchange_in_guest(c, bytes((0x1c, 0, down)))
            require(response[2:-1] == b"\xfb", "stock CI-V request was rejected")
        return send

    def panel(down):
        def scan(c):
            c.mem_write(PORT_PTT, pack("<H", 0 if down else 0x2000))
            for routine in PTT_PASSES:
                call(c, routine)
        return scan

    def publish(c):
        for routine in (BUILD_REQUEST, FILTER_REQUEST, STATUS_TASK):
            call(c, routine)

    def mute(c):
        c.mem_write(AUDIO_GATE, b"\x00")

    def unmute(c):
        c.mem_write(AUDIO_GATE, b"\x01")

    # Stop in the first dash of an extra character before each blocked interval.
    with_partial_mark = pcm + pcm[:6240]  # 390 ms; the first dash starts at 300 ms.
    phases = [("receive", with_partial_mark, publish), ("request acknowledged", pcm, request(True)),
              ("stock transmit", pcm, publish), ("released, still transmit", pcm, request(False)),
              ("stock receive", with_partial_mark, publish), ("panel key down", pcm, panel(True)),
              ("panel key up", with_partial_mark, panel(False)), ("muted", pcm, mute), ("unmuted", pcm, unmute)]
    result = probe(cpu, phases, code, entry, 0, 1)
    expected = [(True, False, False, False, 0), (False, False, True, False, 0),
                (False, True, True, False, 0x8000), (False, True, False, False, 0x8000),
                (True, False, False, False, 0), (False, False, False, True, 0),
                (True, False, False, False, 0), (False, False, False, False, 0),
                (True, False, False, False, 0)]
    for row, (rx, tx, remote, key, filtered) in zip(result["stages"], expected, strict=True):
        require((row["rx_enabled"], row["stock_tx"], row["ci_v_request"], row["panel_ptt"],
                 row["request"], row["filtered"]) == (rx, tx, remote, key, filtered, filtered),
                f"unexpected receive/transmit boundary: {row}")
        require(row["text"] == (TEXT if rx else ""), f"unexpected CW output: {row}")
    require(stores == [1, 0], "stock status task did not publish transmit then receive")
    for i in (1, 5, 7):
        require(result["stages"][i-1]["mark_in_progress"] and result["stages"][i]["discarded_partial_samples"] > 0,
                "missing partial PCM or in-progress CW mark at the receive boundary")
    result["stock_status_stores"] = stores
    result["guest_gpio_accesses"] = [[kind, hex(address), size, value]
                                     for kind, address, size, value in sorted(accesses)]
    return result


def run(dat, evidence):
    main, _, _, digest, _ = load(dat.read_bytes())
    pcm = bytes(render(TEXT, 20, 600, None)) + bytes(8000)
    pcm += bytes(-len(pcm) % 12)
    # Use a separate mapping in the emulator, with no writes to the stock executable.
    with TemporaryDirectory() as folder:
        code, entry = build(Path(folder), address=TEST_CODE)
    control_pcm = pack("<108h", *range(100, 208))
    controls = [probe(radio(main, 0), [("control", control_pcm, None)], code, entry, enable, gate)
                for enable, gate in ((0, 0), (0, 1), (1, 0), (1, 1))]
    trial = probe(radio(main, 0), [("receive", pcm, None)], code, entry, 0, 1)
    require(trial["text"] == TEXT, "streaming ARM decoder did not match the reference")
    dsp = probe(radio(main, 0), [("receive", pcm + pcm[:6240], None),
                                ("DSP reports transmit", pcm, lambda c: feed_dsp_tx(c, True)),
                                ("DSP reports clear", pcm, lambda c: feed_dsp_tx(c, False))], code, entry, 0, 1)
    before, blocked, after = dsp["stages"]
    require(before["text"] == after["text"] == TEXT and before["mark_in_progress"]
            and blocked["dsp_tx"] and not blocked["stock_tx"] and not blocked["rx_enabled"]
            and blocked["discarded_partial_samples"] > 0 and after["rx_enabled"],
            "DSP transmit feedback did not stop and cleanly restart decoding")
    result = dict(stock_main_sha256=digest, test_only=True, expected=TEXT,
                  recording_off_stream=trial, gate_controls=controls,
                  receive_transmit_boundaries=transitions(main, pcm, code, entry), dsp_tx_boundaries=dsp)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(f"J140 PCM and receive transitions passed: {evidence}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    run(args.dat, args.evidence)
