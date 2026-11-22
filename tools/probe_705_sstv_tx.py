"""Offline J140 TX Picture selection, native JPEG preview and SSTV PCM experiment."""
import argparse
from array import array
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from struct import pack, unpack
import sys
from unittest.mock import patch
import wave

import numpy as np
from PIL import Image
from tools import render_705_stock_row as renderer
from tools.build_705_cw_sstv_rx import D6, D6_SHA, combine
from tools.build_705_cw_sim import load_image
from tools.emulate_705 import BASE, arm, call, uc
from tools.probe_705_cw_pcm import feed_dsp_tx
from tools.probe_705_sstv_picture import enter, frame, tick
from tools.render_705_display import load, require
from tools.replay_705_settings import SettingsGuest

TX_IMAGE=0x2064b584
REQUEST=0x203e0f64
JPEG=0x20624708
COMMITTED=0x203e1038
CANVAS_BYTES=320*240*2


def rgb565(raw):
    p=np.frombuffer(raw,"<u2").astype(np.int32).reshape(240,320)
    return np.stack(((p>>11)*255//31,((p>>5)&63)*255//63,(p&31)*255//31),axis=-1)


def mount_card(cpu, directory, rom=lambda pc: pc, *, aliases=None):
    """Supply read-only file operations. The guest constructs paths and decodes JPEGs."""
    paths={f"C:\\IC-705\\Picture\\{p.name}":p for p in directory.glob("*.jpg")}
    for alias, path in (aliases or {}).items():
        paths[f"C:\\IC-705\\Picture\\{alias}"] = path
    opened=[]
    handles={}
    def service(cpu,pc,*_):
        a,b,c,d=(cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,
                                            arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3))
        pc = original[pc]
        status=0
        if pc in (0x2023fec8,0x2023ffbc):
            name=bytes(cpu.mem_read(a,64)).split(b"\0")[0].decode("ascii")
            if name not in paths: status=7
            elif pc==0x2023ffbc:
                cpu.mem_write(b+40,pack("<I",paths[name].stat().st_size))
            else:
                require(b==0 and not handles,"unexpected open or leaked descriptor")
                handles[1]=paths[name].open("rb")
                cpu.mem_write(c,pack("<I",1))
                opened.append(name)
        elif pc==0x2023ff00:
            data=handles[a].read(c)
            if data: cpu.mem_write(b,data)
            cpu.mem_write(d,pack("<I",len(data)))
        else: handles.pop(a).close()
        cpu.reg_write(arm.UC_ARM_REG_R0,status)
        cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
    original = {rom(pc):pc for pc in (0x2023fec8,0x2023ffbc,0x2023ff00,0x2023fee4)}
    for pc in original:
        cpu.hook_add(uc.UC_HOOK_CODE,service,begin=pc,end=pc)
    cpu.mem_write(0x20380172,b"\x03")  # mounted card in the isolated panel guest
    return opened,handles


def directory_ready(cpu, files, rom=lambda pc: pc):
    # Publish the native directory worker's first cache page, then run its UI notification.
    require(0<len(files)<=4,"fixture must fit one catalog page")
    for i,path in enumerate(files):
        name=path.name.encode("ascii")
        require(len(name)<=28,"picker record only has 28 filename bytes")
        record=name.ljust(28,b"\0")+pack("<B3xI",len(name),path.stat().st_size)
        cpu.mem_write(0x2039fa90+36*i,record)
    cpu.mem_write(0x20380820,pack("<I",len(files)))
    cpu.mem_write(0x203807f0,b"\0")
    call(cpu,rom(0x200eccd0),1)
    call(cpu,rom(0x200f3a10))


def decode_request(cpu, rom=lambda pc: pc):
    # Schedule the JPEG worker from the native UI request; model its asynchronous
    # completion at the UI boundary. Filename, JPEG bytes and pixels stay guest-owned.
    request=bytes(cpu.mem_read(REQUEST,40))
    require(request[0]&1 and request[4],"missing native preview request")
    cpu.mem_write(JPEG+185,request[4:32])
    cpu.mem_write(JPEG+216,request[36:40])
    cpu.mem_write(JPEG+220,b"\x00\x01")
    cpu.mem_write(0x20381724,b"\0")
    call(cpu,rom(0x2023ac64),instruction_limit=50_000_000,timeout_us=0)
    valid=cpu.mem_read(0x20381724,1)[0] and cpu.mem_read(JPEG+13,1)[0]!=255
    cpu.mem_write(REQUEST+128,bytes(cpu.mem_read(JPEG+13,1)))
    cpu.mem_write(REQUEST+132,bytes(cpu.mem_read(JPEG+16,4)))
    cpu.mem_write(REQUEST,bytes([request[0]&~1]))
    call(cpu,rom(0x200c53f0 if valid else 0x200c5400))
    return request[4:32].split(b"\0")[0].decode(),bool(valid)


def check_pcm(g,sym,out,mode,raw,defaults=0x20367b78):
    rom = g.rom
    from sstv.decode import SSTVDecoder
    cpu=g.cpu
    dma=0xe8200000
    cpu.reg_write(arm.UC_ARM_REG_R4,dma)
    cpu.reg_write(arm.UC_ARM_REG_R5,288)
    cpu.emu_start(rom(0x200fef1c),rom(0x200fef40))
    banks=[unpack("<III",cpu.mem_read(dma+0x100+i*12,12)) for i in range(2)]
    require(banks==[(0x20400a40,0xe820b018,288),(0x20400b60,0xe820b018,288)],str(banks))
    seq=0
    def audio_block():
        nonlocal seq
        bank=seq%2
        seq+=1
        cpu.mem_write(dma+0x124,pack("<I",0x41 if bank else 0xc1))
        call(cpu,rom(0x200ffd48),timeout_us=0)
        words=cpu.mem_read(banks[bank][0],288)
        samples=bytearray(72)
        samples[::2],samples[1::2]=words[6::8],words[7::8]
        return samples
    def route(armed):
        call(cpu,rom(0x20060c74))
        actual=(cpu.mem_read(0x203e1e60,1)[0],cpu.mem_read(0x20380875,1)[0])
        require(actual==((8,2) if armed else (1,0)),f"unexpected stock MOD routing {actual} armed={armed}")
    def snapshot(): return unpack("<I",cpu.mem_read(sym["tx_snapshot"],4))[0]
    def rx_probe(expect_rx):
        from tools.probe_705_rx_audio import LAYOUTS,completed
        from tools.probe_705_sstv_arm import counters
        layout=LAYOUTS["705J140"]
        before=counters(cpu,sym)
        completed(cpu,rom(layout["rec_dma"]),dma+0xe4,layout["rec_bank"],0,tuple(range(36)),(0,)*36)
        # Wakeup is handled by the dedicated scheduler test. Drain the actual
        # guest worker here while using the very same panel and TX session.
        thread=bytes(cpu.mem_read(sym["sstv_thread"],4))
        cpu.mem_write(sym["sstv_thread"],bytes(4))
        try:
            call(cpu,rom(layout["rec_consume"]))
            call(cpu,sym["sstv_worker"])
        finally:
            cpu.mem_write(sym["sstv_thread"],thread)
        after=counters(cpu,sym)
        require(after["processed"]-before["processed"]==int(expect_rx),"RX transition lost")
    def begin():
        with patch("tools.replay_705_settings.call",lambda c,p,*args:call(c,p,*args,instruction_limit=2_000_000)):
            g.click(365,241)
        tick(g)
        labels,_=frame(g)
        require("STARTING" in labels,str(labels))
        require(snapshot() and bytes(cpu.mem_read(snapshot(),CANVAS_BYTES))==raw,"wrong TX snapshot")
    # Isolated panel inputs. Native routing computes both its DSP control
    # fields and SSI source index. User's persistent source starts at MIC.
    cpu.mem_write(0x203e212f,b"\x70")
    cpu.mem_write(0x203e2136,b"\x70")
    cpu.mem_write(0x203806f4,b"\x80")
    cpu.mem_write(0x203eaac8,bytes(2))
    cpu.mem_write(0x203eaac7,b"\x80")
    # Restore the five initialized stock gains in the isolated LCD guest.
    call(cpu,0x200052ed,defaults+0x87c,0x2038087c,20)
    gains=unpack("<5I",cpu.mem_read(0x2038087c,20))
    require(gains==(65536,43690,32768,21845,10922),"invalid factory modulation gains")
    feed_dsp_tx(cpu,False,rom(0x200d4a28))
    def request(expected):
        from tools.probe_705_cw_pcm import BUILD_REQUEST,FILTER_REQUEST,REQUEST,FILTERED
        call(cpu,rom(BUILD_REQUEST))
        call(cpu,rom(FILTER_REQUEST))
        call(cpu,rom(0x20109e74))
        flags=cpu.mem_read(0x203806f4,1)[0]
        require(not flags&32 and not cpu.mem_read(0x203809c4,1)[0]&1,"external PTT source asserted")
        require(bool(flags&128)==expected,"factory did not publish the requested TX/RX status")
        for addr in (REQUEST,FILTERED):
            value=unpack("<I",cpu.mem_read(addr,4))[0]
            require(bool(value&0x8000)==expected,f"request {addr:#x} = {value:#x}, expected {expected}")
    # Original WLAN playback is the control. Feed its native ring and compare
    # the unarmed output with its signed 32-bit multiplier and channel order.
    cpu.mem_write(0x203eaac8,bytes([3,3]))
    route(True)
    original=tuple((i-18)*113 for i in range(36))
    cpu.mem_write(0x20900000,pack("<36h",*original))
    call(cpu,rom(0x200ff5c8),0x20900000,1)
    require(audio_block()==pack("<36h",*(v*gains[4]>>16 for v in original)),"stock WLAN signal changed")
    cpu.mem_write(0x203806f4,bytes(1))
    cpu.mem_write(0x203eaac8,bytes(2))
    route(False)
    cpu.mem_write(0x203806f4,b"\x20")
    g.click(365,241); tick(g)
    require("REMOTE TX" in frame(g)[0] and not snapshot() and
            cpu.mem_read(0x203806f4,1)[0]&32,"button took ownership of another TX request")
    cpu.mem_write(0x203806f4,bytes(1))
    for addr,value,label in ((0x203809c4,0x40,"TX INHIB"),(0x203809b0,1,"TX REQ"),(0x203809a1,16,"TX ACTIVE")):
        old=bytes(cpu.mem_read(addr,1))
        cpu.mem_write(addr,bytes([value]))
        g.click(365,241); tick(g)
        require(label in frame(g)[0] and not snapshot(),f"missing busy reason {label}")
        cpu.mem_write(addr,old)
    cpu.mem_write(0x203e212f,b"\x20")
    cpu.mem_write(0x203e2136,b"\x20")
    g.click(365,241); tick(g)
    require("SSB AM FM" in frame(g)[0] and not snapshot(),"CW incorrectly armed")
    cpu.mem_write(0x203e212f,b"\x70")
    cpu.mem_write(0x203e2136,b"\x70")
    cpu.mem_write(0x203809c4,b'\x01')  # Raw key sample with published status still RX.
    begin()
    cpu.mem_write(0x203809c4,bytes(1))
    request(True)
    hit=g.click(365,241)
    tick(g); labels,_=frame(g)
    require(not snapshot(),f"button cancel failed {hit:#x} {labels}, tx={cpu.mem_read(sym['tx_state'],4).hex()}")
    request(False)
    tick(g); frame(g)
    begin()
    request(True)
    for _ in range(512): call(cpu,rom(0x20109514),timeout_us=0)
    request(False)
    tick(g); frame(g)
    require("TX TIMEOUT" in frame(g)[0] and not snapshot(),"request did not time out")
    begin()
    request(True)
    route(True)
    require(not any(audio_block()),"PCM before confirmed TX")
    feed_dsp_tx(cpu,True,rom(0x200d4a28))
    prefix=audio_block()
    require(any(prefix),"missing header")
    rx_probe(False)
    g.click(365,241)
    request(False)
    require(not any(audio_block()),"button cancel continued sending")
    feed_dsp_tx(cpu,False,rom(0x200d4a28))
    require(not any(audio_block()),"cancelled encoder returned samples")
    request(False)
    tick(g); frame(g)
    route(False)
    require(not snapshot(),"snapshot held after PTT release")
    rx_probe(True)
    begin()
    g.click(230,193)
    tick(g); frame(g)
    require(g.state()["menu"]==276 and not snapshot(),"armed TX survived leaving PICTURE")
    request(False)
    route(False)
    g.press_exit(); tick(g); frame(g)
    begin()
    request(True)
    route(True)
    feed_dsp_tx(cpu,True,rom(0x200d4a28))
    require(audio_block()==prefix,"restart changed the header")
    expected=round(48000*(0.910+(36 if mode=="Robot 36" else 256*.446446)))
    filename=out/(mode.replace(" ","-")+".wav")
    with wave.open(str(filename),"wb") as wav:
        wav.setparams((1,2,48000,0,"NONE",""))
        wav.writeframesraw(prefix)
        for i in range(36,expected,36):
            if i%(36*256)==0: request(True)
            pcm=audio_block()
            used=min(36,expected-i)*2
            require(not any(pcm[used:]),"nonzero padding after last sample")
            wav.writeframesraw(pcm[:used])
        count=wav.getnframes()
    for _ in range(3): require(not any(audio_block()),"frame repeated while draining")
    request(False)
    tick(g); labels,_=frame(g)
    require("RELEASE" in labels and not any(audio_block()),"held PTT restarted the frame")
    feed_dsp_tx(cpu,False,rom(0x200d4a28))
    tick(g); frame(g)
    require(not snapshot(),"snapshot held after completion")
    rx_probe(True)
    route(False)
    require(not any(cpu.mem_read(0x203eaac8,2)),"persistent source settings changed")
    require(abs(count-expected)<=1,f"sample count {count}, expected {expected}")
    # The independent FFT decoder requires lookahead at the very end of a file.
    with wave.open(str(filename),"rb") as wav:
        payload=wav.readframes(count)
    padded=BytesIO()
    with wave.open(padded,"wb") as wav:
        wav.setparams((1,2,48000,0,"NONE",""))
        wav.writeframes(payload+bytes(48000))
    padded.seek(0)
    with patch("sstv.decode.progress_bar"), patch("sstv.decode.log_message"), SSTVDecoder(padded) as decoder:
        pic=decoder.decode()
        require(pic is not None and decoder.mode.NAME=={"Robot 36":"Robot 36","Martin M1":"Martin 1"}[mode],
                "independent decoder did not identify the selected mode")
    pic.save(filename.with_suffix(".png"))
    ref=Image.fromarray(rgb565(raw).astype("uint8")).resize(pic.size,Image.Resampling.NEAREST)
    err=np.abs(np.asarray(pic.convert("RGB"),dtype=int)-np.asarray(ref,dtype=int))
    result=dict(mode=mode,samples=count,size=pic.size,fft_mae=round(err.mean(),2),
                fft_bottom_mae=round(err[-4:].mean(),2),cancel_restart=True,exit_disarms=True,
                dma_blocks=seq,dma_banks=banks,stock_gain=gains[4],stock_source_restored=True,rx_resumed=True,
                screen_keyed=True,button_cancel=True,unconfirmed_timeout=True,automatic_unkey=True)
    if mode=="Robot 36":
        from tools.sstv_robot36 import decode_rows
        # Check all 240 line indices and RGB fidelity separately from the FFT reader.
        rows=list(decode_rows(array("h",payload+bytes(48000)),48000))
        require([y for y,_ in rows]==list(range(0,240,2)),"incomplete Robot 36")
        decoded=np.frombuffer(b"".join(data for _,data in rows),np.uint8).reshape(240,320,3)
        delta=np.abs(decoded-rgb565(raw))
        result.update(pixel_mae=round(delta.mean(),2),bottom_mae=round(delta[-4:].mean(),2))
        require(delta.mean()<8 and delta[-4:].mean()<8,"Robot 36 PCM differs from the selected JPEG")
    else:
        # Estimate the pixel tone from the waveform at its nominal center. The
        # lagged sinusoidal recurrence is independent of the FFT receiver's bins.
        signal=np.frombuffer(payload,"<i2").astype(float)
        starts=.910+np.arange(256)[:,None]*.446446+.004862+.000572
        centers=(np.arange(320)+.5)*(.146432/320)
        planes=[]
        for channel in range(3):
            ix=np.rint(48000*(starts+channel*(.146432+.000572)+centers)).astype(int)
            energy=np.zeros_like(ix,dtype=float)
            cross=energy.copy()
            for d in range(-3,4):
                middle=signal[ix+d]
                energy+=middle**2
                cross+=middle*(signal[ix+d-4]+signal[ix+d+4])
            hz=np.arccos(np.clip(cross/(2*energy),-1,1))*48000/(8*np.pi)
            planes.append(np.clip((hz-1500)*255/800,0,255))
        decoded=np.stack((planes[2],planes[0],planes[1]),axis=-1)
        delta=np.abs(decoded-np.asarray(ref,dtype=int))
        result.update(pixel_mae=round(delta.mean(),2),bottom_mae=round(delta[-4:].mean(),2))
        require(delta.mean()<8 and delta[-4:].mean()<8,f"Martin M1 PCM error {result}")
    return result


def irq_replay(stock,main,sym,raw,expected,board=None):
    rom = board.rom if board else lambda pc: pc
    from tools.probe_705_rtx_audio import DMA_TIMER,PCM_STEP,TIMERS_CLEARED,probe
    def check(cpu,run,irq,sub,value):
        cpu.mem_write(BASE,main)
        cpu.ctl_remove_cache(BASE,BASE+len(main))
        saved=cpu.context_save()
        cpu.mem_write(0x203e84c9,pack("<H",21))
        sub(sym["sstv_begin"])
        rx=value(sym["pixels"])
        require(rx and value(sym["counts"]),"RX canvas unavailable in native heap")
        # Reuse the catalog result from the independent UI run, then start via
        # the actual button handler on a guest with the original heap and GIC.
        cpu.mem_write(COMMITTED,b"Reverse.jpg\0")
        cpu.mem_write(REQUEST+4,b"Reverse.jpg\0")
        cpu.mem_write(0x203e105d,b"\x01")
        cpu.mem_write(0x20380172,b"\x03")
        cpu.mem_write(TX_IMAGE,raw)
        sub(sym["sstv_tx_toggle"])
        tx=value(sym["tx_snapshot"])
        require(tx and (tx+CANVAS_BYTES<=rx or rx+CANVAS_BYTES<=tx),"TX snapshot unavailable in native heap")
        require(cpu.mem_read(tx,CANVAS_BYTES)==raw,"native heap copy is incomplete")
        cpu.mem_write(0x203806f4,b"\x80")
        sub(rom(0x20060c74))
        require(value(0x20380875,1)==2,"native modulation route failed")
        cpu.mem_write(0x203e1e6c,pack("<I",0x10))
        sub(rom(0x200d4a28))
        cpu.context_restore(saved)
        cpu.mem_write(0x20380874,b"\1")
        for offset in (0xe4,0x424,0x524):
            cpu.mem_write(0xe8200000+offset,pack("<I",1))
        run(rom(TIMERS_CLEARED),rom(PCM_STEP))
        captured=bytearray()
        for bank,status in enumerate((0xc1,0x41)):
            cpu.mem_write(0xe8200124,pack("<I",status))
            irq(DMA_TIMER,rom(PCM_STEP))
            words=unpack("<72i",cpu.mem_read(0x20400a40+288*bank,288))
            captured.extend(pack("<36h",*(v>>16 for v in words[1::2])))
        require(captured==expected,"stock IRQ output differs from complete Robot 36 replay")
        cpu.mem_write(0x203e1e6c,bytes(4))
        sub(rom(0x200d4a28))
        sub(sym["sstv_prepare_frame"])
        require(not value(sym["tx_snapshot"]),"released PTT retained native heap allocation")
        again=sub(rom(0x20127a28),CANVAS_BYTES)
        require(again==tx,"native allocator failed to reuse released TX snapshot")
        sub(rom(0x20127a78),again)
        return dict(rx_canvas=hex(rx),tx_canvas=hex(tx),bytes_each=CANVAS_BYTES,reallocated=True,
                    irq=DMA_TIMER,matched_samples=len(captured)//2)
    return probe(stock,application=main if board else None,audio_experiment=check)


def check_mode_picker(tap, show):
    modes=("Robot 36","Martin M1","Martin M2","Martin M3","Martin M4","Scottie S1","Scottie S2",
           "Scottie DX","Robot 72","SC2-180","PD50","PD90","PD120","PD160","PD180","PD240",
           "PD290","BW 8","BW 12","BW 24","Pasokon P3","Pasokon P5","Pasokon P7")
    for mode in modes:
        labels=tap(450,193)
        for _ in range(6):
            visible=labels[labels.index("SSTV TX MODE")+2:]
            if mode in visible:
                tap(115,52+60*visible.index(mode))
                actual=show()[0]
                require(mode in actual,f"TX menu did not commit {mode}: {labels} -> {actual}")
                break
            labels=tap(395,161)
        else:
            raise ValueError(f"TX menu cannot reach {mode}: {labels}")
    # Return the selector to its default for the original end-to-end tests.
    labels=tap(450,193)
    for _ in range(6):
        if "Robot 36" in labels[labels.index("SSTV TX MODE")+2:]:
            tap(115,52)
            return len(modes)
        labels=tap(395,65)
    raise ValueError("TX menu cannot return to Robot 36")


def exercise(out,clang,installed=None, *, initialize_menus=None, board=None, dat=None):
    out.mkdir(parents=True,exist_ok=True)
    directory=out/"card"/"IC-705"/"Picture"
    directory.mkdir(parents=True,exist_ok=True)
    im=Image.open(".analysis/sstv-robot36-v1/reference.ppm")
    for name,src in (("Bars",im),("Reverse",im.transpose(Image.Transpose.FLIP_LEFT_RIGHT))):
        src.save(directory/(name+".jpg"),quality=94)
    files=[directory/"Bars.jpg",directory/"Reverse.jpg"]
    stock=None if board else load(Path("firmware/705J140.dat").read_bytes())
    d6,meta=load_image(D6/"CW-RX3-WAKE2-PC/CW-RX3-WAKE2-PC.ic705sim")
    require(sha256(d6[0]).hexdigest()==D6_SHA,"D6 base differs")
    if installed is None:
        main,sym,_=combine(d6[0],meta,out/"build",clang,late_join=True,tx_study=True)
    else:
        main,sym=installed
    with patch.object(renderer,"HEAP_START",0x20700000):
        g=board.station_guest(dat)[0] if board else SettingsGuest(stock,front_panel=True)
    rom = g.rom
    cpu=g.cpu
    cpu.mem_map(0xe8200000,4096)
    from tools.probe_705_cw_pcm import simulated_gpio
    simulated_gpio(cpu,rom=rom)
    cpu.mem_write(BASE,main)
    cpu.ctl_remove_cache(BASE,BASE+len(main))
    if initialize_menus:
        initialize_menus(cpu, main)
    cpu.mem_write(sym["sstv_thread"],pack("<I",1))
    cpu.mem_write(g.language_address,bytes(2))
    opened,handles=mount_card(cpu,directory,rom)
    def show(name=None):
        tick(g)
        labels,screen=frame(g)
        if name: (out/(name+".png")).write_bytes(screen)
        return labels,screen
    def tap(x,y): g.click(x,y); return show()[0]
    def committed(): return bytes(cpu.mem_read(COMMITTED,28)).split(b"\0")[0].decode()
    def preview(path):
        name,ok=decode_request(cpu,rom)
        require(ok and name==path.name and not handles,"native JPEG failed")
        raw=bytes(cpu.mem_read(TX_IMAGE,CANVAS_BYTES))
        ref=np.asarray(Image.open(path).convert("RGB"),dtype=int)
        rgb=rgb565(raw)
        require(np.abs(ref-rgb).mean()<8,"wrong JPEG, orientation or channels")
        labels,screen=show(path.stem+"-picker")
        lcd=np.asarray(Image.open(BytesIO(screen)).convert("RGB"),dtype=int)
        err=np.abs(lcd[28:268,4:324]-rgb)
        require(err.mean()<4,f"LCD and TX canvas differ: {err.mean()}")
        return raw
    enter(g); show(); tap(115,116)
    require("SEND" in tap(365,191) and not committed(),"upper RX status started TX")
    show("rx-send-half")
    require("SET PHOTO" in tap(365,241),"empty TX photo accepted")
    tap(230,193); tap(370,194); tap(100,55)
    require(g.state()["menu"]==279,"TX Picture Select missing")
    directory_ready(cpu,files,rom)
    first=preview(files[0])
    tap(450,162)
    second=preview(files[1])
    require(first!=second and not committed(),"browsing committed a photo")
    tap(368,242)
    require(committed()=="Reverse.jpg" and g.state()["menu"]==278,"SET did not commit the second JPEG")
    tap(100,55); directory_ready(cpu,files,rom)
    if g.state()["selection"]: tap(450,69)
    preview(files[0])
    g.press_exit(); show()
    require(committed()=="Reverse.jpg","EXIT committed a browsed image")
    g.press_exit(); show()
    require(g.state()["menu"]==276,"failed to return to TX detail")
    # The isolated card service has finished closing its directory iterator.
    require(cpu.mem_read(0x203807f0,1)==b"\x09","missing directory close request")
    cpu.mem_write(0x203807f0,b"\0")
    # Run the stock reload routine if the asynchronous close has not dispatched it.
    if not cpu.mem_read(REQUEST,1)[0]&1:
        call(cpu,rom(0x200c231c))
    require(decode_request(cpu,rom)==("Reverse.jpg",True),"committed photo reload failed")
    raw=bytes(cpu.mem_read(TX_IMAGE,CANVAS_BYTES))
    require(raw==second,"committed JPEG differs from selection")
    results=[]
    picker_count=check_mode_picker(tap,show)
    for index,mode in enumerate(("Robot 36","Martin M1")):
        labels=tap(450,193)
        require({"SSTV TX MODE","Robot 36","Martin M1"}.issubset(labels),str(labels))
        show("mode-picker")
        tap(115,52+64*index)
        labels,_=show(mode.replace(" ","-")+"-detail")
        require(mode in labels and "MODE" in labels and committed()=="Reverse.jpg",str(labels))
        g.press_exit(); show()
        require(g.state()["menu"]==21,"failed to return to PICTURE")
        results.append(check_pcm(g,sym,out,mode,raw,board.defaults if board else 0x20367b78))
        tap(230,193)
    tap(450,193); g.press_exit()
    require("Martin M1" in show()[0],"cancelled mode selection changed the mode")
    g.press_exit(); show(); g.press_exit(); show()
    enter(g); show(); tap(115,52); labels=tap(230,193)
    require("BLOCK" in labels and "MODE" not in labels,"stock DV button changed")
    tap(450,193)
    require(g.state()["menu"]==277,"DV BLOCK no longer opens stock block selection")
    with wave.open(str(out/"Robot-36.wav"),"rb") as wav:
        irq_result=irq_replay(board.stock if board else stock[0],main,sym,raw,wav.readframes(72),board)
    report=dict(main_sha256=sha256(main).hexdigest(),files_opened=opened,
                selected="Reverse.jpg",picker_modes=picker_count,cancel_retains_selection=True,
                selected_canvas_sha256=sha256(raw).hexdigest(),modes=results,dv_block=True,
                native_irq_heap=irq_result,
                simulation="Host supplies file service, directory cache, JPEG scheduling, TX feedback and DMA completions. PCM read at SSIF0 transmit DMA source, second slot. RF untested.")
    (out/"evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--clang",required=True,type=Path)
    parser.add_argument("--decoder",required=True,type=Path,help="colaclanth/sstv checkout")
    args=parser.parse_args()
    sys.path.insert(0,str(args.decoder.resolve()))
    print(json.dumps(exercise(args.output,args.clang),indent=2))
