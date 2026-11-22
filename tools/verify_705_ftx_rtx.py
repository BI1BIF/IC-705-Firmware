"""Run the RX application with the original RTX scheduler, heap and main dial."""

import json
from hashlib import sha256
from pathlib import Path
from struct import pack

from tools.build_705_ftx_rx import SSTV_BSS, OUT
from tools.emulate_705 import arm, uc
from tools.probe_705_cw_menu import MODE_UI_A
from tools.probe_705_rtx_audio import (
    CURRENT,
    IDLE,
    LOOP,
    PCM_DONE,
    SEM_WAIT,
    TIMER,
    TIMERS_CLEARED,
    UI_HANDLE,
    probe,
)
from tools.render_705_display import load
from tools.replay_705_ftx_live import ROOT, decode_main
from tools.verify_705_ftx_rx import symbols, val


def pressured_ft8(c, run, irq, sub, value, sy, worker):
    """Decode one real recording on the shared 4 KiB RTX stack with the stack pool full."""
    from tools.replay_705_ftx_live import LIB, recording
    from tools.replay_705_gps_inputs import GPS_INIT, GPS_MODE
    from tools.verify_705_ftx_rx import fixture, gps

    feed = fixture(c, map_dma=False)
    data = recording(LIB / "test/wav/websdr_test1.wav", 120000)
    c.mem_write(0x180000, data)
    stack = value(worker + 0x2C)
    saved_sp = value(worker + 0x28)
    marker = value(stack)
    c.mem_write(stack + 4, b"\xa5" * (saved_sp - stack - 4))
    last = None
    first = -48000
    for sent in range(first, 136128, 6 * 96):
        irq(TIMER, IDLE)
        irq(0, LOOP)
        ctx = c.context_save()
        if sent == first:
            c.mem_write(GPS_MODE, b"\1")
            sub(GPS_INIT)
        pos = sent
        end = min(sent + 6 * 96, 136128)
        while pos < end:
            sec = pos // 8000
            if sec != last:
                gps(c, sec)
                c.context_restore(ctx)
                last = sec
            stop = min(
                end, ((pos // 120000 + 1) * 120000), ((sec + 1) * 8000 + 5) // 6 * 6
            )
            sub(
                feed,
                0x180000 + 2 * (pos % 120000 if pos >= 0 else 0),
                (stop - pos) // 6,
            )
            pos = stop
        c.context_restore(ctx)
        run(LOOP, IDLE, limit=500000000)
    mid = value(sy["middle"])
    assert mid & 4 and not value(sy["gaps"]) and not value(sy["overruns"])
    batch = value(sy["ftx_memory"]) + 32768 + (mid & 3) * (8 + 48 * 44)
    count = value(batch)
    messages = [
        bytes(c.mem_read(batch + 8 + 44 * i, 40)).split(b"\0")[0].decode()
        for i in range(count)
    ]
    assert "CQ IK4LZH JN54" in messages and count >= 10, messages
    guard = bytes(c.mem_read(stack + 4, saved_sp - stack - 4))
    untouched = 4 + next((i for i, b in enumerate(guard) if b != 0xA5), len(guard))
    assert untouched >= 512 and value(stack) == marker
    return {
        "messages": count,
        "known_message": "CQ IK4LZH JN54",
        "stack_written": 4096 - untouched,
        "unused_stack": untouched,
        "overruns": 0,
        "gaps": 0,
    }


def scheduler(stock, image, sy, *, exhaust_stack_pool=True):
    def exercise(c, run, irq, sub, value):
        # Enter from the running main task, then let the original scheduler
        # deliver the pending signal, allocate memory, and retire the worker.
        c.mem_write(MODE_UI_A, bytes((16, 1)))
        c.mem_write(0x204BAB5D, b"\1")  # This displayless scheduler represents HOME.
        from tools.verify_705_ftx_rx import map_atlas
        c.mem_map(0x185f0000,0x600000,uc.UC_PROT_READ)
        map_atlas(c,(OUT/"bench-rx.dat").read_bytes())
        sub(sy["ft_data_ready"])
        requested = []

        def allocation(c, *_):
            if val(c, sy["thread"]) and val(c, CURRENT) == val(c, sy["thread"]):
                requested.append(c.reg_read(arm.UC_ARM_REG_R0))

        c.hook_add(uc.UC_HOOK_CODE, allocation, begin=0x20127A28, end=0x20127A28)
        heaps = []
        stacks = []
        visits = []
        create_calls = []
        c.hook_add(
            uc.UC_HOOK_CODE,
            lambda *_: visits.append(value(CURRENT)),
            begin=sy["ftx_step"] & ~1,
            end=sy["ftx_step"] & ~1,
        )
        c.hook_add(
            uc.UC_HOOK_CODE,
            lambda *_: create_calls.append(value(CURRENT)),
            begin=0x202D48C0,
            end=0x202D48C0,
        )

        def largest_free():
            low, high = 0, (SSTV_BSS - 0x20750A40) // 8 + 1
            while low + 1 < high:
                n = (low + high) // 2
                ptr = sub(0x20127A28, 8 * n)
                if ptr:
                    sub(0x20127A78, ptr)
                    low = n
                else:
                    high = n
            return low * 8

        held = 0

        def board_tail(c, *_):
            c.reg_write(arm.UC_ARM_REG_PC, 0x200D5230)

        c.hook_add(uc.UC_HOOK_CODE, board_tail, begin=PCM_DONE, end=PCM_DONE)
        for i, ft4 in enumerate((1, 0, 1)):
            if i:
                irq(TIMER, IDLE)
                irq(0, LOOP)
            ctx = c.context_save()
            c.mem_write(sy["ftx_choice"], pack("<I", ft4))
            cw_state = value(sy["cw_state_anchor"])
            cw_task = value(cw_state + 0x700) if cw_state else 0
            if i == 1 and exhaust_stack_pool:
                assert cw_task
                while sub(0x202D4B17, 0x2049A5C0, 4096):
                    held += 1
                assert held and not sub(0x202D4B17, 0x2049A5C0, 4096)
            before_heap = largest_free()
            limit = 151944 if ft4 else 280700
            guard = 0
            available = before_heap
            if i:  # Cold boot also brings up CW; pressure the initialized radio.
                guard = sub(0x20127A28, before_heap - limit)
                available = largest_free()
                assert guard and limit - 128 <= available <= limit, (
                    before_heap,
                    available,
                )
                assert not sub(0x20127A28, 240268 if ft4 else 451188)
            initial_request = len(requested)
            before = len(create_calls)
            sub(sy["start"])
            assert len(create_calls) - before == int(not cw_task)
            assert value(sy["shared_worker"]) == int(bool(cw_task))
            t = value(sy["thread"])
            stack = value(t + 0x2C)
            assert (
                t
                and value(t + 0x26, 2) == 4096
                and t not in (value(CURRENT), value(UI_HANDLE))
            )
            if cw_task:
                assert t == cw_task
            visits.clear()
            c.context_restore(ctx)
            run(
                LOOP if i else TIMERS_CLEARED,
                SEM_WAIT if not i else IDLE,
                limit=10000000,
            )
            if not i:
                run(SEM_WAIT, IDLE, limit=10000000)
            assert visits and set(visits) == {t}, visits
            m = value(sy["ftx_memory"])
            assert 0x20750A44 <= m < SSTV_BSS and value(sy["state"]) == 2, (
                i,
                hex(m),
                value(sy["state"]),
                available,
                requested[initial_request:],
            )
            calls = requested[initial_request:]
            assert len(calls) >= 3 and m + calls[1] <= SSTV_BSS
            heaps.append(
                {
                    "address": hex(m),
                    "ft4": ft4,
                    "available": available,
                    "requests": calls,
                }
            )
            stacks.append(hex(stack))
            if i == 1:
                decoded = pressured_ft8(c, run, irq, sub, value, sy, t)
                assert set(visits) == {t}
            irq(TIMER, IDLE)
            irq(0, LOOP)
            ctx = c.context_save()
            c.mem_write(0x20380431, b"\x09")
            sub(sy["ftx_input"])
            c.mem_write(0x20380431, b"\0")
            c.context_restore(ctx)
            run(LOOP, IDLE, limit=10000000)
            assert (
                value(sy["state"])
                == value(sy["ftx_memory"])
                == value(sy["thread"])
                == 0
            )
            idle_context = c.context_save()
            assert not guard or largest_free() == available, (
                "session did not restore the native heap"
            )
            if guard:
                sub(0x20127A78, guard)
                assert largest_free() == before_heap
            c.context_restore(idle_context)
        assert (
            heaps[0]["requests"][:2] == heaps[2]["requests"][:2]
            and stacks[1] == stacks[2]
        )
        return {
            "heaps": heaps,
            "stacks": stacks,
            "stack_bytes": 4096,
            "stack_pool_pressure_blocks": held,
            "shared_sessions": 2,
            "busy_pool_ft8": decoded,
            "closed_three_sessions": True,
        }

    return probe(stock[0], application=image, audio_experiment=exercise)


def dial(stock, image, sy, *, tx_panel=False, remote_scope=False, previous=None):
    from tempfile import TemporaryDirectory

    from tools.emulate_705 import call
    from tools.verify_705_ftx_rx import map_atlas

    def attach(c, surface):
        map_atlas(c, ((previous or OUT) / "bench-rx.dat").read_bytes())

        def trial(turn, step, tap, frames):
            tap(37, 32)
            for _ in range(14):
                step()
            assert "FT8/4" in frames[-1]["glyphs"], (
                frames[-1]["glyphs"],
                val(c, 0x203E84C9, 2),
                val(c, sy["state"]),
            )
            tap(431, 192)
            for _ in range(14):
                step()
            assert "FT4" in frames[-1]["glyphs"]
            tap(120, 116)
            for _ in range(16):
                step()
            assert (
                "FT4" in frames[-1]["glyphs"]
                and any("USB-D" in f["glyphs"] for f in frames)
                and val(c, MODE_UI_A, 1) >> 4 == 1
                and val(c, sy["state"]) == 2
            ), frames[-1]
            # Feed the panel an advancing native RTC and exercise live VFO
            # discontinuities while the same worker continues listening.
            tap(440, 249)
            tap(100, 156)
            tap(100, 158)
            tap(441, 249)
            for sec in (0x11, 0x12):
                c.mem_write(0x2038079E, bytes((0x18, 0x32, sec)))
                for _ in range(12):
                    step()
            assert val(c, sy["clock_ready"]) and val(c, sy["enabled"])
            if remote_scope:
                from tools.replay_705_vfo_split import RADIO_ADDRESS, exchange_in_guest
                def shows_receiver():
                    return (val(c, sy["ftx_ft4"]) and not val(c, sy["ft_page"])
                            and any(w["source_target"] == 7 for w in frames[-1]["blits"]))
                c.mem_write(RADIO_ADDRESS,b"\xa4")
                for payload in ("27 10 01", "27 11 01"):
                    ctx = c.context_save()
                    try:
                        reply, _ = exchange_in_guest(c, bytes.fromhex(payload))
                        assert reply[2:-1] == b"\xfb"
                    finally:
                        c.context_restore(ctx)
                    old = len(frames)
                    for _ in range(32): step()
                    assert len(frames)>old and shows_receiver(), frames[-1]
                    assert val(c,sy["state"])==2 and val(c,0x203e84c9,1)==9
                tap(440,249)
                assert val(c,sy["ft_page"]) != 0
                tap(440,249)
                for _ in range(16): step()
                assert shows_receiver()
                return {"stock_scope_page":9,"ft_state":2,"displayed":"FT4","menu_round_trip":True}
            if tx_panel:
                tap(442,104);tap(442 if previous else 405,136)
                assert val(c,sy["ft_page"])==2
                for x,value in ((90,"BI1BIF"),(265,"OM89")):
                    tap(x,130)
                    for ch in value:
                        i="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".index(ch)
                        tap(18+39*(i%9),140+33*(i//9))
                    tap(442,173)
                tap(441,246)
                result=[]
                for directed in (False,True):
                    if directed:
                        tap(442,246)
                        now=val(c,sy["anchor_second"])*1000//7500
                        ctx=c.context_save()
                        row=call(c,sy["row_text"],0)
                        c.mem_write(row,b"CQ JA1ABC PM95".ljust(36,b"\0")+pack("<4iBB",1250,42,3,-13,0,11))
                        call(c,sy["view_publish"],now if now%2 else now-1,1)
                        call(c,sy["view_invalidate"]);c.context_restore(ctx)
                        for _ in range(16):step()
                        tap(121,109);tap(442,104)
                    assert val(c,sy["ft_page"])==1
                    # Model the handset sample at the touch; the simulated radio
                    # otherwise updates it from its own idle GPIO on every step.
                    addr=sy["ft_panel_touch"] & ~1
                    key_sample=c.hook_add(uc.UC_HOOK_CODE,lambda cpu,*_:cpu.mem_write(0x203809c4,b"\x01"),
                                          begin=addr,end=addr)
                    tap(405,105)  # inside both the painted key and its new left edge
                    c.hook_del(key_sample)
                    if previous:
                        reason=bytes(c.mem_read(val(c,sy["notice"]),32)).split(b"\0")[0].decode()
                        assert val(c,sy["stage"])==0 and reason=="PTT / TX busy"
                        return {"raw_mic_at_touch":1,"reason":reason}
                    assert val(c,sy["stage"])==1
                    for sec in (range(23,31) if directed else range(13,16)):
                        c.mem_write(0x2038079e,bytes((0x18,0x32,int(str(sec),16))))
                        for _ in range(12):step()
                        if val(c,sy["stage"])==2:break
                    request=val(c,0x203809ac)
                    filtered=val(c,0x203809b0)
                    assert request & filtered & 0x8000 and val(c,sy["stage"])==2
                    for _ in range(180):
                        step()
                        if val(c,sy["stage"])==0:break
                    ptr=val(c,sy["notice"])
                    reason=bytes(c.mem_read(ptr,32)).split(b"\0")[0].decode()
                    assert reason=="No DSP TX ack" and not val(c,0x203809b0)&0x8000
                    result.append(dict(path="reply" if directed else "CQ",request=request,filtered=filtered,
                                       raw_mic_at_touch=1,feedback_withheld=reason))
                    # Give the native RTC consecutive UART/I2C samples before the next touch.
                    if not directed:
                        for sec in range(16,24):
                            c.mem_write(0x2038079e,bytes((0x18,0x32,int(str(sec),16))))
                            for _ in range(12):step()
                return {"panel_transactions":result}

            up = turn(1)
            down = turn(-1)
            assert (
                up["after"] > up["before"]
                and down["after"] == up["before"]
                and val(c, sy["state"]) == 2
            )

            def publish(first, count):
                context = c.context_save()
                try:
                    row = call(c, sy["row_text"], 0)
                    for i in range(first, first + count):
                        text = f"CQ JA1ABC PM{i % 100:02}".encode()
                        c.mem_write(
                            row,
                            text.ljust(36, b"\0")
                            + pack("<4iBB", 1250, 40, 3, -13, 0, 11),
                        )
                        call(c, sy["view_publish"], i, 1)
                finally:
                    c.context_restore(context)

            publish(0, 240)
            full = turn(1)
            arriving = turn(-1, lambda i: publish(240 + i, 1))
            assert full == up and arriving == down
            assert val(c, sy["clock_ready"]) and val(c, sy["enabled"])

            def press(keys):
                for _ in range(18):
                    step(keys=keys)
                for _ in range(8):
                    step(keys=(0, 0))

            c.mem_write(0x203EAE2D, b"\1")
            c.mem_write(0x203E213C, b"\1")
            press((16, 0))
            assert val(c, 0x204BD19E, 2) == 0x201
            old_af = val(c, 0x204BD19E)
            tap(50, 248)
            for _ in range(8):
                step()
            assert val(c, 0x204BD19E) != old_af
            press((0, 4))
            assert not val(c, 0x204BD19E, 1) and val(c, sy["state"]) == 2
            press((2, 0))
            assert val(c, 0x204BD028, 1)
            press((1, 0))
            assert val(c, 0x204BD0BC, 2) == 0x101
            clock = val(c, sy["ftx_rtc"])
            tap(438, 99)
            assert val(c, sy["ftx_rtc"]) == clock
            press((0, 4))
            assert not val(c, 0x204BD028, 1) and val(c, sy["state"]) == 2
            tap(436, 242)
            tap(436, 213)
            for _ in range(14):
                step()
            assert not val(c, sy["state"]) and not val(c, sy["ftx_memory"])
            return {
                "up": up,
                "down": down,
                "after_240": full,
                "during_arrivals": arriving,
                "af_multi_twin": True,
                "touch_exit": True,
            }

        return (lambda: None), trial

    with TemporaryDirectory() as folder:
        return probe(
            stock[0],
            application=image,
            graphics=stock,
            render_output=Path(folder),
            screen=True,
            live=True,
            panel_experiment=attach,
        )


def coexistence(stock, image, sy):
    from struct import iter_unpack

    from tools.build_705_cw_sim import load_image
    from tools.build_705_cw_sstv_rx import D6
    from tools.probe_705_cw_field_audio import audio, bl_target, measure
    from tools.probe_705_sstv_arm import scheduler_replay
    from tools.replay_705_ftx_live import BASELINE

    _, meta = load_image(D6 / "CW-RX3-WAKE2-PC/CW-RX3-WAKE2-PC.ic705sim")
    wav = ROOT / ".analysis/sstv-robot36-v1/robot36.wav"
    reference = json.loads((ROOT / ".analysis/sstv-auto-rx/evidence.json").read_text())[
        "image_rgb565_sha256"
    ]
    raw = audio("CQ", trim_leading=True) + bytes(3204)
    cw = measure(
        image,
        meta,
        bl_target(image, meta["symbols"]["cw_rtx_worker"] + 28),
        list(iter_unpack("<6h", raw[: len(raw) // 12 * 12])),
        0,
        None,
    )
    assert cw["text"].strip() == "CQ"
    result = scheduler_replay(
        stock[0],
        image,
        symbols(OUT / "sstv/rx.elf"),
        wav,
        reference,
        combined=meta,
        from_reset=True,
    )
    return {"cw": cw, "sstv": result}


if __name__ == "__main__":
    from sys import argv

    candidate = (OUT / "bench-rx.dat").read_bytes()
    sy = symbols(OUT / "rx.elf")
    stock = load((ROOT / "firmware/705J140.dat").read_bytes())
    mode = argv[1]
    result = {"scheduler": scheduler, "dial": dial, "remote-panel":lambda *args: dial(*args,remote_scope=True), "tx-panel": lambda *args: dial(*args,tx_panel=True), "other-receivers": coexistence}[
        mode
    ](stock, bytes(decode_main(candidate)[1]), sy)
    if mode=="tx-panel":
        previous=OUT.parent/"j140-ftx-tx2e"
        prior=(previous/"bench-rx.dat").read_bytes()
        result["TX2e"]=dial(stock,bytes(decode_main(prior)[1]),symbols(previous/"rx.elf"),
                            tx_panel=True,previous=previous)
    result["dat_sha256"] = sha256(candidate).hexdigest()
    (OUT / (mode + ".json")).write_text(json.dumps(result, indent=2))
    print(result)
