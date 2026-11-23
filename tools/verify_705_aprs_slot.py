"""Verify release-slot updates and exercise the installed mode callback at a cold HOME."""
import argparse
import json
from hashlib import sha256
from pathlib import Path
from struct import pack, unpack_from

from tools.build_705_aprs_slot import ROOT, FIRST_OFFSET, TAIL_OFFSET, FT_OUT
from tools.decode_705_main import BOOT_SIZE, decode_main
from tools.emulate_705 import arm, uc, BOOT
from tools.probe_705_boot_selection import FIRST, SECOND, NOR_BYTES, MARKER
from tools.render_705_stock_row import FONT_HEADER, SMALL_FONT_HEADER
from tools.replay_705_aprs_task import FM_HZ, e140_rom
from tools.replay_705_font_boot import replay_resource_task
from tools.replay_705_stock_install import A_PREFIX, SHARED, load_a
from tools.verify_705_ftx_rx import symbols


def run(region, test, folder=None):
    folder=folder or ROOT/region/"aprs-slot"
    package=(folder/f"705{region}140.dat").read_bytes()
    report=json.loads((folder/"package.json").read_text())
    assert sha256(package).hexdigest()==report["sha256"]
    main,flash=load_a(package,report["main_sha256"])
    ms=symbols(folder/"manager.elf")
    if test in ("update","upgrade-v140"):
        from tools.build_705_aprs_rx_dat import install_and_boot
        stock=Path(f"firmware/705{region}140.dat").read_bytes()
        prior=(Path(".analysis/aprs-hop/smart-final")/region/f"705{region}140.dat").read_bytes() if test=="upgrade-v140" else stock
        original,stock_nor=load_a(prior,sha256(decode_main(prior)[1]).hexdigest())
        japan=decode_main(Path("firmware/705J140.dat").read_bytes())[1] if region=="E" else None
        result=install_and_boot(prior,package,original,stock_nor,flash,main,ms,japan=japan)
    elif test in ("panel","popup-layout","messages","default-comment","timer-baseline","timer-ptt-baseline","multi","lists","list-baseline","function","scope","scope-baseline"):
        app=main[:report.get("ft_previous_main_size")]
        result=check_panel(region,folder,app,flash,ms,test=test)
    elif test=="dprs":
        result=check_dprs(region,folder,main[:report.get("ft_previous_main_size")],ms)
    else:
        slot=FIRST if test in ("first","settings-boot","settings-smart","history-save","history-restore") else SECOND
        nor=bytearray(b"\xff"*NOR_BYTES)
        nor[:BOOT_SIZE]=flash[:BOOT_SIZE]
        at=slot-BOOT
        nor[at:at+A_PREFIX-BOOT_SIZE]=flash[BOOT_SIZE:A_PREFIX]
        nor[SHARED:SHARED+len(flash)-A_PREFIX]=flash[A_PREFIX:]
        if slot==SECOND:
            nor[MARKER-BOOT:MARKER-BOOT+16]=flash[0x47e8:0x47f8]
        def font(at):
            n,=unpack_from("<I",flash,at)
            return flash[at+4:at+4+n]
        result={}
        class Done(Exception):
            pass
        def observe(cpu,frame):
            result.update(check_home(cpu,frame,slot,region,folder,ms,report,test=test))
            raise Done()
        if region=="E":
            from tools.replay_705_e140_home_heap import european_boot_replay
            replay=european_boot_replay()
        else:
            replay=replay_resource_task
        try:
            replay(main,font(A_PREFIX),font(A_PREFIX+SMALL_FONT_HEADER-FONT_HEADER),
                fixture_return=False,loader=flash[0x4000:0x49bc],adc_sample=0x180,scif_wait="board_power",
                vbus_high=True,power_key_released=False,riic0_idle=True,riic0_finish="stop",eeprom=b"\xff"*16,
                startup_dma="format-current",startup_home_probe=True,no_power_on_check=True,startup_input="close-cw",
                startup_flash=flash[:A_PREFIX],stock_mmu=True,startup_from_nor=True,nor_snapshot=bytes(nor),
                home_observer=observe)
        except Done:
            pass
        assert result
    (folder/f"{test}.json").write_text(json.dumps(dict(dat_sha256=report["sha256"],result=result),indent=2)+"\n")
    print(region,test,"passed",flush=True)


