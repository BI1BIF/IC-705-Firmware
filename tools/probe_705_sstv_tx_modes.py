"""Compare the packaged TX modulation waveform against independent pySSTV frames."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
import subprocess

import numpy as np
from PIL import Image
from tools.decode_705_main import decode_main
from tools.emulate_705 import machine, call
from tools.probe_705_sstv_multimode import encoders
from tools.probe_705_sstv_tx import rgb565


def run(main, sym, root, clang):
    # Batch original 36-sample modulation callbacks on the ARM and retain 8 kHz
    # at the output. Stop on the encoder's actual drain transition.
    obj = root/"tx-wave-probe.o"
    wrapper = b"""unsigned run(short *out, unsigned (*block)(void), volatile unsigned *state) {
      unsigned n=0;
      while(n<12000 && *state==2) {
        block();
        for(unsigned i=0;i<36;i+=6) out[n++]=((short*)0x20401c14)[i];
      }
      return n;
    }"""
    subprocess.run([clang,"--target=arm-none-eabi","-mcpu=cortex-a9","-marm","-O2",
                    "-x","c","-c","-","-o",obj],input=wrapper,check=True)
    binary=obj.with_suffix(".bin")
    subprocess.run([clang.with_name("llvm-objcopy"+clang.suffix),"-j",".text","-O","binary",obj,binary],check=True)
    y,x=np.indices((240,320))
    palette=np.array([0xe18b,0x1685,0x391e,0xd6e4,0x25f9,0xc4b4],dtype="<u2")
    canvas=palette[(x*6//320+y*7//240)%6].tobytes()
    picture=Image.fromarray(rgb565(canvas).astype(np.uint8))
    classes=encoders()
    classes[:2]=classes[1::-1]
    word=lambda n:pack("<I",n)
    results={}
    for index,cls in enumerate(classes):
        cpu=machine(main)
        cpu.mem_write(0x20900000,binary.read_bytes())
        cpu.mem_write(0x20800000,canvas)
        cpu.mem_write(sym["counts"],word(1))
        cpu.mem_write(0x203e84c9,pack("<H",21))
        cpu.mem_write(0x203809a1,b"\x10")
        cpu.mem_write(sym["tx_mode"],word(index))
        call(cpu,sym["tx_pcm_begin"],0x20800000)
        cpu.mem_write(sym["tx_state"],word(2))
        audio=bytearray()
        while cpu.mem_read(sym["tx_state"],4)==word(2):
            n=call(cpu,0x20900000,0x20910000,sym["sstv_tx_mod_block"],sym["tx_state"],
                   timeout_us=0,instruction_limit=15_000_000)
            assert n>0 and len(audio)<8_000_000
            audio.extend(cpu.mem_read(0x20910000,2*n))
        pcm=np.frombuffer(audio,"<i2").astype(float)
        ref=picture.resize((cls.WIDTH,cls.HEIGHT),Image.Resampling.NEAREST)
        tones=np.fromiter((complex(f,t) for f,t in cls(ref,8000,16).gen_freq_bits()),np.complex128)
        ends=np.rint(8*np.cumsum(tones.imag)).astype(int)
        assert abs(len(pcm)-ends[-1])<25,(cls.__name__,len(pcm),ends[-1])
        # Estimate tone from the real signal over short windows. Compare against
        # flat portions independently, including VIS and the final image lines.
        reference=np.repeat(tones.real,np.diff(ends,prepend=0))
        centers=np.arange(20,min(len(reference),len(pcm))-20,16)
        changes=np.r_[0,np.cumsum(np.diff(reference)!=0)]
        centers=centers[changes[centers-16]==changes[centers+16]]
        w=pcm[centers[:,None]+np.arange(-7,8)]
        v=w[:,1:-1]
        ratio=(v*(w[:,:-2]+w[:,2:])).sum(1)/(2*np.maximum(1,(v*v).sum(1)))
        measured=np.arccos(np.clip(ratio,-1,1))*8000/(2*np.pi)
        err=np.abs(measured-reference[centers])
        header=centers<7280
        tail=centers>len(pcm)*.98
        good=float((err<35).mean())
        assert err[header].max()<15 and good>.97 and (err[tail]<35).mean()>.95,(cls.__name__,good)
        results[cls.__name__]=dict(vis=cls.VIS_CODE&127,samples_8k=len(pcm),reference_samples=int(ends[-1]),
                                   tone_match=round(good,5))
        print(cls.__name__,results[cls.__name__],flush=True)
    return results


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat",type=Path)
    parser.add_argument("--clang",type=Path,required=True)
    args=parser.parse_args()
    root=args.dat.parent
    data=args.dat.read_bytes()
    main=bytes(decode_main(data)[1])
    assert main.count((root/"build/rx.bin").read_bytes())==1
    nm=args.clang.with_name("llvm-nm"+args.clang.suffix)
    listing=subprocess.check_output([nm,root/"build/rx.elf"],text=True)
    sym={v[2]:int(v[0],16) for line in listing.splitlines() if len(v:=line.split())==3}
    results=run(main,sym,root/"build",args.clang)
    (root/"tx-multimode.json").write_text(json.dumps(dict(dat_sha256=sha256(data).hexdigest(),modes=results),indent=2))
