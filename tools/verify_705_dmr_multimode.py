"""Exercise the packaged ARM decoder, 16 KiB stack, card relocations and voice queue with RF fixtures."""
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfilt

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/".analysis/ic705-emulator/deps")]
from tools.build_705_dmr_station import OUT
from tools.emulate_705 import machine, call, arm
from tools.verify_705_ftx_rx import symbols
from tools.probe_705_dmr_rx import UP

def discriminator(path):
    xy=np.fromfile(path,np.uint8).astype(float).reshape(-1,2)-127.5
    iq=xy[:,0]+1j*xy[:,1]
    iq=sosfilt(butter(4,6500,fs=48000,output="sos"),iq)
    hz=np.angle(iq[1:]*iq[:-1].conj())*48000/(2*np.pi)
    return np.rint(sosfilt(butter(3,3900,fs=48000,output="sos"),hz)).astype("<i2")

def replay(name,mode,pcm):
    folder=OUT/"core"
    layout=json.loads((folder/"payload.json").read_text())
    base=layout["link_base"]
    sy=symbols(folder/f"payload-{base:08x}.elf")
    card=(OUT/"J/DMRRX.BIN").read_bytes()
    assert card==(OUT/"E/DMRRX.BIN").read_bytes()
    c=machine()
    c.mem_write(base,card[:layout["image_bytes"]])
    c.reg_write(arm.UC_ARM_REG_C1_C0_2,0xf00000)
    c.reg_write(arm.UC_ARM_REG_FPEXC,0x40000000)
    sp=0x206f0000
    c.mem_write(sp-20000,b"\xa5"*20000)
    c.mem_write(sy["digital_mode"],struct.pack("<I",mode))
    scratch=0x20690000
    def invoke(key,*args):
        return call(c,sy[key],*args,stack=sp,instruction_limit=30_000_000,timeout_us=0)
    pcm=np.pad(pcm,(0,24012+(-len(pcm))%36))
    rows=set()
    out=bytearray()
    for i in range(0,len(pcm),36):
        c.mem_write(scratch,pcm[i:i+36].tobytes())
        invoke("dmr_core_input",scratch,438000000,i//36+1)
        if i//36%4==0:
            invoke("dmr_core_work")
            invoke("dmr_core_status",scratch+128)
            row=bytes(c.mem_read(scratch+164,48)).split(b"\0")[0].decode()
            if row: rows.add(row)
        n=invoke("dmr_audio_pull6",scratch+96)
        if n: out.extend(c.mem_read(scratch+96,n*2))
    stack=bytes(c.mem_read(sp-20000,20000))
    used=len(stack)-next(i for i,b in enumerate(stack) if b!=165)
    assert used<12288,(name,used)
    with wave.open(str(OUT/(name+".wav")),"wb") as f:
        f.setparams((1,2,8000,0,"NONE","")); f.writeframes(out)
    info=dict(input=name,card_sha256=sha256(card).hexdigest(),samples=len(out)//2,
              pcm_sha256=sha256(out).hexdigest(),rows=sorted(rows),stack_bytes=used)
    print(info,flush=True)
    return info

if __name__=="__main__":
    names=sys.argv[1:] or ["p25p1_c4fm_no_hdu_synth","ysf_synth","p25p1_c4fm_vc","ysf"]
    for name in names:
        pcm=discriminator(UP/"tests/fixtures/iq"/(name+".iq"))
        result=replay(name,3 if name.startswith("p25") else 2,pcm)
        (OUT/(name+".json")).write_text(json.dumps(result,indent=2))
