"""Exercise the packaged DMR station through both stock SSIF0 DMA directions."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
import wave

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/".analysis/ic705-emulator/deps"),str(ROOT/".analysis/ftx-tools")]
from tools.build_705_aprs_slot import scatter
from tools.decode_705_main import decode_main
from tools.emulate_705 import BASE, SP, STOP, arm, call, machine, uc
from tools.probe_705_rx_audio import FRAMES, DMAC, LAYOUTS, completed
from tools.verify_705_dmr_radio import HERE, discriminator, mobile_call, render_if
from tools.verify_705_ftx_rx import symbols

from tools.build_705_dmr_station import OUT

def playback_reference(pcm):
    src=np.frombuffer(pcm,"<i2").astype(np.int32)
    level=np.abs(src)
    magnitude=np.minimum(level,12288)*2+np.maximum(level-12288,0)//4
    return (np.sign(src)*magnitude).astype("<i2").tobytes()

def reference_alert(data, starts):
    samples=np.frombuffer(data,"<i2").astype(np.int32)
    sine=(0,1061,1500,1061,0,-1061,-1500,-1061)
    for start in starts:
        for t in range(280):
            samples[start+t]+=int(sine[t%8]*min(t,16,279-t)/16)
    return samples.clip(-32768,32767).astype("<i2").tobytes()

def bench(region, samples, reference, *, highpass=0, field=False, field_repeats=1, package_dir=OUT, digital=None, retune=False):
    folder=package_dir/region
    dat=(folder/f"705{region}140.dat").read_bytes()
    card=(folder/"DMRRX.BIN").read_bytes()
    meta=json.loads((folder/"package.json").read_text())
    assert sha256(dat).hexdigest()==meta["sha256"] and sha256(card).hexdigest()==meta["card_sha256"]
    sy=symbols(folder/"station.elf")
    main=bytes(decode_main(dat)[1])
    assert sha256(main).hexdigest()==meta["main_sha256"]
    cpu=machine(main)
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2,0xf00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC,0x40000000)
    scatter(cpu)
    offset=228 if region=="E" else 0
    def invoke(pc,*args):
        return call(cpu,pc,*args,instruction_limit=20_000_000,timeout_us=0)
    def word(pc): return int.from_bytes(cpu.mem_read(pc,4),"little")
    def put(pc,value): cpu.mem_write(pc,struct.pack("<I",value))
    def stat(): return struct.unpack("<5I",cpu.mem_read(sy["status"],20))
    def intercept(name,fn):
        pc=sy[name]&~1
        def dispatch(c,*_):
            args=[c.reg_read(i) for i in (arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3)]
            result=fn(*args)
            c.reg_write(arm.UC_ARM_REG_R0,result or 0)
            c.reg_write(arm.UC_ARM_REG_PC,c.reg_read(arm.UC_ARM_REG_LR))
        cpu.hook_add(uc.UC_HOOK_CODE,dispatch,begin=pc,end=pc)
    layout=json.loads((package_dir/"core/payload.json").read_text())
    link=layout["link_base"]
    cs=symbols(package_dir/"core"/f"payload-{link:08x}.elf")
    pool=0x207a5024 if region=="J" else 0x208718ad
    worker_sp=SP-0x18000
    stress=field_repeats>1
    if stress or package_dir.resolve()!=OUT.resolve():
        cold=json.loads((folder/"station-ui/results.json").read_text())
        assert cold["dat"]==meta["sha256"]
        expected_stack=cold["stack_size"]
    else:
        expected_stack=16384
    if stress:
        pool=int(cold["allocation"],16)
        worker_stack=int(cold["stack"],16)
        worker_sp=worker_stack+cold["stack_size"]
        monitor_bytes=16384
        cpu.mem_write(worker_stack-monitor_bytes,b"\xa5"*(monitor_bytes+cold["stack_size"]))
        put(worker_stack,0xe25a2ea5)
        first_crossing=[]
        def crossing(c,kind,address,size,value,_):
            if not first_crossing:
                first_crossing.append(dict(pc=hex(c.reg_read(arm.UC_ARM_REG_PC)),sp=hex(c.reg_read(arm.UC_ARM_REG_SP)),
                                           address=hex(address),value=hex(value),lr=hex(c.reg_read(arm.UC_ARM_REG_LR))))
        cpu.hook_add(uc.UC_HOOK_MEM_WRITE,crossing,begin=worker_stack-monitor_bytes,end=worker_stack+3)
        samples=np.tile(samples,field_repeats)
    base=(pool+63)&~63
    live,freed,created=[],[],[]
    def alloc(n,*_):
        assert not live and n==layout["mem_bytes"]+63
        live.append(pool)
        return pool
    def free(ptr,*_):
        assert live.pop()==ptr
        freed.append(ptr)
    def create(desc,*_):
        pc,priority,instances,stack=struct.unpack("<4I",cpu.mem_read(desc,16))
        assert (pc,priority,instances,stack)==(sy["worker"],0xe8,1,expected_stack)
        created.append(pc)
        return 9
    current_card=[None]
    def open_file(path,mode,fd,*_):
        assert bytes(cpu.mem_read(path,32)).split(b"\0")[0]==b"C:\\IC-705\\DMRRX.BIN" and mode==0
        if current_card[0] is None: return 4
        put(fd,7)
    def read_file(fd,dst,n,count):
        assert fd==7 and n==len(card)
        cpu.mem_write(dst,current_card[0])
        put(count,len(current_card[0]))
    intercept("radio_alloc",alloc)
    intercept("radio_free",free)
    intercept("make_thread",create)
    intercept("signal_thread",lambda *a: 1)
    intercept("sd_open",open_file)
    intercept("sd_read",read_file)
    intercept("sd_close",lambda fd,*_: 0 if fd==7 else 2)
    cpu.mem_write(0x203e2128,b"\x70\0")
    put(0x20380714,435590000 if field else 438500000)
    error_states=[]
    for value in (None,card[:128],card[:55]+bytes([card[55]^1])+card[56:]):
        current_card[0]=value
        assert not invoke(sy["dmr_rx_set_enabled"],1)
        assert stat()[:2]==(0,4) and not live and not created, (stat(),live,created)
        error_states.append(stat()[:2])
    current_card[0]=card
    mode=digital[0] if digital else 1
    assert invoke(sy["dmr_rx_set_enabled"],1)==1 and stat()[:2]==(1,0)
    assert word(sy["image"])==base
    monitor_checked = field and "dmr_monitor_page" in sy
    if monitor_checked:
        from tools.replay_705_aprs_fm import DSP_NOISE, DSP_STATUS, SQL_KNOB, SQL_PUBLISH, SQL_SETTINGS, SQL_STATE, SQL_STEP
        from tools.replay_705_aprs_task import e140_rom
        cpu.mem_write(0x203ebc33,b"\x70")
        cpu.mem_write(DSP_STATUS,b"\x40")
        cpu.mem_write(SQL_KNOB,b"\x64")
        invoke(SQL_SETTINGS+offset)
        for noise in (65535,0):
            cpu.mem_write(DSP_NOISE,struct.pack("<H",noise))
            invoke(SQL_STEP+offset)
            invoke(e140_rom(SQL_PUBLISH) if region=="E" else SQL_PUBLISH)
            assert cpu.mem_read(SQL_STATE,1)==bytes([noise==0])
            assert cpu.mem_read(0x203e1b30+0x2fc,1)==b"\1"

    # Keep the real task frame across periodic wakeups; only the RTX wait and
    # dispatch are simulated. The worker executes both work and status publication.
    waited=[0]
    wait=sy["wait_signal"]&~1
    def wait_hook(c,*_):
        waited[0]+=1
        if waited[0]>=2: c.emu_stop(); return
        c.reg_write(arm.UC_ARM_REG_R0,1)
        c.reg_write(arm.UC_ARM_REG_PC,c.reg_read(arm.UC_ARM_REG_LR))
    cpu.hook_add(uc.UC_HOOK_CODE,wait_hook,begin=wait,end=wait)
    worker_context=None
    def pump():
        nonlocal worker_context
        caller=cpu.context_save()
        if worker_context is None:
            cpu.reg_write(arm.UC_ARM_REG_SP,worker_sp)
            cpu.reg_write(arm.UC_ARM_REG_LR,STOP)
            pc=created[-1]
        else:
            cpu.context_restore(worker_context)
            pc=cpu.reg_read(arm.UC_ARM_REG_PC) | ((cpu.reg_read(arm.UC_ARM_REG_CPSR)>>5)&1)
        waited[0]=0
        cpu.emu_start(pc,STOP,count=20_000_000)
        at=cpu.reg_read(arm.UC_ARM_REG_PC)
        assert at in (wait,STOP),hex(at)
        worker_context=cpu.context_save()
        cpu.context_restore(caller)
        return at
    dma=LAYOUTS["705J140"]
    cpu.mem_map(DMAC,4096)
    cpu.reg_write(arm.UC_ARM_REG_R4,DMAC)
    cpu.reg_write(arm.UC_ARM_REG_R5,288)
    cpu.emu_start(0x200fef1c+offset,0x200fef40+offset)
    banks=[struct.unpack("<III",cpu.mem_read(DMAC+0x100+i*12,12)) for i in range(2)]
    assert banks==[(0x20400a40,0xe820b018,288),(0x20400b60,0xe820b018,288)]
    def play(b):
        put(DMAC+0x124,0x41 if b else 0xc1)
        invoke(0x200ffd48+offset)
        slots=struct.unpack("<72i",cpu.mem_read(banks[b][0],288))
        assert not any(slots[i] for i in range(72) if i%12)
        return struct.pack("<6h",*(v>>16 for v in slots[::12]))
    def core_word(name): return word(base+cs[name]-link)
    if digital:
        for requested in range(2,mode+1):
            assert invoke(sy["dmr_rx_set_enabled"],requested)==1
            assert word(sy["switching"]) and stat()[0]==requested
            pump()
            assert not word(sy["switching"]) and core_word("digital_mode")==requested
        assert len(created)==1 and len(live)==1
    # Actual native audio task call site, previously connected to the APRS manager.
    hook=0x200d4f74+offset
    branch=word(hook)
    assert branch>>24==0xeb
    step=hook+8+4*(((branch&0xffffff)^0x800000)-0x800000)
    captured=bytearray()
    wire=bytearray()
    phases=set()
    playback_runs=[]
    first=None
    native_priority_checked=False
    # The field recording's long second PTT lasts from about 2 to 12 seconds.
    # Leave while there is queued speech, tune across vacant channels, then
    # restore only the live tail. No header or stored samples are replayed.
    leave,back=(4000,4560) if field else (2100,2300)
    center=word(0x20380714)
    resumed=None
    fine_audio=0
    lamp_test=field and not stress and "dmr_rx_lamp" in sy
    lamp_runs=[]
    raw_changes=0
    previous_raw=None
    preference_checked=False
    if lamp_test:
        from tools.replay_705_aprs_task import e140_rom
        panel_led=e140_rom(0x200611d0) if region=="E" else 0x200611d0
        cpu.mem_map(0xfcfe3000,4096)
        cpu.mem_write(0x203e1b30+0x37e,b"\1")
        def lamp(carrier,enabled=True):
            cpu.mem_write(0x203eae3a,bytes([enabled]))
            cpu.mem_write(0x203e1b30+0x2fa,bytes([carrier]))
            invoke(panel_led)
            assert cpu.mem_read(0x20380273,1)==bytes([carrier])
            return cpu.mem_read(0x203e1b30+0x2ad,1)[0]&3
    for i in range(0,len(samples),FRAMES):
        block=i//FRAMES
        if lamp_test:
            now=(0xfffff900+block*3//4)&0xffffffff
            put(0x20381e08,now)
        rx=samples[i:i+FRAMES]
        if retune:
            if leave<=block<back:
                put(0x20380714,center+12500*(1+(block-leave)//40))
                rx=np.zeros(FRAMES,dtype=np.int16)
            elif block>=back:
                put(0x20380714,center+(0,100,300,500,200,-200,-400)[((block-back)//20)%7])
            if lamp_test and block==leave:
                assert lamp(1)==0
        completed(cpu,dma["rec_dma"]+offset,DMAC+0xe4,dma["rec_bank"],block,
                  rx.tolist(),(0,)*FRAMES,timeout_us=0)
        invoke(step)
        if block%4==0:
            pump()
            phases.add(stat()[1])
        if lamp_test and block%8==0:
            # Drive the stock panel carrier indication on/off every 30 ms.
            raw=(block//40)&1
            raw_changes+=previous_raw is not None and raw!=previous_raw
            previous_raw=raw
            lit=lamp(raw)
            if lit:
                assert stat()[1]==2 and not (retune and leave<=block<back)
                if lamp_runs and lamp_runs[-1][1]==block:
                    lamp_runs[-1][1]+=8
                else:
                    lamp_runs.append([block,block+8])
                if not preference_checked:
                    assert lamp(1,False)==0 and lamp(0)==1
                    put(0x20381e08,(word(sy["voice_tick"])+241)&0xffffffff)
                    assert lamp(1)==0
                    put(0x20381e08,now)
                    assert lamp(0)==1
                    preference_checked=True
        before=core_word("consumed")
        if not native_priority_checked and core_word("produced")>before:
            # Keep valid voice queued while the factory plays one native block.
            marker=struct.pack("<6h",211,-212,213,-214,215,-216)
            cpu.mem_write(SP-0x1000,marker)
            invoke(0x200ff4d8+offset,SP-0x1000)
            played=word(sy["status"]+32)
            assert play(block%2)==marker
            assert core_word("consumed")==before and word(sy["status"]+32)==played
            native_priority_checked=True
        chunk=play(block%2)
        emitted=core_word("consumed")-before
        assert 0<=emitted<=6
        if retune and leave<=block<back:
            assert not emitted and chunk==bytes(12),(block,emitted)
        if retune and block>=back and emitted:
            if resumed is None:
                resumed=block
                assert stat()[1]==2,stat()
                if field: assert stat()[2:]==(6,4601205,9),stat()
                if mode==3: assert stat()[2:]==(0x293,1,1),stat()
            fine_audio+=emitted
        if emitted:
            if first is None: first=block
            if playback_runs and playback_runs[-1][1]==block*6:
                playback_runs[-1][1]+=emitted
            else:
                playback_runs.append([block*6,block*6+emitted])
            captured.extend(chunk[:emitted*2])
        wire.extend(chunk)
    pump()
    if lamp_test:
        assert len(lamp_runs)==(3 if retune else 2) and preference_checked and raw_changes>300,lamp_runs
        assert lamp_runs[-1][1]<len(samples)//36 and lamp(1)==0
        cpu.mem_write(0x203806f4,b"\x80")
        cpu.mem_write(0x203809a1,b"\x50")
        assert lamp(0)==2
        cpu.mem_write(0x203806f4,b"\0")
        cpu.mem_write(0x203809a1,b"\x40")
        label="rx-led-retune" if retune else "rx-led"
        led_report=dict(dat_sha256=meta["sha256"],lit_intervals_ms=[[a*.75,b*.75] for a,b in lamp_runs],
                        alternating_carrier_transitions=raw_changes,preference_off_and_tx_red=True,
                        stalled_worker_timeout_ms=240,stock_carrier_independent=True)
    assert core_word("written")==len(samples)//36, (core_word("written"),len(samples)//36)
    if retune:
        assert first is not None and first<leave and resumed is not None and resumed-back<1500,(first,resumed,back)
        assert fine_audio>=2400 and len(created)==1 and stat()[0]==mode,(fine_audio,stat())
        assert np.max(np.abs(np.frombuffer(captured[-2*fine_audio:],"<i2").astype(int)))>200
        assert not invoke(sy["dmr_rx_set_enabled"],0) and pump()==STOP and not live
        if lamp_test:
            assert [lamp(i) for i in (1,0,1)]==[1,0,1]
            (folder/(label+".json")).write_text(json.dumps(led_report,indent=2))
        label="dmr" if field else digital[1]
        result=dict(dat_sha256=meta["sha256"],card_sha256=meta["card_sha256"],single_worker=True,
                    muted_off_channel=True,reacquired_ms=(resumed-back)*0.75,
                    fine_tuning_samples=fine_audio,fixture=label)
        (folder/("retune-"+label+".json")).write_text(json.dumps(result,indent=2))
        print(region,result,flush=True)
        return
    if digital:
        fixture,expected=digital[1:]
        assert native_priority_checked and 2 in phases
        assert bytes(captured)==playback_reference(expected)
        assert core_word("consumed")==core_word("produced")==len(expected)//2
        pos=core_word("produced")
        put(base+cs["produced"]-link,pos+6)
        cpu.mem_write(base+cs["queue"]-link+2*(pos%2048),struct.pack("<6h",*([1000]*6)))
        assert invoke(sy["dmr_rx_set_enabled"],1)
        assert play(0)==bytes(12) and core_word("consumed")==pos
        pump()
        assert core_word("digital_mode")==1 and core_word("consumed")==pos+6
        assert not invoke(sy["dmr_rx_set_enabled"],0) and pump()==STOP and not live
        result=dict(dat_sha256=meta["sha256"],fixture=fixture,samples=len(captured)//2,runs=playback_runs,
                    native_dma_matches_card_gain=True,native_playback_priority=True,worker_retired=True)
        (folder/(fixture+"-dma.json")).write_text(json.dumps(result,indent=2))
        print(result,flush=True)
        return
    expected_status=(1,3,6,4601205,9) if field else (1,3,7,1234567,3100)
    assert stat()==expected_status,stat()
    input_blocks, varying_blocks=struct.unpack("<2I",cpu.mem_read(sy["status"]+20,8))
    assert input_blocks==len(samples)//36 and 0<varying_blocks<=input_blocks
    expected_samples=field_repeats*522*160 if field else len(reference)//2
    assert {0,2,3}<=phases and core_word("produced")==core_word("consumed")==expected_samples
    panel_audio=struct.unpack("<2I",cpu.mem_read(sy["status"]+28,8))
    assert panel_audio==(expected_samples,expected_samples), panel_audio
    assert first is not None and native_priority_checked
    start=first*12
    has_alerts="digital_alert" in cs
    adjusted=meta.get("dmr_playback_gain")==2
    gain_report={}
    if field:
        # The file has two distinct calls. Preserve their separation in the DMA recording.
        assert not any(wire[:start]) and len(captured)==2*expected_samples
        if adjusted and not stress:
            previous=ROOT/".analysis/dmr-rx6-worker/final"/region/"dmr-received-field.wav"
            with wave.open(str(previous),"rb") as wav:
                original=wav.readframes(wav.getnframes())
            if has_alerts: original=reference_alert(original,[a for a,b in playback_runs])
            assert bytes(wire)==playback_reference(original)
            old=np.frombuffer(original,"<i2").astype(float)
            new=np.frombuffer(wire,"<i2").astype(float)
            gain_report=dict(before_peak=int(np.max(abs(old))),after_peak=int(np.max(abs(new))),
                             rms_gain_db=float(10*np.log10(np.sum(new**2)/np.sum(old**2))),
                             compressed_samples=int(np.count_nonzero(abs(old)>12288)))
    else:
        if has_alerts: reference=reference_alert(reference,[0])
        if adjusted: reference=playback_reference(reference)
        assert bytes(captured)==reference
        assert wire[start:start+len(reference)]==reference, "DMA playback contained gaps during speech"
        assert not any(wire[:start]) and not any(wire[start+len(reference):])
    final=stat()
    if stress:
        painted=bytes(cpu.mem_read(worker_stack-monitor_bytes,monitor_bytes+cold["stack_size"]))
        painted=painted[:monitor_bytes]+b"\xa5"*4+painted[monitor_bytes+4:]
        untouched=next(i for i,v in enumerate(painted) if v!=0xa5)
        stats=dict(dat_sha256=meta["sha256"],region=region,calls=2*field_repeats,
                   input_blocks=input_blocks,voice_frames=expected_samples//160,
                   playback_samples=panel_audio[1],stack_base=hex(worker_stack),
                   stack_size=cold["stack_size"],observed_stack_writes_span=len(painted)-untouched,
                   stack_sentinel_and_lower_guard_intact=not first_crossing and word(worker_stack)==0xe25a2ea5,
                   first_crossing=first_crossing,codec_arena_peak=core_word("dmr_audio_heap_peak"),
                   payload_base=hex(base),scope="Real packaged code, repeated recorded calls. Cooperative simulated scheduling, without board IRQ preemption, LCD or IF DSP.")
    if adjusted and not field and not highpass:
        # Drive full-scale samples and both knees through the installed DMA callback.
        src=(-32768,-12289,-12288,0,12288,32767)
        pos=core_word("consumed")
        for idx,value in enumerate(src):
            cpu.mem_write(base+cs["queue"]-link+2*((pos+idx)%(2048 if has_alerts else 1024)),struct.pack("<h",value))
        put(base+cs["produced"]-link,pos+6)
        assert play(0)==struct.pack("<6h",-29696,-24576,-24576,0,24576,29695)
    assert not invoke(sy["dmr_rx_set_enabled"],0) and pump()==STOP and not live
    if lamp_test:
        assert [lamp(i) for i in (1,0,1)]==[1,0,1]
        (folder/(label+".json")).write_text(json.dumps(led_report,indent=2))
    assert word(sy["thread_id"])==0 and word(sy["image"])==0 and len(freed)==4
    assert play(0)==bytes(12)
    if stress:
        (folder/"freeze-stress.json").write_text(json.dumps(stats,indent=2)+"\n",encoding="utf-8")
        print(region,stats,flush=True)
        assert stats["stack_sentinel_and_lower_guard_intact"], stats
        return
    suffix="-field" if field else f"-hp{highpass}" if highpass else ""
    with wave.open(str(folder/f"dmr-received{suffix}.wav"),"wb") as wav:
        wav.setparams((1,2,8000,0,"NONE",""))
        wav.writeframes(wire if field else captured)
    result=dict(dat_sha256=meta["sha256"],card_sha256=meta["card_sha256"],blocks=len(samples)//36,
                clear_call_status=list(final),phases=sorted(phases),pcm_samples=expected_samples,
                input_blocks=input_blocks,varying_blocks=varying_blocks,panel_audio_samples=panel_audio,
                native_playback_priority_checked=native_priority_checked,
                voice_frames=expected_samples//160,first_output_dma_block=first,
                pcm_sha256=sha256(captured).hexdigest(),heap_address=hex(base),
                sd_error_states=error_states,exit_freed=True,
                emulated="48 kHz discriminator input, card/heap/RTX scheduling; original SSIF0 DMA, packaged code and worker")
    if gain_report: result["playback_gain"]=gain_report
    if not field: result["gaps"]=0
    if field: result["playback_runs_at_8khz"]=playback_runs
    if field: result["dmr_monitor_checked_under_open_squelch"]=monitor_checked
    if field: result["input"]="705 SD WAV, SHA-256 1d652acae9a071c13ae6e56fcd42789110df82bd8e0afd695cfa358ddd95d5a4; resampled at 48 kHz"
    if highpass: result["synthetic_input_filter"]=f"Butterworth high-pass order 1 at {highpass} Hz, then low-pass order 2 at 3000 Hz"
    (folder/f"station-air{suffix}.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(region,result,flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("region",nargs="*",choices=["J","E"])
    parser.add_argument("--digital",choices=["ysf","p25p1_c4fm_vc"])
    parser.add_argument("--retune",action="store_true",help="Leave and rejoin the same ongoing call during a dial sweep")
    parser.add_argument("--highpass",type=int,choices=(200,250,300),default=0)
    parser.add_argument("--field-wav",type=Path,help="Known DMR field recording for regression")
    parser.add_argument("--field-repeats",type=int,default=1,help="Repeat the field recording in one receiver session and measure its worker stack")
    parser.add_argument("--package-dir",type=Path,default=OUT,help="Use the named build with its matching payload and cold UI evidence")
    args=parser.parse_args()
    if args.retune and (not (args.field_wav or args.digital) or args.field_repeats!=1):
        parser.error("--retune requires a field WAV or digital IQ fixture")
    if args.digital:
        from tools.verify_705_dmr_multimode import discriminator as iq_pcm, UP
        name=args.digital
        samples=iq_pcm(UP/"tests/fixtures/iq"/(name+".iq"))
        samples=np.pad(samples,(0,24012+(-len(samples))%36))
        with wave.open(str(OUT/(name+".wav")),"rb") as f: expected=f.readframes(f.getnframes())
        for r in args.region or ["J","E"]:
            bench(r,samples,None,package_dir=args.package_dir,
                  digital=(2 if name=="ysf" else 3,name,expected),retune=args.retune)
        sys.exit(0)
    if args.field_repeats<1 or (args.field_repeats>1 and not args.field_wav):
        parser.error("--field-repeats must be positive and requires --field-wav for stress runs")
    if args.field_wav:
        from scipy.signal import resample_poly
        assert not args.highpass and sha256(args.field_wav.read_bytes()).hexdigest()=="1d652acae9a071c13ae6e56fcd42789110df82bd8e0afd695cfa358ddd95d5a4"
        with wave.open(str(args.field_wav),"rb") as wav:
            assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(8000,1,2)
            raw=np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2")
        samples=np.rint(resample_poly(raw.astype(float),6,1)).clip(-32768,32767).astype("<i2")
        samples=np.pad(samples,(0,(-len(samples))%36+5760))
        for r in args.region or ["J","E"]: bench(r,samples,None,field=True,field_repeats=args.field_repeats,package_dir=args.package_dir,retune=args.retune)
        sys.exit(0)
    source=(HERE/"dmr-reference/voice9.bin").read_bytes()
    padded=source+source[-9:]
    from tools.probe_705_dmr_rx import transform
    expected=transform(padded,encode=False)[0]
    with wave.open(str(HERE/"dmr-reference/reference.wav"),"rb") as wav:
        assert expected[:len(source)//9*320]==wav.readframes(wav.getnframes())
    samples=discriminator(render_if(mobile_call(padded)))
    if args.highpass:
        from scipy.signal import butter,sosfilt
        filtered=sosfilt(butter(1,args.highpass,fs=48000,btype="high",output="sos"),samples)
        samples=np.rint(sosfilt(butter(2,3000,fs=48000,output="sos"),filtered)).astype("<i2")
    samples=np.pad(samples,(0,(-len(samples))%36+2880*2))
    for r in args.region or ["J","E"]:
        bench(r,samples,expected,highpass=args.highpass,package_dir=args.package_dir)
