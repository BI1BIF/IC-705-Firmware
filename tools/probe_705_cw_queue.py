"""Measure J140's CW handoff and exercise delayed work and preemption offline."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory

from tools.emulate_705 import STOP, arm, call, uc
from tools.probe_705_cw_break_in import audio
from tools.probe_705_cw_pcm import DECIMATED, feed_dsp_tx
from tools.probe_705_cw_session import Lab, WORKER_STACK, build, pcm_ranges
from tools.render_705_display import load
from tools.render_705_stock_row import require


def open_cw(lab):
    guest = lab.guest
    guest.press_menu()
    guest.render()
    require(guest.click(80, 247) == 0 and lab.view()["active"], "CW menu did not open")


def trial(images, extension):
    lab = Lab(images, *extension)
    cpu, guest = lab.cpu, lab.guest
    lab.mode(2)
    guest.render()
    open_cw(lab)
    pcm = audio("CQ TEST 123")
    published_text = []
    tapped = []

    def read_pcm(c, *_):
        sp = c.reg_read(arm.UC_ARM_REG_SP)
        tapped.append(bytes(c.mem_read(sp+8, 12)))

    tap = cpu.hook_add(uc.UC_HOOK_CODE, read_pcm, begin=lab.hooks[DECIMATED], end=lab.hooks[DECIMATED])

    # Count instructions only for short runs so the long replay can use native emulation speed.
    steps = {"capture": [], "worker": []}
    active = None
    length = 0
    detector_runs = 0

    def count(c, addr, *_):
        nonlocal active, length, detector_runs
        if addr == lab.hooks[DECIMATED]:
            active, length = "capture", 0
        elif addr == lab.symbols["cw_lab_work"]:
            active, length = "worker", 0
        elif addr == 0x2010FEB0 and active == "capture":
            steps[active].append(length)
            active = None
        if addr == lab.symbols["cw_feed"]:
            require(active == "worker", "detector ran in capture")
            require(not c.reg_read(arm.UC_ARM_REG_CPSR) & 0x80, "detector ran with IRQ masked")
            detector_runs += 1
        if active:
            length += 1

    tracing = cpu.hook_add(uc.UC_HOOK_CODE, count)
    lab.feed(pcm[:384], service=0)
    require(detector_runs == 0 and lab.view()["queued"] == 32 and not lab.view()["text"],
            "capture invoked detector or failed to queue")
    lab.work(32)
    steps["worker"].append(length)
    active = None
    cpu.hook_del(tracing)
    require(detector_runs == 2 and len(steps["capture"]) == 32, "instruction trace incomplete")

    # Repeatedly draw the original MENU and live text between capture and worker.
    # Batches of 60 represent 45 ms of supplied 8 kHz PCM.
    delay_groups, draws, highest = 60, 0, 0
    for batch, offset in enumerate(range(384, len(pcm), delay_groups * 12)):
        part = pcm[offset:offset+delay_groups*12]
        # Measure a second worker batch where the fixture has a nonzero tone.
        measure = batch == 7 and any(part)
        if measure:
            tracing = cpu.hook_add(uc.UC_HOOK_CODE, count)
        state = lab.feed(part, service=0)
        highest = max(highest, state["queued"])
        require(state["queued"] == len(part)//12 and not state["drops"], "worker lag lost samples")
        if not measure and (batch < 4 or batch % 20 == 0):
            require(guest.render()[0] == ["MENU"], "stock redraw changed page")
            call(cpu, lab.draw, instruction_limit=4_000_000)
            guest.surface.select_target()
            draws += 1
        lab.work(delay_groups)
        if measure:
            steps["worker"].append(length)
            active = None
            cpu.hook_del(tracing)
        published_text.append(lab.view()["text"])
    state = lab.view()
    require(state["text"] == "CQ TEST 123" and not state["drops"] and
            state["fed"] == (len(pcm)//2)//80 and not state["queued"], "deferred replay lost words or blocks")
    require(all(b.startswith(a) for a, b in zip(published_text, published_text[1:])), "transcript regressed")
    require(state["scope"] == pcm_ranges(pcm), "waveform differs from input PCM")
    cpu.hook_del(tap)
    require(b"".join(tapped) == pcm and len(steps["worker"]) == 2,
            "stock PCM or timing sample differed")

    # Saturate the extension queue. Original DMA must still advance and no stale
    # prefix/half-symbol may leak from either the dropped queue or detector state.
    packets = pack("<390h", *range(1, 391))  # 65 groups, one more than capacity
    state = lab.feed(packets, service=0)
    require((state["queued"], state["drops"], state["partial_symbol"]) == (1, 64, False),
            "overflow did not leave only the newest group in a new epoch")
    require(lab.work() == 1 and lab.view()["scope"] == pcm_ranges(packets[-12:]),
            "overflow retained old scope samples")
    state = lab.feed(audio("DE IC705"))
    require(state["text"] == "CQ TEST 123 DE IC705", "recovery decoder read a mixed symbol")

    def interleave(action):
        # Suspend during the original instruction stream of the ARM detector.
        # Run a stock event on a separate stack, then restore the worker's CPU context.
        stop_at = lab.symbols["cw_feed"] + 4
        contexts = []

        def suspend(c, *_):
            contexts.append(c.context_save())
            c.emu_stop()

        hook = cpu.hook_add(uc.UC_HOOK_CODE, suspend, begin=stop_at, end=stop_at)
        cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1f)
        cpu.reg_write(arm.UC_ARM_REG_SP, WORKER_STACK)
        cpu.reg_write(arm.UC_ARM_REG_LR, STOP)
        cpu.reg_write(arm.UC_ARM_REG_R0, 32)
        cpu.emu_start(lab.symbols["cw_lab_work"], STOP, count=150_000)
        cpu.hook_del(hook)
        require(len(contexts) == 1 and not cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80,
                "did not preempt an interruptible decode")
        action()
        cpu.context_restore(contexts[0])
        cpu.emu_start(stop_at, STOP, count=150_000)
        require(cpu.reg_read(arm.UC_ARM_REG_PC) == STOP, "worker did not return after preemption")

    def tx():
        lab.civ_request(True)  # No intervening audio or TX publication.

    lab.feed(pcm[:384], service=0)
    interleave(tx)
    after_tx = lab.view()
    require(after_tx["blocked"] and after_tx["fed"] == state["fed"] and
            after_tx["text"] == state["text"] and not after_tx["queued"] and not any(after_tx["scope"]),
            "preempting TX request allowed stale work to publish")
    lab.publish()
    feed_dsp_tx(cpu, True)
    lab.civ_request(False)
    lab.publish()
    feed_dsp_tx(cpu, False)
    lab.feed(pcm[:384], service=0)

    def close_reopen():
        guest.press_exit()
        require(not lab.view()["active"], "EXIT did not close during decode")
        guest.render()
        open_cw(lab)

    interleave(close_reopen)
    reopened = lab.view()
    require(reopened["active"] and not reopened["text"] and not reopened["fed"] and not any(reopened["scope"]),
            "worker published into a new session")
    require(lab.feed(pcm)["text"] == "CQ TEST 123", "reopened session did not decode normally")
    return dict(stock_main_sha256=guest.main_hash, dma_groups=lab.blocks, max_queued=highest,
                scheduled_lag_ms=delay_groups * 0.75, interleaved_draw_passes=draws,
                capture_instruction_count=dict(min=min(steps["capture"]), max=max(steps["capture"])),
                worker_instructions_for_32_silent_groups=steps["worker"][0],
                worker_instructions_for_60_tone_groups=steps["worker"][1], detector_calls_measured=detector_runs,
                original_pcm_exact=True, pcm_sha256=sha256(pcm).hexdigest(),
                queue_capacity=64, controlled_overflow_drops=64,
                early_tx_and_exit_preemption=True, transcript_recovered=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    original = args.dat.read_bytes()
    with TemporaryDirectory() as folder:
        result = trial(load(original), build(Path(folder)))
    require(args.dat.read_bytes() == original, "original DAT changed")
    result["original_dat_sha256"] = sha256(original).hexdigest()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"J140 CW queue: {result['dma_groups']} stock DMA groups; {args.evidence}")


if __name__ == "__main__":
    main()
