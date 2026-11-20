"""Exercise the exact J140 RX DAT through its MODE shortcut and native PCM callbacks."""

import json
import subprocess
from functools import lru_cache
from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from struct import pack, unpack_from
from tempfile import TemporaryDirectory
from time import perf_counter, sleep
from unittest.mock import patch

from elftools.elf.elffile import ELFFile
from PIL import Image, ImageChops

from tools import render_705_stock_row as renderer
from tools.build_705_cw_sim import load_image
from tools.build_705_ftx_rx import CC, OUT, SITES, word
from tools.emulate_705 import BASE, arm, call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC
from tools.probe_705_sstv_picture import frame, tick
from tools.render_705_display import load
from tools.replay_705_ftx_live import BASELINE, LAB, LIB, ROOT, decode_main, recording
from tools.replay_705_gps_inputs import BYTE_RX, GPS_INIT, GPS_MODE, RMC, nmea
from tools.replay_705_ptt_tune import INIT_RANGES
from tools.replay_705_settings import GRID_PAGE, SettingsGuest
from tools.replay_705_vfo_split import SELECT_VFO, seed_vfos, exchange_in_guest


@contextmanager
def session_heap(surface, budget=None, max_calls=None):
    baseline = sum(surface.blocks.values())
    alloc = surface.alloc
    requests = []

    def limited(size):
        used = sum(surface.blocks.values()) - baseline
        denied = (budget is not None and used + size > budget) or (
            max_calls is not None and len(requests) >= max_calls
        )
        ptr = 0 if denied else alloc(size)
        requests.append((size, ptr))
        return ptr

    with patch.object(surface, "alloc", limited):
        yield requests


def symbols(path):
    with path.open("rb") as f:
        return {
            s.name: s["st_value"]
            for s in ELFFile(f).get_section_by_name(".symtab").iter_symbols()
        }


def menu_init(cpu, main):
    count=(word(main,0x200052E8)-word(main,0x200052E4)-48)//16
    for i in range(count):
        src, dst, size, func = unpack_from(
            "<4I", main, word(main, 0x200052E4) - BASE + 48 + 16 * i
        )
        call(cpu, func | 1, src, dst, size)


def val(c, a, size=4):
    return int.from_bytes(c.mem_read(a, size), "little")


def map_atlas(c, dat, bank=0x185F0000):
    from tools.build_705_ftx_rx import KEY_OFFSET, FT_DATA_OFFSET, INDEX_OFFSET, PIXEL_OFFSET
    from tools.decode_705_main import checked_group_a, decode_a_range

    _, group = checked_group_a(dat)
    for at, length in [(KEY_OFFSET,0x26b000-KEY_OFFSET),(FT_DATA_OFFSET, INDEX_OFFSET-FT_DATA_OFFSET), (INDEX_OFFSET, 0x21000), (PIXEL_OFFSET, 0x10000)]:
        # The decoder feedback immediately before both erased regions is 0xff.
        data = bytes(decode_a_range(dat, group["offset"] + at, length, 0xFF))
        c.mem_write(bank + at, data)


def published_rows(cpu, batch, *, legacy=False):
    count, slot = val(cpu, batch), val(cpu, batch + 4)
    rows = [bytes(cpu.mem_read(batch + 8 + i * 44, 44)) for i in range(count)]
    if not legacy:
        rows = [row for row in rows if int.from_bytes(row[36:40], "little") == slot]
    return [r[:35].split(b"\0")[0].decode() for r in rows], rows


@lru_cache
def tile_letters():
    from tools.build_705_ft_panel_assets import RX_CHARS, RX_SPLIT
    from tools.build_705_ftx_rx import INDEX_OFFSET
    import re
    header = (OUT/"atlas_tag.h").read_text()
    offsets = [int(re.search(rf"#define FT_RX_{name} (\d+)u",header)[1]) for name in ("FIRST","SECOND")]
    return {bank+INDEX_OFFSET+offsets[i>=RX_SPLIT]+448*i+224*selected+208: ch
            for bank in (0x18000000,0x185f0000) for i,ch in enumerate(RX_CHARS) for selected in (0,1)}