def check_home(cpu,frame,slot,region,folder,ms,report,*,test):
    from tools.replay_705_aprs_fm import ax25_burst
    import tools.verify_705_aprs_overlay as overlay
    ft=symbols(FT_OUT/"rx.elf")
    sy=symbols(folder/"aprs-task.elf")
    rom=e140_rom if region=="E" else lambda a:a
    def word(addr):
        return int.from_bytes(cpu.mem_read(addr,4),"little")
    def invoke(entry,*args,until=None):
        ctx=cpu.context_save()
        end=until or cpu.reg_read(arm.UC_ARM_REG_PC)
        stop=cpu.hook_add(uc.UC_HOOK_CODE,lambda c,*_:c.emu_stop(),begin=end,end=end)
        try:
            for reg,val in zip((arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2),args):
                cpu.reg_write(reg,val)
            cpu.reg_write(arm.UC_ARM_REG_LR,end | int(not until and bool(cpu.reg_read(arm.UC_ARM_REG_CPSR)&32)))
            cpu.emu_start(entry,end,count=4_000_000)
            assert cpu.reg_read(arm.UC_ARM_REG_PC)==end,(hex(entry),hex(cpu.reg_read(arm.UC_ARM_REG_PC)))
            return cpu.reg_read(arm.UC_ARM_REG_R0)
        finally:
            cpu.hook_del(stop)
            cpu.context_restore(ctx)
    site=int(report["entry"],16)
    def tick():
        invoke(site,until=site+4)
        return word(ms["loaded"])
    assert (FIRST if cpu.mem_read(0x2038089d,1)[0] else SECOND)==slot
    assert not word(ms["bound_hz"]) and not word(ms["loaded"])
    cpu.mem_write(0x203e2128,b"\x70\0")
    cpu.mem_write(0x20380714,pack("<I",FM_HZ))
    if test.startswith("settings-"):
        from tools.verify_705_ftx_tx import mount_station_card
        paths=[rf"C:\IC-705\APRS{i}.CFG" for i in range(2)]
        # Native GPS TX Mode is OFF after selecting APRS. Blank emulator EEPROM is 0xff.
        cpu.mem_write(0x20380172,bytes(1));tick()
        card,_,_=mount_station_card(cpu,ft,rom,extra_paths=paths)
        smart=test=="settings-smart"
        source=folder/"default-comment" if smart else folder
        for i,path in enumerate(paths):
            card[path]=(source/f"APRS{i}.CFG").read_bytes()
        newest=max(paths,key=lambda p:unpack_from("<I",card[p],4)[0])
        fallback=slot==SECOND
        if fallback: card[newest]=card[newest][:25]
        cpu.mem_write(0x203eb172,b"\xff");assert not tick() and not word(ms["mount_seen"])
        cpu.mem_write(0x203eb172,bytes(1))
        base=tick()
        assert word(ms["bound_hz"])==FM_HZ and base,(hex(base),word(ms["bound_hz"]),word(ms["mount_seen"]),bytes(cpu.mem_read(0x203eb172,1)).hex(),bytes(cpu.mem_read(0x20380172,1)).hex(),list(card))
        def setting(name,n=1):
            return bytes(cpu.mem_read(base+sy[name]-overlay.LINK,n))
        assert setting("aprs_beacon_ssid")==bytes([3]) and setting("aprs_auto_beacon")==bytes([1])
        assert setting("aprs_tx_enabled")==bytes([1]) and setting("aprs_beacon_interval")==bytes([5 if smart else 0])
        if not fallback and not smart:
            assert setting("aprs_tx_path")==bytes([1]) and setting("saved_comment",11)==b"Field test\0"
            assert setting("saved_symbol",2)==b"/*"
        return dict(slot=hex(slot),restored_bound_hz=FM_HZ,ssid=3,rx_tx=True,
                    interval_minutes=None if smart else 1,smart_beacon=smart,
                    recovered_previous_record=fallback,initial_tx_stage=word(base+sy["stage"]-overlay.LINK))
    assert not tick(), ("unbound",word(ms["loaded"]),word(ms["bound_hz"]))
    invoke(ms["aprs_overlay_bind"],FM_HZ)
    base=tick()
    assert base and word(base+sy["aprs_channel_hz"]-overlay.LINK)==FM_HZ, ("bound",hex(base),hex(word(ms["bound_hz"])),hex(word(ms["history_tail"])),hex(word(ms["history_last"])),word(ms["retry_pending"]))
    def entry(name):
        return base+sy[name]-overlay.LINK
    if test.startswith("history-"):
        return check_history_card(cpu,rom,slot,folder,ms,ft,entry,tick,invoke,word,test,int(report["history_prefix"],16))
    from tools.replay_705_gps_inputs import GPS_MODE
    cpu.mem_write(GPS_MODE,b"\x02")
    cpu.mem_write(0x203ea85d,pack(">BHcBHc",35,30000,b"N",139,30000,b"E"))
    wave=ax25_burst("!3531.00N/13930.00E>slot",45)
    buf=invoke(rom(0x20127a28),576)
    assert buf
    for i in range(0,len(wave),288):
        part=wave[i:i+288]
        cpu.mem_write(buf,pack(f"<{len(part)}h",*part))
        invoke(entry("aprs_rx_feed"),buf,len(part))
    invoke(rom(0x20127a78),buf)
    invoke(entry("aprs_record_receive"))
    assert word(entry("aprs_record_count"))==1
    history=bytes(cpu.mem_read(sy["aprs_history_prefix"],340))
    assert b">slot" in history
    distance,=unpack_from("<H",history,338)
    assert distance==185, distance
    for i in range(1,64):
        seq=word(entry("aprs_rx_written"))
        frame=entry("aprs_rx_frames")+340*(seq%4)
        cpu.mem_write(frame,pack("<I",i)+history[4:])
        cpu.mem_write(entry("aprs_rx_written"),pack("<I",seq+1))
        invoke(entry("aprs_record_receive"))
    def records():
        parts=[(sy["aprs_history_prefix"],report["prefix_slots"]),
               (word(entry("aprs_records")),22),(word(entry("aprs_history_last_bank")),64-report["prefix_slots"]-22)]
        return b"".join(bytes(cpu.mem_read(p,340*n)) for p,n in parts)
    saved_records=records()
    assert all(unpack_from("<I",saved_records,i*340)==(1,) and
               unpack_from("<H",saved_records,i*340+338)==(185,) for i in range(64))
    assert invoke(ms["pin_audio"],0)==base
    cpu.mem_write(ft["state"],pack("<I",2))
    assert tick()==base
    invoke(ms["unpin_audio"])
    assert not tick(), (word(ms["audio_users"]),word(entry("stage")),word(ft["state"]))
    # After unloading, both full SSTV canvas requests must fit in this HOME heap.
    canvases=[invoke(rom(0x20127a28),size) for size in (153631,153600)]
    assert all(canvases), (canvases,word(entry("aprs_records")))
    for p in reversed(canvases):
        invoke(rom(0x20127a78),p)
    cpu.mem_write(ft["state"],bytes(4))
    cpu.mem_write(0x20380714,pack("<I",FM_HZ+10000))
    assert not tick()
    cpu.mem_write(0x20380714,pack("<I",FM_HZ))
    base=tick()
    assert base and word(entry("aprs_record_count"))==64
    assert records()==saved_records
    invoke(ms["aprs_overlay_bind"],0)
    assert not tick()
    return dict(slot=hex(slot),home_frame=frame,module_resource_addresses=[
        hex(slot-BOOT_SIZE+n) for n in (FIRST_OFFSET,TAIL_OFFSET)],off_kept_unloaded=True,
        ft_receive_unloaded=True,other_frequency_kept_unloaded=True,resumed_history=64,
        held_until_audio_returned=True,
        preserved_distance_km=distance/100,
        both_sstv_canvas_requests=[hex(p) for p in canvases],idle_state_injected=True)


