"""Drive the installed FT panel, native TX request/filter and SSI output, then decode with WSJT-X."""

import json
import subprocess
import wave
from array import array
from hashlib import sha256
from struct import pack

from tools.probe_705_cw_pcm import (
    BUILD_REQUEST,
    FILTER_REQUEST,
    REQUEST,
    FILTERED,
    feed_dsp_tx,
    simulated_gpio,
)
from tools.verify_705_ftx_rx import (
    BASE,
    DMAC,
    INIT_RANGES,
    OUT,
    ROOT,
    SELECT_VFO,
    SettingsGuest,
    arm,
    call,
    compose,
    decode_main,
    load,
    map_atlas,
    menu_init,
    seed_vfos,
    symbols,
    uc,
    val,
)


def mount_station_card(cpu, sy, rom=lambda pc: pc):
    files, opened, pending, faults = {}, {}, [], {}
    paths = {r"C:\IC-705\FTX0.CFG", r"C:\IC-705\FTX1.CFG", r"C:\IC-705\FTLOG.ADI"}
    def operation(c, address, *_):
        a,b,n,d = (c.reg_read(reg) for reg in (
            arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3))
        rc=0
        address = original[address]
        if address==0x202D48C0:
            handler=val(c,a)
            if handler&~1 != sy["log_worker"]&~1: return
            assert not pending
            pending.append(handler);rc=1
        elif address==0x2023FEC8:
            path=bytes(c.mem_read(a,32)).split(bytes(1))[0].decode()
            assert path in paths and b in (0,0x201,0x202)
            if not b and path not in files: rc=7
            else:
                assert not opened
                files.setdefault(path,b"")
                opened[1]=[path,0]
                c.mem_write(n,pack("<I",1))
        elif address==0x2023FEE4:
            path,_=opened.pop(a)
            if path.endswith(".ADI") and faults.pop("close",False): rc=1
        else:
            path,pos=opened[a]
            if address==0x2023FF64:
                pos=(len(files[path]) if n==2 else 0)+b
                c.mem_write(d,pack("<I",pos))
            else:
                if address==0x2023FF00:
                    data=files[path][pos:pos+n]
                    if data:c.mem_write(b,data)
                else:
                    size=83 if n==320 and faults.pop("short",False) else n
                    data=bytes(c.mem_read(b,size))
                    files[path]=files[path][:pos]+data+files[path][pos+size:]
                c.mem_write(d,pack("<I",len(data)))
                pos+=len(data)
            opened[a][1]=pos
        c.reg_write(arm.UC_ARM_REG_R0,rc)
        c.reg_write(arm.UC_ARM_REG_PC,c.reg_read(arm.UC_ARM_REG_LR))

    original = {rom(pc): pc for pc in (0x202D48C0,0x2023FEC8,0x2023FEE4,0x2023FF00,0x2023FF18,0x2023FF64)}
    for pc in original:
        cpu.hook_add(uc.UC_HOOK_CODE,operation,begin=pc,end=pc)
    cpu.mem_write(0x20380172,bytes([3]))
    def pump():
        if pending: call(cpu,pending.pop(),instruction_limit=0)
    return files,pump,faults


