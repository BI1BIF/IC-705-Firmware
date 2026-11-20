"""Run the J140 Robot 36 A32 receiver from stock simulated SSI0 DMA to the native LCD."""
import argparse
from array import array
from hashlib import sha256
from io import BytesIO
import json
import os
from math import cos, pi, sin
from pathlib import Path
import shutil
from struct import pack, unpack
import subprocess
import sys
from unittest.mock import patch
import wave

from PIL import Image
from tools import render_705_stock_row as renderer
from tools.emulate_705 import call
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC, LAYOUTS, completed
from tools.probe_705_sstv_picture import SSTV, RX_IMAGE, branch, enter, frame, install_guest_picker, tick
from tools.render_705_display import load
from tools.render_705_stock_row import require
from tools.replay_705_settings import SettingsGuest

BASE = 0x21100000
SIZE = 0x40000
LAYOUT = LAYOUTS["705J140"]
ROOT = Path(__file__).resolve().parents[1]
FIELDS = "active offered dropped processed peak locks rows samples phase mode".split()


def counters(cpu,sym):
    return dict(zip(FIELDS,unpack("<10I",cpu.mem_read(sym["counts"],40))))


def martin_audio(path):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    data,rate=sf.read(path,always_2d=True)
    divisor=gcd(rate,48000)
    mono=resample_poly(data.mean(axis=1),48000//divisor,rate//divisor)
    samples=array("h",np.rint(mono*27000/max(abs(mono))).astype(np.int16).tobytes())
    samples.extend([0]*(-len(samples)%36))
    return samples


def build(folder, compiler, *, base=BASE, limit=BASE+SIZE, cw_pcm=None, diagnostics=False, robot_sync=False, basic=False, late_join=False, tx_study=False, bss_address=None):
    folder.mkdir(parents=True, exist_ok=True)
    cc = Path(shutil.which(str(compiler)) or compiler).resolve()
    tool = lambda name: str(cc.with_name(name+cc.suffix))
    thresholds = [round(16384*cos(2*pi*(855+10*i)/8000)) for i in range(256)]
    (folder/"sstv_cosine.h").write_text("static const short cosine_threshold[] = {"
                                        + ",".join(map(str,thresholds)) + "};\n")
    script = folder/"rx.ld"
    script.write_text(f"SECTIONS {{ . = {base:#x}; .text : {{ *(.text*) }} .rodata : {{ *(.rodata*) }} "
                      ".data : { *(.data*) } " + (f". = {bss_address:#x}; " if bss_address else "") + ".bss : { *(.bss*) *(COMMON) } end_rx = .; "
                      "/DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) } }")
    elf = folder/"rx.elf"
    extra=[] if cw_pcm is None else ["-DSSTV_DEVICE",
                                      f"-Wl,--defsym,sstv_d6_pcm={cw_pcm:#x}"]
    if diagnostics:
        extra.append("-DSSTV_RX_DIAG")
    if robot_sync:
        extra.append("-DSSTV_ROBOT_SYNC")
    if basic:
        extra.append("-DSSTV_BASIC")
    if late_join:
        extra.append("-DSSTV_LATE_JOIN")
    if tx_study:
        extra.append("-DSSTV_TX_STUDY")
    subprocess.run([str(cc),*extra,"--target=arm-none-eabi","-mcpu=cortex-a9","-marm","-mfloat-abi=soft",
                    "-O2","-ffreestanding","-fno-builtin","-nostdlib","-fuse-ld=lld",
                    "-Wl,-e,sstv_open",f"-Wl,-T,{script}","-I",str(folder),
                    str(ROOT/"samples/sstv-j140-rx.c"),"-x","assembler-with-cpp",str(ROOT/"samples/sstv-j140-rx.s"),
                    "-o",str(elf)],check=True,
                   env={**os.environ, **dict.fromkeys(("TMPDIR","TEMP","TMP"), str(folder.resolve()))})
    symbols = {}
    for line in subprocess.check_output([tool("llvm-nm"),str(elf)],text=True).splitlines():
        parts=line.split()
        if len(parts)==3:
            symbols[parts[2]]=int(parts[0],16)
    require(base < symbols["end_rx"] <= limit, "receiver outside link region")
    binary=folder/"rx.bin"
    subprocess.run([tool("llvm-objcopy"),"-O","binary",str(elf),str(binary)],check=True)
    return binary.read_bytes(),symbols


def replay(images, binary, sym, wav, original, out, martin=None, *, installed=None):
    with patch.object(renderer,"HEAP_START",0x20700000):
        g=SettingsGuest(images,front_panel=True)
    # The allocator's end bound still applies to later operations.
    cpu=g.cpu
    cpu.mem_write(g.language_address,bytes(2))
    cpu.mem_map(DMAC,0x1000)
    def redirect(site, expected, name):
        require(cpu.mem_read(site,4)==pack("<I",expected), f"unexpected instruction at {site:#x}")
        cpu.mem_write(site,pack("<I",branch(site,sym[name])))
    if installed is None:
        install_guest_picker(g,images[0])
        cpu.mem_map(BASE,SIZE)
        cpu.mem_write(BASE,binary)
        redirect(SSTV,0xe92d4010,"sstv_open")
        redirect(0x2010feac,0xe3a04000,"sstv_pcm_hook")
        redirect(0x2013c5e8,0xe92d5ff0,"sstv_frame_hook")
        redirect(0x2018e838,0xe59f4430,"sstv_image_hook")
        redirect(0x2018f818,0xe5d4001d,"sstv_thumbnail_hook")
        for site in (0x2018fd0c,0x201911d0,0x20191268):
            require(cpu.mem_read(site,4)==pack("<I",branch(site,0x20142698,0xeb000000)),
                    "unexpected Picture metadata draw")
            cpu.mem_write(site,pack("<I",branch(site,sym["sstv_picture_label"],0xeb000000)))
    else:
        installed(g)

    def canvas():
        if installed is None:
            return sym["image"]
        return int.from_bytes(cpu.mem_read(sym["pixels"],4),"little")
    cpu.mem_write(AUDIO_GATE,b"\1")
    require(cpu.mem_read(LAYOUT["rec_enable"],1)==b"\0","expected recorder off")
    with wave.open(str(wav)) as source:
        require((source.getframerate(),source.getnchannels(),source.getsampwidth())==(48000,1,2),"48 kHz PCM required")
        samples=array("h",source.readframes(source.getnframes()))
    if sys.byteorder!="little":
        samples.byteswap()
    require(len(samples)%36==0,"fixture must end on a DMA boundary")
    total=len(samples)//36
    ref=Image.open(original).convert("RGB")
    require(ref.size==(320,240),"expected Robot 36 reference")
    reference=ref.tobytes()
    def stats():
        return counters(cpu,sym)
    def open_rx():
        enter(g)
        require("SSTV" in frame(g)[0],"selector missing")
        g.click(115,116)
        tick(g)
        labels, screen=frame(g)
        require(g.state()["menu"]==21 and "SSTV AUTO" in labels and stats()["active"],"SSTV half panel missing")
        (out/"half-entry.png").write_bytes(screen)
        return screen
    def switch_view(menu):
        before=stats()
        if menu==274:
            require(g.click(60,193)==0x170,"RX thumbnail missed")
        else:
            g.press_exit()
        tick(g)
        require(g.state()["menu"]==menu,"unexpected Picture navigation")
        require(stats()==before and before["active"],"switching view reset reception")
    dma_number=0
    def feed(first, stop, source=None):
        nonlocal dma_number
        if source is None: source=samples
        for block in range(first,stop):
            left=source[36*block:36*(block+1)]
            completed(cpu,LAYOUT["rec_dma"],DMAC+0xe4,LAYOUT["rec_bank"],dma_number,left,(0,)*36,timeout_us=0)
            call(cpu,LAYOUT["rec_consume"],timeout_us=0)
            dma_number+=1
    def drain():
        call(cpu,sym["sstv_worker"],instruction_limit=2_000_000,timeout_us=0)
    def leave():
        g.press_exit()
        tick(g)
        frame(g)
        require(g.state()["menu"]==0 and not stats()["active"],"EXIT did not detach decoder")
        if installed:
            require(canvas()==0,"EXIT retained the private SSTV canvas")
    def capture(count):
        menu=g.state()["menu"]
        labels,screen=frame(g)
        lcd=Image.frombytes("RGBA",(480,272),bytes(g.surface.pixels)).convert("RGB")
        if menu==274:
            require({"RX PICTURE","Robot 36","320 x 240"}.issubset(labels),"wrong Robot 36 detail metadata")
            rgb=lcd.crop((4,28,324,268)).tobytes()
            visible=count*320*3
            mae=sum(abs(x-y) for x,y in zip(rgb[:visible],reference[:visible]))/visible
            require(mae<7 and not any(rgb[visible:]),f"incorrect LCD after {count} rows: {mae=}")
            name=f"rx-{count}.png"
        else:
            require(menu==21 and "Robot 36" in labels,"missing Robot 36 mode label")
            # VG samples the center of each 2x2 cell. The RX badge overlays
            # the bottom-left corner, so compare identical 132-column strips.
            preview=lcd.crop((31,150,163,270))
            rgb=preview.tobytes()
            reduced=ref.resize((160,120),Image.Resampling.NEAREST).crop((28,0,160,120)).tobytes()
            visible=count//2*132*3
            mae=sum(abs(x-y) for x,y in zip(rgb[:visible],reduced[:visible]))/visible
            require(mae<8 and not any(rgb[visible:]),f"incorrect thumbnail after {count} rows: {mae=}")
            require(control_pixels(lcd)==tx_controls,"TX/control area changed during RX")
            name=f"half-{count}.png"
        (out/name).write_bytes(screen)
        return dict(rows=count,menu=menu,file=name,rgb_mae=round(mae,4),sha256=sha256(screen).hexdigest())
    def run_blocks(n, checkpoints=()):
        screens=[]
        next_check=iter(checkpoints)
        target=next(next_check,None)
        for start in range(0,n,18):
            feed(start,min(n,start+18))
            drain()
            count=stats()["rows"] & ~1
            if target is None or count<target:
                continue
            require(count==target,"missed LCD checkpoint")
            screens.append(capture(count))
            switch_view(274 if g.state()["menu"]==21 else 21)
            screens.append(capture(count))
            target=next(next_check,None)
        require(target is None,"incomplete display checkpoints")
        return screens
    stock=bytes(cpu.mem_read(RX_IMAGE,153600))
    diagnostic="displayed_peak" in sym
    def control_pixels(lcd):
        tile=lcd.crop((165,168,480,272))
        if diagnostic:
            # Only the text inside the two diagnostic buttons may change.
            tile.paste(0,(168,10,250,41))
            tile.paste(0,(168,60,250,93))
        return tile.tobytes()
    entry=open_rx()
    tx_controls=control_pixels(Image.open(BytesIO(entry)).convert("RGB"))
    switch_view(274)
    require("RX PICTURE" in frame(g)[0],"empty RX tile must open")
    switch_view(21)
    require(frame(g)[1]==entry,"empty RX return differs from half panel")
    require(g.click(230,193)==0x171,"TX thumbnail missed")
    tick(g)
    require("No SD Card is found." in frame(g)[0],"missing native TX no-card message")
    g.press_exit()
    tick(g)
    require(frame(g)[1]==entry and stats()["active"],"TX dialog EXIT failed")
    checks={}
    if diagnostic:
        def assert_status(expected):
            labels,screen=frame(g)
            if "sstv_tx_mod_block" in sym and (expected in ("NO PCM","QUEUE") or expected.startswith("P ")):
                require("SEND" in labels and expected not in labels,str(labels))
                return
            require(expected in labels,f"{expected} missing from field diagnostics: {labels}")
            checks[expected]=True
        assert_status("NO PCM")
        quiet=array("h",[0])*36
        feed(0,1,quiet)
        assert_status("QUEUE")
        drain()
        assert_status("P 0")
        tone_blocks=array("h",[700])*36*18
        for start in range(0,511,18):
            feed(0,min(511-start,18),tone_blocks)
            drain()
        assert_status("P 700")
        feed(0,33)
        assert_status("GAP")
        leave()
        open_rx()
        assert_status("NO PCM")
    run_blocks(5000)
    partial=stats()
    require(0<partial["rows"]<240,"partial receive was not established")
    feed(5000,5003)  # Leave with three blocks queued.
    leave()
    before=stats()
    feed(5003,5011)
    drain()
    require(stats()==before,"inactive session consumed audio")
    open_rx()
    require(not any(stats()[f] for f in FIELDS if f!="active"),"new session inherited counters")
    screens=run_blocks(total,(60,120,180,240))
    final=stats()
    require(final["locks"]==1 and final["rows"]==240 and final["phase"]==2 and final["dropped"]==0
            and total==final["offered"]==final["processed"] and final["samples"]==6*total,"incomplete RX")
    image_digest=sha256(cpu.mem_read(canvas(),153600)).hexdigest()
    sequences={}
    if martin:
        import numpy as np
        from tools.emulate_705 import uc
        m1=martin_audio(martin)
        m1_ref=np.asarray(Image.open(martin.with_suffix(".png")).convert("RGB"),dtype=float)
        def receive_martin(prefix):
            next_row=80
            before=stats()
            # Check the first pixel write on each bottom scanline. The fixture
            # ends in a dark band, which alone cannot distinguish a crop.
            bottom_rows={}
            canvas_base=canvas()
            def bottom_write(cpu,access,address,size,value,user):
                offset=address-canvas_base
                if offset%640==0:
                    bottom_rows[stats()["rows"]]=offset//640
            hook=cpu.hook_add(uc.UC_HOOK_MEM_WRITE,bottom_write,begin=canvas_base+225*640,
                              end=canvas_base+240*640-1)
            for start in range(0,len(m1)//36,24):
                feed(start,min(start+24,len(m1)//36),m1)
                drain()
                state=stats()
                if state["mode"]==44 and state["rows"]==next_row and next_row<=160:
                    switch_view(274 if next_row==80 else 21)
                    labels,screen=frame(g)
                    require("Martin M1" in labels and (next_row!=80 or "320 x 256" in labels),"M1 view mismatch")
                    (out/f"{prefix}-{next_row}.png").write_bytes(screen)
                    next_row+=80
            cpu.hook_del(hook)
            require(all(bottom_rows.get(y)==y*240//256 for y in range(240,256)),
                    "at least one of the final 16 source lines was not mapped to the LCD")
            state=stats()
            print(prefix,state,flush=True)
            require(next_row==240 and state["phase"]==2 and state["rows"]==256 and state["mode"]==44
                    and state["locks"]==2 and state["dropped"]==0,"incomplete M1 sequence")
            labels,screen=frame(g)
            require("Martin M1" in labels and g.state()["menu"]==21,"wrong final mode")
            (out/f"{prefix}-half.png").write_bytes(screen)
            switch_view(274)
            labels,screen=frame(g)
            require({"Martin M1","320 x 256"}.issubset(labels),"wrong M1 detail metadata")
            (out/f"{prefix}-detail.png").write_bytes(screen)
            actual=np.asarray(Image.open(BytesIO(screen)).convert("RGB"),dtype=float)[28:268,4:324]
            # The streaming renderer keeps the last source row mapped to each LCD row.
            expected=m1_ref[((np.arange(240)+1)*256-1)//240]
            mae=np.abs(actual-expected).mean(axis=(1,2))
            print(prefix,"RGB MAE",mae.mean(),"bottom",mae[-15:].mean(),flush=True)
            require(mae.mean()<30 and mae[-15:].mean()<35,"M1 image differs from independent reference")
            switch_view(21)
            frame(g)
            return dict(previous=before,final=state,rgb_mae=float(mae.mean()),bottom_mae=float(mae[-15:].mean()),
                        last_source_row=255,last_lcd_row=bottom_rows[255],
                        rgb565_sha256=sha256(cpu.mem_read(canvas(),153600)).hexdigest())
        sequences["complete_then_martin"]=receive_martin("complete-then-m1")
        leave()
        open_rx()
        run_blocks(5000)
        interrupted=stats()
        silence=array("h",[0])*(36*800)
        for start in range(0,800,20):
            feed(start,start+20,silence)
            drain()
        if "sstv_tx_mod_block" in sym:
            require(stats()["phase"]==1 and stats()["rows"]>interrupted["rows"],"fade reset the frame")
        else:
            require(interrupted["phase"]==1 and stats()["phase"]==3,"truncation did not lose sync")
            require("SSTV AUTO" in frame(g)[0],"interruption did not restore AUTO indicator")
            if diagnostic:
                assert_status("SYNC" if "robot_loss" in sym else "LOST")
        sequences["interrupted_then_martin"]=receive_martin("interrupted-then-m1")
        require(sequences["complete_then_martin"]["rgb565_sha256"]==
                sequences["interrupted_then_martin"]["rgb565_sha256"],"reacquisition image differs")
        # Feed full leaders, start/stop and first sync with either bad parity
        # or an unsupported but valid VIS. Neither may erase the last picture.
        unsupported=15 if "basic_modes" in sym else 12
        for code,parity in ((8,0),(unsupported,0)):
            bits=[(code>>i)&1 for i in range(7)]+[parity]
            tones=[(1900,300),(1200,10),(1900,300),(1200,30)]
            tones += [(1100 if bit else 1300,30) for bit in bits]
            tones += [(1200,39),(1500,48)]
            header=array("h",(round(14000*sin(2*pi*f*i/48000)) for f,ms in tones for i in range(ms*48)))
            header.extend([0]*(-len(header)%36))
            for start in range(0,len(header)//36,18):
                feed(start,min(start+18,len(header)//36),header)
                drain()
            require(stats()["locks"]==2 and stats()["mode"]==44 and stats()["rows"]==256 and
                    sha256(cpu.mem_read(canvas(),153600)).hexdigest()==
                    sequences["interrupted_then_martin"]["rgb565_sha256"],"invalid or unsupported VIS replaced image")
            if diagnostic:
                assert_status("PARITY" if code==8 else f"VIS {unsupported}")
        sequences["rejected_vis"]=["Robot 36 with invalid parity",f"unsupported VIS {unsupported} with valid parity"]
        sequences["martin_ogg_sha256"]=sha256(martin.read_bytes()).hexdigest()
    if diagnostic:
        sequences["diagnostics"]=checks
    leave()
    open_rx()
    feed(0,40)
    drain()
    overload=stats()
    require(overload["dropped"]==8 and overload["peak"]==32 and overload["phase"]==3,"overrun was not detected")
    leave()
    require(cpu.mem_read(RX_IMAGE,153600)==stock,"DV image buffer changed")
    enter(g)
    require("DV" in frame(g)[0],"missing DV selector after SSTV")
    g.click(115,52)
    tick(g)
    native_labels,dv_screen=frame(g)
    require("PICTURE" in native_labels and "SSTV AUTO" not in native_labels and not stats()["active"],
            "DV re-entry retained SSTV title or active decoder")
    require(g.click(60,193)==0x170,"DV RX touch missed")
    tick(g)
    require("RX PICTURE" in frame(g)[0] and g.state()["menu"]==274 and not stats()["active"],
            "DV detail inherited the SSTV session")
    g.press_exit()
    tick(g)
    require(g.state()["menu"]==21 and frame(g)[1]==dv_screen,"DV detail did not return to PICTURE")
    require(cpu.mem_read(LAYOUT["rec_enable"],1)==b"\0","recorder setting changed")
    return dict(source=wav.name,firmware_main_sha256=sha256(images[0] if installed is None else binary).hexdigest(),
                pcm48_sha256=sha256(wav.read_bytes()).hexdigest(),code_sha256=sha256(binary).hexdigest(),
                code_bytes=len(binary),guest_bytes=sym["end_rx"]-sym.get("sstv_link_base",BASE),
                partial=partial,queued_at_exit=before["offered"]-before["processed"],reopened=final,
                checkpoints=screens,overload=overload,dv_buffer_unchanged=True,sequences=sequences,
                empty_detail_returns=True,tx_no_card_returns=True,dv_reentry=True,
                image_rgb565_sha256=image_digest,
                scheduling="Host supplies simulated DMA and polls the ARM worker after up to 24 blocks in normal reception")


def scheduler_replay(main, binary, sym, wav, expected_image, *, combined=None, from_reset=False):
    from tools.probe_705_rtx_audio import (CURRENT, DMA_TIMER, IDLE, LOOP, PCM_DONE, PCM_STEP,
                                           SEM_WAIT, TIMER, TIMERS_CLEARED, UI_HANDLE, probe)
    from tools.emulate_705 import uc
    with wave.open(str(wav)) as source:
        samples=array("h",source.readframes(source.getnframes()))
    if sys.byteorder!="little":
        samples.byteswap()

    def exercise(cpu, run, irq, sub, value):
        if combined is None:
            cpu.mem_map(BASE,SIZE)
            cpu.mem_write(BASE,binary)
            site=0x2010feac
            require(value(site)==0xe3a04000,"unexpected native PCM hook")
            cpu.mem_write(site,pack("<I",branch(site,sym["sstv_pcm_hook"])))
            cpu.ctl_remove_cache(site,site+4)
        else:
            from tools.emulate_705 import BASE as image_base
            cpu.mem_write(image_base,binary)
            cpu.ctl_remove_cache(image_base,image_base+len(binary))
        saved=cpu.context_save()
        main_thread=value(CURRENT)
        # The panel replay exercises real entry and exit. Start this separate
        # scheduler replay in the matching RX PICTURE session.
        cpu.mem_write(0x203e84c9,pack("<H",21))
        sub(sym["sstv_begin"])
        thread=value(sym["sstv_thread"])
        require(thread and thread not in (main_thread,value(UI_HANDLE)) and value(thread+2,1)==0xe9,
                "stock RTX failed to create the decoder thread")
        cpu.context_restore(saved)
        cpu.mem_write(AUDIO_GATE,b"\1")
        cpu.mem_write(0x20380874,b"\1")
        for offset in (0x124,0x424,0x524):
            cpu.mem_write(DMAC+offset,pack("<I",1))
        calls=0
        def on_worker(*_):
            nonlocal calls
            require(value(CURRENT)==thread,"decode dispatched on the wrong RTX thread")
            calls+=1
        cpu.hook_add(uc.UC_HOOK_CODE,on_worker,begin=sym["sstv_worker"],end=sym["sstv_worker"])
        def status():
            return counters(cpu,sym)
        run(TIMERS_CLEARED,PCM_STEP)
        blocks=len(samples)//36
        for first in range(0,blocks,6):
            background=PCM_STEP if first==0 else IDLE
            for block in range(first,min(first+6,blocks)):
                bank=block&1
                left=samples[36*block:36*(block+1)]
                words=[word for sample in left for word in ((sample&65535)<<16,0)]
                cpu.mem_write(LAYOUT["rec_bank"]+288*bank,pack("<72I",*words))
                cpu.mem_write(DMAC+0xe4,pack("<I",0x41 if bank else 0xc1))
                irq(DMA_TIMER,background)
            cpu.mem_write(DMAC+0xe4,pack("<I",1))
            if first:
                for target in (IDLE,PCM_STEP):
                    irq(TIMER,IDLE)
                    irq(0,LOOP)
                    run(LOOP,target)
            run(PCM_STEP,PCM_DONE)
            if not first:
                require(value(thread+24,2)&1 and not calls,"first event not queued before thread startup")
                run(LOOP,SEM_WAIT)
                run(SEM_WAIT,IDLE,limit=2_000_000)
            else:
                run(LOOP,IDLE,limit=2_000_000)
        final=status()
        image_base=sym["image"] if combined is None else value(sym["pixels"])
        digest=sha256(cpu.mem_read(image_base,153600)).hexdigest()
        require(final["processed"]==blocks==final["offered"] and final["locks"]==1 and final["dropped"]==0
                and final["rows"]==240 and final["phase"]==2 and digest==expected_image,"RTX image mismatch")
        extra={}
        if combined is not None:
            state=value(combined["symbols"]["cw_state_anchor"])
            cw_thread=value(state+0x700) if state else 0
            require(cw_thread and cw_thread!=thread and value(cw_thread+2,1)==0xe9 and image_base%32==0,
                    "shared-scheduler CW worker or SSTV heap missing")
            extra=dict(cw_thread=hex(cw_thread),cw_state=hex(state),canvas=hex(image_base))
        return dict(**extra,thread=hex(thread),priority=value(thread+2,1),stack_bytes=value(thread+0x26,2),
                    worker_turns=calls,stats=final,image_rgb565_sha256=digest,
                    first_notification_precedes_worker_start=True)
    return probe(main,audio_experiment=exercise,application=binary if from_reset else None)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("firmware",type=Path)
    p.add_argument("wav",type=Path)
    p.add_argument("reference",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--clang",default="clang")
    p.add_argument("--martin",type=Path,help="independent m1.ogg with matching m1.png reference")
    args=p.parse_args()
    binary,sym=build(args.output/"build",args.clang)
    images=load(args.firmware.read_bytes())
    result=replay(images,binary,sym,args.wav,args.reference,args.output,args.martin)
    result["rtx"]=scheduler_replay(images[0],binary,sym,args.wav,result["image_rgb565_sha256"])
    (args.output/"evidence.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
