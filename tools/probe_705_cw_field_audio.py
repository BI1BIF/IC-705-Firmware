"""Trace the shipped J140 CW audio path in an isolated PC ARM guest.

Set PYTHONPATH=.analysis/ic705-emulator/deps and run:
python -m tools.probe_705_cw_field_audio <released.ic705sim> <new-report.json>

Feeds synthetic PCM to the original DMA-completion routine; never opens a radio
or creates an update image. The worker is called directly, so this separates
input and gating from RTOS scheduling, rather than validating scheduling again.
"""

import argparse
import json
from pathlib import Path
from struct import iter_unpack, pack, unpack

from tools.build_705_cw_sim import load_image
from tools.emulate_705 import BASE, SCRATCH, arm, call, machine, uc
from tools.probe_705_cw_break_in import audio
from tools.probe_705_cw_pcm import DECIMATED, LAYOUT, REC_TASK_STEP
from tools.probe_705_cw_session import read_session
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC, completed, require


RELEASE_MAIN = "1be7f473e2329f61537adf9d496d7dc2e9de1b48eceb9bf0bd8d89170aba0f70"
STATE = 0x20900000


def bl_target(main, address):
    op, = unpack("<I", main[address-BASE:address-BASE+4])
    require(op >> 24 == 0xeb, "expected an ARM call in the CW bridge")
    return address + 8 + ((op & 0x7fffff) - (op & 0x800000))*4