def replay(dat, ft4, *, e140=None):
    mode = "FT4" if ft4 else "FT8"
    folder = (e140.folder if e140 else OUT) / mode
    folder.mkdir(parents=True, exist_ok=True)
    if e140:
        p, image = e140.station_guest(dat)
    else:
        p = SettingsGuest(load((ROOT / "firmware/705J140.dat").read_bytes()), front_panel=True)
        image = bytes(decode_main(dat)[1])
        p.cpu.mem_write(BASE, image)
        p.cpu.ctl_remove_cache(BASE, BASE + len(image))
        menu_init(p.cpu, image)
        map_atlas(p.cpu, dat)
    c, sy = p.cpu, symbols(OUT / "rx.elf")
    rom = p.rom
    c.mem_map(DMAC, 4096)
    simulated_gpio(c, rom=rom)
    call(c, rom(INIT_RANGES))
    seed_vfos(c, (14074000, 14080000))
    call(c, rom(SELECT_VFO[0]))
    c.mem_write(p.language_address, bytes(2))
    p.render()
    call(c, rom(0x200F1F04), 1)
    from tools.probe_705_sstv_picture import tick

    tick(p)

    def store(addr, n):
        c.mem_write(addr, pack("<I", n))

    def attr(name, n):
        store(sy[name], n)

    def get(name):
        return val(c, sy[name])

    def native(name, *args):
        return call(c, sy[name], *args, instruction_limit=0)

    def clock(ms):
        store(0x20381E08, ms)
        if get("ftx_rtc"):
            sec=ms//1000%86400
            c.mem_write(0x2038079e,bytes.fromhex(f"{sec//3600:02}{sec//60%60:02}{sec%60:02}"))
        attr("anchor_tick", ms // 1000 * 1000)
        attr("anchor_second", ms // 1000)
        attr("clock_ready", 1)

    def request(expected):
        for pc in (BUILD_REQUEST, FILTER_REQUEST, 0x20109E74):
            call(c, rom(pc))
        flags = [val(c, a) for a in (REQUEST, FILTERED)]
        assert [bool(f & 0x8000) for f in flags] == [expected] * 2, (
            flags,
            expected,
            get("stage"),
            mode,
        )
        assert bool(val(c, 0x203806F4, 1) & 128) == expected

    def route(armed):
        call(c, rom(0x20060C74))
        actual = (val(c, 0x203E1E60, 1), val(c, 0x20380875, 1))
        assert actual == ((8, 2) if armed else (1, 0)), (actual, armed)

    cw = p.surface.alloc(5120)
    c.mem_write(cw, bytes(5120))
    store(cw + 0x700, 1)
    attr("cw_state_anchor", cw)

    def wake(cpu, *_):
        cpu.reg_write(arm.UC_ARM_REG_R0, 0)
        cpu.reg_write(arm.UC_ARM_REG_PC, cpu.reg_read(arm.UC_ARM_REG_LR))

    c.hook_add(uc.UC_HOOK_CODE, wake, begin=rom(0x202D4850), end=rom(0x202D4850))
    p.click(37, 32)
    tick(p)
    compose(p)
    p.click(431, 192)
    tick(p)
    assert mode in compose(p)[0]
    p.click(120, 116 if ft4 else 79)
    tick(p)
    assert get("state") == 1
    native("ftx_step")
    assert get("state") == 2 and get("ftx_ft4") == ft4 and "USB-D" in compose(p)[0]
    c.mem_write(0x203EAAC7, bytes([128]))
    c.mem_write(0x203EAAC8, bytes(2))
    call(c, 0x200052ED, (0x20367B78 if e140 is None else e140.defaults) + 0x87C, 0x2038087C, 20)
    feed_dsp_tx(c, False, rom(0x200D4A28))
    attr("enabled", 1)
    beeps = []
    c.hook_add(
        uc.UC_HOOK_CODE,
        lambda cpu, *_: beeps.append(cpu.reg_read(arm.UC_ARM_REG_R0)),
        begin=rom(0x2007D478),
        end=rom(0x2007D478),
    )

    def tap(x, y, accepted=True):
        start = len(beeps)
        p.click(x, y)
        assert beeps[start:] == ([1] if accepted else []), (
            x,
            y,
            get("ft_page"),
            beeps[start:],
        )

    def panel(name):
        native("view_invalidate")
        labels, img = compose(p)
        img.save(folder / (name + ".png"))
        return labels

    clock(60000)
    # Choose the RTC on the actual panel and supply a valid native calendar.
    tap(440, 249)
    tap(100, 156)
    tap(100, 158)
    tap(441, 249)
    c.mem_write(0x2038079A, bytes.fromhex("26112005000100"))
    clock(60000)
    tap(437, 177, False)
    tap(443, 105)
    tap(443, 169, False)
    # A missing callsign and a missing grid each lead to the relevant setup page.
    tap(442,104)
    assert get("ft_page")==2 and get("stage")==0

    def field(x, value):
        tap(x, 130)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for ch in value:
            i = alphabet.index(ch)
            tap(18 + 39 * (i % 9), 140 + 33 * (i // 9))
        tap(442, 173)

    field(90, "K1ABC")
    tap(441,246)
    tap(442,104)
    assert get("ft_page")==2 and get("stage")==0
    field(265, "PM95")
    panel("settings")
    tap(441, 246)
    period = 7500 if ft4 else 15000

    def choose_station():
        if get("ft_page")==1: tap(442,246)  # end the retained QSO explicitly
        if ft4:
            # Publish a fresh CQ in B and choose the last visible decode.
            slot = val(c, 0x20381E08) // period
            msg = b"CQ JA1ABC PM95"
            row = native("row_text", 0)
            c.mem_write(row, msg.ljust(36, bytes(1)) + pack("<4iBB", 1250, 42, 3, -13, 0, 11))
            native("view_publish", slot if slot % 2 else slot - 1, 1)
            panel("received")
            visible = min(10, get("visible_count"))
            tap(120, 109 + 17*(visible-1))
        tap(442, 104)
    if ft4:
        tap(442,246)
        choose_station()
    expected = "JA1ABC K1ABC PM95" if ft4 else "CQ K1ABC PM95"
    assert expected in panel("preview")
    # Compare left/right rails, fixed end caps and actual fill on cached QSO frames.
    edge_ms=60000
    for offset,width in ((0,0),(period//2,35),(period-1,69),(period,0)):
        clock(edge_ms+offset)
        labels,pic=compose(p)
        pixels=[pic.getpixel((x,94)) for x in range(148,218)]
        filled=[i for i,(r,g,b) in enumerate(pixels) if b>170]
        assert filled==list(range(width)),(mode,offset,filled)
        assert pic.getpixel((147,94))==pic.getpixel((218,94))==pic.getpixel((173,90))
        assert ("B" if offset==period else "A") in labels
    clock(edge_ms)
    tap(405,213 if ft4 else 138)
    assert get("ft_page")==2
    # Keep the QSO cache token to model a previous draw that completed after the touch.
    attr("cached",2)
    labels, first_setup=compose(p)
    assert "1500" in " ".join(labels) and expected not in labels, labels
    clock(60500)
    native("ftx_input")
    labels, next_setup=compose(p)
    assert "A  00.5s" in labels and first_setup.crop((0,110,355,246)).tobytes()==next_setup.crop((0,110,355,246)).tobytes()
    tap(442,246)
    clock(60000)
    assert expected in compose(p)[0]
    assert "SEND > WAIT A" not in panel("play")
    request(False)
    # No clock, radio busy, different TX VFO, and cancellation before the slot.
    attr("clock_ready", 0)
    tap(442, 104)
    request(False)
    no_clock_notice = "Select a fresh decode" if ft4 else "Waiting for UTC"
    assert get("stage") == 0 and no_clock_notice in panel("no-clock")
    clock(60000)
    c.mem_write(0x203809C4, b"\x40")
    tap(442, 104)
    assert get("stage") == 0
    assert "Radio TX inhibit" in panel("inhibit")
    c.mem_write(0x203809C4, b"\0")
    for addr, mask, reason in ((0x203806f4,32,"Remote PTT"),(FILTERED,1,"Other TX request"),
                               (0x203809a1,16,"Radio TX active"),(0x203806f4,128,"Radio TX active")):
        prior=val(c,addr,1)
        c.mem_write(addr,bytes([prior|mask]))
        tap(442,104)
        assert get("stage")==0 and reason in compose(p)[0]
        c.mem_write(addr,bytes([prior]))
    call(c, rom(0x20103914), 0, 1)
    tap(442, 104)
    assert get("stage") == 0
    call(c, rom(0x20103914), 0, 0)
    tap(442, 104)
    assert get("stage") == 1, (
        get("stage"),
        [
            (hex(a), bytes(c.mem_read(a, 4)).hex())
            for a in (
                0x203E2128,
                0x203E212F,
                0x203E2136,
                0x203806F4,
                0x203809B0,
                0x203809C4,
                0x203809A1,
                0x20380714,
            )
        ],
        call(c, rom(0x201031DC), 0),
        panel("failed-arm"),
    )
    assert "WAIT TX A" in panel("queued")
    assert ("A -15.0s" if ft4 else "A -30.0s") in compose(p)[0]
    tap(442, 104)
    request(False)
    choose_station()
    tap(442, 104)
    old = val(c, 0x20380714)
    store(0x20380714, old + 10)
    request(False)
    assert get("stage") == 0
    store(0x20380714, old)
    tap(442, 104)
    period = 7500 if ft4 else 15000
    clock(60000 + period)
    request(False)
    start = 60000 + 2 * period
    clock(start+260)  # A busy display can delay the native poll beyond 180 ms.
    request(True)
    route(True)
    assert get("stage") == 2
    c.reg_write(arm.UC_ARM_REG_R4, DMAC)
    c.reg_write(arm.UC_ARM_REG_R5, 288)
    c.emu_start(rom(0x200FEF1C), rom(0x200FEF40))
    seq = 0

    def audio():
        nonlocal seq
        bank = seq % 2
        seq += 1
        c.mem_write(DMAC + 0x124, pack("<I", 0x41 if bank else 0xC1))
        call(c, rom(0x200FFD48), timeout_us=0)
        words = c.mem_read(0x20400A40 + bank * 288, 288)
        out = bytearray(72)
        out[::2], out[1::2] = words[6::8], words[7::8]
        return out

    def send_armed(stop_at_drain=False):
        slot = get("waiting_slot") + 1
        slot += (slot & 1) != get("parity")
        edge = slot * period
        clock(edge)
        request(True)
        route(True)
        feed_dsp_tx(c, True, rom(0x200D4A28))
        clock(edge + 500)
        audio()
        assert get("stage") == 3
        attr("symbol", 104 if ft4 else 78)
        attr("sample", (2304 if ft4 else 7680) - 36)
        clock(edge + 500 + (5040 if ft4 else 12640) - 1)
        audio()
        assert get('stage') == 4
        if stop_at_drain:
            tap(442, 104)
        assert not any(audio()) and not any(audio())
        request(False)
        feed_dsp_tx(c, False, rom(0x200D4A28))
        request(False)
        route(False)
        assert get("stage") == 0
        return slot

    def incoming(msg, slot):
        row = native("row_text", 0)
        sender = msg.index(" ") + 1
        c.mem_write(
            row,
            msg.encode().ljust(36, bytes(1))
            + pack("<4iBB", 1250, 42, sender, -13, 0, 0),
        )
        native("view_publish", slot, 1)
        labels, _ = compose(p)
        return labels

    assert not any(audio())
    # Cancel while keyed. All audio stays silent until the DSP acknowledges RX.
    feed_dsp_tx(c, True, rom(0x200D4A28))
    tap(443, 104)
    request(False)
    assert not any(audio())
    feed_dsp_tx(c, False, rom(0x200D4A28))
    request(False)
    route(False)
    choose_station()
    tap(442, 104)
    clock(start + 2 * period)
    request(True)
    route(True)
    clock(start + 2 * period + 601)
    request(False)
    feed_dsp_tx(c, False, rom(0x200D4A28))
    request(False)
    assert get("stage") == 0
    clock(start + 3 * period)
    c.mem_write(0x203809c4,b"\x01")  # raw mic sample, no published TX owner
    tap(442, 104)
    start += 4 * period
    clock(start)
    request(True)
    route(True)
    feed_dsp_tx(c, True, rom(0x200D4A28))
    pcm = array("h")
    for i in range(period * 48 // 36):
        store(0x20381E08, start + i * 36 // 48)
        if i % 32 == 0:
            request(True)
        pcm.frombytes(audio())
        if i==720: assert "ON AIR" in panel("on-air")
        if get("stage") == 5:
            break
    assert get("stage") == 5 and get("attempts") == 1
    request(False)
    feed_dsp_tx(c, False, rom(0x200D4A28))
    request(False)
    route(False)
    c.mem_write(0x203809c4,b"\0")
    assert bool(get("sequence_on")) == (not ft4) and get("stage") == 0
    if not ft4:
        # Manual CQ also repeats. A fresh answer cancels the reserved CQ and
        # opens the report for the operator without keying automatically.
        reply_slot=start//period+1
        clock(reply_slot*period+period-1100)
        native("ft_station_tick")
        assert get("stage")==1 and get("waiting_slot")==reply_slot
        row=native("row_text",0)
        c.mem_write(row,b"K1ABC DL1ABC JO62".ljust(36,bytes(1))+pack("<4iBB",1180,42,6,-11,0,0))
        native("view_publish",reply_slot,1)
        assert "DL1ABC K1ABC -11" in compose(p)[0]
        assert not get("stage") and not get("sequence_on")
        request(False)
        # Other valid responders stay distinct. Browsing them must not arm RF.
        for msg in ("K1ABC F4ABC JN18","K1ABC F4ABC JN18","K1ABC G4ABC IO91"):
            incoming(msg,reply_slot)
        assert get("others")==2
        tap(442,175);assert "F4ABC" in panel("other-caller")
        tap(442,175);assert "G4ABC" in compose(p)[0]
        tap(442,136);assert "DL1ABC K1ABC -11" in panel("manual-report")
        tap(442,104);tap(442,104);request(False)
        assert get("ft_page")==1 and get("stage")==0 and not get("sequence_on")
        clock((reply_slot+1)*period+300)
        request(False)
        tap(442,104)
        assert "A -29.7s" in panel("late-report")
        own=send_armed()
        native("ft_station_tick")
        assert own==reply_slot+3 and get("ft_page")==1
        clock((own+1)*period+period-900)
        labels=incoming("K1ABC DL1ABC R-09",own+1)
        assert "K1ABC DL1ABC R-09" in labels and "DL1ABC K1ABC RR73" in labels
        assert get("stage")==0 and get("checked_partner")
        tap(442,104);tap(442,104);request(False)
        assert not get("outcome") and not get("log_complete")
        tap(442,104)
        send_armed(stop_at_drain=True)
        native('ft_station_tick')
        assert get('ft_page')==1 and not get('outcome') and not get('log_complete') and not get('sequence_on')
        # A new station identity cannot inherit the old operator's exchange proof.
        def last_call_letter(letter):
            tap(442,213)
            tap(90,130)
            tap(442,136)
            tap(18+39*(ord(letter)-ord("A")),140)
            tap(442,173)
            tap(441,246)
        assert get("checked_partner")
        last_call_letter("D")
        tap(442,104)
        assert get("stage")==1 and not get("checked_partner")
        tap(442,104)
        last_call_letter("C")
        tap(442,246)
    pcm.extend([0] * (period * 48 - len(pcm)))
    active = [i for i, sample in enumerate(pcm) if sample]
    assert (
        0.49 <= active[0] / 48000 < 0.53
        and abs(active[-1] / 48000 - (0.5 + (5.04 if ft4 else 12.64))) < 0.026
    )
    wav = folder / "261119_120000.wav"
    with wave.open(str(wav), "wb") as f:
        f.setparams((1, 2, 12000, 0, "NONE", ""))
        f.writeframes(pcm[::4].tobytes())
    decoded = subprocess.run(
        [
            "wsl",
            "-d",
            "Debian",
            "-e",
            "jt9",
            "--" + mode.lower(),
            "-p",
            str(period / 1000),
            "-d",
            "2",
            wav.name,
        ],
        cwd=folder,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    print(mode, decoded.stdout, decoded.stderr, flush=True)
    assert decoded.returncode == 0 and expected in decoded.stdout, (
        expected,
        decoded.stdout,
        decoded.stderr,
    )
    # Subsequent protocol tests fast-forward the middle of each encoded frame.
    # First and last blocks still pass through the native SSI and DSP feedback.
    clock(start + period - 100)
    native("ft_station_tick")
    choose_station()
    records, pump, faults = mount_station_card(c,sy,rom)
    tap(442,213 if ft4 else 136)
    tap(87, 230)  # AUTO SEQ
    tap(441, 247)
    assert get("config_sequence") == 1
    if ft4:
        tap(442,136)
        tap(175,184)
        assert "TX A   1250 Hz    AUTO x3" in panel("reply-channel")
    tap(442, 104)
    assert get("stage") == 1 and get("sequence_on")

    own = send_armed()
    clock((own + 1) * period + 600)
    native("ft_station_tick")
    assert get("stage")==1
    incoming("K1ABC JA1ABC 73", own - 1)
    assert get("sequence_on") and get("stage") == 1
    incoming("K1ABC XX1AB PM95", own - 1)
    assert get("stage") == 1
    sequence = [expected]
    for received, following in (
        ("K1ABC JA1ABC -12" if ft4 else "K1ABC JA1ABC PM95", "R-13" if ft4 else "-13"),
        ("K1ABC JA1ABC RR73" if ft4 else "K1ABC JA1ABC R-09", "73" if ft4 else "RR73"),
    ):
        msg = "JA1ABC K1ABC " + following
        messages=incoming(received, own+1)
        assert msg in messages,(received,msg,messages, get("kind"),get("stage"),get("sequence_on"))
        assert get("stage") == 1 and get("sequence_on")
        sequence.append(msg)
        previous_own=own
        own = send_armed()
        assert own==previous_own+2
        clock((own + 1) * period + period-900)
    # Recover a partial record, then a successful write whose close reports an error.
    faults["short"]=True
    logpath=r"C:\IC-705\FTLOG.ADI"
    for i in range(8):
        clock((own+2)*period+450+4000*i)
        native("ft_station_tick")
        if logpath in records and 40<len(records[logpath])<320: faults.setdefault("close",True)
        pump()
        if records.get(logpath,b"").count(b"<EOR>")==1 and i>=5:break
    assert records[logpath].count(b"<EOR>")==1,records
    import re
    adif=records[logpath].decode("ascii")
    fields={k:adif[m.end():m.end()+int(n)] for m in re.finditer(r"<([A-Z_]+):([0-9]+)>",adif) for k,n in [m.groups()]}
    assert fields["CALL"]=="JA1ABC" and fields["STATION_CALLSIGN"]=="K1ABC" and fields["BAND"]=="20m",fields
    assert fields.get("SUBMODE",fields["MODE"])==mode and fields["QSO_DATE"]=="20261120",fields
    assert fields["RST_SENT"]=="-13" and fields["RST_RCVD"]==("-12" if ft4 else "-09"),fields
    assert fields["TIME_OFF"]>fields["TIME_ON"],fields
    (folder/"FTLOG.ADI").write_bytes(records[logpath])
    native("ft_station_tick")
    assert not get("sequence_on") and get("stage") == 0
    assert get("outcome")==3 and get("ft_page")==1
    panel("written-log")
    tap(442,246)
    tap(442,104)  # home CQ preview
    tap(442, 104)
    cq_slots=[]
    for retry in range(1, 4):
        own = send_armed()
        assert get("attempts") == retry
        cq_slots.append(own)
        clock((own + (2 if retry==3 else 1)) * period + 100)
        native("ft_station_tick")
    assert not get("sequence_on") and get("stage") == 0
    assert cq_slots==list(range(cq_slots[0],cq_slots[0]+6,2)),cq_slots
    assert "No reply - stopped" in panel("retry-limit")
    # A delayed decode after the last unanswered CQ cannot restart TX.
    incoming("K1ABC DL1ABC JO62", own+1)
    request(False)
    assert not get("sequence_on") and get("kind")==0 and not get("stage")
    # Start a second saved record, then model a short read after a power cycle.
    tap(442, 136)
    tap(88, 162)
    tap(442, 246)
    assert get("config_sequence") == 2 and len([k for k in records if k.endswith(".CFG")]) == 2

    def reboot_prefs():
        attr("config_sequence", 0)
        c.mem_write(sy["pref"], image[sy["pref"] - BASE : sy["pref"] - BASE + 22])
        native("ft_station_close")
        native("ft_station_open")
        assert get("stage") == get("sequence_on") == 0
        assert bytes(c.mem_read(sy["pref"], 6)) == b"K1ABC" + bytes(1)
        assert bytes(c.mem_read(sy["pref"] + 12, 5)) == b"PM95" + bytes(1)

    reboot_prefs()
    assert get("config_sequence") == 2 and get("parity") == 1
    last = next(name for name in records if "FTX0" in name)
    records[last] = records[last][:8]
    reboot_prefs()
    assert get("config_sequence") == 1 and get("parity") == 0
    # An already-worked sender must be excluded even after reopening FT.
    logptr=p.surface.alloc(32);c.mem_write(logptr,b"JA1ABC"+bytes(1))
    def poll(ms):
        clock(ms);native("ft_station_tick");pump();native("ft_station_tick")
    base=300*period
    tap(440,249);tap(80,125)  # FT menu -> log
    for i in range(4):
        native("ft_worked",logptr);poll(base+300*i)
    assert native("ft_worked",logptr)==1
    assert "JA1ABC" in panel("log")
    store(0x20380714,7074000);poll(base+1800)
    native("ft_worked",logptr);poll(base+2400)
    assert native("ft_worked",logptr)==0
    store(0x20380714,14074000);poll(base+2700)
    tap(440,249)
    # Real home Auto -> choose scope -> Enable. A public CQ and a
    # directed call arrive in the same frame; only the directed call is armed.
    tap(440,141);tap(80,125);tap(440,105)
    assert get("ft_auto_armed") and not get("stage")
    slot=302
    clock((slot+1)*period+400)
    for msg in ("CQ DL1ABC JO62","K1ABC JA1ABC PM95","K1ABC F4ABC JN18"):
        pos=msg.index(" ")+1
        row=native("row_text",0)
        c.mem_write(row,msg.encode().ljust(36,bytes(1))+pack("<4iBB",1410,42,pos,-11,0,0))
        native("view_publish",slot,1)
    for i in range(4):
        compose(p);poll((slot+1)*period+450+300*i)
    assert not get("ft_auto_armed") and get("stage")==1,(get("stage"),get("ft_auto_armed"))
    assert "F4ABC K1ABC -11" in panel("auto-directed")
    tap(440,104);request(False)
    assert get("ft_page")==1 and not get("sequence_on") and records[logpath].count(b"<EOR>")==1
    tap(442,246)
    # In directed-only mode a fresh public CQ remains on the receive screen.
    tap(440,141);tap(80,125);tap(440,105)
    slot+=3
    clock((slot+1)*period+400)
    incoming("CQ DL1ABC JO62",slot)
    poll((slot+1)*period+900);compose(p)
    assert get("ft_auto_armed") and not get("stage")
    tap(440,104)
    # Explicit permission for public CQ allows one first reply.
    tap(440,141);tap(80,125);tap(440,105)
    slot+=3
    clock((slot+1)*period+400)
    incoming("CQ DL1ABC JO62",slot);poll((slot+1)*period+900);compose(p)
    assert get("stage")==1 and "DL1ABC K1ABC PM95" in panel("auto-public")
    tap(440,104);request(False)
    # RTC UTC offset crosses the preceding day at midnight.
    c.mem_write(0x2038079A,bytes.fromhex("26010104003015"))
    c.mem_write(sy["pref"]+22,bytes([4]))
    assert native("utc_stamp",logptr)==1 and bytes(c.mem_read(logptr,14))==b"20251231233015"
    from tools.verify_705_ftx_rx import gps,BYTE_RX,GPS_INIT,GPS_MODE
    c.mem_write(GPS_MODE,bytes([1]));call(c,rom(GPS_INIT))
    for second in range(3605,3611):gps(c,second,rom(BYTE_RX))
    attr("ftx_rtc",0)
    assert native("utc_stamp",logptr)==1 and bytes(c.mem_read(logptr,14))==b"20261114010010"
    return {
        "wsjtx": decoded.stdout.strip(),
        "first_sample_ms": active[0] / 48,
        "last_sample_ms": active[-1] / 48,
        "native_beeps": len(beeps),
        "adif":fields,
        "automatic_first_reply":"F4ABC (directed, public CQ and worked station skipped)",
        "worked_band_and_utc_rollover":True,
        "manual_caller_regression": ("retained peer, two unique alternative callers, cancel and retry, 29.7 s to next A, stop RR73 during drain without logging" if not ft4 else "directed reply with native RF grant"),
        "changed_station_identity_cannot_log_old_exchange": True if not ft4 else "covered by shared FT8 scenario",
        "late_caller_after_cq_limit_ignored": True,
        "auto_sequence": sequence,
        "unanswered_limit": 3,
        "cq_slots": cq_slots,
        "sd_records_validated": 2,
        "stop_and_retune": True,
        "busy_split_missing_feedback_and_stale_clock": True,
        "settings_clock_and_return_to_preview":True,
        "raw_mic_sample_during_complete_tx":True,
        "wav_sha256": sha256(wav.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sstv",
        action="store_true",
        help="exercise the original SSTV modulation path in the same image",
    )
    args = parser.parse_args()
    data = (OUT / "bench-rx.dat").read_bytes()
    if args.sstv:
        from tools.probe_705_sstv_tx import exercise

        results = exercise(
            OUT / "sstv-tx",
            None,
            (bytes(decode_main(data)[1]), symbols(OUT / "sstv/rx.elf")),
            initialize_menus=menu_init,
        )
    else:
        results = {mode: replay(data, i) for i, mode in enumerate(("FT8", "FT4"))}
    results["dat_sha256"] = sha256(data).hexdigest()
    (OUT / ("sstv-tx.json" if args.sstv else "station.json")).write_text(
        json.dumps(results, indent=2)
    )
