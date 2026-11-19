"""Reproduce the D1 field PTT block using only the stock J140 guest and synthetic PCM."""

import argparse
import json
from hashlib import sha256
from pathlib import Path
from struct import iter_unpack, pack, unpack

from tools.build_705_cw_sim import load_image
from tools.emulate_705 import call
from tools.probe_705_cw_break_in import MAILBOX, UNPACK_STATUS, audio
from tools.probe_705_cw_field_audio import STATE, bl_target
from tools.probe_705_cw_pcm import (
    BUILD_REQUEST, DSP_STATUS, FILTER_REQUEST, FILTERED, KEY_ACTIVITY, LAYOUT,
    REC_TASK_STEP, REQUEST, feed_dsp_tx, simulated_gpio,
)
from tools.probe_705_cw_session import read_session
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC, completed, require
from tools.probe_705_tx_icon import ICON_FIELD
from tools.replay_705_ptt_tune import FLAGS, PANEL_PTT, PORT_PTT, PTT_PASSES, STATUS_TASK, byte, radio, word
from tools.replay_705_stock_install import load_a
from tools.replay_705_vfo_split import exchange_in_guest, read_in_guest


def replay(bundle, baseline_dat):
    (main, _, _, digest, _), meta = load_image(bundle)
    if baseline_dat is not None:
        require(load_a(baseline_dat, digest)[0] == main, "bundle and DAT do not contain the same application")
    cpu = radio(main, 0, pair=(145_149_300, 7_030_000), split=False)
    simulated_gpio(cpu)
    cpu.mem_map(DMAC, 4096)
    cpu.mem_write(meta["symbols"]["cw_state_anchor"], pack("<I", STATE))
    cpu.mem_write(STATE, pack("<2I", 1, 1))  # Isolated, already open CW page.
    cpu.mem_write(STATE+1692, pack("<I", 350))
    reply, _ = exchange_in_guest(cpu, bytes((6, 3, 1)))  # Stock CI-V selects CW/FIL1 in the guest.
    require(reply[2:-1] == b"\xfb", "stock CW mode change failed")
    cpu.mem_write(LAYOUT["rec_enable"], b"\x01")
    cpu.mem_write(AUDIO_GATE, b"\x01")
    worker = bl_target(main, meta["symbols"]["cw_rtx_worker"]+28)
    pcm = list(iter_unpack("<6h", audio("CQ", trim_leading=True)+bytes(3204)))

    def signals():
        call(cpu, 0x20095784)  # Original HOME icon selection; no display pixels injected.
        return dict(panel_bytes=bytes(cpu.mem_read(PANEL_PTT, 3)).hex(),
                    published_tx=bool(byte(cpu, FLAGS) & 0x80), command_tx=bool(byte(cpu, FLAGS) & 0x20),
                    request=word(cpu, REQUEST), filtered=word(cpu, FILTERED),
                    dsp_tx=bool(byte(cpu, DSP_STATUS) & 0x10), key=byte(cpu, KEY_ACTIVITY),
                    stock_status=read_in_guest(cpu, "1c 00")[0].hex(), stock_tx_icon=byte(cpu, ICON_FIELD))

    def scan(pressed):
        cpu.mem_write(PORT_PTT, pack("<H", 0 if pressed else 0x2000))
        for _ in range(3):
            for step in (*PTT_PASSES, BUILD_REQUEST, FILTER_REQUEST, STATUS_TASK):
                call(cpu, step)
        require(bool(byte(cpu, PANEL_PTT) & 1) == pressed, "stock scan did not follow the simulated pin")
        return signals()

    index = 0

    def receive(groups):
        nonlocal index
        cpu.mem_write(STATE+0x71c, bytes(24))  # Reset the test measurement window only.
        peak = 0
        for six in groups:
            wire = tuple(x for x in six for _ in range(6))
            completed(cpu, LAYOUT["rec_dma"], DMAC+0xE4, LAYOUT["rec_bank"], index,
                      wire, (0,)*36, timeout_us=0)
            index += 1
            call(cpu, REC_TASK_STEP, timeout_us=0)
            if read_session(cpu, STATE)["queued"]:
                call(cpu, worker, 1, timeout_us=0)
            peak = max(peak, *map(abs, read_session(cpu, STATE)["scope"]))
        counts = list(unpack("<6I", cpu.mem_read(STATE+0x71c, 24)))
        return dict(groups=len(groups), counts=counts, waveform_peak=peak, text=read_session(cpu, STATE)["text"])

    held = scan(True)
    require(not any(held[k] for k in ("published_tx", "command_tx", "request", "filtered", "dsp_tx", "key"))
            and held["stock_status"] == "00" and held["stock_tx_icon"] == 1,
            "simulated raw press did not stay in the stock receive state")
    replayed = receive(pcm[:666])
    report = dict(application_sha256=digest, input_held_by_fixture=held, first_666=replayed,
                  limitation="The simulated PTT pin does not identify the physical cause on the radio.")
    if baseline_dat is not None:
        require(replayed["counts"] == [666, 666, 0, 0, 3, 3] and not replayed["waveform_peak"],
                "D1 field pattern did not reproduce")
        report.update(dat_sha256=sha256(baseline_dat).hexdigest(), input_released_by_fixture=scan(False))
        remaining = pcm  # Send a fresh message after clearing raw PTT.
    else:
        require(replayed["counts"] == [666, 666, 666, 666, 3, 0] and replayed["waveform_peak"],
                "raw-only PTT still blocks the candidate")
        remaining = pcm[666:]
    ok = receive(remaining)
    require(ok["counts"][:4] == [len(remaining)]*4 and ok["waveform_peak"] and ok["text"].strip() == "CQ",
            "expected to decode the complete CQ message")
    report["normal_receive"] = ok
    if baseline_dat is not None:
        return report

    def transmit_command(down):
        reply, _ = exchange_in_guest(cpu, bytes((0x1c, 0, down)))
        require(reply[2:-1] == b"\xfb", "stock transmit request was not accepted in the guest")

    def must_block(reason):
        rx = receive(pcm[:24])
        require(rx["counts"] == [24, 24, 0, 0, 3, reason] and not rx["waveform_peak"] and rx["text"] == "CQ",
                f"receive guard {reason} failed: {rx}")
        return rx

    transmit_command(True)
    request_replay = must_block(2)
    transmit_command(False)
    feed_dsp_tx(cpu, True)
    dsp_replay = must_block(6)
    feed_dsp_tx(cpu, False)
    cpu.mem_write(MAILBOX, b"\x20")
    cpu.mem_write(MAILBOX+0x40, b"\x01")
    call(cpu, UNPACK_STATUS)
    require(byte(cpu, KEY_ACTIVITY), "stock DSP key status did not update")
    key_replay = must_block(7)
    cpu.mem_write(MAILBOX, b"\x00")
    call(cpu, UNPACK_STATUS)
    recovered = receive(pcm)
    require(recovered["counts"][:4] == [len(pcm)]*4 and recovered["text"].endswith("CQ"),
            "candidate did not resume after stock key/DSP cleared")
    report.update(request_block=request_replay, dsp_block=dsp_replay, key_block=key_replay, recovered=recovered)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("bundle", type=Path)
    p.add_argument("report", type=Path)
    p.add_argument("--baseline-dat", type=Path, help="verify against the exact field DAT and expect the original PTT block")
    a = p.parse_args()
    report = replay(a.bundle, a.baseline_dat.read_bytes() if a.baseline_dat else None)
    with a.report.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