def check_history_card(cpu,rom,slot,folder,ms,ft,entry,tick,invoke,word,test,prefix):
    from tools.verify_705_ftx_tx import mount_station_card
    path=r"C:\IC-705\APRHIST.BIN"
    card,_,faults=mount_station_card(cpu,ft,rom,extra_paths=[rf"C:\IC-705\APRS{i}.CFG" for i in range(2)])
    cpu.mem_write(0x203eb172,bytes(1))
    if test=="history-save":
        from tools.replay_705_gps_inputs import GPS_MODE
        cpu.mem_write(GPS_MODE,b"\x02")
        cpu.mem_write(0x203ea85d,pack(">BHcBHc",35,30000,b"N",139,30000,b"E"))
        count=entry("aprs_record_count")
        def receive(n):
            src=bytes(c*2 for c in b"N0CARD")
            freq=bytes(c*2 for c in b"APRS  ")
            frame=freq+b"\x60"+src+b"\x61\x03\xf0"+f"!3531.00N/13930.00E>>card record {n:02d}".encode()+bytes(2)
            seq=word(entry("aprs_rx_written"))
            cpu.mem_write(entry("aprs_rx_frames")+340*(seq%4),pack("<II",n,len(frame))+frame)
            cpu.mem_write(0x2038079a,bytes.fromhex("26112307152211"))
            cpu.mem_write(entry("aprs_rx_written"),pack("<I",seq+1))
            invoke(ms["aprs_slot_drain"])
            assert word(count)==n
            tick()
        for n in range(1,68): receive(n)
        # Keep one complete record in the older on-card format.
        disk=bytearray(card[path])
        old=23*512
        disk[old+4:old+8]=pack("<I",0x12345678)
        checksum=2166136261
        for byte in disk[old:old+352]:
            checksum=((checksum ^ byte)*16777619)&0xffffffff
        disk[old+352:old+356]=pack("<I",checksum ^ 0x31585241)
        complete=card[path]=bytes(disk)
        assert len(complete)==65*512
        (folder/"APRHIST.BIN").write_bytes(complete)
        faults["aprs-short"]=True
        receive(68)
        torn=card[path]
        assert torn!=complete and torn[512*2+83:]==complete[512*2+83:]
        (folder/"APRHIST-torn.BIN").write_bytes(torn)
        tick();assert card[path]==torn
        cpu.mem_write(0x20381e08,pack("<I",word(0x20381e08)+5000))
        tick();assert card[path]!=torn and word(entry("history_saved"))==68
        return dict(wrote_records=67,card_bytes=len(complete),short_write_remained_pending=True,retried=True)
    card[path]=(folder/("APRHIST-torn.BIN" if test=="history-recover" else "APRHIST.BIN")).read_bytes()
    tick()
    assert word(entry("aprs_record_count"))==64
    assert not cpu.mem_read(entry("aprs_popup_owned"),1)[0]
    assert word(entry("history_saved"))==64 and word(entry("card_sequence"))==67
    frames=(bytes(cpu.mem_read(address,340*n)) for address,n in
            ((word(ms["history_tail"]),22),(word(ms["history_last"]),22)))
    tail=b"".join(frames)
    assert b">card record 67" in tail[-340:] and b">card record 24" in tail[:340]
    oldest=bytes(cpu.mem_read(prefix,340))
    assert b">card record 04" in oldest
    assert unpack_from("<I",oldest)==(1,) and unpack_from("<I",tail,len(tail)-340)==(1,)
    assert unpack_from("<I",tail)==(0,) and unpack_from("<H",tail,338)==(185,)
    assert bytes(cpu.mem_read(entry("arrival")+12*63+6,6))==bytes.fromhex("261123152211")
    return dict(slot=hex(slot),restored=64,latest=67,first=4,saved_timestamp="2026-11-23 15:22:11",
                recovered_direction=True,legacy_distance_without_direction=True,partial_write=test=="history-recover")


