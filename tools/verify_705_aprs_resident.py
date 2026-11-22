"""Replay APRS residency and beacon eligibility on the two FT/SSTV/CW images."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
from unittest.mock import patch

from tools import replay_705_e140_ft as eu
from tools import verify_705_ftx_rtx as jp
from tools import verify_705_ftx_rx as receiver
from tools.decode_705_main import decode_main
from tools.probe_705_rtx_audio import probe
from tools.replay_705_aprs_task import build_task, e140_rom, FM_HZ
from tools.replay_705_stock_install import A_PREFIX, load_a

OUT = Path(".analysis/aprs-combined-resident")
REGIONS = {"J":"5c985561d9217588b07b31571a05bf36638dbdacd51b131e1763e9e4935ab167",
           "E":"1c96571f7aa158778e81ffb94ce4bef920b0025c132e2bd557179d44edc3ca17"}

def populate(c, sub, value, sy):
    from tools.replay_705_aprs_fm import ax25_burst
    # Feed a real fixture once, then exercise the decoder -> history queue
    # with 63 copies. The receiver sequence/end sample differs in every slot.
    wave = ax25_burst("!3531.00N/13930.00E>history", 45)
    addr = 0x180000
    mapped = (len(wave)*2+4095)&~4095
    c.mem_map(addr,mapped)
    c.mem_write(addr,pack(f"<{len(wave)}h",*wave))
    for start in range(0,len(wave),288):
        sub(sy["aprs_rx_feed"], addr+2*start,min(288,len(wave)-start))
    c.mem_unmap(addr,mapped)
    assert value(sy["aprs_rx_written"]) == 1
    frame = bytes(c.mem_read(sy["aprs_rx_frames"],340))
    for i in range(64):
        c.mem_write(sy["aprs_rx_frames"] + i%4*340,pack("<I",len(wave)*(i+1))+frame[4:])
        c.mem_write(sy["aprs_rx_written"],pack("<I",i+1))
        sub(sy["aprs_record_receive"])
    assert value(sy["aprs_record_count"]) == 64
    ring = value(sy["aprs_records"])
    assert ring
    parts = ([(sy["aprs_history_prefix"],58),(ring,6)] if "aprs_history_prefix" in sy else [(ring,64)])
    snapshot = b"".join(bytes(c.mem_read(address,slots*340)) for address,slots in parts)
    assert all(snapshot[i*340:i*340+4] == pack("<I",len(wave)*(i+1)) for i in range(64))
    return parts

def check_modes(c, sub, value, sy, ft, sstv, rom):
    from tools.replay_705_vfo_split import SELECT_VFO, seed_vfos
    from tools.replay_705_ptt_tune import INIT_RANGES
    seed_vfos(c,(FM_HZ,145000000))
    sub(rom(INIT_RANGES))
    sub(rom(SELECT_VFO[0]))
    for addr in [0x203e2128,0x203e212f,0x203e2136]:
        c.mem_write(addr,b"\x70\0")
    c.mem_write(0x20380714,pack("<I",FM_HZ))
    c.mem_write(sy["aprs_channel_hz"],pack("<I",FM_HZ))
    for name in ("aprs_auto_beacon","aprs_tx_enabled"):
        c.mem_write(sy[name],b"\1")
    c.mem_write(sy["aprs_beacon_interval"],b"\0")
    c.mem_write(0x203e2499,b"N0CALL  ")
    c.mem_write(0x203eb16c,b"\2")
    c.mem_write(0x203ea85d,pack(">BHcBHc",33,51234,b"S",151,12678,b"W"))
    c.mem_write(0x204bab5d,b"\1")
    # The receiver replay finishes with an open squelch. Model a clear FM
    # channel and a released hand mic for the positive timer control.
    for addr,n in [(0x2038026c,1),(0x203809c4,1),(0x203806f4,1),(0x203809b0,4),(0x203809a1,1)]:
        c.mem_write(addr,bytes(n))
    assert sub(sy["aprs_standby_ready"])
    clock = 0x20381e08
    now = value(clock)
    sub(sy["aprs_beacon_reschedule"])
    cases = [
        ("FT receive",ft["state"],2),
        ("FT waiting for slot",ft["stage"],1),
        ("FT modulating",ft["stage"],3),
        ("SSTV waiting for TX",sstv["tx_state"],1),
        ("SSTV modulating",sstv["tx_state"],2),
        ("SSTV releasing",sstv["tx_state"],3),
        ("SSTV picture",sstv["counts"],1),
    ]
    for name, address, setting in cases:
        c.mem_write(address,pack("<I",setting))
        if name == "SSTV picture":
            c.mem_write(0x203e84c9,pack("<H",21))
        assert sub(sy["aprs_active_frequency"])==0, name
        assert sub(sy["aprs_beacon_start"]) and value(sy["stage"])==0, name
        now = (now + 60000) & 0xffffffff
        c.mem_write(clock,pack("<I",now))
        sub(sy["aprs_beacon_poll"])
        assert value(sy["stage"]) == 0 and sub(sy["aprs_tx_requested"],0) == 0, name
        c.mem_write(address,bytes(4))
    c.mem_write(0x203e84c9,bytes(2))
    assert sub(sy["aprs_active_frequency"])==FM_HZ
    # Enter just before a deadline and stay through several slots. The last
    # slot's deadline must not turn into a pending beacon on the way to FM.
    for ft4 in (0,1):
        c.mem_write(ft["ftx_ft4"],pack("<I",ft4))
        sub(sy["aprs_beacon_reschedule"])
        for elapsed,state in [(59999,1),(60000,2),(120001,2),(185000,3)]:
            c.mem_write(ft["state"],pack("<I",state))
            c.mem_write(clock,pack("<I",(now+elapsed)&0xffffffff))
            sub(sy["aprs_beacon_poll"])
            assert value(sy["stage"]) == 0 and sub(sy["aprs_tx_requested"],0) == 0
        c.mem_write(ft["state"],bytes(4))
        c.mem_write(0x20380714,pack("<I",FM_HZ+10000))
        now=(now+390000)&0xffffffff
        c.mem_write(clock,pack("<I",now))
        sub(sy["aprs_beacon_poll"])
        assert value(sy["stage"]) == 0
        c.mem_write(0x20380714,pack("<I",FM_HZ))
        sub(sy["aprs_beacon_poll"])
        assert value(sy["stage"]) == 0 and value(sy["beacon_cycle_started"]) == now
        c.mem_write(clock,pack("<I",(now+59999)&0xffffffff))
        sub(sy["aprs_beacon_poll"])
        assert value(sy["stage"]) == 0
        now=(now+60000)&0xffffffff
        c.mem_write(clock,pack("<I",now))
        sub(sy["aprs_beacon_poll"])
        assert value(sy["stage"]) == 1
        # Race: FT opens after the timer arms, before the DSP grants PTT.
        c.mem_write(ft["state"],pack("<I",1))
        assert sub(sy["aprs_tx_source"],1) == sub(ft["ft_tx_source"],1)
        # Simulate a final FT release block; only the original FT modulator
        # may write it even if the APRS timer had already armed.
        c.mem_write(ft["stage"],pack("<I",5))
        seen = []
        entry = ft["ft_tx_mod_block"] & ~1
        hook = c.hook_add(receiver.uc.UC_HOOK_CODE,lambda *_:seen.append(True),begin=entry,end=entry)
        try:
            assert sub(sy["aprs_tx_mod_block"]) == 4 and seen == [True]
        finally:
            c.hook_del(hook)
        assert sub(sy["aprs_tx_requested"],0) == 0 and value(sy["stage"]) == 0
        assert value(ft["stage"]) == 0
        c.mem_write(ft["state"],bytes(4))
    return [name for name,_,_ in cases]

def check_sstv(c,sub,value,sy,sstv,full_image_dir=None):
    if sy:
        assert not value(sy["stage"])
    c.mem_write(0x203e84c9,pack("<H",21))
    sub(sstv["sstv_begin"])
    rx=value(sstv["pixels"])
    assert rx and value(sstv["counts"]), "SSTV RX canvas"
    # Supply the committed JPEG selection at the original catalog boundary.
    for addr in (0x203e1038,0x203e0f68):
        c.mem_write(addr,b"Reverse.jpg\0")
    c.mem_write(0x203e105d,b"\1")
    c.mem_write(0x20380172,b"\3")
    image=bytes(range(256))*600
    if full_image_dir:
        palette = (0xffff,0xf800,0x07e0,0x001f)
        image = b"".join(pack("<H",palette[(x//80+y//60)%4]) for y in range(240) for x in range(320))
    c.mem_write(0x2064b584,image)
    sub(sstv["sstv_tx_toggle"])
    tx=value(sstv["tx_snapshot"])
    assert tx and abs(tx-rx)>=len(image) and bytes(c.mem_read(tx,len(image)))==image
    if sy:
        sub(sy["aprs_beacon_reschedule"])
        clock=0x20381e08
        c.mem_write(clock,pack("<I",(value(clock)+60000)&0xffffffff))
        sub(sy["aprs_beacon_poll"])
        assert not value(sy["stage"])
    assert value(sstv["tx_state"])==1
    c.mem_write(0x203809a1,b"\x10")
    assert sub(sstv["sstv_tx_mod_block"])==4 and value(sstv["tx_state"])==2
    assert any(c.mem_read(0x20401c14,72))
    full = {}
    if full_image_dir:
        from tools.verify_705_aprs_overlay import finish_robot36
        full = finish_robot36(c,sub,value,sstv,image,full_image_dir)
    c.mem_write(0x203809a1,b"\0")
    sub(sstv["sstv_prepare_frame"])
    assert not value(sstv["tx_snapshot"])
    return dict(rx=hex(rx),tx=hex(tx),bytes_each=len(image),snapshot_matched=True,
                beacon_idle_at_deadline=True if sy else None,first_36_samples_generated=True,tx_snapshot_released=True,**full)

def run(region, combined_base=False, split_history=False, overlay=False):
    european = region=="E"
    folder = Path(".analysis/aprs-integration-base" if combined_base else ".analysis/ft-key-style")/region
    dat = (folder/f"705{region}140.dat").read_bytes()
    baseline = json.loads((folder/"evidence.json").read_text())["sha256"] if combined_base else REGIONS[region]
    assert sha256(dat).hexdigest()==baseline
    stock = bytes(decode_main(Path(f"firmware/705{region}140.dat").read_bytes())[1])
    main,flash=load_a(dat,sha256(decode_main(dat)[1]).hexdigest())
    ft=receiver.symbols(jp.OUT/"rx.elf")
    sstv=receiver.symbols(jp.OUT/"sstv/rx.elf")
    aliases={"ft_session_state":ft["state"],"ft_tx_stage":ft["stage"],
             "sstv_tx_state":sstv["tx_state"],"sstv_rx_only":sstv["sstv_rx_only"]}
    for name in ("ft_tx_requested","ft_tx_source","ft_tx_mod_block"):
        aliases[name] = ft[name+"_arm"]
    flags=["-DAPRS_COMBINED",*(f"-Wl,--defsym,{k}={v:#x}" for k,v in aliases.items())]
    if split_history:
        from tools.build_705_cw_sim import PICKER_TABLE
        assert combined_base
        prefix=PICKER_TABLE+(224 if european else 0)
        flags.extend(["-DAPRS_HISTORY_SPLIT",f"-Wl,--defsym,aprs_history_prefix={prefix:#x}"])
    if combined_base:
        folder=folder/("aprs-overlay" if overlay else "aprs-split-history" if split_history else "aprs-resident")
    else:
        folder=OUT/region
    folder.mkdir(parents=True,exist_ok=True)
    rom=e140_rom if european else lambda a:a
    def resident_probe(stock_image, *, application, audio_experiment):
        def resident(c, run_loop, irq, sub, value):
            frame=c.context_save()
            if overlay:
                from tools.verify_705_aprs_overlay import replay
                def away():
                    c.context_restore(frame)
                    playback = audio_experiment(c,run_loop,irq,sub,value)
                    picture = check_sstv(c,sub,value,None,sstv,folder)
                    c.mem_write(0x203e84c9,bytes(2))
                    sub(sstv["sstv_prepare_frame"])
                    assert not value(sstv["pixels"]) and not sub(sstv["sstv_rx_only"])
                    return dict(ft=playback,sstv=picture)
                return dict(baseline=baseline, **replay(folder,european,flags,rom,c,sub,value,away))
            allocation=sub(rom(0x20127a28),65536)
            assert allocation
            base=(allocation+31)&~31
            code,sy=build_task(folder,european=european,base=base,flags=flags)
            assert sy["__bss_end__"] <= allocation+65536
            c.mem_write(base,code)
            c.mem_write(sy["__bss_start__"],bytes(sy["__bss_end__"]-sy["__bss_start__"]))
            sub(sy["aprs_set_channel"],FM_HZ)
            parts=populate(c,sub,value,sy)
            def history():
                return b"".join(bytes(c.mem_read(address,slots*340)) for address,slots in parts)
            snapshot=history()
            c.context_restore(frame)
            playback=audio_experiment(c,run_loop,irq,sub,value)
            assert history()==snapshot and value(sy["aprs_records"])==parts[-1][0]
            modes=check_modes(c,sub,value,sy,ft,sstv,rom)
            picture=check_sstv(c,sub,value,sy,sstv)
            assert history()==snapshot
            return dict(baseline=baseline,aprs_code_and_state_heap=hex(allocation),
                        aprs_reserved_bytes=65536,history_address=hex(parts[0][0]),history_bytes=len(snapshot),
                        history_parts=[(hex(a),n) for a,n in parts],history_heap_bytes=parts[-1][1]*340,
                        records=64,history_sha256=sha256(snapshot).hexdigest(),
                        preserved_after_ft_exit=True,blocked_modes=modes,resumed_at_ms=60000,playback=playback,
                        ft_pause_cases=["FT8","FT4"],off_frequency_return_skipped=True,
                        sstv=picture,preserved_after_sstv_tx=True)
        return probe(stock_image,application=application,audio_experiment=resident)

    if european:
        with patch.object(eu,"probe",resident_probe):
            report=eu.replay(stock,main,flash[:A_PREFIX],ft,"FT8",1)
    else:
        with patch.object(jp,"probe",resident_probe),patch.object(receiver,"map_atlas",lambda c,_dat:c.mem_write(0x185f0000,flash[:A_PREFIX])):
            # Leave an RTX stack for the SSTV worker entered after FT exits.
            report=jp.scheduler((stock,),main,ft,exhaust_stack_pool=False)
    (folder/"result.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(region,folder/"result.json")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("region",choices=REGIONS)
    parser.add_argument("--combined-base",action="store_true")
    parser.add_argument("--split-history",action="store_true")
    parser.add_argument("--overlay",action="store_true",help="exercise the loader on the split-history combined image")
    args=parser.parse_args()
    run(args.region,args.combined_base or args.overlay,args.split_history or args.overlay,args.overlay)
