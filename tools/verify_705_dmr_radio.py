"""Replay continuous discriminator PCM through the integer Cortex-A9 DMR receiver."""
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
from scipy.signal import hilbert

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.probe_705_dmr_rx import HERE, ROOT, SYNC_PAIRS, UP, call, machine, real_if, sync_symbols
from tools.verify_705_dmr_mobile import mobile_call, render_if

OUT = HERE / "integer-radio"
WRAPPER = """
#include "dmr-radio.h"
dmr_radio state;
const unsigned state_bytes=sizeof(state);
unsigned char output[4096];
unsigned used;
static void save(void *arg,const uint8_t v[27]) {
    (void)arg;
    if (used+27>sizeof(output)) return;
    for (unsigned i=0;i<27;++i) output[used++]=v[i];
}
void run(const int16_t *pcm,unsigned n) {
    while (n) {
        unsigned block=n<36?n:36;
        dmr_radio_feed(&state,pcm,block,save,0);
        pcm+=block;
        n-=block;
    }
}
"""

def build():
    OUT.mkdir(exist_ok=True)
    (OUT/"wrapper.c").write_text(WRAPPER,encoding="utf-8")
    subprocess.run(["arm-none-eabi-gcc","-std=c11","-Os","-mcpu=cortex-a9","-marm",
                    "-fno-builtin","-ffreestanding","-Wall","-Wextra","-Werror",
                    "-nostdlib","-Wl,-e,run,-Ttext=0x20005000","-I",ROOT/"samples",
                    ROOT/"samples/dmr-radio.c","wrapper.c","-lc","-lgcc","-o","test.elf"],cwd=OUT,check=True)
    subprocess.run(["arm-none-eabi-objcopy","-O","binary","test.elf","test.bin"],cwd=OUT,check=True)
    table=subprocess.check_output(["arm-none-eabi-nm","-n",OUT/"test.elf"],text=True)
    syms={t[2]:int(t[0],16) for line in table.splitlines() if len(t:=line.split())==3}
    return (OUT/"test.bin").read_bytes(),syms

def discriminator(samples):
    z=hilbert(samples.astype(float))
    phase=np.angle(z[1:]*z[:-1].conj())
    freq=phase*(48000/(2*np.pi))-12000
    return np.clip(np.rint(freq),-32768,32767).astype("<i2")

def replay(binary, pcm):
    data,syms=binary
    cpu=machine(data)
    base=0x20100000
    cpu.mem_write(base,pcm.tobytes())
    call(cpu,syms["run"],base,len(pcm),timeout_us=0,instruction_limit=100_000_000)
    size=struct.unpack("<I", cpu.mem_read(syms["state_bytes"],4))[0]
    counters=struct.unpack("<6I3B",cpu.mem_read(syms["state"],27))
    result=dict(zip(("source","target","headers","bursts","ends","losses","active","family","color_code"),counters))
    n=struct.unpack("<I",cpu.mem_read(syms["used"],4))[0]
    frames=bytes(cpu.mem_read(syms["output"],n))
    return result, frames, size

def main():
    binary=build()
    source=(HERE/"dmr-reference/voice9.bin").read_bytes()
    sent=source+source[-9:]
    bursts=mobile_call(sent)
    cases={}

    def check(name,pcm,expected,count,fields=None,end=None,lost=None,family=None):
        result,frames,size=replay(binary,pcm)
        digest=sha256(frames).hexdigest()
        assert result["headers"]==count and digest==expected, (name,result,digest,len(frames))
        if fields:
            assert (result["color_code"],result["source"],result["target"])==fields, (name,result)
        if end is not None:
            assert result["ends"]==end and not result["active"], (name,result)
        if lost is not None:
            assert result["losses"]==lost, (name,result)
        if family is not None:
            assert result["family"]==family, (name,result)
        cases[name]=dict(**result,frames=len(frames)//9,sha256=digest,state_bytes=size)

    def symbols_burst(family):
        b=[x.copy() for x in bursts]
        data,voice=SYNC_PAIRS[family]
        for i,bts in enumerate(b):
            header=i==0 or i==len(b)-1
            if header or (i-1)%6==0:
                bts[54:78]=np.frombuffer(sync_symbols(data if header else voice),dtype=np.uint8)
        return b

    base=discriminator(real_if(UP/"tests/fixtures/iq/dmr_voice_synth.iq"))
    check("upstream_bs",base,"d7c3b5d4dec2ca411927b519a1296568371bdad398ec7d5fcc1d56caabc338d6",
          1,(2,1001,100),end=1,family=1)
    fields=(7,1234567,3100)
    good=sha256(sent).hexdigest()
    pcm=discriminator(render_if(bursts))
    check("upstream_ms",pcm,good,1,fields,end=1,family=2)
    for number,family in enumerate(("DIRECT1","DIRECT2"),3):
        data=discriminator(render_if(symbols_burst(family)))
        check(family,np.rint(data.astype(float)*-.35+120).astype("<i2"),good,1,fields,end=1,family=number)
    # A 100 ppm sample clock error eventually shifts the eye by >2 symbols.
    idx=np.arange(0,len(pcm)-1,1.0001)
    drift=np.interp(idx,np.arange(len(pcm)),pcm).astype("<i2")
    check("100ppm",drift,good,1,fields,end=1)
    tail=discriminator(render_if(bursts+[bursts[1]]))
    check("after_terminator",tail,good,1,fields,end=1)
    empty=sha256(b"").hexdigest()
    check("late_entry",discriminator(render_if(bursts[1:8])),sha256(sent[5*27:7*27]).hexdigest(),1,fields)
    check("incomplete_embedded_lc",discriminator(render_if(bursts[1:5])),empty,0)
    # This discriminator fixture represents deviation in Hz. Vary receiver
    # offset during a headerless call and compare every accepted AMBE byte.
    late=discriminator(render_if(bursts[1:]))
    offsets=np.array([0,80,160,250,160,80,0,-80,-160,-250,-160,-80])
    swing=offsets[(np.arange(len(late))//720)%len(offsets)]
    check("late_entry_during_fine_tuning",np.clip(late+swing,-32768,32767).astype("<i2"),
          sha256(sent[5*27:]).hexdigest(),1,fields)
    drop=discriminator(render_if(bursts[:4]))
    drop=np.concatenate((drop,np.zeros(6*2880,dtype="<i2")))
    check("lost_carrier",drop,sha256(sent[:81]).hexdigest(),1,fields,end=0,lost=1)
    check("seeded_noise",np.random.default_rng(705).normal(0,2000,96000).astype("<i2"),empty,0)
    damaged=[b.copy() for b in bursts[:4]]
    damaged[0][:30]^=3
    check("bad_link_control",discriminator(render_if(damaged)),empty,0)
    corrected=[b.copy() for b in bursts[:4]]+[bursts[-1]]
    corrected[0][17]^=1 # BPTC data bit
    corrected[0][50]^=2 # Golay-protected slot type
    corrected[2][54]^=1 # QR-protected embedded signalling
    check("correctable_bits",discriminator(render_if(corrected)),sha256(sent[:81]).hexdigest(),1,fields,end=1)
    check("reacquire_after_loss",np.concatenate((drop,pcm)),sha256(sent[:81]+sent).hexdigest(),
          2,fields,end=1,lost=1)
    print(json.dumps(cases,indent=2))
    (OUT/"results.json").write_text(json.dumps(cases,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