def bitmap_messages(surface):
    rows = {}
    for write in surface.pixel_writes:
        x,y,w,h = write["rect"]
        if write["target"]!=7 or (w,h)!=(8,14):
            continue
        letter=tile_letters().get(int(write["ptr"],16))
        if letter is not None:
            row=rows.setdefault(y,{})
            row[x]=letter
    return ["".join(row[x] for x in sorted(row)) for row in rows.values()]


def compose(p):
    _, raw = frame(p)
    # The panel fixture supplies the stock compositor's draw and commit stages.
    c = p.cpu
    c.emu_start(SITES["frame"], SITES["frame"] + 4, count=12000000)
    assert c.reg_read(arm.UC_ARM_REG_PC) == SITES["frame"] + 4
    p.surface.select_target()
    picture = Image.frombytes("RGBA", (480, 272), bytes(p.surface.pixels)).convert(
        "RGB"
    )
    raw = Image.open(BytesIO(raw)).convert("RGB")
    assert not ImageChops.difference(
        raw.crop((0, 0, 480, 84)), picture.crop((0, 0, 480, 84))
    ).getbbox()
    return [
        "".join(chr(g["key"]) for g in e["glyphs"]).strip() for e in p.surface.events
    ] + bitmap_messages(p.surface), picture


def fixture(cpu, *, map_dma=True):
    with TemporaryDirectory() as tmp:
        elf = Path(tmp) / "dma.elf"
        subprocess.run(
            [
                CC,
                "-Os",
                "-marm",
                "-mcpu=cortex-a9",
                "-nostdlib",
                "-Wl,-Ttext=0x100000,-e,feed_banks",
                ROOT / "tools/fixtures/ftx_device_pcm.c",
                "-o",
                elf,
            ],
            check=True,
        )
        cpu.mem_map(0x100000, 0x200000)
        with elf.open("rb") as f:
            for seg in ELFFile(f).iter_segments():
                if seg["p_type"] == "PT_LOAD":
                    cpu.mem_write(seg["p_vaddr"], seg.data())
        feed = symbols(elf)["feed_banks"]
    if map_dma:
        cpu.mem_map(DMAC, 4096)
    cpu.mem_write(AUDIO_GATE, b"\1")
    return feed


def gps(c, s):
    s %= 86400
    stamp = f"{s // 3600:02d}{s // 60 % 60:02d}{s % 60:02d}"
    for b in nmea(RMC.format(time=stamp)):
        call(c, BYTE_RX, b)


STACK_TOP = 0x2E0000


def service(c, sy):
    call(
        c,
        sy["ftx_cw_bridge"],
        64,
        stack=STACK_TOP,
        instruction_limit=0,
        timeout_us=30000000,
    )


