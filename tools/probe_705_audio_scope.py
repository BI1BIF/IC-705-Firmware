"""Trace J140's original AUDIO SCOPE and CW's existing PCM point back to SSIF0."""

import argparse
import json
from pathlib import Path
from struct import unpack

from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC, LAYOUTS, completed, require, samples
from tools.render_705_display import load
from tools.virtual_705_panel import start


def verify(images):
    cases = {}
    layout = LAYOUTS["705J140"]
    for scope, placement in ((True, "first"), (True, "second"), (False, "first")):
        guest = start(images)
        cpu = guest.cpu
        cpu.mem_write(guest.language_address, bytes(2))
        for address in (MODE_UI_A, MODE_VFO_A):
            cpu.mem_write(address, b"\x20")
        guest.render()
        if scope:
            guest.press_menu()
            guest.render()
            guest.click(145, 76)
            labels, _ = guest.render()
            require("AUDIO SCOPE" in labels, f"wrong stock page: {labels}")
        require(cpu.mem_read(0x2038001E, 1)[0] == scope, "original scope did not enable its consumer")
        cpu.mem_map(DMAC, 0x1000)
        waveform, downstream = [], []

        def raw(c, _pc, _size, _):
            waveform.append(unpack("<36h", c.mem_read(c.reg_read(arm.UC_ARM_REG_R0), 72)))

        def decimated(c, _pc, _size, _):
            downstream.append(unpack("<6h", c.mem_read(c.reg_read(arm.UC_ARM_REG_SP) + 8, 12)))

        cpu.hook_add(uc.UC_HOOK_CODE, raw, begin=0x20009DAC, end=0x20009DAC)
        cpu.hook_add(uc.UC_HOOK_CODE, decimated, begin=0x2010FEAC, end=0x2010FEAC)
        first_blocks = []
        # Enough for the native waveform sampler; FFT startup/board scheduling
        # is outside this input-point comparison.
        for block in range(120):
            signal = samples(block)[0]
            zero = (0,) * len(signal)
            first, second = (signal, zero) if placement == "first" else (zero, signal)
            first_blocks.append(first)
            completed(cpu, layout["rec_dma"], DMAC + 0xE4, layout["rec_bank"], block, first, second)
            try:
                call(cpu, layout["rec_consume"])
            except uc.UcError as e:
                raise ValueError(f"unmodeled audio-scope operation at {cpu.reg_read(arm.UC_ARM_REG_PC):#x}, block {block}") from e
        require(waveform == (first_blocks if scope else []), "stock AUDIO SCOPE did not see the first SSIF0 slot")
        require(downstream == [v[::6] for v in first_blocks], "the later CW hook saw a different slot")
        cases[f"{'audio_scope' if scope else 'home'}_{placement}"] = {
            "audio_scope_raw_blocks": len(waveform),
            "audio_scope_input_peak": max((abs(v) for block in waveform for v in block), default=0),
            "decimated_hook_blocks": len(downstream),
            "decimated_hook_peak": max(abs(v) for block in downstream for v in block),
        }
    return {"stock_main_sha256": images[3], "mode": "CW", "cases": cases,
            "input": "synthetic SSIF0 DMA blocks; not board capture"}


def verify_transition(images):
    """Compare the original AUDIO screen and CW pickup across one guest session."""
    guest = start(images)
    cpu, layout = guest.cpu, LAYOUTS["705J140"]
    cpu.mem_write(guest.language_address, bytes(2))
    for address in (MODE_UI_A, MODE_VFO_A):
        cpu.mem_write(address, b"\x20")
    guest.render()
    cpu.mem_map(DMAC, 0x1000)
    raw, down = [], []

    def capture(pc, reg, offset, size, sink):
        def read(c, _pc, _size, _):
            sink.append(unpack(f"<{size}h", c.mem_read(c.reg_read(reg) + offset, 2 * size)))
        cpu.hook_add(uc.UC_HOOK_CODE, read, begin=pc, end=pc)

    capture(0x20009DAC, arm.UC_ARM_REG_R0, 0, 36, raw)
    capture(0x2010FEAC, arm.UC_ARM_REG_SP, 8, 6, down)

    phases = []
    for name, scope, gate in (("home_before", False, 0), ("audio_gate_0", True, 0),
                              ("audio_gate_1", True, 1), ("home_after", False, 1)):
        if name == "audio_gate_0":
            guest.press_menu()
            guest.render()
            guest.click(145, 76)
        elif name == "home_after":
            guest.press_exit()
        labels, _ = guest.render()
        require(("AUDIO SCOPE" in labels) == scope, f"{name}: wrong visible screen")
        enabled, = cpu.mem_read(0x2038001E, 1)
        require(enabled == scope, f"{name}: AUDIO consumer state disagrees with the screen")
        cpu.mem_write(AUDIO_GATE, bytes((gate,)))  # Model input states; not a firmware edit.
        raw.clear()
        down.clear()
        expected = []
        for index in range(60):
            i = 60 * len(phases) + index
            left, right = samples(i)
            expected.append(left)
            completed(cpu, layout["rec_dma"], DMAC + 0xE4, layout["rec_bank"], i, left, right)
            call(cpu, layout["rec_consume"])
        require(raw == (expected if scope else []), f"{name}: original scope sample mismatch")
        require(down == [v[::6] for v in expected], f"{name}: samples lost before CW pickup")
        phases.append(dict(phase=name, scope_enable=enabled, recording_gate=gate,
                           scope_blocks=len(raw), cw_pickup_blocks=len(down),
                           scope_peak=max((abs(n) for b in raw for n in b), default=0),
                           cw_pickup_peak=max(abs(n) for b in down for n in b)))
    return {"stock_main_sha256": images[3], "mode": "CW", "phases": phases,
            "input": "same guest; synthetic SSIF0 DMA; controlled recording gate; no radio or CW worker"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="original Japanese 1.40 DAT")
    parser.add_argument("--transition", action="store_true", help="test AUDIO entry/exit in one guest")
    args = parser.parse_args()
    probe = verify_transition if args.transition else verify
    print(json.dumps(probe(load(args.dat.read_bytes())), indent=2))
