"""Generate colour bars using pySSTV and replay full frames on the packaged A32 receiver."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
import subprocess
import sys

import numpy as np
from PIL import Image
from tools.decode_705_main import decode_main
from tools.emulate_705 import machine,call
from tools.probe_705_sstv_arm import counters


def encoders():
    from pysstv import color as c, grayscale as g
    from pysstv.sstv import byte_to_freq
    class PD50(c.PD90):
        VIS_CODE,PIXEL=93,.286
    class BW12(g.Robot8BW):
        VIS_CODE,SCAN=6,93
    class M3(c.MartinM1):
        VIS_CODE,HEIGHT=36,128
    class M4(c.MartinM2):
        VIS_CODE,HEIGHT=32,128
    class Robot72(c.Robot36):
        VIS_CODE=12
        def encode_line(self,line):
            # Colaclanth R72: Y followed by Cr and Cb within each line.
            yield 1500,3
            for channel,duration,sep in ((0,138,0),(2,69,1500),(1,69,2300)):
                if sep:
                    yield sep,4.5
                    yield 1900,1.5
                for x in range(self.WIDTH):
                    yield byte_to_freq(self.yuv[x,line][channel]),duration/self.WIDTH
    return [c.MartinM1,c.Robot36,c.MartinM2,M3,M4,c.ScottieS1,c.ScottieS2,c.ScottieDX,
            Robot72,c.WraaseSC2180,PD50,c.PD90,c.PD120,c.PD160,c.PD180,c.PD240,c.PD290,
            g.Robot8BW,BW12,g.Robot24BW,c.PasokonP3,c.PasokonP5,c.PasokonP7]


def check_mode(main,sym,runner,cls,*,cut=0):
    w,h=cls.WIDTH,cls.HEIGHT
    y,x=np.indices((h,w))
    colors=np.array([[208,51,75],[48,177,85],[53,88,201],[204,172,61],[83,178,195],[194,90,170]],dtype=np.uint8)
    pic=Image.fromarray(colors[(x*6//w+y*7//h)%6])
    source=cls(pic,8000,16)
    tones=np.fromiter((complex(f,t) for f,t in source.gen_freq_bits()),np.complex128)
    ends=np.rint(8*np.cumsum(tones.imag)).astype(int)
    freq=np.repeat(tones.real,np.diff(ends,prepend=0))
    pcm=np.rint(13000*np.sin(np.cumsum(freq)*(2*np.pi/8000))).astype("<i2")
    if cut:
        pcm=pcm[cut:]
    pcm=np.pad(pcm,(0,240-len(pcm)%6))
    cpu=machine(main)
    cpu.mem_write(sym["counts"],pack("<I",1))
    cpu.mem_write(sym["generation"],pack("<I",1))
    cpu.mem_write(sym["pixels"],pack("<I",0x20800000))
    cpu.mem_write(0x203e84c9,pack("<H",21))
    cpu.mem_write(0x20900000,runner)
    for i in range(0,len(pcm),12000):
        chunk=pcm[i:i+12000]
        cpu.mem_write(0x20910000,chunk.tobytes())
        call(cpu,0x20900000,0x20910000,len(chunk)//6,sym["sstv_capture"],sym["sstv_worker"],
             timeout_us=0,instruction_limit=30_000_000)
    state=counters(cpu,sym)
    lcd=np.frombuffer(cpu.mem_read(0x20800000,153600),"<u2").astype(int).reshape(240,320)
    rgb=np.stack(((lcd>>11)*8,((lcd>>5)&63)*4,(lcd&31)*8),axis=-1)
    if cls.VIS_CODE in (2,6,10): pic=pic.convert("L").convert("RGB")
    ref=np.asarray(pic.resize((320,240),Image.Resampling.NEAREST),dtype=int)
    error=np.abs(rgb-ref)
    return dict(vis=cls.VIS_CODE&127,detected=state["mode"],rows=state["rows"],height=h,locks=state["locks"],
                phase=state["phase"],drops=state["dropped"],mae=round(float(error.mean()),2),
                bottom_mae=round(float(error[-4:].mean()),2))


def pcm_runner(root,clang):
    obj=root/"build/pcm-runner.o"
    code=b"""void feed(short *p,unsigned n,void (*capture)(short*),void (*drain)(void)) {
        while(n) { unsigned k=n<18?n:18; n-=k; while(k--) {capture(p);p+=6;} drain(); }
    }"""
    subprocess.run([str(clang),"--target=arm-none-eabi","-mcpu=cortex-a9","-marm","-O2",
                    "-ffreestanding","-x","c","-c","-","-o",str(obj)],input=code,check=True)
    binary=obj.with_suffix(".bin")
    subprocess.run([str(clang.with_name("llvm-objcopy"+clang.suffix)),"-j",".text",
                    "-O","binary",str(obj),str(binary)],check=True)
    return binary.read_bytes()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("dat",type=Path)
    p.add_argument("--clang",type=Path,required=True)
    p.add_argument("--encoder",type=Path,required=True)
    p.add_argument("--mid-frame",action="store_true")
    args=p.parse_args()
    sys.path.insert(0,str(args.encoder.resolve()))
    root=args.dat.parent
    nm=args.clang.with_name("llvm-nm"+args.clang.suffix)
    entries=subprocess.check_output([str(nm),str(root/"build/rx.elf")],text=True)
    sym={s[2]:int(s[0],16) for line in entries.splitlines() if len(s:=line.split())==3}
    package=args.dat.read_bytes()
    app=bytes(decode_main(package)[1])
    assert app.count((root/"build/rx.bin").read_bytes())==1
    runner=pcm_runner(root,args.clang)
    results={}
    for cls in encoders():
        r=check_mode(app,sym,runner,cls,cut=17001 if args.mid_frame else 0)
        print(cls.__name__,r,flush=True)
        results[cls.__name__]=r
    if args.mid_frame:
        (root/"mid-frame.json").write_text(json.dumps(dict(dat_sha256=sha256(package).hexdigest(),modes=results),indent=2))
        ambiguous={36:44,32:40,6:10}
        assert all(r["detected"]==ambiguous.get(r["vis"],r["vis"]) and r["locks"]==1 and not r["drops"]
                   and r["rows"]*5>r["height"]*4 for r in results.values()),"late-entry regression"
        return
    (root/"multimode.json").write_text(json.dumps(dict(dat_sha256=sha256(package).hexdigest(),modes=results),indent=2))
    assert all(r["phase"]==2 and r["vis"]==r["detected"] and r["locks"]==1 and r["rows"]==r["height"] and not r["drops"]
               and r["mae"]<18 and r["bottom_mae"]<20 for r in results.values()),"multimode regression"


if __name__=="__main__":
    main()
