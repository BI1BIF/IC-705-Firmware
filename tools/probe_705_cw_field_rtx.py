"""Check the shipped J140 CW task with audio arriving before its first wait.

Set PYTHONPATH=.analysis/ic705-emulator/deps and run:
python -m tools.probe_705_cw_field_rtx stock.dat released.ic705sim new-report.json

Uses the original ARM scheduler and reads the released PC image. No updater,
radio, or direct call to the CW worker is used. UI delay is a test input.
"""

import argparse
import json
from pathlib import Path
from struct import pack, unpack

from tools.build_705_cw_sim import load_image
from tools.emulate_705 import BASE, uc
from tools.probe_705_cw_field_audio import RELEASE_MAIN
from tools.probe_705_cw_pcm import DECIMATED, LAYOUT
from tools.probe_705_cw_session import read_session
from tools.probe_705_rtx_audio import (
    AUDIO_GATE, CURRENT, DMA_TIMER, DMAC, IDLE, LOOP, PCM_DONE, PCM_STEP, SEM_WAIT,
    TIMER, TIMERS_CLEARED, UI_HANDLE, audio, probe, require,
)
from tools.render_705_display import load


def exercise(field_rtx, cpu, run, irq, reg, value):
    app, meta, ui_batches = field_rtx
    base = meta["code_base"]
    stock_main = value(CURRENT)
    cpu.mem_write(base, app[base-BASE:])
    for at in (TIMERS_CLEARED, DECIMATED):
        cpu.mem_write(at, app[at-BASE:at-BASE+4])
        cpu.ctl_remove_cache(at, at+4)
    run(TIMERS_CLEARED, PCM_STEP)
    state = value(meta["symbols"]["cw_state_anchor"])
    thread = value(state+0x700) if state else 0
    require(state and thread and value(CURRENT) == stock_main and
            value(thread+2, 1) == 0xe9, "the shipped launcher did not attach the stock CW task")
    # Opened-session fixture; entry and LCD are tested separately.
    cpu.mem_write(state, pack("<2I", 1, 1))
    cpu.mem_write(state+1692, pack("<I", 350))
    for addr, data in ((0x203E2128, b"\x20"), (AUDIO_GATE, b"\x01"), (0x20380874, b"\x01")):
        cpu.mem_write(addr, data)
    for offset in (0x124, 0x424, 0x524):
        cpu.mem_write(DMAC+offset, pack("<I", 1))

    pcm = audio("T", trim_leading=True)
    sent, initial_wait_returns = 0, []
    wait_return = meta["symbols"]["cw_rtx_worker"] + 16
    cpu.hook_add(uc.UC_HOOK_CODE, lambda *_: initial_wait_returns.append(reg("R0")),
                 begin=wait_return, end=wait_return)

    def send(count, background):
        nonlocal sent
        for _ in range(count):
            six = unpack("<6h", pcm[sent*12:sent*12+12])
            interleaved = [v for a in six for v in ((a & 0xffff) << 16, 0)*6]
            bank = sent % 2
            cpu.mem_write(LAYOUT["rec_bank"]+bank*0x120, pack("<72I", *interleaved))
            cpu.mem_write(DMAC+0xe4, pack("<I", 0x41 if bank else 0xc1))
            irq(DMA_TIMER, background)
            sent += 1
        cpu.mem_write(DMAC+0xe4, pack("<I", 1))

    def measure():
        s = read_session(cpu, state)
        return dict(queued=s["queued"], drops=s["drops"], fed=s["fed"],
                    wave_peak=max(map(abs, s["scope"])), pending_event=value(thread+24, 2))

    send(6, PCM_STEP)
    run(PCM_STEP, PCM_DONE)
    before_wait = measure()
    require(before_wait["queued"] == 6 and before_wait["pending_event"] & 1 and not initial_wait_returns,
            f"no queued PCM before the first wait: {before_wait}")
    run(LOOP, SEM_WAIT)
    require(value(CURRENT) == value(UI_HANDLE), "stock UI did not run before new lower-priority CW task")

    def tick_from(background):
        for n in (1, 2):
            irq(TIMER, background)
            irq(0, LOOP)
            run(LOOP, background if n == 1 else PCM_STEP)
        run(PCM_STEP, PCM_DONE)
        run(LOOP, background if background == SEM_WAIT else IDLE)

    for _ in range(ui_batches):
        # Hold the ready UI at its real semaphore entry while main has more PCM.
        send(6, SEM_WAIT)
        tick_from(SEM_WAIT)
        require(value(CURRENT) == value(UI_HANDLE) and not initial_wait_returns,
                "test delay unexpectedly dispatched the lower-priority CW task")

    before_release = measure()
    run(SEM_WAIT, IDLE)
    after_release = measure()
    require(initial_wait_returns == [8] and after_release["queued"] == 0 and after_release["wave_peak"] > 0,
            f"stock worker did not consume its preposted event: {initial_wait_returns}, {after_release}")
    send(6, IDLE)
    tick_from(IDLE)
    after_next = measure()
    require(initial_wait_returns == [8, 8] and after_next["queued"] == 0 and after_next["wave_peak"] > 0,
            f"stock worker missed a notification after going to sleep: {initial_wait_returns}, {after_next}")
    expected_drops = 0 if not ui_batches else 64
    require(before_release["drops"] == after_next["drops"] == expected_drops and
            before_release["queued"] == sent-6-expected_drops, "unexpected queue retention during the delay")
    return dict(thread=hex(thread), worker_priority=value(thread+2, 1), ui_priority=value(value(UI_HANDLE)+2, 1),
                before_wait=before_wait, before_ui_releases=before_release, after_ui_releases=after_release,
                after_next=after_next, input_groups=sent, wait_results=initial_wait_returns)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dat", type=Path)
    p.add_argument("image", type=Path)
    p.add_argument("report", type=Path)
    a = p.parse_args()
    (app, _, _, digest, _), meta = load_image(a.image)
    require(digest == RELEASE_MAIN, "expected the single-entry release")
    report = dict(released_main_sha256=digest, scenarios={})
    stock = load(a.dat.read_bytes())[0]
    for name, batches in (("audio_before_first_wait", 0), ("ui_delay_past_queue_capacity", 11)):
        report["scenarios"][name] = probe(stock, field_rtx=(app, meta, batches))
    a.report.parent.mkdir(parents=True, exist_ok=True)
    with a.report.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(a.report)


if __name__ == "__main__":
    main()
