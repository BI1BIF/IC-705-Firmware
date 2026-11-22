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
    if test=="update":
        from tools.build_705_aprs_rx_dat import install_and_boot
        stock=Path(f"firmware/705{region}140.dat").read_bytes()
        original,stock_nor=load_a(stock,sha256(decode_main(stock)[1]).hexdigest())
        japan=decode_main(Path("firmware/705J140.dat").read_bytes())[1] if region=="E" else None
        result=install_and_boot(stock,package,original,stock_nor,flash,main,ms,japan=japan)
    elif test in ("panel","messages","default-comment","timer-baseline","timer-ptt-baseline","multi","lists","list-baseline","function","scope","scope-baseline"):
        result=check_panel(region,folder,main,flash,ms,test=test)
    elif test=="dprs":
        result=check_dprs(region,folder,main,ms)
    else:
        slot=FIRST if test in ("first","settings-boot","settings-smart") else SECOND
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
            result.update(check_home(cpu,frame,slot,region,folder,ms,report,settings=test if test.startswith("settings-") else None))
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


def check_home(cpu,frame,slot,region,folder,ms,report,*,settings=False):
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
    if settings:
        from tools.verify_705_ftx_tx import mount_station_card
        paths=[rf"C:\IC-705\APRS{i}.CFG" for i in range(2)]
        # Native GPS TX Mode is OFF after selecting APRS. Blank emulator EEPROM is 0xff.
        cpu.mem_write(0x20380172,bytes(1));tick()
        card,_,_=mount_station_card(cpu,ft,rom,extra_paths=paths)
        smart=settings=="settings-smart"
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
    assert all(unpack_from("<I",saved_records,i*340)==(i,) and
               unpack_from("<H",saved_records,i*340+338)==(185,) for i in range(1,64))
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
    p.add_argument("test",choices=("first","second","update","dprs","panel","messages","default-comment","timer-baseline","timer-ptt-baseline","multi","lists","list-baseline","function","scope","scope-baseline","settings-boot","settings-fallback","settings-smart"))
    p.add_argument("--folder",type=Path)
    args=p.parse_args()
    run(args.region,args.test,args.folder)