def check_panel(region,folder,main,flash,ms,*,test="panel"):
    from tools.build_705_ftx_rx import MENU
    from tools.emulate_705 import BASE, call
    from tools.replay_705_aprs_fm import original_fm,load_aprs_panel,ax25_burst,GUARD,LAYOUT
    from tools.replay_705_aprs_menu import GRID_PAGE
    from tools.probe_705_rx_audio import completed,DMAC,FRAMES
    from tools.probe_705_cw_feedback import BEEP
    from tools.verify_705_aprs_overlay import LINK
    from tools.replay_705_gps_inputs import GPS_MODE
    from tools.probe_705_rtx_audio import PCM_STEP
    dest=folder/"panel"
    dest.mkdir(exist_ok=True)
    images,e=load_aprs_panel(Path(f"firmware/705{region}140.dat").read_bytes())
    guest=original_fm(images,dest,rom=e140_rom if e else None)
    cpu,rom=guest.cpu,guest.rom
    cpu.mem_write(BASE,main)
    cpu.ctl_remove_cache(BASE,BASE+len(main))
    cpu.mem_write(0x185f0000,flash[:A_PREFIX])
    end=unpack_from("<I",main,0x2e8)[0]
    for pos in (end-32,end-16):
        src,dst,size,method=unpack_from("<4I",main,pos-BASE)
        call(cpu,method|1,src,dst,size)
    def word(addr):
        return int.from_bytes(cpu.mem_read(addr,4),"little")
    original=bytes(cpu.mem_read(MENU,320*72))
    def screen(name,*expected):
        labels,png=guest.render()
        assert set(expected)<=set(labels),(name,labels)
        (dest/f"{name}.png").write_bytes(png)
        return labels
    def gps():
        guest.press_menu()
        guest.render()
        if cpu.mem_read(GRID_PAGE,1)!=b"\2":
            guest.click(274,251)
            guest.render()
        guest.click(145,178)
        guest.render()
        guest.click(160,104)
        screen("tx-mode","GPS TX Mode","OFF","D-PRS","NMEA","APRS")
    if test in ("function","scope","scope-baseline"):
        from tools.replay_705_aprs_function import exercise
        return exercise(guest,folder,ms,gps,scope_test=test if test!="function" else None)
    gps()
    guest.click(150,240)
    screen("mode-cancel","APRS Mode")
    guest.press_exit()
    screen("cancel-back","GPS TX Mode")
    assert not word(ms["bound_hz"]) and bytes(cpu.mem_read(MENU,len(original)))==original
    for ident,title in ((317,"Digital"),(277,"KEYER/DECODE"),(293,"SSTV TX MODE")):
        guest.click(150,240)
        guest.render()
        call(cpu,rom(0x200cd628),ident,0xffff)
        screen(f"interrupted-{ident}",title)
        assert bytes(cpu.mem_read(MENU,len(original)))==original
        guest.press_exit()
        guest.render()
    tones=[]
    beep=rom(BEEP)
    cpu.hook_add(uc.UC_HOOK_CODE,lambda c,*_:tones.append(c.reg_read(arm.UC_ARM_REG_R0)),begin=beep,end=beep)
    for choice in (1,0):
        guest.click(150,240)
        screen(f"mode-{choice}","APRS Mode","RX Only","RX & TX")
        tones.clear()
        guest.click(115,55+61*choice)
        labels=screen(f"chosen-{choice}","GPS TX Mode","APRS")
        assert "APRS Mode" not in labels and guest.state()["selection"]==3 and [n for n in tones if n]==[1],(labels,tones)
        assert word(ms["bound_hz"])==FM_HZ and word(ms["tx_enabled"])==choice
        assert bytes(cpu.mem_read(MENU,len(original)))==original
    guest.press_exit()
    screen("gps-enabled","GPS TX Mode","APRS")
    for _ in range(2):
        guest.press_exit()
        guest.render()
    call(cpu,ms["aprs_overlay_prepare"],instruction_limit=4_000_000,timeout_us=0)
    base=word(ms["loaded"])
    assert base
    sy=symbols(folder/"aprs-task.elf")
    count=base+sy["aprs_record_count"]-LINK
    cpu.mem_write(GPS_MODE,b"\x02")
    cpu.mem_write(0x203ea85d,pack(">BHcBHc",35,30000,b"N",139,30000,b"E"))
    site=rom(PCM_STEP)
    op=word(site)
    step=site+8+4*(((op&0xffffff)^0x800000)-0x800000)
    assert step==ms["aprs_slot_record"]
    info="!3531.00N/13930.00E>panel"
    if test=="popup-layout":
        cpu.mem_write(0x2038079a,bytes.fromhex("26112307152208"))
    wave=GUARD+ax25_burst(info+" bad",30,bad_fcs=True)+GUARD+ax25_burst(info,30)+GUARD
    wave+=(0,)*(-len(wave)%FRAMES)
    for i in range(0,len(wave),FRAMES):
        block=i//FRAMES
        completed(cpu,rom(LAYOUT["rec_dma"]),DMAC+0xe4,LAYOUT["rec_bank"],block,wave[i:i+FRAMES],(0,)*FRAMES,timeout_us=0)
        if block%6==5 or i+FRAMES==len(wave):
            call(cpu,step,timeout_us=0)
    record=bytes(cpu.mem_read(sy["aprs_history_prefix"],340))
    assert word(count)==1 and b">panel" in record and b">panel bad" not in record
    assert unpack_from("<H",record,338)==(185,)
    if test=="popup-layout":
        return check_popup_layout(guest,folder,base,sy,ms)
    if test in ("lists","list-baseline"):
        from tools.replay_705_aprs_stations import exercise
        return exercise(guest,folder,base,sy,ms,baseline=test=="list-baseline")
    if test=="multi":
        result=check_multi(guest,folder,gps,base,sy)
        call(cpu,rom(0x200cd628),317,0xffff)
        screen("multi-to-digital","Digital")
        assert bytes(cpu.mem_read(MENU,len(original)))==original
        return dict(result,native_menu_rows_restored=320)
    if test in ("messages","default-comment","timer-baseline","timer-ptt-baseline"):
        from tools.replay_705_aprs_reply import exercise
        return exercise(guest,folder,base,sy,ms,gps,tones,timer_baseline=test=="timer-baseline",ptt_baseline=test=="timer-ptt-baseline",default_comment=test=="default-comment")
    gps()
    guest.click(150,55)
    screen("gps-off","GPS TX Mode","OFF")
    assert word(ms["bound_hz"])==0
    call(cpu,ms["aprs_overlay_prepare"])
    assert not word(ms["loaded"])
    return dict(rx_only_and_rx_tx_selected=True,cancel_preserved_off=True,interrupting_selectors=[317,277,293],
                native_confirm_tone=1,bound_hz=FM_HZ,
                dma_frames=len(wave)//FRAMES,decoded_records=1,bad_fcs_rejected=True,
                reception_distance_km=1.85,off_unloaded=True)


