"""Run the V2 FT panel and transmit engine from a packaged J140/E140 DAT."""
from array import array
import argparse
from hashlib import sha256
import json
from os import environ
from pathlib import Path
import subprocess
from struct import pack, unpack
import wave

from tools.build_705_aprs_slot import scatter
from tools.build_705_ft_operating import CAPACITY, RAM, ROOT
from tools.emulate_705 import arm, call, machine, uc
from tools.probe_705_cw_pcm import (BUILD_REQUEST, FILTER_REQUEST, FILTERED, REQUEST,
                                     feed_dsp_tx, simulated_gpio)
from tools.probe_705_sstv_picture import tick
from tools.replay_705_stock_install import load_a
from tools.verify_705_e140_station import E_MAIN, EuropeanReplay
from tools.verify_705_ftx_rx import (BASE, DMAC, INIT_RANGES, OUT, SELECT_VFO, SettingsGuest,
                                    compose, decode_main, fixture, load, map_atlas, menu_init,
                                    published_rows, recording, seed_vfos, symbols, val)
from tools.verify_705_ftx_tx import mount_station_card


def replay(package, ft4, *, receive_only=False, layout_only=False):
    record = json.loads((package/"package.json").read_text())
    region = record["region"]
    name = f"705{region}140.dat"
    dat = (package/name).read_bytes()
    assert sha256(dat).hexdigest() == record["sha256"]
    stock_dat = (ROOT/"firmware"/name).read_bytes()
    # The decompression tail is temporary at cold boot. Loading it again
    # over a live display fixture would overwrite that fixture's native data.
    loaded_bytes = record["ft_previous_main_size"]
    if region == "E":
        stock, stock_flash = load_a(stock_dat, E_MAIN)
        board = EuropeanReplay(stock,stock_flash,record["main_sha256"])
        guest, image = board.station_guest(dat,loaded_bytes=loaded_bytes)
        defaults = board.defaults
    else:
        stock = bytes(decode_main(stock_dat)[1])
        image = bytes(decode_main(dat)[1])
        guest = SettingsGuest(load(stock_dat),front_panel=True)
        guest.cpu.mem_write(BASE,image[:loaded_bytes])
        guest.cpu.ctl_remove_cache(BASE,BASE+loaded_bytes)
        menu_init(guest.cpu,image)
        map_atlas(guest.cpu,dat)
        defaults = 0x20367B78

    cpu, rom = guest.cpu, guest.rom
    boot_memory = machine(image)
    scatter(boot_memory)
    cpu.mem_write(RAM,bytes(boot_memory.mem_read(RAM,CAPACITY)))
    cpu.ctl_remove_cache(RAM,RAM+CAPACITY)
    labels = symbols(OUT/"rx.elf")
    operating = symbols(package/"operating.elf")
    mode = "FT4" if ft4 else "FT8"
    period = 7500 if ft4 else 15000
    folder = package/mode
    folder.mkdir(exist_ok=True)

    def native(label, *args):
        return call(cpu,labels[label],*args,instruction_limit=0)

    def get(label, size=4):
        return val(cpu,labels[label],size)

    def status():
        return call(cpu,operating["operating_status"])

    def attr(label, word):
        cpu.mem_write(labels[label],pack("<I",word))

    def clock(ms):
        cpu.mem_write(0x20381e08,pack("<I",ms))
        sec = ms//1000%86400
        cpu.mem_write(0x2038079e,bytes.fromhex(f"{sec//3600:02}{sec//60%60:02}{sec%60:02}"))
        attr("anchor_tick",ms//1000*1000)
        attr("anchor_second",ms//1000)
        attr("clock_ready",1)
        # UI and TX scenarios supply decoded rows directly. Mark the panel
        # clock as receiving audio; receive_only tests the native PCM path.
        attr("audio_tick",ms)

    def panel(label):
        native("view_invalidate")
        words,image = compose(guest)
        image.save(folder/f"{label}.png")
        return words

    def tap(x,y):
        guest.click(x,y)

    def poll():
        native("ftx_input")

    def request(on):
        for handler in (BUILD_REQUEST,FILTER_REQUEST,0x20109e74):
            call(cpu,rom(handler))
        flags = [bool(val(cpu,address)&0x8000) for address in (REQUEST,FILTERED)]
        assert flags == [on,on], (mode,on,flags,get("stage"))

    cpu.mem_map(DMAC,4096)
    simulated_gpio(cpu,rom=rom)
    call(cpu,rom(INIT_RANGES))
    seed_vfos(cpu,(14074000,14080000))
    call(cpu,rom(SELECT_VFO[0]))
    cpu.mem_write(guest.language_address,bytes(2))
    guest.render()
    call(cpu,rom(0x200f1f04),1)
    tick(guest)
    cw = guest.surface.alloc(5120)
    cpu.mem_write(cw,bytes(5120))
    cpu.mem_write(cw+0x700,pack("<I",1))
    attr("cw_state_anchor",cw)

    def wake(c,*_):
        c.reg_write(arm.UC_ARM_REG_R0,0)
        c.reg_write(arm.UC_ARM_REG_PC,c.reg_read(arm.UC_ARM_REG_LR))

    notify = rom(0x202d4850)
    cpu.hook_add(uc.UC_HOOK_CODE,wake,begin=notify,end=notify)
    for x,y in ((37,32),(431,192),(120,116 if ft4 else 79)):
        tap(x,y)
        tick(guest)
        compose(guest)
    assert get("state") == 1
    native("ftx_step")
    assert get("state") == 2 and get("ftx_ft4") == ft4 and "USB-D" in compose(guest)[0]
    assert bytes(cpu.mem_read(operating["operating"] ,4)) == pack("<I",1)
    cpu.mem_write(0x203eaac7,b"\x80\0\0")
    cpu.mem_write(0x2038087c,stock[defaults+0x87c-BASE:defaults+0x890-BASE])
    feed_dsp_tx(cpu,False,rom(0x200d4a28))
    attr("enabled",1)
    card,pump,faults = mount_station_card(cpu,labels,rom)

    clock(60000)
    tap(440,249)               # Menu
    tap(100,156)               # Time
    tap(100,158)               # RTC
    tap(441,249)               # Return to list
    assert get("ftx_rtc") == 1
    cpu.mem_write(0x2038079a,bytes.fromhex("26112005000100"))
    clock(60000)
    tap(442,104)               # Missing callsign routes to station settings
    assert get("ft_page") == 2 and get("stage") == 0

    def type_call(value):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for ch in value:
            i = alphabet.index(ch)
            tap(18+39*(i%9),140+33*(i//9))
        tap(442,173)

    tap(90,130)
    type_call("K1ABC")
    tap(265,130)
    type_call("PM95")
    tap(441,246)
    pump()
    assert bytes(cpu.mem_read(labels["pref"],6)) == b"K1ABC\0"
    # Setup opened from the CQ button. Return to the list without an RF request.
    assert get("ft_page") == 0 and get("stage") == 0
    if layout_only:
        cpu.mem_write(0x203EB16C,bytes([2]))
        cpu.mem_write(0x203EA85D,pack('>BHcBHc',35,41000,b'N',139,41400,b'E'))
        clock(82500)
        rows=[
            ('JA3ABC','PM74',-6,845), ('HL2ABC','PM37',-11,1035),
            ('9M2ABC','OJ03',-17,1870), ('ZL1ABC','RF73',-9,720),
            ('VK2ABC','QF56',-14,2510), ('HZ1ABC','LL34',-18,1290),
            ('DL1ABC','JO62',-3,1785), ('VE7ABC','CN89',-12,2310),
            ('PY2ABC','GG66',-21,975), ('VR2ABC','OL72',-8,1430)]
        bodies=[
            'CQ JA3ABC','JA3ABC HL2ABC -11','CQ DX 9M2ABC OJ03','K1ABC ZL1ABC 73',
            'VE7ABC VK2ABC R-14','CQ HZ1ABC LL34','EA8/DL1XYZ DL1ABC RR73',
            'VK2ABC VE7ABC CN89','K1ABC PY2ABC RRR','CQ VR2ABC OL72']

        def publish(station,grid,db,hz,body,slot):
            row=native('row_text',0)
            cpu.mem_write(row,body.encode().ljust(36,bytes(1))+pack('<4iBB',hz,42,body.index(station),db,0,
                          body.index(grid)+1 if grid in body else 0))
            native('view_publish',slot,1)
        for station,grid,db,hz in rows:
            publish(station,grid,db,hz,f'CQ {station} {grid}',1)
        for i,(station,grid,db,hz) in enumerate(rows):
            publish(station,grid,db,hz,bodies[i],4+i//5)
        native('view_invalidate')
        words,image=compose(guest)
        image.save(folder/'mixed-list.png')
        assert 'QTH' in words and '-21' in words and '2510' in words
        return dict(dat_sha256=record['sha256'],message_cells=22,columns=[214,280,310,352],
                    image='mixed-list.png')

    words = compose(guest)[0] if receive_only else panel("listen")
    assert "QTH" in words and status() == 0,words

    def header_layout():
        texts, bars = {}, []
        regs = (arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3)

        def text_call(c,*_):
            pos = tuple(c.reg_read(reg) for reg in regs)
            if pos[1] != 88:
                return
            ptr = c.reg_read(arm.UC_ARM_REG_R0)
            word = bytes(c.mem_read(ptr,6)).split(b"\0",1)[0].decode("ascii",errors="replace")
            texts[word] = pos

        def rectangle_call(c,*_):
            pos = tuple(c.reg_read(reg) for reg in regs)
            if pos[0] in (56,57) and pos[1] in (90,91):
                bars.append(pos)

        hooks = []
        for name, handler in (("text",text_call),("rectangle",rectangle_call)):
            site = labels[name]&~1
            hooks.append(cpu.hook_add(uc.UC_HOOK_CODE,handler,begin=site,end=site))
        for phase, offset in (("A",0),("B",period)):
            clock(60000+offset+period//2)
            texts.clear()
            bars.clear()
            panel(f"header-{phase}")
            assert texts[mode] == (4,88,13) and texts[phase] == (42,88,13), texts
            assert texts["QTH"] == (214,88,13) and texts["dB"] == (280,88,13), texts
            assert texts["Hz"] == (310,88,13), texts
            assert texts["k"] == (352,88,13) and texts["m"] == (360,88,13), texts
            assert len(bars) == 3 and bars[:2] == [(56,90,82),(57,91,80)], bars
            assert bars[-1][:2] == (57,91) and 25 < bars[-1][2] <= 40, bars
            if "ECO" in texts:
                assert texts["ECO"][0] >= 144, texts
        prior_width = bars[-1][2]
        clock(60000+period+period*3//4)
        texts.clear()
        bars.clear()
        compose(guest)
        assert mode not in texts and texts["B"] == (42,88,13), texts
        assert len(bars) == 3 and bars[:2] == [(56,90,82),(57,91,80)], bars
        assert bars[-1][:2] == (57,91) and prior_width < bars[-1][2] <= 60, bars
        position_mode, manual_position = 0x203EB16C, 0x203EA85D
        saved_mode = bytes(cpu.mem_read(position_mode,1))
        saved_position = bytes(cpu.mem_read(manual_position,8))
        cpu.mem_write(position_mode,b"\2")
        cpu.mem_write(manual_position,pack(">BHcBHc",39,47125,b"N",116,37476,b"E"))
        texts.clear()
        assert "M" in panel("header-manual-position") and texts["M"] == (376,88,12), texts
        for word, limit in (("m",376),("M",397)):
            glyph, = (event["glyphs"][-1] for event in guest.surface.events
                      if "".join(chr(g["key"]) for g in event["glyphs"]).strip() == word)
            # The compositor unfolds this LCD tile 360 pixels to the right.
            right = 360+glyph["offset"][0]+max(glyph["coordinates"][::2])
            assert right < limit, (word,right)
        cpu.mem_write(position_mode,saved_mode)
        cpu.mem_write(manual_position,saved_position)
        for hook in hooks:
            cpu.hook_del(hook)
        clock(60000)
        return dict(mode_x=4,slot_x=42,text_y=88,heading_size=13,manual_heading_fits=True,
                    rail_x=56,rail_width=82,full_and_cached_draw=True)

    if receive_only:
        frame_samples = period*8
        wav = (ROOT/".analysis/ftx-station/FT4/busy/000000_000001.wav" if ft4 else
               ROOT/".analysis/ftx-lib/test/wav/websdr_test1.wav")
        feed = fixture(cpu,map_dma=False,e140=region=="E")
        cpu.mem_write(0x180000,recording(wav,frame_samples))
        cpu.mem_write(0x1c0000,bytes(2*frame_samples))
        attr("clock_ready",0)
        attr("last_second",0xffffffff)
        audio_peak = 0
        def measure(cpu,*_):
            nonlocal audio_peak
            start = cpu.reg_read(arm.UC_ARM_REG_R0)
            audio_peak = max(audio_peak,*map(abs,unpack("<6h",cpu.mem_read(start,12))))
        entry=labels["ftx_audio"]&~1
        probe=cpu.hook_add(uc.UC_HOOK_CODE,measure,begin=entry,end=entry)
        received = {}
        end = frame_samples+24000
        for index in range(-48000,end,576):
            stop = min(index+576,end)
            while index < stop:
                slot,offset = divmod(index,frame_samples)
                sec = index//8000
                ms = (index+48000)//8+120000
                cpu.mem_write(0x20381e08,pack("<I",ms))
                day = sec%86400
                cpu.mem_write(0x2038079e,bytes.fromhex(f"{day//3600:02}{day//60%60:02}{day%60:02}"))
                until = min(stop,(slot+1)*frame_samples,((sec+1)*8000+5)//6*6)
                source = 0x180000 if slot == 0 else 0x1c0000
                call(cpu,feed,source+2*offset,(until-index)//6,instruction_limit=0)
                index=until
            native("ftx_step")
            mid = get("middle")
            if mid&4:
                batch = get("ftx_memory")+32768+(mid&3)*(8+48*44)
                slot = val(cpu,batch+4) % (86400000//period)
                rows,_ = published_rows(cpu,batch)
                if rows: received[slot] = rows
        found = received.get(0,[])
        cpu.hook_del(probe)
        assert len(found)>=10 and not get("overruns") and not get("gaps"),(
            received,audio_peak,{key:get(key) for key in ("adc","enabled","clock_ready","last_second",
                  "anchor_second","tuning_blocked","phase","generation","consumed","gaps","overruns","middle")},
            {hex(a):val(cpu,a) for a in (0x203809a1,0x203809ac,0x203809b0,0x2038089d)})
        panel("native-rx")
        return dict(dat_sha256=record["sha256"],protocol=mode,native_dma_messages=found,
                    audio_sha256=sha256(wav.read_bytes()).hexdigest(),gaps=0,overruns=0)

    # The candidate still uses the factory DMA route and decoder.
    cpu.reg_write(arm.UC_ARM_REG_R4,DMAC)
    cpu.reg_write(arm.UC_ARM_REG_R5,288)
    cpu.emu_start(rom(0x200fef1c),rom(0x200fef40))
    block = 0

    header = header_layout()

    def audio():
        nonlocal block
        bank = block%2
        block += 1
        cpu.mem_write(DMAC+0x124,pack("<I",0x41 if bank else 0xc1))
        call(cpu,rom(0x200ffd48),timeout_us=0)
        words = cpu.mem_read(0x20400a40+bank*288,288)
        result = bytearray(72)
        result[::2],result[1::2] = words[6::8],words[7::8]
        return result

    def send(expected, *, decode=False):
        assert get("stage") == 1
        assert bytes(cpu.mem_read(labels["outgoing"],36)).split(b"\0",1)[0].decode() == expected
        slot = get("waiting_slot")+1
        slot += (slot&1) != get("parity")
        edge = slot*period
        clock(edge)
        request(True)
        call(cpu,rom(0x20060c74))
        feed_dsp_tx(cpu,True,rom(0x200d4a28))
        pcm = array("h")
        end = 5040 if ft4 else 12640
        if decode:
            for i in range(period*48//36):
                cpu.mem_write(0x20381e08,pack("<I",edge+i*36//48))
                if i%32 == 0: request(True)
                pcm.frombytes(audio())
                if i == 720:
                    assert "QTH" in panel("on-air") and status() == 2
                if get("stage") == 5: break
        else:
            clock(edge+500)
            audio()
            assert get("stage") == 3
            attr("symbol",104 if ft4 else 78)
            attr("sample",(2304 if ft4 else 7680)-36)
            clock(edge+500+end-1)
            audio()
            assert get("stage") == 4 and not any(audio()) and not any(audio())
        assert get("stage") == 5
        request(False)
        feed_dsp_tx(cpu,False,rom(0x200d4a28))
        request(False)
        call(cpu,rom(0x20060c74))
        assert get("stage") == 0
        if decode:
            pcm.extend([0]*(period*48-len(pcm)))
            wav = folder/"261119_120000.wav"
            with wave.open(str(wav),"wb") as stream:
                stream.setparams((1,2,12000,0,"NONE",""))
                stream.writeframes(pcm[::4].tobytes())
            host_decoder = environ.get("IC705_FTX_HOST_DECODER")
            decoder = ([host_decoder,*(["-ft4"] if ft4 else [])] if host_decoder else
                       ["wsl","-d","Debian","-e","jt9","--"+mode.lower(),
                        "-p",str(period/1000),"-d","2"])
            result = subprocess.run([*decoder,wav.name],cwd=folder,
                                    capture_output=True,text=True,check=True,timeout=60)
            assert expected in result.stdout,(result.stdout,result.stderr)
        return slot

    def incoming(slot,*messages):
        for message in messages:
            msg = message.encode()
            row = native("row_text",0)
            cpu.mem_write(row,msg.ljust(36,b"\0")+pack("<4iBB",1250,42,msg.index(b" ")+1,-13,0,0))
            native("view_publish",slot,1)
        compose(guest)

    def at_reply(slot):
        clock((slot+2)*period-900)
        poll()

    # A single tap starts CQ and keeps the ten-row list through the QSO.
    clock(120000)
    tap(440,104)
    assert get("stage") == 1 and "QTH" in panel("queued")
    first = send("CQ K1ABC PM95",decode=True)
    at_reply(first)
    incoming(first+1,"K1ABC JA1ABC PM95","K1ABC F4ABC JN18","K1ABC JA1ABC PM95")
    request(False)
    assert "QTH" in panel("caller-choice") and status() == 3 and get("stage") == 0
    count = min(get("visible_count"),10)
    tap(120,109+17*(count-2))   # Select F4ABC, not the first caller.
    assert get("stage") == 1 and "F4ABC" in panel("selected")
    own = send("F4ABC K1ABC -13")
    at_reply(own)
    incoming(own+1,"K1ABC JA1ABC R-08","K1ABC F4ABC R-09")
    assert get("stage") == 1
    own = send("F4ABC K1ABC RR73")
    log_path = r"C:\IC-705\FTLOG.ADI"
    faults["short"] = True
    for i in range(8):
        clock((own+2)*period+450+4000*i)
        poll()
        pump()
        if card.get(log_path,b"").count(b"<EOR>") == 1: break
    adif = card[log_path]
    assert adif.count(b"<EOR>") == 1 and b"<CALL:5>F4ABC" in adif
    assert get("stage") == 0 and get("ft_page") == 0
    (folder/"FTLOG.ADI").write_bytes(adif)
    panel("completed")
    tap(440,249)
    tap(130,245)
    assert native("ft_is_history") and "QTH" in panel("history")
    tap(440,104)
    assert not native("ft_is_history") and get("stage") == 0

    # Manual mode waits for the operator at the report step.
    tap(440,249)
    tap(140,214)
    tap(120,125)
    tap(120,125)
    tap(440,249)
    tap(440,249)
    clock((own+10)*period)
    tap(440,104)
    own = send("CQ K1ABC PM95")
    at_reply(own)
    incoming(own+1,"K1ABC DL1ABC JO62")
    assert get("stage") == 0 and status() == 4 and "QTH" in panel("manual-confirm")
    request(False)
    tap(440,248)
    assert get("stage") == 1
    tap(440,104)
    request(False)
    assert get("stage") == 0 and get("ft_page") == 0
    panel("stopped")

    # A typed target and a fresh third-party RR73 need an explicit send tap.
    clock((own+5)*period)
    tap(440,246)
    tap(440,140)
    type_call("VK2ABC")
    assert get("stage") == 0 and "VK2ABC" in panel("specified-call")
    assert bytes(cpu.mem_read(labels["pref"],6)) == b"K1ABC\0"
    request(False)
    tap(440,104)
    assert get("stage") == 1 and bytes(cpu.mem_read(labels["outgoing"],17)) == b"VK2ABC K1ABC PM95"
    tap(440,104)
    request(False)
    clock((own+10)*period-900)
    incoming(own+9,"W1XYZ G4ABC RR73")
    tap(120,109+17*(min(get("visible_count"),10)-1))
    assert get("stage") == 0 and "G4ABC" in panel("tail-chase")
    tap(440,104)
    assert get("stage") == 1
    assert bytes(cpu.mem_read(labels["outgoing"],36)).split(b"\0",1)[0] == b"G4ABC K1ABC PM95"
    tap(440,104)
    request(False)

    # A full-auto session starts only from the explicit Start action.
    tap(440,249)
    tap(140,214)
    tap(120,125)
    tap(120,125)               # Manual → Semi → Full
    for _ in range(7): tap(120,154)  # Three sends → one
    clock((own+14)*period)
    poll()
    request(False)
    tap(440,105)               # Explicit auto CQ
    own = send("CQ K1ABC PM95")
    at_reply(own)
    request(False)
    clock((own+2)*period+100)
    poll()
    assert get("stage") == 0 and get("ft_page") == 0 and not get("sequence_on")

    tap(440,249)
    tap(140,214)
    tap(120,215)               # CQ → Find
    tap(120,246)               # On limit → Next
    panel("auto-settings")
    assert unpack("<5I",cpu.mem_read(operating["operating"],20)) == (2,1,0,1,1)
    clock((own+20)*period)
    poll()
    request(False)
    assert get("stage") == 0
    tap(440,105)               # Explicit Start
    assert get("ft_page") == 0 and status() == 5 and "QTH" in panel("auto-armed")
    start_slot = own+20
    def acquire(search_slot,*calls):
        clock((search_slot+1)*period-3200)
        incoming(search_slot,*calls)
        for elapsed in range(0,2600,400):
            if get("stage") == 1: return
            clock((search_slot+1)*period-3200+elapsed)
            poll()
            pump()
            compose(guest)
        assert get("stage") == 1, panel("not-armed")

    acquire(start_slot+1,"CQ JA1ABC PM95")
    own = send("JA1ABC K1ABC PM95")
    at_reply(own)
    assert get("stage") == 0, "the configured one-send limit allowed a retry"
    request(False)
    clock((own+2)*period+100)
    poll()
    assert get("stage") == 0 and get("ft_page") == 0 and status() == 5
    panel("auto-find")
    acquire(own+3,"CQ JA1ABC PM95","CQ DL1ABC JO62")
    assert get("stage") == 1
    queued = bytes(cpu.mem_read(labels["outgoing"],36)).split(b"\0",1)[0]
    assert queued == b"DL1ABC K1ABC PM95",queued
    panel("auto-next")
    cpu.mem_write(0x204bd028,b"\x01")  # OEM side menu is over the stop key
    guest.press_exit()
    poll()
    request(False)
    assert get("stage") == 0 and not get("sequence_on")

    return dict(dat_sha256=record["sha256"], protocol=mode, decoded_first_cq=True, qso_rx_list=True,
                cq_decoder=Path(environ.get("IC705_FTX_HOST_DECODER","jt9")).name,
                caller_choice="F4ABC", attempted_other_caller_ignored=True, adif=adif.decode(),
                manual_report_required_confirmation=True, stop_removed_native_request=True,
                specified_call_and_completed_station_chase=True,
                automatic_cq_started_explicitly=True, automatic_find_started_explicitly=True,
                history_returned_live_without_transmit=True, configured_limit_and_cooldown=True,
                physical_exit_with_stock_sidebar=True, header_layout=header)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package",type=Path)
    parser.add_argument("protocol",choices=["FT8","FT4"])
    parser.add_argument("--receive",action="store_true")
    parser.add_argument("--layout",action="store_true")
    args = parser.parse_args()
    results = replay(args.package.resolve(),args.protocol=="FT4",receive_only=args.receive,layout_only=args.layout)
    report = args.package/args.protocol/("layout.json" if args.layout else "receive.json" if args.receive else "operating.json")
    report.write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
    print(report,results["dat_sha256"],flush=True)
