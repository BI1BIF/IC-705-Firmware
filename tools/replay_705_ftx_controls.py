"""Panel-side J140 replay with the RX-only guest module loaded in test memory."""

import json
from io import BytesIO
from struct import pack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from elftools.elf.elffile import ELFFile
from PIL import Image, ImageChops
from tools import render_705_stock_row as renderer
from tools.build_705_cw_sim import load_image
from tools.build_705_cw_sstv_rx import D6
from tools.emulate_705 import BASE, arm, call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_cw_session import read_session, build as build_cw
from tools.probe_705_cw_pcm import DECIMATED
from tools.probe_705_rtx_audio import probe
from tools.probe_705_sstv_picture import frame, tick
from tools.render_705_display import load
from tools.replay_705_ftx_live import BASELINE, Guest, LAB, LIB, ROOT, build, decode_main, recording
from tools.replay_705_settings import GRID_PAGE, KEY_EVENT, SettingsGuest
from tools.replay_705_ftx_arm import PCM
from tools.replay_705_ptt_tune import INIT_RANGES
from tools.replay_705_vfo_split import SELECT_VFO, exchange_in_guest, seed_vfos


def dial_trial(elf):
    """Observe a real stock UI frame for each tune while the guest RX runs."""

    def attach(cpu, surface):
        context = cpu.context_save()
        g = Guest(elf, cpu, map_dma=False)
        cpu.context_restore(context)
        pending = []
        captured = 0
        discarded = 0
        last_hz = 0
        active = False
        snapshots = []

        def observe(c, *_):
            if active:
                pending.append(bytes(c.mem_read(c.reg_read(arm.UC_ARM_REG_SP) + 8, 12)))

        cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=DECIMATED, end=DECIMATED)

        def overlay():
            nonlocal captured, discarded, last_hz
            if not active:
                return
            state = cpu.context_save()
            try:
                # Snapshot the VFO after the input bank is consumed. If it has
                # moved, discard this frame's ambiguous samples on both sides
                # of the tune and resume at the next complete slot.
                hz = int.from_bytes(cpu.mem_read(0x20380714, 4), "little")
                first = captured + 6 * len(pending)
                if last_hz and hz != last_hz:
                    discarded += 6 * len(pending)
                    pending.clear()
                    captured = first
                g.call("live_vfo", hz, captured, captured // 120000, captured % 120000)
                last_hz = hz
                for pcm in pending:
                    cpu.mem_write(PCM, pcm)
                    g.call("live_capture", PCM, captured)
                    captured += 6
                pending.clear()
                while g.call("live_pending"):
                    g.call("live_poll")
                surface.select_target()
                header = bytes(surface.pixels[: 480 * 86 * 4])
                g.call("view_draw", 0, captured)
                surface.select_target()
                assert bytes(surface.pixels[: len(header)]) == header
                snapshots.append(Image.frombytes("RGBA", (480, 272), bytes(surface.pixels)).convert("RGB"))
            finally:
                cpu.context_restore(state)

        def trial(turn, step, tap, frames):
            nonlocal active
            tap(37, 32)
            for _ in range(6):
                step()
            tap(329, 241)
            for _ in range(8):
                step()
            assert any("USB-D" in f["glyphs"] for f in frames), frames[-1]["glyphs"]
            control = turn(1)
            state = cpu.context_save()
            g.call("live_open", 0, 0, 0, 0)
            cpu.context_restore(state)
            active = True
            for _ in range(6):
                step()
            before = snapshots[-1]
            down = turn(-1)
            after = snapshots[-1]
            up = turn(1)
            assert (
                0 < discarded < captured
                and up["after"] == control["after"]
                and down["after"] == control["before"]
            )
            area = (150, 38, 373, 85)
            assert ImageChops.difference(before.crop(area), after.crop(area)).getbbox()
            after.save(LAB / "native-dial-rtx.png")
            return dict(
                stock=control,
                rx_down=down,
                rx_up=up,
                mode="USB-D",
                ftx_frames=len(snapshots),
                captured_samples=captured,
                discarded_around_tunes=discarded,
                header_matches_stock=True,
                frequency_digits_changed=True,
            )

        return overlay, trial

    images = load((ROOT / "firmware/705J140.dat").read_bytes())
    with TemporaryDirectory() as folder:
        return probe(
            images[0],
            build_cw(Path(folder), rtx=True),
            graphics=images,
            render_output=Path(folder),
            screen=True,
            live=True,
            panel_experiment=attach,
        )


def main(elf=None):
    if elf is None:
        elf = build()
    with patch.object(renderer, "HEAP_START", 0x20700000):
        panel = SettingsGuest(load((ROOT / "firmware/705J140.dat").read_bytes()), front_panel=True)
    cpu = panel.cpu
    main_image = bytes(decode_main(BASELINE.read_bytes())[1])
    cpu.mem_write(BASE, main_image)
    cpu.ctl_remove_cache(BASE, BASE + len(main_image))
    cpu.mem_write(panel.language_address, bytes(2))
    with (BASELINE.parent / "build/rx.elf").open("rb") as f:
        symbols = {s.name: s["st_value"] for s in ELFFile(f).get_section_by_name(".symtab").iter_symbols()}
    # Same simulated scheduler endpoints as the existing isolated panel probe.
    cpu.mem_write(symbols["sstv_thread"], pack("<I", 1))

    def event(cpu, *_):
        cpu.reg_write(arm.UC_ARM_REG_R0, 0)
        cpu.reg_write(arm.UC_ARM_REG_PC, cpu.reg_read(arm.UC_ARM_REG_LR))

    cpu.hook_add(uc.UC_HOOK_CODE, event, begin=0x202D4850, end=0x202D4850)
    g = Guest(elf, cpu)
    seed_vfos(cpu, (14074000, 14080000))
    call(cpu, INIT_RANGES)
    call(cpu, SELECT_VFO[0])
    for address in (MODE_UI_A, MODE_VFO_A):
        cpu.mem_write(address, b"\x10")
    panel.render()
    panel._press_key(1, 0)
    panel.render()
    panel.click(37, 32)
    panel.render()
    panel.click(329, 241)
    assert "USB-D" in panel.render()[0]
    g.call("live_open", 0, 0, 0, 0)
    g.call("fixture_clock", 0)
    result = g.feed(recording(LIB / "test/wav/websdr_test1.wav", 120000))
    assert result and len(result[1]) >= 10

    def render(name, phase=60000):
        _, stock = panel.render()
        raw = Image.open(BytesIO(stock)).convert("RGB")
        panel.surface.events.clear()
        g.call("view_draw", 1, phase)
        panel.surface.select_target()
        screen = Image.frombytes("RGBA", (480, 272), bytes(panel.surface.pixels)).convert("RGB")
        assert (
            ImageChops.difference(raw.crop((0, 0, 480, 86)), screen.crop((0, 0, 480, 86))).getbbox() is None
        )
        labels = ["".join(chr(glyph["key"]) for glyph in e["glyphs"]).strip() for e in panel.surface.events]
        screen.save(LAB / (name + ".png"))
        return raw, screen, labels

    home, screen, labels = render("native-ten-rows")
    assert len(set(labels) & set(result[1])) == 10, labels
    g.call("view_page", 1)
    assert len(set(render("native-next-page")[2]) & set(result[1])) == len(result[1]) - 10
    g.call("view_page", 0)
    # The DSP status marks a valid RX meter sample. Run the original
    # smoothing/update task between front-panel frames, including decay.
    cpu.mem_write(0x203809A1, b"\x40")
    previous = None
    readings = []
    bar = (51, 75, 148, 80)
    for n, raw in enumerate((0, 8000, 14000, 0)):
        cpu.mem_write(0x203804F8, pack("<H", raw))
        for _ in range(10):
            call(cpu, 0x200B4CF8)
        reply = exchange_in_guest(cpu, b"\x15\x02")[0]
        measured = render(f"native-meter-{n}-{raw}")[1].crop(bar)
        diff = ImageChops.difference(previous, measured).getbbox() if previous else None
        assert not n or diff
        segments = int.from_bytes(cpu.mem_read(0x204BABF4, 2), "little")
        readings.append(dict(input=raw, ci_v=reply.hex(), segments=segments, bar_pixel_delta=diff))
        previous = measured
    levels = [r["segments"] for r in readings]
    assert levels[0] < levels[1] < levels[2] and levels[3] < levels[2]
    key_state = int.from_bytes(cpu.mem_read(0x2007E054, 4), "little")

    def exit_rx(name):
        keys = []

        def key_event(c, *_):
            keys.append(c.mem_read(key_state + 5, 1)[0])

        hook = cpu.hook_add(uc.UC_HOOK_CODE, key_event, begin=KEY_EVENT, end=KEY_EVENT)
        panel.press_exit()
        cpu.hook_del(hook)
        assert keys == [9] and g.call("live_enabled")
        for key in keys:
            g.call("live_panel_key", key)
        assert not g.call("live_enabled")
        tick(panel)
        stock, clear, labels = render(name)
        assert ImageChops.difference(stock, clear).getbbox() is None and not labels
        return keys

    ft8_keys = exit_rx("native-exit")
    # Tune the virtual VFO with a regular CI-V frequency command.
    reply, _ = exchange_in_guest(cpu, bytes.fromhex("05 00 00 08 14 00"))
    assert reply[2:-1] == b"\xfb" and int.from_bytes(cpu.mem_read(0x20380714, 4), "little") == 14080000
    g.call("live_open", 1, 0, 0, 0)
    g.call("fixture_clock", 0)
    ft4_rows = g.feed(recording(LAB.parent / "FT4/busy/000000_000001.wav", 60000))[1]
    assert len(ft4_rows) == 12
    assert len(set(render("native-ft4-ten-rows", 30000)[2]) & set(ft4_rows)) == 10
    ft4_keys = exit_rx("native-ft4-exit")
    panel.press_menu()
    tick(panel)
    frame(panel)
    if cpu.mem_read(GRID_PAGE, 1) != b"\x02":
        panel.click(274, 251)
        tick(panel)
        frame(panel)
    panel.click(52, 175)
    tick(panel)
    assert "SSTV" in frame(panel)[0], panel.state()
    panel.click(115, 116)
    tick(panel)
    assert "SSTV AUTO" in frame(panel)[0] and cpu.mem_read(symbols["counts"], 1) == b"\1"
    assert not g.call("live_pending")
    panel.press_exit()
    tick(panel)
    frame(panel)
    _, meta = load_image(D6 / "CW-RX3-WAKE2-PC/CW-RX3-WAKE2-PC.ic705sim")
    state = panel.surface.alloc(5120)
    cpu.mem_write(state, bytes(5120))
    cpu.mem_write(meta["symbols"]["cw_state_anchor"], pack("<I", state))
    for address in (MODE_UI_A, MODE_VFO_A):
        cpu.mem_write(address, b"\x20")
    panel.press_menu()
    tick(panel)
    frame(panel)
    if cpu.mem_read(GRID_PAGE, 1) == b"\x02":
        panel.click(186, 251)
        tick(panel)
        frame(panel)
    panel.click(240, 77)
    tick(panel)
    assert "CW DECODE" in frame(panel)[0]
    panel.click(115, 116)
    tick(panel)
    assert read_session(cpu, state)["active"]
    record = dict(
        ten_rows=True,
        next_page=True,
        stock_header_pixel_match=True,
        meter=readings,
        stock_exit_keys={"FT8": ft8_keys, "FT4": ft4_keys},
        ft4_decodes=len(ft4_rows),
        exit_closed_rx=True,
        exit_pixel_match=True,
        opened_sstv=True,
        opened_cw=True,
    )
    record["rtx_dial"] = dial_trial(elf)
    (LAB / "controls.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