def check_popup_layout(guest,folder,base,sy,ms):
    from io import BytesIO
    from PIL import Image
    from tools.emulate_705 import call
    from tools.render_705_stock_row import coverage
    from tools.replay_705_dv_panel import attach_position_graphics
    from tools.replay_705_gps_inputs import GPS_MODE
    from tools.verify_705_aprs_overlay import LINK
    cpu=guest.cpu
    attach_position_graphics(guest)
    def sym(name): return base+sy[name]-LINK
    def addr(name,flags): return bytes(ch*2 for ch in name.ljust(6))+bytes([flags])
    def receive(header,info,second):
        frame=header+b"\x03\xf0"+info.encode()+bytes(2)
        written=sym("aprs_rx_written")
        seq=int.from_bytes(cpu.mem_read(written,4),"little")
        cpu.mem_write(0x2038079a,bytes.fromhex(f"261123071522{second:02}"))
        cpu.mem_write(sym("aprs_rx_frames")+340*(seq%4),pack("<II",seq,len(frame))+frame)
        cpu.mem_write(written,pack("<I",seq+1))
        call(cpu,ms["aprs_slot_drain"])
    header=addr(b"WWWWWW",0x7e)+addr(b"WWWWWW",0x7e)
    for i in range(8): header+=addr(b"WWWWWW",0xfe+(i==7))
    route="WWWWWW-15>WWWWWW-15"+",WWWWWW-15"*8+"*"
    comment="Walking north past the park. Second line and third line with lowercase descenders."
    cpu.mem_write(sym("aprs_alert_styles"),bytes(7))
    receive(addr(b"APRS",0x60)+addr(b"N0STAT",0x61),">No coordinates",8)
    receive(addr(b"APRS",0x60)+addr(b"BI1BIF",0x73),"!3530.00N/13931.50E>Mobile",9)
    receive(addr(b"APRS",0x60)+addr(b"BG1QGD",0x75),"!3528.00N/13930.00E&IGATE",10)
    receive(header,"!3531.00N/13930.00Er"+comment,11)
    prefix=sy["aprs_history_prefix"]
    assert [int.from_bytes(cpu.mem_read(prefix+340*i,4),"little") for i in range(1,5)]==[0,3,5,1]
    cpu.mem_write(GPS_MODE,b"\0")
    guest._press_key(1,1);guest.render()
    guest.click(150,55)
    words,png=guest.render()
    assert {"APRS RX List","WWWWWW-15","BG1QGD-10","BI1BIF-9","2026-11-23","1.85 km"}<=set(words),words
    image=Image.open(BytesIO(png)).convert("RGB")
    masks=[]
    for i in range(4):
        y=55+61*i
        crop=image.crop((95,y,112,y+23))
        masks.append(tuple(j for j,(r,g,b) in enumerate(crop.getdata()) if r>145 and g<85 and b<85))
    assert len(set(masks[:3]))==3 and all(masks[:3]) and not masks[3],masks
    (folder/"rx-list-layout.png").write_bytes(png)
    cpu.mem_write(GPS_MODE,b"\x02")
    spans=[]
    entry=sym("label_span")
    def capture(c,*_):
        p,n,x,y=(c.reg_read(reg) for reg in (arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3))
        spans.append((x,y,bytes(c.mem_read(p,n)).decode("latin1")))
    def popup(*expected, reply=False):
        spans.clear()
        hook=cpu.hook_add(uc.UC_HOOK_CODE,capture,begin=entry,end=entry)
        try:
            guest.click(150,55)
            words,png=guest.render()
        finally:
            cpu.hook_del(hook)
        assert set(expected)<=set(words),words
        lines=dict((y,text) for x,y,text in spans if x==14 and y>=204)
        assert len(lines)>1 and "".join(lines[y] for y in sorted(lines))==route,(lines,spans)
        # Check original glyph coverage against both control rectangles.
        seen=set()
        for event in guest.surface.events:
            glyphs=event["glyphs"]
            line="".join(chr(g["key"]) for g in glyphs).rstrip()
            if line not in lines.values():
                continue
            seen.add(line)
            for glyph in glyphs:
                pixels=coverage(glyph["segments"],glyph["coordinates"],glyph["offset"],480,272)
                for pixel in pixels:
                    y,x=divmod(pixel,480)
                    assert y<220 or x<335,(event["origin"],glyph)
                    assert not reply or y<222 or x<240,(event["origin"],glyph)
        assert seen==set(lines.values()),(seen,lines)
        return png,len(lines)

    png,rows=popup("POSITION BEACON","COMMENT","WWWWWW-15","1.85 km")
    details=sorted({y for x,y,_ in spans if 109<=y<=205 and x in (133,225)})
    assert len(details)>=5 and set(b-a for a,b in zip(details,details[1:]))=={19},spans
    assert (165,82,"WWWWWW-15") in spans
    position=Image.open(BytesIO(png)).convert("RGB")
    rule=position.crop((67,52,415,53))
    assert rule.getextrema()[0][0]>0
    (folder/"popup-layout.png").write_bytes(png)
    guest.press_exit();call(cpu,sym("aprs_update_panel"));guest.render()
    guest.click(150,55+3*61)
    words,status=guest.render()
    assert {"APRS STATUS","No coordinates"}<=set(words),words
    assert Image.open(BytesIO(status)).convert("RGB").crop((67,52,415,53)).tobytes()==rule.tobytes()
    (folder/"status-layout.png").write_bytes(status)
    for _ in range(2):
        guest.press_exit();call(cpu,sym("aprs_update_panel"));guest.render()
    call(cpu,ms["aprs_set_mode"],2)
    cpu.mem_write(0x203e2499,b"N0HOME  ")
    receive(header,":N0HOME   :Long path message{01",12)
    guest._press_key(1,1);guest.render()
    guest.click(150,55);guest.render()
    msg,reply_rows=popup("APRS MESSAGE","Long path message","Reply",reply=True)
    message=Image.open(BytesIO(msg)).convert("RGB")
    assert message.crop((67,52,415,53)).tobytes()==rule.tobytes()
    (folder/"reply-layout.png").write_bytes(msg)
    return dict(route=route,raw_rows=rows,reply_raw_rows=reply_rows,detail_baselines=details,station_baseline=82,
                return_and_reply_buttons_clear=True,shared_popup_divider=["position","message","status"],
                list_arrows=["north","south","east",None],saved_bearing_used_with_gps_off=True,
                rx_list="rx-list-layout.png")