def measure(main, meta, worker, fixture, routing, override, *, recording=False, drain=True, audio_scope=None,
            replay_raw=False):
    cpu = machine(main)
    cpu.mem_map(DMAC, 4096)
    cpu.mem_write(meta["symbols"]["cw_state_anchor"], pack("<I", STATE))
    cpu.mem_write(STATE, pack("<2I", 1, 1))  # Isolated, already opened CW view.
    cpu.mem_write(STATE + 1692, pack("<I", 350))
    cpu.mem_write(0x203E2128, b"\x20")
    cpu.mem_write(AUDIO_GATE, b"\x01")
    recording |= override == (LAYOUT["rec_enable"], 1)
    if recording:
        cpu.mem_write(LAYOUT["rec_enable"], b"\x01")
    if override:
        address, value = override
        cpu.mem_write(address, bytes((value,)))
    stats = dict(dma_blocks=0, ring_peaks=[0, 0], tap_calls=0, tap_peak=0,
                 queued_groups=0, max_queued=0, worker_groups=0, waveform_peak=0, after_record_gate_peak=0)
    if replay_raw:
        require(audio_scope is not None, "earlier feed needs a raw capture")
        pcm = bl_target(main, meta["symbols"]["cw_pcm_bridge"] + 32)
        cpu.mem_write(DECIMATED, pack("<I", 0xe3a04000))  # Restore stock MOV in guest RAM only.
        stats["early_feed_groups"] = 0
    raw = scope = None
    if audio_scope is not None:
        cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
        cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
        cpu.mem_write(0x2038001E, bytes([audio_scope]))
        stats.update(raw_blocks=0, scope_blocks=0, recorder_samples_verified=0)

        def observe_raw(c, *_):
            nonlocal raw
            raw = unpack("<36h", c.mem_read(c.reg_read(arm.UC_ARM_REG_SP) + 32, 72))
            stats["raw_blocks"] += 1

        def observe_scope(c, *_):
            nonlocal scope
            scope = unpack("<36h", c.mem_read(c.reg_read(arm.UC_ARM_REG_R0), 72))
            stats["scope_blocks"] += 1

        cpu.hook_add(uc.UC_HOOK_CODE, observe_raw, begin=0x2010FE34, end=0x2010FE34)
        cpu.hook_add(uc.UC_HOOK_CODE, observe_scope, begin=0x20009DAC, end=0x20009DAC)

    def observe_tap(c, _addr, _size, _data):
        stats["tap_calls"] += 1
        six = unpack("<6h", c.mem_read(c.reg_read(arm.UC_ARM_REG_SP) + 8, 12))
        stats["tap_peak"] = max(stats["tap_peak"], *map(abs, six))
        if audio_scope is not None:
            require(raw is not None and raw[::6] == six, "earlier raw and current CW samples diverge")
            require(scope == (raw if audio_scope else None), "AUDIO SCOPE source or visibility differs")

    cpu.hook_add(uc.UC_HOOK_CODE, observe_tap, begin=DECIMATED, end=DECIMATED)
    for i, six in enumerate(fixture):
        raw = scope = None
        if routing is not None:
            if audio_scope is None:
                track = tuple(n for n in six for _ in range(6))
            else:
                following = six[1:] + (fixture[i+1][0] if i+1 < len(fixture) else 0,)
                track = tuple(a + (b-a)*k//6 for a,b in zip(six, following) for k in range(6))
            inputs = [(0,)*36, (0,)*36]
            inputs[routing] = track
            completed(cpu, LAYOUT["rec_dma"], DMAC+0xE4, LAYOUT["rec_bank"], i, *inputs, timeout_us=0)
            stats["dma_blocks"] += 1
            for lane, ring in enumerate((LAYOUT["rec_ring"], LAYOUT["rec_right"])):
                stored = unpack("<36h", cpu.mem_read(ring + (i % 8)*72, 72))
                require(stored == inputs[lane], f"original ring {lane} did not receive its slot")
                stats["ring_peaks"][lane] = max(stats["ring_peaks"][lane], *map(abs, stored))
        try:
            call(cpu, REC_TASK_STEP, timeout_us=0)
        except uc.UcError as err:
            raise ValueError(f"stock audio task failed at {cpu.reg_read(arm.UC_ARM_REG_PC):#x}, block {i}, scope={audio_scope}") from err
        if audio_scope is not None:
            require(raw == inputs[0] and stats["tap_calls"] == i+1, "PCM lost between DMA and the two taps")
        if replay_raw:
            require(read_session(cpu, STATE)["queued"] == 0, "current hook still queued data in earlier feed control")
            cpu.mem_write(SCRATCH, pack("<6h", *raw[::6]))
            call(cpu, pcm, SCRATCH, timeout_us=0)
            stats["early_feed_groups"] += 1
        q = read_session(cpu, STATE)["queued"]
        stats["max_queued"] = max(q, stats["max_queued"])
        if drain and q:
            stats["queued_groups"] += q
            stats["worker_groups"] += call(cpu, worker, 1, timeout_us=0)
            stats["waveform_peak"] = max(stats["waveform_peak"], *map(abs, read_session(cpu, STATE)["scope"]))
        if recording and i % 18 == 17:
            # Sample the slot just completed by the stock first-track recorder.
            slot = LAYOUT["rec_stage"] + 0x271c8 + (i//18)*220
            stored = unpack("<108h", cpu.mem_read(slot, 216))
            stats["after_record_gate_peak"] = max(stats["after_record_gate_peak"], *map(abs, stored))
            if audio_scope is not None:
                require(stored == tuple(n for group in fixture[i-17:i+1] for n in group), "first recording track differs")
                stats["recorder_samples_verified"] += len(stored)
    state = read_session(cpu, STATE)
    return dict(stats, cw_blocked=bool(state["blocked"]), text=state["text"],
                audio_gate=cpu.mem_read(AUDIO_GATE, 1)[0])


def compare_lan(main):
    results = {}
    inputs = tuple(range(-18000, 18000, 1000))
    for name, enabled in (("stock_permit_off", False), ("stock_permit_on", True)):
        cpu = machine(main)
        cpu.mem_map(DMAC, 4096)
        cpu.mem_write(0x2038026D, bytes([enabled]))
        cpu.mem_write(LAYOUT["lan_ramp"] + 2, pack("<H", 480 if enabled else 0))
        raw = []

        def before_network_gain(c, *_):
            n = c.reg_read(arm.UC_ARM_REG_R1) & 0xffff
            raw.append(n - 65536 if n >= 32768 else n)

        cpu.hook_add(uc.UC_HOOK_CODE, before_network_gain, begin=0x20100124, end=0x20100124)
        completed(cpu, LAYOUT["lan_dma"], DMAC+0x524, LAYOUT["lan_bank"], 0, inputs, (0,) * 36, timeout_us=0)
        post_gain = unpack("<72h", cpu.mem_read(LAYOUT["lan_ring"], 144))[::2]
        require(tuple(raw) == inputs and post_gain == (inputs if enabled else (0,) * 36), "WLAN alternate-source contrast failed")
        results[name] = dict(raw_samples=len(raw), raw_peak=max(map(abs, raw)), ring_peak=max(map(abs, post_gain)))
    return results


def run(path, *, candidate=False, field_recording=False, source_comparison=False):
    (main, _, _, digest, _), meta = load_image(path)
    require(meta.get("picker_id") == 277 and (digest != RELEASE_MAIN if candidate else digest == RELEASE_MAIN),
            "expected the specified single-entry baseline or candidate image")
    worker = bl_target(main, meta["symbols"]["cw_rtx_worker"] + 28)
    raw = audio("CQ", trim_leading=True) + bytes(3204)
    fixture = list(iter_unpack("<6h", raw[:len(raw)//12*12]))
    if source_comparison:
        # The short positive control exercises the real input routine before its
        # unmodeled FFT task wakes; the full controls exercise the CW decoder.
        cases = {name: measure(main, meta, worker, fixture[:120] if scope else fixture, 0, None,
                               recording=recording, audio_scope=scope)
                 for name, scope, recording in (("cw_only", False, False), ("cw_and_record", False, True),
                                                 ("scope_forced_in_guest", True, True))}
        for name in ("cw_only", "cw_and_record"):
            row = cases[name]
            require(row["raw_blocks"] == row["worker_groups"] == len(fixture) and row["text"].strip() == "CQ",
                    f"{name}: decoder feed comparison failed")
        require(cases["cw_only"]["scope_blocks"] == cases["cw_and_record"]["scope_blocks"] == 0 and
                cases["scope_forced_in_guest"]["scope_blocks"] == 120, "unexpected native scope callback")
        for name, guard in (("earlier_raw", None), ("earlier_raw_tx_guard", (0x203809a1, 0x10))):
            cases[name] = measure(main, meta, worker, fixture, 0, guard, recording=True, audio_scope=False, replay_raw=True)
        earlier, guarded = cases["earlier_raw"], cases["earlier_raw_tx_guard"]
        require(earlier["early_feed_groups"] == earlier["worker_groups"] == len(fixture) and
                earlier["text"].strip() == "CQ" and earlier["waveform_peak"] == cases["cw_and_record"]["waveform_peak"],
                "earlier PCM feed did not match the current feed")
        require(guarded["early_feed_groups"] == len(fixture) and guarded["after_record_gate_peak"] > 0 and
                not guarded["waveform_peak"] and not guarded["max_queued"], "changing sources bypassed the receive guard")
        return dict(application_sha256=digest, groups=len(fixture), cases=cases, separate_wlan=compare_lan(main),
                    note="isolated CW-open fixture; stock scope flag forced for a short positive control; WLAN input simulated independently")
    if field_recording:
        # Keep stock recording on in every case. Withholding the worker is a
        # diagnostic control, not a board scheduling reproduction.
        scenarios = {
            "recording_normal": (None, True),
            "recording_worker_withheld": (None, False),
            "recording_key_status": ((0x203e1e68, 1), True),
            "recording_tx_pending": ((0x203809ad, 0x80), True),
            "recording_dsp_tx_feedback": ((0x203809a1, 0x10), True),
        }
        fixture = fixture[:180]
        results = {label: measure(main, meta, worker, fixture, 0, override, recording=True, drain=drain)
                   for label, (override, drain) in scenarios.items()}
        for name, result in results.items():
            require(result["tap_peak"] == result["after_record_gate_peak"] > 0, f"{name}: no stock recording audio")
        normal, withheld = results["recording_normal"], results["recording_worker_withheld"]
        require(normal["worker_groups"] == len(fixture) and normal["waveform_peak"] > 0, "normal RX did not draw a waveform")
        require(withheld["max_queued"] > 0 and not withheld["worker_groups"] and not withheld["waveform_peak"], "worker control failed")
        for name in ("recording_key_status", "recording_tx_pending", "recording_dsp_tx_feedback"):
            result = results[name]
            require(result["cw_blocked"] and not result["max_queued"] and not result["waveform_peak"], f"{name}: guard control failed")
        return dict(application_sha256=digest, groups=len(fixture), worker=hex(worker), scenarios=results)
    scenarios = {
        "slot_0": (0, None), "slot_1": (1, None), "no_dma": (None, None),
        "gate_zero": (0, (AUDIO_GATE, 0)), "gate_two": (0, (AUDIO_GATE, 2)),
        "dsp_tx": (0, (0x203809a1, 0x10)), "early_key": (0, (0x203e1e68, 1)),
        "request_pending": (0, (0x203809ad, 0x80)),
        "recording_slot_0": (0, (LAYOUT["rec_enable"], 1)),
        "recording_slot_1": (1, (LAYOUT["rec_enable"], 1)),
    }
    results = {label: measure(main, meta, worker, fixture, *params) for label, params in scenarios.items()}
    peak = max(abs(n) for group in fixture for n in group)
    positive = results["slot_0"]
    require(positive["text"].strip() == "CQ" and positive["tap_peak"] == peak and
            positive["waveform_peak"] > 0 and positive["worker_groups"] == len(fixture), f"positive control failed: {positive}")
    other = results["slot_1"]
    require(other["ring_peaks"] == [0, peak] and not other["tap_peak"] and not other["waveform_peak"] and
            not other["text"] and other["worker_groups"] == len(fixture), "second-lane control failed")
    for name in ("dsp_tx", "early_key", "request_pending", *(() if candidate else ("gate_zero", "gate_two"))):
        blocked = results[name]
        require(blocked["tap_peak"] == peak and blocked["cw_blocked"] and
                not blocked["queued_groups"] and not blocked["waveform_peak"], f"{name} negative control failed")
    if candidate:
        for name in ("gate_zero", "gate_two"):
            rx = results[name]
            require(rx["queued_groups"] == rx["worker_groups"] == len(fixture) and rx["waveform_peak"] == peak and
                    rx["text"].strip() == "CQ" and not rx["cw_blocked"], f"{name}: valid RX PCM did not reach CW")
    require(not results["no_dma"]["tap_calls"], "unexpected PCM in the no-DMA control")
    require(results["recording_slot_0"]["after_record_gate_peak"] == peak and
            not results["recording_slot_1"]["after_record_gate_peak"], "stock first-track comparison failed")
    return dict(application_sha256=digest, candidate=candidate, groups=len(fixture), worker=hex(worker), scenarios=results)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("image", type=Path)
    p.add_argument("report", type=Path)
    p.add_argument("--candidate", action="store_true", help="require corrected receive behavior")
    compare = p.add_mutually_exclusive_group()
    compare.add_argument("--field-recording", action="store_true", help="compare queue and worker stages while stock recording has PCM")
    compare.add_argument("--source-comparison", action="store_true", help="compare raw, AUDIO SCOPE and recorder PCM with the CW view active")
    a = p.parse_args()
    result = run(a.image, candidate=a.candidate, field_recording=a.field_recording, source_comparison=a.source_comparison)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    with a.report.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    print(a.report)


if __name__ == "__main__":
    main()
