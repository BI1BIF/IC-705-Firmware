"""Drive the E140 MODE menu and LCD with touch, encoder, EXIT and recorded audio."""
from array import array
from hashlib import sha256
import json
import wave
from struct import unpack_from

from tools.build_705_ft_panel_assets import RX_CHARS, RX_SPLIT
from tools.emulate_705 import arm, uc
from tools.replay_705_e140_ft import (A_PREFIX, E_KEYS, E_MAIN, GRAPHICS_FLASH, INDEX_OFFSET, OUT,
                                      REPORTS, ROOT, fixture, probe, recording)
from tools.render_705_stock_row import FONT_HASH, FONT_HEADER, SMALL_FONT_HASH, SMALL_FONT_HEADER, png
from tools.verify_705_ftx_rx import val, symbols


def panel_graphics(stock, flash, resources):
    def stock_font(offset, expected):
        size = unpack_from("<I", flash, offset)[0]
        font = flash[offset+4:offset+4+size]
        assert sha256(font).hexdigest() == expected
        return font

    return (stock, stock_font(A_PREFIX, FONT_HASH), resources, E_MAIN,
                stock_font(A_PREFIX+SMALL_FONT_HEADER-FONT_HEADER, SMALL_FONT_HASH))


def panel(stock, flash, image, resources, sy, mode):
    graphics = panel_graphics(stock, flash, resources)
    out = REPORTS/("panel-"+mode.lower())
    out.mkdir(exist_ok=True, parents=True)
    ft4 = mode == "FT4"
    samples = 60000 if ft4 else 120000
    path = (ROOT/".analysis/ftx-station/FT4/busy/000000_000001.wav" if ft4 else
            ROOT/".analysis/ftx-lib/test/wav/websdr_test1.wav")
    expected = ({line.split(maxsplit=5)[5].strip() for line in path.with_name("generated.txt").read_text().splitlines()
                 if line.strip()} if ft4 else
                {line.split("~", 1)[1].strip().split("   ",1)[0] for line in path.with_suffix(".txt").read_text().splitlines()[:13]})
    waveform = recording(path, samples)
    # The two glyph banks contain tiles for the same alphabet at different offsets.
    first = E_KEYS + len((OUT/"key-faces.bin").read_bytes()) - RX_SPLIT*448
    second = 0x5f0000 + len((OUT/"countries.bin").read_bytes()) - unpack_from("<I", resources, INDEX_OFFSET+16)[0] - len(RX_CHARS)*448
    chars = {GRAPHICS_FLASH+(first if i<RX_SPLIT else second)+i*448+selected*224+208: ch
             for i,ch in enumerate(RX_CHARS) for selected in (0,1)}

    def attach(c, surface):
        # The stock loop periodically saves settings after a dial change. Provide
        # volatile backing for its RIIC0 EEPROM while exercising the receiver UI.
        eeprom = {}
        saves = []

        def write_eeprom(cpu, _pc, *_):
            address, source, size = (cpu.reg_read(r) for r in
                                     (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))
            assert 0 < size <= 64 and 0 <= address <= 0x40000 - size
            data = bytes(cpu.mem_read(source, size))
            eeprom.update(zip(range(address, address + size), data))
            saves.append([address, size])
            cpu.reg_write(arm.UC_ARM_REG_R0, 0)
            cpu.reg_write(arm.UC_ARM_REG_PC, cpu.reg_read(arm.UC_ARM_REG_LR))

        def read_eeprom(cpu, _pc, *_):
            address, buffer, size = (cpu.reg_read(r) for r in
                                     (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))
            assert 0 < size <= 64 and all(at in eeprom for at in range(address, address + size))
            cpu.mem_write(buffer, bytes(eeprom[at] for at in range(address, address + size)))
            cpu.reg_write(arm.UC_ARM_REG_R0, 0)
            cpu.reg_write(arm.UC_ARM_REG_PC, cpu.reg_read(arm.UC_ARM_REG_LR))

        for address, operation in ((0x2005bb18, write_eeprom), (0x2005bbc4, read_eeprom)):
            c.hook_add(uc.UC_HOOK_CODE, operation, begin=address, end=address)

        def trial(turn, step, tap, frames):
            def settle(n=14):
                for _ in range(n):
                    step()

            def save(label):
                surface.select_target()
                (out/(label+".png")).write_bytes(png(480,272,surface.pixels))

            tap(37,32)
            settle()
            assert "FT8/4" in frames[-1]["glyphs"]
            save("02-mode")
            tap(431,192)
            settle()
            assert {"Digital","FT8","FT4"} <= set(frames[-1]["glyphs"])
            save("03-selector")
            tap(120,116 if ft4 else 82)
            settle(16)
            assert val(c,sy["state"]) == 2 and bool(val(c,sy["ftx_ft4"])) == ft4
            assert mode in frames[-1]["glyphs"]
            tap(440,249)
            tap(100,156)
            tap(100,158)
            tap(441,249)
            assert val(c,sy["ftx_rtc"]) == 1

            dma = fixture(c, map_dma=False, e140=True)
            # Leading silence, followed by two copies of the recording. One main-task
            # pass processes 570 additional fixture samples and 36 ordinary DMA samples.
            sound = bytes(48000*2)+waveform*2+bytes(606*2)
            c.mem_write(0x120000, sound)
            start = val(c,sy["adc"])
            visible, outputs = [], set()
            for _ in range((48000+samples*2)//606):
                n = val(c,sy["adc"])-start
                day = ((n-48000)//8000)%86400
                c.mem_write(0x2038079e, bytes.fromhex(f"{day//3600:02}{day//60%60:02}{day%60:02}"))
                step(part=sound[2*n:2*(n+36)], audio_input=lambda sub: sub(dma,0x120000+(n+36)*2,95))
                assert val(c,sy["adc"])-start == n+606
                rows = {}
                for w in surface.pixel_writes:
                    x,y,width,height = w["rect"]
                    if w["target"] == 7 and (width,height) == (8,14):
                        rows.setdefault(y,{})[x] = chars[int(w["ptr"],16)]
                if len(rows) == 10:
                    visible = ["".join(cols[x] for x in sorted(cols)).strip() for _,cols in sorted(rows.items(),reverse=True)]
                    assert all(row in expected for row in visible), visible
                if visible and any(w["source_target"] == 7 for w in frames[-1]["blits"]):
                    outputs.add(val(c,0x20380cbc,1))
                if len(outputs) == 2:
                    break
            assert len(visible) == 10 and outputs == {0,1}
            assert not val(c,sy["gaps"]) and not val(c,sy["overruns"])
            save("04-ten-rows")
            up, down = turn(1), turn(-1)
            assert down["after"] == up["before"] and up["after"] > up["before"]
            assert val(c,sy["state"]) == 2
            for _ in range(18):
                step(keys=(0,4))
            for _ in range(12):
                step(keys=(0,0))
            assert val(c,sy["state"]) == val(c,sy["thread"]) == val(c,sy["ftx_memory"]) == 0
            assert frames[-1]["page"] == 1 and all(w["source_target"] != 7 for w in frames[-1]["blits"])
            save("05-exit")
            siblings = {}
            if ft4:
                from tools.probe_705_cw_break_in import audio as morse
                from tools.probe_705_cw_session import read_session
                from tools.probe_705_sstv_arm import counters

                def click(x, y):
                    tap(x,y)
                    settle()

                def press(keys):
                    for _ in range(18):
                        step(keys=keys)
                    for _ in range(12):
                        step(keys=(0,0))

                click(37,32)
                click(145,192)
                press((8,0))
                click(237,77)
                assert {"CW DECODE","KEYER/DECODE"} <= set(frames[-1]["glyphs"])
                click(120,116)
                assert "CW DECODE" in frames[-1]["glyphs"]
                anchor = val(c,sy["cw_state_anchor"])
                assert anchor and read_session(c,anchor)["active"]
                message = morse("CQ")+bytes(8004)
                for off in range(0,len(message),72):
                    step(part=message[off:off+72].ljust(72,b"\0"))
                state = read_session(c,anchor)
                assert state["text"].strip() == "CQ",state["text"]
                save("06-cw")
                press((0,4))
                assert not read_session(c,anchor)["active"]

                press((8,0))
                click(274,251)
                click(52,175)
                assert {"PICTURE","DV","SSTV"} <= set(frames[-1]["glyphs"])
                click(120,116)
                ss = symbols(OUT/"sstv/rx.elf")
                assert "SSTV AUTO" in frames[-1]["glyphs"] and counters(c,ss)["active"]
                with wave.open(str(ROOT/".analysis/sstv-robot36-v1/robot36.wav")) as recording_file:
                    assert (recording_file.getframerate(), recording_file.getsampwidth(), recording_file.getnchannels()) == (48000,2,1)
                    robot = array("h",recording_file.readframes(recording_file.getnframes()))[::6].tobytes()
                # SSTV queues 32 six-sample blocks. Deliver 24 per scheduler turn.
                robot += bytes(-len(robot)%288)
                c.mem_write(0x120000,robot)
                for off in range(0,len(robot),288):
                    step(part=robot[off:off+72], audio_input=lambda sub: sub(dma,0x120000+off+72,18))
                after = counters(c,ss)
                image_hash = sha256(c.mem_read(val(c,ss["pixels"]),320*240*2)).hexdigest()
                expected_image = json.loads((ROOT/".analysis/sstv-auto-rx/evidence.json").read_text())
                assert after["rows"] == 240 and after["dropped"] == 0
                assert image_hash == expected_image["image_rgb565_sha256"]
                assert "Robot 36" in frames[-1]["glyphs"]
                overlay = " ".join(frames[-1]["glyphs"]).lower()
                if "headset battery" in overlay:
                    # The virtual board has no headset battery telemetry. Dismiss
                    # the original low-battery dialog before testing the EXIT key.
                    click(355,192)
                    assert "headset battery" not in " ".join(frames[-1]["glyphs"]).lower()
                save("07-sstv")
                press((0,4))
                settle(24)
                assert not counters(c,ss)["active"] and not val(c,ss["canvas_owner"]), (
                    counters(c,ss), hex(val(c,ss["canvas_owner"])), frames[-1]["page"], frames[-1]["glyphs"])
                assert frames[-1]["page"] == 1 and not val(c,sy["state"])
                siblings = dict(cw_text=state["text"].strip(), sstv_rows=after["rows"], sstv_dropped=after["dropped"],
                                robot36_rgb565_sha256=image_hash,
                                sstv_returned_home=True)
            return dict(mode=mode, visible=visible, lcd_selectors=sorted(outputs), dial_up=up, dial_down=down,
                        gaps=0, overruns=0, hardware_exit_home=True, siblings=siblings,
                        simulated_eeprom_writes=saves, main_sha256=sha256(image).hexdigest())
        return None, trial

    return probe(stock, application=image, graphics=graphics, render_output=out,
                 screen=True, live=True, panel_experiment=attach)