def check_multi(guest,folder,gps,base,sy):
    from tools.emulate_705 import call
    from tools.verify_705_aprs_overlay import LINK
    from tools.render_705_display import PAGE
    cpu=guest.cpu
    dest=folder/"multi"
    dest.mkdir(exist_ok=True)
    gps()
    guest.press_exit()
    guest.render()
    guest.click(150,177)
    assert "RX Alert" in guest.render()[0]

    def settle():
        # The isolated renderer skips the UI task's last-frame handoff.
        delta=0x204bd690-PAGE
        cpu.mem_write(PAGE+delta,bytes(cpu.mem_read(PAGE,delta)))
        cpu.mem_write(0x20380c98,bytes(2))

    def turn(steps):
        for _ in range(steps):
            assert call(cpu,guest.rom(0x200cd168),1,1)
        guest.render()

    transitions=[]
    def press(name,*expected):
        # Paint the parent, then let the untouched panel become fully idle.
        settle()
        guest.render()
        settle()
        quiet,before=guest.render()
        assert not quiet,(name,"not idle",quiet)
        settle()
        guest._press_key(0,1)  # MULTI down and up; no encoder movement.
        words,after=guest.render()
        (dest/(name+".png")).write_bytes(after)
        assert set(expected)<=set(words) and before!=after,(name,words,before==after)
        transitions.append(name)

    press("01-alert","RX Alert","Position Beacon")
    press("02-position-tone","Position Beacon","Silent Popup","Short Tone")
    turn(1)
    press("03-choose-tone","RX Alert","Weather")
    assert cpu.mem_read(base+sy["aprs_alert_styles"]-LINK,1)==b"\x02"
    guest.press_exit()
    guest.render()
    turn(3)
    press("04-interval","Beacon Interval","10 min")
    press("05-confirm-interval","APRS","Beacon Interval  10 min")
    press("06-reopen-interval","Beacon Interval","10 min")
    turn(1)
    press("07-choose-30min","APRS","Beacon Interval  30 min")
    assert cpu.mem_read(base+sy["aprs_beacon_interval"]-LINK,1)==b"\x04"
    return dict(first_press_visible=transitions,encoder_steps_after_press=0,
                tone_index=2,interval_minutes=30)