def listen(p, sy, feed, ft4, slots, output, compact, remote=False):
    c = p.cpu

    def step():
        service(c, sy)

    def set_time(second):
        if ft4:
            gps(c, second)
        else:
            s = second % 86400
            digits = f"{s // 3600:02}{s // 60 % 60:02}{s % 60:02}"
            c.mem_write(0x2038079E, bytes.fromhex(digits))

    count = 60000 if ft4 else 120000
    path = (
        (LAB.parent / "FT4/busy/000000_000001.wav")
        if ft4
        else LIB / "test/wav/websdr_test1.wav"
    )
    raw = recording(path, count)
    c.mem_write(0x180000, raw)
    c.mem_write(GPS_MODE, bytes([int(ft4)]))
    call(c, GPS_INIT)
    # Prime the factory NMEA validity filter, then cross midnight into slot 0.
    for sec in range(-6, 0):
        set_time(sec)
        # Feed six actual seconds; 48,000 samples is an exact DMA-block count.
        n = (8000 * (sec + 7) + 5) // 6 - (8000 * (sec + 6) + 5) // 6
        while n:
            take = min(96, n)
            call(c, feed, 0x180000, take, instruction_limit=0)
            step()
            n -= take
    set_time(0)
    assert (
        val(c, sy["enabled"])
        and min(val(c, sy["phase"]), count - val(c, sy["phase"])) < 200
    ), (
        {
            k: val(c, sy[k])
            for k in (
                "adc",
                "enabled",
                "phase",
                "last_second",
                "clock_ready",
                "tuning_blocked",
                "anchor_adc",
                "consumed",
                "generation",
            )
        },
        bytes(c.mem_read(MODE_UI_A, 2)).hex(),
        val(c, 0x203809A1, 1),
        val(c, 0x203809AC),
        val(c, 0x203809B0),
    )
    total = count // 6 * slots + 5000
    base_adc = val(c, sy["adc"])
    sent = peak = sec = 0
    result = []
    arrivals = {}
    first_paint = {}
    # Cross an actual recorded FT4 slot in each factory display-off state.
    sleep_records=[]
    dark=ft4 and not compact and "display_suspended" in sy
    session=val(c,sy["ftx_memory"])
    def dim(saver):
        c.mem_write(0x20380721,bytes([saver]))
        c.mem_write(0x2038049c,bytes([saver]))
        c.mem_write(0x2038072a,bytes([not saver]))
        c.mem_write(0x204BAB5D,b"\x04")
        call(c,sy["ftx_input"])
        assert val(c,sy["state"])==2 and val(c,sy["display_suspended"])
    if dark: dim(True)
    # The Passport controller enables the native screen once on connection, then
    # polls one read command every 65 ms and receives a separate waveform stream.
    polls = [bytes.fromhex(x) for x in ("15 02", "03", "1c 00", "15 02", "26 00", "1c 00")]
    poll_count = connections = 0
    def civ(command):
        response = exchange_in_guest(c, command)[0][2:-1]
        expected = b"\xfb" if len(command)==3 else command
        assert response.startswith(expected), (command, response)
        return response
    start = perf_counter()

    def published(cpu, *_):
        slot = cpu.reg_read(arm.UC_ARM_REG_R0) % (86400 * 8000 // count)
        rows = cpu.reg_read(arm.UC_ARM_REG_R1)
        if slot < slots and rows:
            elapsed = (perf_counter() - start - (slot + 1) * count / 8000) * 1000
            arrivals.setdefault(slot, []).append((rows, round(elapsed, 1)))

    hook = c.hook_add(
        uc.UC_HOOK_CODE,
        published,
        begin=sy["view_publish"] & ~1,
        end=sy["view_publish"] & ~1,
    )
    while sent < total:
        due = min(total, int((perf_counter() - start) * 8000 / 6))
        if due == sent:
            sleep(0.012)
            continue
        # Retain sample order and GPS-second boundaries even when the worker lags.
        while sent < due:
            this_sec = sent * 6 // 8000
            if this_sec != sec:
                set_time(this_sec)
                sec = this_sec
            index = sent % (count // 6)
            blocks = min(
                due - sent, (count // 6) - index, ((sec + 1) * 8000 + 5) // 6 - sent
            )
            call(
                c,
                feed,
                0x180000 + index * 12,
                blocks,
                instruction_limit=0,
                timeout_us=8000000,
            )
            sent += blocks
        queued = (val(c, sy["head"]) - val(c, sy["tail"])) & 0xFFFFFFFF
        peak = max(peak, queued)
        if remote and sent*6 >= count*2:
            required_connections = 1 + (sent*6 >= count*4)
            if connections < required_connections:
                civ(bytes.fromhex("27 10 01"))
                # The two UDP commands may arrive on separate UI ticks.
                call(c, sy["ftx_input"])
                assert val(c, sy["state"]) == 2 and val(c, 0x203e84c9, 1)==9
                civ(bytes.fromhex("27 11 01"))
                assert civ(bytes.fromhex("27 11"))[-1] == 1
                connections += 1
            while poll_count*520 <= sent*6-count*2:
                civ(polls[poll_count % len(polls)])
                poll_count += 1
            call(c, sy["ftx_input"])
            assert val(c, sy["state"]) == 2 and val(c, sy["ftx_memory"]) == session
        step()
        m = val(c, sy["middle"])
        if arrivals:
            bank = (m & 3) if m & 4 else val(c, sy["front"])
            batch = val(c, sy["ftx_memory"]) + 32768 + bank * (8 + 48 * 44)
            msgs, _raw_rows = published_rows(c, batch)
            lines = len(msgs)
            slot = val(c, batch + 4)
            slot %= 86400 * 8000 // count
            if slot not in arrivals:
                continue
            if slot not in first_paint:
                assert val(c, sy["candidate_count"]) and lines
                first_message = msgs[-1]
                if dark and slot in (0,1):
                    assert session==val(c,sy["ftx_memory"]) and val(c,sy["display_suspended"])
                    p.surface.pixel_writes.clear()
                    call(c,sy["ftx_frame"])
                    assert not p.surface.pixel_writes
                    c.mem_write(0x204BAB5D,b"\1")
                    # Wake over CQ. The whole gesture belongs to stock wake.
                    c.mem_write(0x203e1f23,bytes.fromhex("00 01 b8 00 69"))
                    assert call(c,sy["ftx_touch"])
                    assert call(c,sy["ftx_touch"])
                    c.mem_write(0x203e1f23,b"\1")
                    assert call(c,sy["ftx_touch"])
                    if slot==0:
                        assert val(c,0x2038049c,1)==2
                        c.mem_write(0x20380721,b"\0")  # factory restoration complete
                        c.mem_write(0x2038049c,b"\0")
                    else: assert not val(c,0x2038072a,1)
                    call(c,sy["ftx_input"])
                    assert val(c,sy["state"])==2 and not val(c,sy["ft_page"])
                    assert not val(c,sy["display_suspended"])
                    sleep_records.append(dict(slot=slot,source="battery saver" if slot==0 else "POWER LCD off",message=first_message))

                labels, _ = compose(p)
                assert first_message in labels, (first_message, labels)
                first_paint[slot] = round(
                    (perf_counter() - start - (slot + 1) * count / 8000) * 1000, 1
                )
            if val(c, sy["candidate_count"]):
                continue
            if not result or slot != result[-1]["slot"]:
                if not ft4:
                    assert "CQ IK4LZH JN54" in msgs, (slot, msgs)
                if ft4:
                    want = {
                        r.split(maxsplit=5)[5].strip()
                        for r in (path.parent / "generated.txt")
                        .read_text()
                        .splitlines()
                        if r.strip()
                    }
                    if compact:
                        assert set(msgs) <= want and len(set(msgs)) >= 10, (slot, msgs)
                    else:
                        assert set(msgs) == want, (slot, sorted(want-set(msgs)), peak, val(c,sy["rx_short_searches"]), arrivals[slot])
                result.append(
                    {
                        "slot": slot,
                        "rows": len(msgs),
                        "missing": sorted(want - set(msgs)) if ft4 else [],
                        "first_ms": arrivals[slot][0][1],
                        "first_panel_frame_ms": first_paint[slot],
                        "late_ms": arrivals[slot][-1][1],
                        "search_finished_ms": round(
                            (perf_counter() - start - (slot + 1) * count / 8000) * 1000,
                            1,
                        ),
                    }
                )
                if dark and slot==0: dim(False)
    c.hook_del(hook)
    assert not val(c, sy["rx_late_slots"])
    curtailed = val(c, sy["rx_short_searches"])
    assert [r["slot"] for r in result] == list(range(slots)), result
    assert (
        val(c, sy["adc"]) - base_adc == total * 6
        and not val(c, sy["overruns"])
        and not val(c, sy["gaps"])
    )
    # Forced screenshots and page changes are foreground UI checks. Run
    # those after the timed stream, which already draws a live frame per slot.
    call(c, sy["view_invalidate"])
    labels, pic = compose(p)
    # The live page shows the latest ten rows across slot boundaries. Compare
    # the rendered order and parity even when a single slot has fewer than ten.
    all_messages, records = published_rows(c, batch, legacy=True)
    visible = all_messages[-10:]
    assert len(visible) == 10 and bitmap_messages(p.surface) == visible, (visible, labels)
    parity = [("B" if r[36] & 1 else "A") + ("*" if r[35] & 1 else "") for r in records[-10:]]
    assert [s for s in labels if s in ("A","B","A*","B*")][-10:] == parity, labels
    assert not {"GPS","RTC","LIMIT"} & set(labels) and val(c, sy["ftx_rtc"]) == (not ft4)
    assert any(val(c, batch + 8 + 44 * i + 43, 1) for i in range(lines))
    assert any(w["rect"][2:] == [16, 12] for w in p.surface.pixel_writes)
    pic.save(output / ("FT4-ten.png" if ft4 else "FT8-ten.png"))
    # With PCM stopped, panel input must report the stall even though the
    # sample counter cannot schedule a repaint. Resume on the same FT session.
    session = val(c, sy["ftx_memory"])
    stalled_at = (val(c, sy["audio_tick"]) + 2001) & 0xffffffff
    c.mem_write(0x20381e08, pack("<I", stalled_at))
    call(c, sy["ftx_input"])
    labels, _ = compose(p)
    assert "No RX audio" in labels and bitmap_messages(p.surface) == visible
    call(c, feed, 0x180000, 24, instruction_limit=0)
    call(c, sy["ftx_input"])
    assert val(c, sy["audio_tick"]) == stalled_at
    assert not call(c, sy["ftx_status"]) and val(c, sy["ftx_memory"]) == session
    labels, _ = compose(p)
    assert bitmap_messages(p.surface) == visible and "No RX audio" not in labels
    if len(msgs) > 10:
        assert call(c, sy["ft_history_enabled"],0)
        p.click(416,177)
        labels,second=compose(p)
        second.save(output / ("FT4-more.png" if ft4 else "FT8-more.png"))
        assert call(c,sy["ft_is_history"]) and call(c,sy["ft_history_enabled"],1)
        p.click(456,177)
        labels,_=compose(p)
        assert not call(c,sy["ft_is_history"]) and bitmap_messages(p.surface)==visible
    # The stock transmit-request flag also suspends reception. With the request
    # released, the worker must relock the same session and clear its status.
    assert not val(c, 0x203809ac)
    c.mem_write(0x203809ac, pack("<I",1))
    call(c, feed, 0x180000, 24, instruction_limit=0)
    step()
    assert "RX paused" in compose(p)[0]
    c.mem_write(0x203809ac, pack("<I",0))
    call(c, feed, 0x180000, 24, instruction_limit=0)
    step()
    assert val(c, sy["ftx_memory"]) == session and not call(c, sy["ftx_status"])
    if remote:
        assert connections==2 and poll_count >= (slots-2)*count//520
        civ(bytes.fromhex("27 11 00"))
        assert civ(bytes.fromhex("27 11"))[-1] == 0 and val(c,sy["state"])==2
        # Close the factory scope after the coexistence checks for the exit fixture.
        civ(bytes.fromhex("27 10 00"))
    if ft4:
        assert max(s["late_ms"] for s in result) < 7500
    return {
        "slots": result,
        "esp32_civ": {"scope_enables":connections,"polls":poll_count,"interval_ms":65} if remote else None,
        "pcm_stall_ms": 2001,
        "pcm_resumed_same_session": True,
        "display_wake": sleep_records,
        "peak_blocks": peak,
        "capacity": 2048,
        "curtailed_searches": curtailed,
        "overruns": 0,
        "gaps": 0,
    }


def panel_trial(stock, image, sy, compact=False, remote=False):
    output = OUT / ("remote-audio" if remote else "compact") if remote or compact else OUT
    output.mkdir(exist_ok=True)
    with patch.object(renderer, "HEAP_START", 0x20700000):
        p = SettingsGuest(stock, front_panel=True)
    c = p.cpu
    map_atlas(c, (OUT / "bench-rx.dat").read_bytes())
    c.mem_write(BASE, image)
    c.ctl_remove_cache(BASE, BASE + len(image))
    menu_init(c, image)
    feed = fixture(c)
    c.mem_write(p.language_address, bytes(2))
    seed_vfos(c, (14074000, 14080000))
    call(c, INIT_RANGES)
    call(c, SELECT_VFO[0])
    for a in (MODE_VFO_A, MODE_UI_A):
        c.mem_write(a, b"\x20")

    cw_state = p.surface.alloc(5120)
    c.mem_write(cw_state, bytes(5120))
    c.mem_write(cw_state + 0x700, pack("<I", 1))
    c.mem_write(sy["cw_state_anchor"], pack("<I", cw_state))
    c.mem_protect(STACK_TOP - 8192, 4096, uc.UC_PROT_NONE)

    def stub(c, a, *_):
        assert a != 0x202D48C0, "FT requested another RTX task while CW worker exists"
        c.reg_write(arm.UC_ARM_REG_R0, 0)
        c.reg_write(arm.UC_ARM_REG_PC, c.reg_read(arm.UC_ARM_REG_LR))

    for a in (0x202D48C0, 0x202D4850):
        c.hook_add(uc.UC_HOOK_CODE, stub, begin=a, end=a)
    p.render()
    beeps = []

    def record_beep(cpu, *_):
        beeps.append(cpu.reg_read(arm.UC_ARM_REG_R0))

    c.hook_add(uc.UC_HOOK_CODE, record_beep, begin=0x2007D478, end=0x2007D478)
    rec = {}
    for ft4 in (0, 1):
        if ft4:
            p._press_key(1, 0)
            tick(p)
        original_scope = call(c, 0x200F1E48)
        assert original_scope == ft4
        p.click(37, 32)
        tick(p)
        labels, pic = compose(p)
        assert "MODE" in labels and "FT8/4" in labels
        pic.save(output / "MODE-entry.png")
        before = len(beeps)
        p.click(431, 192)
        assert beeps[before:] == [1], beeps[before:]
        tick(p)
        labels, pic = compose(p)
        assert {"FT8", "FT4"} <= set(labels)
        pic.save(output / "MODE-select.png")
        p.click(120, 116 if ft4 else 79)
        tick(p)
        assert val(c, sy["state"]) == 1 and val(c, sy["ftx_ft4"]) == ft4
        c.mem_write(STACK_TOP - 4096, b"\xa5" * 4096)
        budget = (
            151944 if ft4 else 280700
        )  # RX2 single allocation, including both FFT and display.
        if compact:
            budget = 120000 if ft4 else 210000
        with session_heap(p.surface, budget) as requests:
            service(c, sy)
        allocated = {
            ptr: p.surface.blocks[ptr] for _, ptr in requests if ptr in p.surface.blocks
        }
        refused = [size for size, ptr in requests if not ptr]
        assert refused and sum(allocated.values()) <= budget
        rec["FT4_heap" if ft4 else "FT8_heap"] = {
            "limit": budget,
            "allocated": list(allocated.values()),
            "refused": refused,
        }
        assert val(c, sy["state"]) == 2 and val(c, sy["ftx_memory"])
        labels, _ = compose(p)
        assert (
            "USB-D" in labels
            and ("Waiting for RTC tick" if ft4 else "Waiting for GPS UTC") in labels
        )
        p.click(440,249)
        p.click(100,156)
        p.click(100,125 if ft4 else 158)
        p.click(440,249)
        service(c, sy)
        labels, _ = compose(p)
        assert ("Waiting for GPS UTC" if ft4 else "Waiting for RTC tick") in labels
        assert ("ECO" in labels) == compact
        # FT preserves the original mini-scope pass under its composited panel.
        assert any(w["target"] == 16 and w["rect"][2] == 475 for w in p.surface.pixel_writes)
        assert val(c, 0x20380714) == 14074000 and call(c, 0x200F1E48)
        if ft4:
            levels = []
            previous = None
            c.mem_write(0x203809A1, b"\x40")
            for raw_value in (0, 8000, 14000, 0):
                c.mem_write(0x203804F8, pack("<H", raw_value))
                for _ in range(10):
                    call(c, 0x200B4CF8)
                tick(p)
                labels, pic = compose(p)
                bar = pic.crop((51, 75, 148, 80))
                if previous:
                    assert ImageChops.difference(previous, bar).getbbox()
                previous = bar
                levels.append(val(c, 0x204BABF4, 2))
            assert levels[0] < levels[1] < levels[2] and levels[3] < levels[2]
            rec["meter"] = levels
        print("receiving", ft4, flush=True)
        rec["FT4" if ft4 else "FT8"] = listen(
            p, sy, feed, ft4, 8 if ft4 else 6, output, compact, remote
        )
        if not ft4:
            # Freeze the RTC, then switch a previously locked receiver to an
            # unavailable GPS. A stale result must disappear in both states.
            for _ in range(40):
                call(c, feed, 0x180000, 96, instruction_limit=0)
                service(c, sy)
            labels, _ = compose(p)
            assert "Waiting for RTC tick" in labels and not val(c, sy["enabled"])
            p.click(440,249)
            p.click(100,156)
            p.click(100,125)
            p.click(440,249)
            service(c, sy)
            labels, _ = compose(p)
            assert "Waiting for GPS UTC" in labels
            p.click(440,249)
            p.click(100,156)
            p.click(100,158)
            p.click(440,249)
            service(c, sy)
        p.press_exit()
        tick(p)
        assert val(c, sy["state"]) == 3
        service(c, sy)
        assert allocated.keys().isdisjoint(p.surface.blocks), (
            "leaked FT session allocation"
        )
        stack = bytes(c.mem_read(STACK_TOP - 4096, 4096))
        untouched = next(i for i, b in enumerate(stack) if b != 0xA5)
        assert untouched >= 512, ("insufficient IRQ/context margin", untouched)
        rec["FT4" if ft4 else "FT8"]["peak_stack_written"] = 4096 - untouched
        assert (
            not val(c, sy["ftx_memory"])
            and not val(c, sy["thread"])
            and not val(c, sy["state"])
        )
        # The remote fixture explicitly closed the scope with 27 10 00.
        expected_scope = 0 if remote else original_scope
        assert call(c, 0x200F1E48) == expected_scope
        _, raw = frame(p)
        _, closed = compose(p)
        if expected_scope:
            assert any(
                w["target"] == 16 and w["rect"][2] == 475
                for w in p.surface.pixel_writes
            )
        assert not ImageChops.difference(
            Image.open(BytesIO(raw)).convert("RGB"), closed
        ).getbbox()
    from tools.build_705_cw_sstv_rx import D6
    from tools.probe_705_cw_session import read_session

    prev = symbols(OUT / "sstv/rx.elf")
    c.mem_write(prev["sstv_thread"], pack("<I", 1))
    p.press_menu()
    tick(p)
    frame(p)
    if val(c, GRID_PAGE, 1) != 2:
        p.click(274, 251)
        tick(p)
        frame(p)
    p.click(52, 175)
    tick(p)
    assert "SSTV" in frame(p)[0]
    p.click(115, 116)
    tick(p)
    assert "SSTV AUTO" in frame(p)[0]
    p.press_exit()
    tick(p)
    frame(p)
    _, meta = load_image(D6 / "CW-RX3-WAKE2-PC/CW-RX3-WAKE2-PC.ic705sim")
    st = p.surface.alloc(5120)
    c.mem_write(st, bytes(5120))
    c.mem_write(meta["symbols"]["cw_state_anchor"], pack("<I", st))
    for a in (MODE_VFO_A, MODE_UI_A):
        c.mem_write(a, b"\x20")
    p.press_menu()
    tick(p)
    frame(p)
    if val(c, GRID_PAGE, 1) == 2:
        p.click(186, 251)
        tick(p)
        frame(p)
    p.click(240, 77)
    tick(p)
    assert "CW DECODE" in frame(p)[0]
    p.click(115, 116)
    tick(p)
    assert read_session(c, st)["active"]
    rec.update(
        after_exit=["SSTV AUTO", "CW DECODE"], frame_restored=True, original_header=True
    )
    return rec


if __name__ == "__main__":
    candidate = (OUT / "bench-rx.dat").read_bytes()
    sy = symbols(OUT / "rx.elf")
    stock = load((ROOT / "firmware/705J140.dat").read_bytes())
    import argparse

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compact", action="store_true")
    group.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    rec = panel_trial(stock, bytes(decode_main(candidate)[1]), sy, args.compact, args.remote)
    rec["dat_sha256"] = sha256(candidate).hexdigest()
    ((OUT / "remote-audio" if args.remote else OUT / "compact" if args.compact else OUT) / "panel-audio.json").write_text(
        json.dumps(rec, indent=2)
    )
    print(rec)
