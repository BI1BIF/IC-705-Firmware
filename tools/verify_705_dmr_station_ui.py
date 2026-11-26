"""Replay packaged MODE > DMR with the installed SD payload and cold HOME allocator state."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack_from
import sys
from unittest.mock import patch

_ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(_ROOT),str(_ROOT/".analysis/ic705-emulator/deps"),str(_ROOT/".analysis/ftx-tools")]
from tools import verify_705_aprs_slot as boot
from tools.build_705_dmr_ui import ROOT
from tools.build_705_dmr_station import OUT
from tools.emulate_705 import BASE, RAM, RAM_BYTES, arm, call, uc
from tools.probe_705_canvas_heap import CanvasAudit
from tools.probe_705_sstv_picture import tick
from tools.render_705_stock_row import TextSurface
from tools.replay_705_aprs_fm import DSP_NOISE, SQL_PUBLISH, SQL_STATE, SQL_STEP, load_aprs_panel, original_fm
from tools.replay_705_aprs_task import e140_rom
from tools.replay_705_stock_install import A_PREFIX, load_a
from tools.verify_705_ftx_rx import compose, symbols
from tools.verify_705_ftx_tx import mount_station_card


def cold_ram(region, folder, output, meta):
    target=output/"home.bin"
    identity=output/"home.json"
    if target.exists() and identity.exists():
        previous=json.loads(identity.read_text())
        data=target.read_bytes()
        if meta["sha256"]==previous["dat"] and sha256(data).hexdigest()==previous["ram"]:
            return data

    class Captured(Exception): pass
    def observe(cpu, frame, *_args, **_kwargs):
        assert cpu.mem_read(0x204bab5d,1)==b"\x01"
        ram=bytes(cpu.mem_read(RAM,RAM_BYTES))
        target.write_bytes(ram)
        identity.write_text(json.dumps(dict(dat=meta["sha256"],frame=frame,
            ram=sha256(ram).hexdigest()),indent=2),encoding="utf-8")
        raise Captured()
    with patch.object(boot,"check_home",observe),patch.object(boot,"symbols",lambda _:{}):
        try: boot.run(region,"first",folder)
        except Captured: return target.read_bytes()
    raise AssertionError("verified HOME missing")


def run(region):
    folder=OUT/region
    output=folder/"station-ui"
    output.mkdir(parents=True,exist_ok=True)
    meta=json.loads((folder/"package.json").read_text())
    test(region,folder,output,meta,cold_ram(region,folder,output,meta))


def test(region,folder,output,meta,ram,*,aprs_elf=None,scope_probe=False):
    dat=(folder/f"705{region}140.dat").read_bytes()
    sd=(folder/"DMRRX.BIN").read_bytes()
    assert sha256(dat).hexdigest()==meta["sha256"] and sha256(sd).hexdigest()==meta["card_sha256"]
    main,flash=load_a(dat,meta["main_sha256"])
    sy=symbols(folder/"station.elf")
    code=sy["dmr_rx_set_enabled"]&~1
    assert main[code-BASE:code-BASE+16]==ram[code-RAM:code-RAM+16]
    images,e=load_aprs_panel((ROOT/"firmware"/f"705{region}140.dat").read_bytes())
    old_dispatch=TextSurface.dispatch
    def dispatch(surface,c,at,*args):
        caller=c.reg_read(arm.UC_ARM_REG_LR)&~1
        if (sy["worker"]&~1) <= caller < sy["__work_start"] and at in (sy["radio_alloc"],sy["radio_free"]):
            return  # execute the untouched native allocator body for DMR
        return old_dispatch(surface,c,at,*args)
    with patch.object(TextSurface,"dispatch",dispatch):
        g=original_fm(images,output,rom=e140_rom if e else None)
    c=g.cpu
    app=main[:meta.get("ft_previous_main_size")]
    c.mem_write(BASE,app); c.ctl_remove_cache(BASE,BASE+len(app))
    c.mem_write(0x185f0000,flash[:A_PREFIX])
    # Cold application heap, thread list, TCB and stack pool; all come from this same DAT.
    for lo,hi in ((0x20380c48,0x20380c4c),(0x20381e00,0x20382200),
                  (0x20499000,0x204ba000),(0x206b0000,0x206d0000),(0x20750000,0x20830a40)):
        c.mem_write(lo,bytes(ram[lo-RAM:hi-RAM]))
    end=unpack_from("<I",main,0x2e8)[0]
    for pos in (end-32,end-16):
        src,dst,size,method=unpack_from("<4I",main,pos-BASE);call(c,method|1,src,dst,size)
    def read(a,n=4): return int.from_bytes(c.mem_read(a,n),"little")
    bank=0x21000000
    c.mem_map(bank,4096)
    c.mem_write(bank,pack("<2I",0xe8bd4000,0xe8bd8000))
    def svc(cpu,number,_):
        assert number==2
        sp=cpu.reg_read(arm.UC_ARM_REG_SP)-8
        pc=cpu.reg_read(arm.UC_ARM_REG_PC)
        cpsr=cpu.reg_read(arm.UC_ARM_REG_CPSR)
        cpu.mem_write(sp,pack("<2I",cpu.reg_read(arm.UC_ARM_REG_LR),pc|((cpsr>>5)&1)))
        cpu.reg_write(arm.UC_ARM_REG_SP,sp)
        cpu.reg_write(arm.UC_ARM_REG_LR,bank)
        cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_R12))
    c.hook_add(uc.UC_HOOK_INTR,svc)
    for a in (0xe8201000,0xe8202000): c.mem_map(a,4096)
    sdpath=r"C:\IC-705\DMRRX.BIN"
    files,_,_=mount_station_card(c,{"log_worker":0},g.rom,extra_paths=[
        sdpath,r"C:\IC-705\APRS0.CFG",r"C:\IC-705\APRS1.CFG"])
    audit=CanvasAudit(c,stock=False)
    def heap(): return audit.free_list()
    def snap(name,*want):
        tick(g);strings,screen=compose(g)
        screen.save(output/(name+".png"))
        assert set(want)<=set(strings),(name,want,strings,read(sy["status"]+4))
        return strings
    def tap(x,y):
        return g.click(x,y,instruction_limit=50_000_000)
    def menu():
        tap(37,32); snap("mode","MODE","DV","FT8/4")
    from tools.probe_705_cw_feedback import BEEP_ENABLE, SEQUENCER
    original_beep=read(BEEP_ENABLE,1)
    tones=[]
    def note(cpu,*_):
        if cpu.reg_read(arm.UC_ARM_REG_R0)==1:
            tones.append(read(sy["status"]))
    c.hook_add(uc.UC_HOOK_CODE,note,begin=sy["beep"],end=sy["beep"])
    def clear_tones(enabled):
        c.mem_write(BEEP_ENABLE,bytes([enabled]))
        call(c,g.rom(0x2000e73c),0)
        tones.clear()
    if scope_probe:
        files[sdpath]=sd
        menu(); tap(130,242); snap("dv","DV")
        initial=bytes(c.mem_read(RAM,RAM_BYTES))
        regs=c.context_save()
        traces={}
        def screen_state():
            return [read(0x203e84c9,1),read(0x203e84d3,1),read(0x204bab61,1)]
        calls=[]
        def capture(cpu,at,*_):
            calls.append([hex(at),screen_state(),cpu.reg_read(arm.UC_ARM_REG_R0),cpu.reg_read(arm.UC_ARM_REG_R1)])
        for at in (sy["dmr_ui_touch"]&~1,sy["mode_select"],g.rom(0x200f1600),g.rom(0x200f0954)):
            c.hook_add(uc.UC_HOOK_CODE,capture,begin=at,end=at)
        for size in ("off","mini","normal","expanded"):
            c.mem_write(RAM,initial); c.context_restore(regs)
            clear_tones(0)
            if size=="mini": g._press_key(1,0)
            if size in ("normal","expanded"):
                g.press_menu(); snap(size+"-menu","MENU")
                tap(52,80)
                if size=="expanded": tap(438,254)
            snap(size+"-initial","DV")
            start=screen_state()
            assert start=={"off":[0,0,0],"mini":[0,1,2],"normal":[9,0,0],"expanded":[9,0,1]}[size]
            transitions=[]
            for label in ("DMR","YSF","P25","DV"):
                calls.clear()
                menu()
                menu_state=screen_state()
                tap(130,242)
                expected=(label,"SPECTRUM SCOPE") if "mode_pop" in sy and start[0]==9 else (label,)
                snap(size+"-"+label,*expected)
                transitions.append(dict(mode=label,menu=menu_state,after=screen_state(),calls=calls.copy()))
            traces[size]=dict(before=start,steps=transitions)
        if "mode_pop" in sy:
            assert all(step["after"]==view["before"] for view in traces.values() for step in view["steps"]), traces
            # Begin a separate deferred entry with no retired worker in flight.
            c.mem_write(RAM,initial); c.context_restore(regs)
            clear_tones(0)
            g.press_menu(); snap("deferred-menu","MENU")
            tap(52,80); tap(438,254)
            menu()
            select=sy["mode_select"]&~1
            def defer(cpu,*_):
                cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
            hook=c.hook_add(uc.UC_HOOK_CODE,defer,begin=select,end=select)
            try: tap(130,242)
            finally: c.hook_del(hook)
            snap("expanded-deferred","DV","SPECTRUM SCOPE","FM mode not ready")
            call(c,sy["mode_select"],2,4)
            c.mem_write(0x20381e08,pack("<I",(read(0x20381e08)+125)&0xffffffff))
            call(c,sy["dmr_ui_input"],instruction_limit=50_000_000,timeout_us=0)
            snap("expanded-retry","DMR","SPECTRUM SCOPE")
            assert screen_state()==[9,0,1]
        (output/"scope-cycle.json").write_text(json.dumps(dict(dat=meta["sha256"],layouts=traces),indent=2))
        return traces
    def start_dmr():
        menu(); tap(130,242); snap("stock-dv","DV")
        assert read(0x203e2128,1)>>4==9
        menu(); tap(130,242)
    before=heap()
    aprs=symbols(aprs_elf or ROOT/".analysis/release-v1.4.0/rebuild"/region/"manager.elf")
    def aprs_fm(): return call(c,aprs["plain_fm"])
    def check_monitor(playback):
        for noise, carrier in ((65535, 0), (0, 1)):
            c.mem_write(DSP_NOISE,pack("<H",noise))
            call(c,g.rom(SQL_STEP))
            call(c,g.rom(SQL_PUBLISH))
            assert read(SQL_STATE,1)==carrier
            assert read(0x203e1b30+0x2fc,1)==playback
    check_monitor(0)
    assert aprs_fm()==1
    for name in ("missing","corrupt","rx5-card"):
        if name=="corrupt": files[sdpath]=bytes([sd[0]^1])+sd[1:]
        if name=="rx5-card": files[sdpath]=(ROOT/".analysis/dmr-rx5-start/final"/region/"DMRRX.BIN").read_bytes()
        start_dmr(); snap(name,"Check SD card")
        assert not read(sy["allocation"]) and not read(sy["thread_id"]) and heap()==before
        tap(200,99); snap(name+"-exit","FM")
        check_monitor(0)
    files[sdpath]=sd
    # Only substitute the named service's return to this candidate. Native
    # callers (e.g. the canvas allocator) keep their normal behavior.
    def refused(name):
        at=sy[name]&~1
        def reject(cpu,*_):
            lr=cpu.reg_read(arm.UC_ARM_REG_LR)
            if (sy["dmr_rx_set_enabled"]&~1)<= (lr&~1) < sy["__work_start"]:
                cpu.reg_write(arm.UC_ARM_REG_R0,0)
                cpu.reg_write(arm.UC_ARM_REG_PC,lr)
        return c.hook_add(uc.UC_HOOK_CODE,reject,begin=at,end=at)
    def retry_tick():
        c.mem_write(0x20381e08,pack("<I",(read(0x20381e08)+125)&0xffffffff))
        call(c,sy["dmr_ui_input"],instruction_limit=50_000_000,timeout_us=0)
    # Delay the native FM key completion to a later panel tick.
    menu(); tap(130,242); menu()
    mode=sy["mode_select"]&~1
    def delay_mode(cpu,*_):
        cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
    hook=c.hook_add(uc.UC_HOOK_CODE,delay_mode,begin=mode,end=mode)
    try: tap(130,242)
    finally: c.hook_del(hook)
    snap("mode-pending","FM mode not ready")
    call(c,sy["mode_select"],2,4)
    c.mem_write(0x203809ac,pack("<I",1))
    retry_tick(); snap("tx-busy","TX request active")
    c.mem_write(0x203809ac,bytes(4)); retry_tick()
    assert not read(sy["thread_id"]) and not read(sy["dmr_guard_active"],1)
    tap(200,99)
    for service,reason in (("radio_alloc","DMR memory full"),("make_thread","Worker unavailable"),
                           ("factory_fm_available","Other RX active")):
        hook=refused(service)
        try:
            start_dmr(); snap(service,"FM",reason)
        finally: c.hook_del(hook)
        assert not read(sy["allocation"]) and not read(sy["thread_id"]) and heap()==before
        retry_tick(); snap(service+"-no-auto-retry",reason)
        tap(200,99)
    hook=refused("aprs_overlay_unload")
    try:
        start_dmr(); snap("aprs-wait","APRS busy")
        for _ in range(8): retry_tick()
        snap("aprs-timeout","APRS busy")
        assert not read(sy["allocation"]) and not read(sy["dmr_guard_active"],1)
        tap(200,99)
        start_dmr(); snap("aprs-cancel","APRS busy")
        tap(200,99); retry_tick()
        assert not read(sy["notice"],1) and not read(sy["retries"])
        start_dmr()
    finally: c.hook_del(hook)
    # Fragment the native RTX stack pool using its own allocate/free pair.
    # Leave one isolated 16 KiB block and verify the old request cannot fit.
    pool=0x2049a5c0
    def stack_alloc(n): return call(c,g.rom(0x202d4b16)+1,pool,n)
    def stack_free(ptr): call(c,g.rom(0x202d4dc8)+1,pool,ptr)
    held_stacks=[]
    while block:=stack_alloc(16384):
        held_stacks.append(block)
    assert len(held_stacks)>=2
    gap=held_stacks.pop(-2)
    stack_free(gap)
    assert stack_alloc(32768)==0
    clear_tones(1)
    retry_tick()
    assert tones==[1] and read(SEQUENCER,1)==1,(tones,read(SEQUENCER,1))
    retry_tick()
    assert tones==[1]
    # This panel harness drives no beep timer. End the tested click before
    # driving unrelated native keys, which observe the sequencer busy flag.
    clear_tones(original_beep)
    assert "FM" not in snap("searching","DMR")
    check_monitor(1)
    from PIL import Image, ImageChops
    worker=read(sy["thread_id"])
    def put_row(text):
        c.mem_write(sy["status"]+36,text.encode()+bytes(1))
    rows={}
    def check_row(name,text,compact):
        put_row("")
        idle_name=name+"-idle"
        assert "UR:" not in snap(idle_name,"DMR")
        put_row(text)
        assert "UR:" not in snap(name,text)
        idle=Image.open(output/(idle_name+".png")).convert("RGB")
        incoming=Image.open(output/(name+".png")).convert("RGB")
        bounds=ImageChops.difference(idle,incoming).getbbox()
        assert bounds,(name,"empty")
        left,top,right,bottom=bounds
        _,x,y,_,_,width,height=unpack_from("<7H",c.mem_read(sy["caller_rect"],14))
        assert x<=left<right<=x+width and y<=top<bottom<=y+height,(name,bounds,x,y,width,height)
        assert idle.crop(bounds).getbbox() is None,(name,"underlying content",bounds)
        if compact:
            assert 148<=left and 54<=top<bottom<=84,(name,bounds)
        else:
            assert 42<=left<right<=418 and 89<=top<bottom<=111,(name,bounds)
        put_row("")
        snap(name+"-end","DMR")
        assert not ImageChops.difference(idle,Image.open(output/(name+"-end.png")).convert("RGB")).getbbox()
        put_row(text)
        assert read(sy["thread_id"])==worker and read(sy["dmr_guard_active"],1)==1
        rows[name]=bounds
    row="PVT CC 6 ID 4601205 TO 54611"
    check_row("caller-row",row,False)
    g._press_key(1,0)
    check_row("mini-scope",row,True)
    g.press_menu(); snap("main-menu","MENU")
    tap(52,80); snap("full-scope-entry",row)
    assert read(0x203e84c9,1)==9
    check_row("full-scope",row,False)
    tap(438,254)
    check_row("expanded-scope",row,True)
    check_row("expanded-long","PVT CC 15 TS 2 ID 16777215 TO 16777214",True)
    g.press_exit(); snap("scope-exit","DMR")
    assert read(sy["thread_id"])==worker and read(sy["status"])==1
    if call(c,g.rom(0x200f1e48)): g._press_key(1,0)
    menu(); g.press_exit(); snap("cancel-mode","DMR")
    g.press_exit(); snap("dmr-exit-key","DMR")
    assert read(sy["thread_id"])==worker and read(sy["dmr_guard_active"],1)==1
    tap(318,191)
    assert read(sy["status"])==1
    tcb=read(sy["thread_id"]); allocation=read(sy["allocation"])
    stack=read(tcb+0x2c); stack_size=read(tcb+0x26,2)
    thread_return=read(read(tcb+0x28)+52)
    assert stack==gap and stack_size==16384 and read(stack)==0xe25a2ea5 and allocation and read(sy["status"])==1
    using=heap()
    assert aprs_fm()==0
    assert sum(n for _,n in using)<sum(n for _,n in before)
    # Resume the installed worker once on its allocated stack after the application's EXIT signal.
    wait=sy["wait_signal"]&~1
    def wake(cpu,*_):
        cpu.reg_write(arm.UC_ARM_REG_R0,1)
        cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
    def retire_worker():
        tcb=read(sy["thread_id"])
        stack=read(tcb+0x2c)
        size=read(tcb+0x26,2)
        h=c.hook_add(uc.UC_HOOK_CODE,wake,begin=wait,end=wait)
        try: call(c,sy["worker"],stack=stack+size-64)
        finally: c.hook_del(h)
        assert read(sy["thread_id"])==read(sy["allocation"])==read(sy["image"])==0 and heap()==before

    for m,title in ((2,"YSF"),(3,"P25")):
        menu(); clear_tones(1); tap(130,242)
        assert tones==[m] and read(SEQUENCER,1)==1,(title,tones)
        clear_tones(original_beep)
        snap("mode-"+title,title)
        g.press_exit(); snap("exit-key-"+title,title)
        if m==3:
            example=b"GRP NAC 293 ID 4601205 TG 9"
            c.mem_write(sy["status"]+36,example+bytes(1))
            snap("p25-caller-row",example.decode())
        assert read(sy["thread_id"])==tcb and read(sy["allocation"])==allocation
        assert read(sy["status"])==m and read(sy["dmr_guard_active"],1)==1
    menu(); tap(130,242); snap("cycle-dv","DV")
    assert not read(sy["status"])
    retire_worker()
    menu(); tap(51,242); snap("exit","FM")
    check_monitor(0)
    assert aprs_fm()==1
    assert thread_return==g.rom(0x202d4904)+1
    retire=read((thread_return&~1)+20)
    assert retire==g.rom(0x202d60ac)+1 and call(c,retire,tcb)==0
    reused=call(c,g.rom(0x202d4b16)+1,0x2049a5c0,stack_size)
    assert reused==stack
    call(c,g.rom(0x202d4dc8)+1,0x2049a5c0,reused)
    for block in reversed(held_stacks): stack_free(block)
    full=stack_alloc(32768)
    assert full
    stack_free(full)
    menu(); tap(130,242); snap("stock-dv","DV")
    # Replay the same DV keypress independently under both preferences.
    dv_ram=bytes(c.mem_read(RAM,RAM_BYTES))
    dv_regs=c.context_save()
    for enabled in (0,1):
        menu(); clear_tones(enabled); tap(130,242)
        assert tones==[1] and read(SEQUENCER,1)==enabled,(tones,enabled,read(SEQUENCER,1))
        c.mem_write(RAM,dv_ram)
        c.context_restore(dv_regs)
    menu(); tap(431,192); snap("ft-selector","FT8","FT4","Digital")
    result=dict(mode_beep_after_selection=True,first_dmr_beep_on_off_and_retry=True,
        caller_row_bounds=rows,exit_keeps_all_three_modes=True,dat=meta["sha256"],card=meta["card_sha256"],cold_memory=True,
        stack_size=stack_size,stack=hex(stack),thread=hex(tcb),allocation=hex(allocation),
        native_heap_free_before=sum(n for _,n in before),native_heap_free_active=sum(n for _,n in using),
        native_heap_freelist_identical_after_exit=True,native_rtx_stack_reused_after_retire=hex(reused),
        missing_and_corrupt_card_error_then_successful_retry=True,mode_search_exit_dv_ft=True,
        startup_failures_and_cleanup=["radio_alloc","make_thread","factory_fm_available"],
        aprs_wait_timeout_cancel_recovery=True,
        deferred_mode_then_tx_refusal=True,
        native_pool_refused_32k_started_16k=True,old_rx5_card_refused=True,
        rx_monitor_follows_dmr_with_carrier_and_without=True,
        aprs_fm_available_before_during_after=[1,0,1],
        fixtures="SD API serves supplied BIN. LCD graphics modeled. SVC calls execute the installed kernel service without timer preemption; worker wake/resume and the stock return-stub retirement service after EXIT are driven explicitly.")
    (output/"results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(result,flush=True)


if __name__=="__main__":
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("region",choices=["J","E"])
    run(parser.parse_args().region)