def check_dprs(region,folder,main,ms):
    from tools.replay_705_aprs_fm import original_fm,load_aprs_panel
    from tools.replay_705_aprs_panel import Panel
    from tools.verify_705_ftx_rx import menu_init
    from tools.emulate_705 import BASE
    name=f"705{region}140.dat"
    images,european=load_aprs_panel((Path("firmware")/name).read_bytes())
    hashes=[]
    for label in ("stock","candidate"):
        dest=folder/("dprs-"+label)
        dest.mkdir(exist_ok=True)
        guest=original_fm(images,dest,rom=e140_rom if european else None)
        if label=="candidate":
            guest.cpu.mem_write(BASE,main)
            guest.cpu.ctl_remove_cache(BASE,BASE+len(main))
            if european:
                from tools.emulate_705 import call
                end=unpack_from("<I",main,0x2e8)[0]
                for record in (end-32,end-16):
                    src,dst,size,method=unpack_from("<4I",main,record-BASE)
                    call(guest.cpu,method|1,src,dst,size)
            else:
                menu_init(guest.cpu,main)
        panel=Panel(guest,dest,(None,symbols(folder/"aprs-task.elf")),channel=0,european=european)
        panel.seed_dv()
        frames=[]
        for i in range(2):
            labels,png=guest.render()
            assert panel.window()==[13,0] and "RX POSITION DISPLAY" in labels
            (dest/f"position-{i}.png").write_bytes(png)
            frames.append(sha256(png).hexdigest())
            guest.press_exit()
            assert panel.window()==[0,0]
            guest.render()
            if not i:
                panel.tap_position(aprs=False)
        if label=="candidate":
            assert not any(guest.cpu.mem_read(ms["loaded"],4))
        hashes.append(frames)
    assert hashes[0]==hashes[1]
    return dict(stock_and_candidate_frames=hashes[0],icon_reopened=True,physical_exit_closed_twice=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("region",choices=("J","E"))
    p.add_argument("test",choices=("first","second","update","upgrade-v140","dprs","panel","popup-layout","messages","default-comment","timer-baseline","timer-ptt-baseline","multi","lists","list-baseline","function","scope","scope-baseline","settings-boot","settings-fallback","settings-smart","history-save","history-restore","history-recover"))
    p.add_argument("--folder",type=Path)
    args=p.parse_args()
    run(args.region,args.test,args.folder)
