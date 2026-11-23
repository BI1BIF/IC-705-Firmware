"""Transmit known independently encoded link words to the packaged receiver and compare the three audible cues."""
import json
from pathlib import Path
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfilt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.verify_705_dmr_multimode import UP, OUT, replay, discriminator
sys.path.insert(0,str(UP/"tools"))
import build_iq_fixtures as gen

def air(levels):
    return np.repeat(np.r_[np.zeros(50),levels,np.zeros(50)],10).astype("<i2")*500

def sound(name):
    with wave.open(str(OUT/(name+".wav")),"rb") as f:
        return np.frombuffer(f.readframes(f.getnframes()),"<i2").astype(int)

def pulse():
    return np.array([int((0,1061,1500,1061,0,-1061,-1500,-1061)[t%8]*min(t,16,279-t)/16) for t in range(280)])

def check_p25():
    imbe=gen.p25_imbe_silent_bits()
    rng=np.random.default_rng(833)
    result={}
    for name,opcode,dest,service in (("group",0,9,0),("private",3,460011,0),("all",0,65535,0),("protected",0,9,64)):
        lc=bytes([opcode,0,service])+dest.to_bytes(3,"big")+int(4601205).to_bytes(3,"big")
        code=gen.rs64_encode(gen.p25_hexbits(lc),12)
        ldu=gen.p25_ldu_bits(5,code,rng,imbe)
        info=replay(name,3,air(gen.bits_to_levels(ldu+ldu)))
        result[name]=info
        if service:
            assert not info["rows"] and not info["samples"]
            continue
        kind={"group":"GRP","private":"PVT","all":"ALL"}[name]
        row=f"{kind} NAC 293 ID 4601205 {'TO' if opcode else 'TG'} {dest}"
        assert info["rows"]==[row] and info["samples"]==2880
    group=sound("group")
    for name,count in (("private",2),("all",3)):
        delta=np.zeros_like(group)
        for i in range(1,count):
            delta[480*i:480*i+280]=pulse()
        np.testing.assert_array_equal(sound(name)-group,delta)
    return result

def check_fusion():
    def encode_fich(dt):
        info=gen.msb_bits(1,2)+gen.msb_bits(0,2)+gen.msb_bits(3,2)+[0]*4+[0]*3+[1]*3+[0]*6+gen.msb_bits(dt,2)+[0]+gen.msb_bits(7,7)
        info+=gen.msb_bits(gen.crc16_ccitt_inverted(info),16)
        coded=[]
        for i in range(0,48,12):
            data=int("".join(map(str,info[i:i+12])),2)
            coded+=gen.msb_bits(gen.golay_24_12(data),24)
        airbits=[0]*200
        convolution=gen.k5_convolve(coded+[0]*4)
        for i in range(100):
            pos=(i%5)*40+2*(i//5)
            airbits[pos:pos+2]=convolution[2*i:2*i+2]
        return gen.msb_bits(gen.YSF_FS,40)+airbits
    result={}
    for dt,name in ((0,"vd1"),(2,"vd2"),(3,"vw")):
        frame=encode_fich(dt)+[0]*720
        info=replay(name,2,air(gen.bits_to_levels(frame*2)))
        assert info["samples"]==1600 and info["rows"]==["PVT "+("VW" if dt==3 else "DN")+" DG-ID 07"]
        result[name]=info
    return result

def check_dmr():
    from tools.verify_705_dmr_radio import discriminator as fm, mobile_call, render_if, HERE
    voice=(HERE/"dmr-reference/voice9.bin").read_bytes()[:27*6]
    result={}
    for title,target,opcode in (("GRP",9,0),("PVT",222,3),("ALL",0xfffff5,0)):
        name="dmr-"+title
        result[name]=replay(name,1,fm(render_if(mobile_call(voice,target,opcode))))
        assert result[name]["samples"]==18*160
        assert result[name]["rows"]==[f"{title} CC 7 ID 1234567 {'TO' if opcode else 'TG'} {target}"]
    base=sound("dmr-GRP")
    for name,count in (("dmr-PVT",2),("dmr-ALL",3)):
        delta=np.zeros_like(base)
        for i in range(1,count): delta[480*i:480*i+280]=pulse()
        np.testing.assert_array_equal(sound(name)-base,delta)
    return result

def check_dmr_late():
    from tools.verify_705_dmr_radio import discriminator as fm, mobile_call, render_if, HERE
    voice=(HERE/"dmr-reference/voice9.bin").read_bytes()[:27*12]
    result={}
    for case,target,opcode,expected in (
        ("group",9,0,"GRP CC 7 ID 1234567 TG 9"),
        ("private",222,3,"PVT CC 7 ID 1234567 TO 222"),
        ("privacy",9,0x4000,None),("damaged",9,0,None)):
        bursts=mobile_call(voice,target,opcode)[1:-1]
        if case=="damaged":
            for burst in bursts[1::6]:
                burst[58:70]^=3
        # Include a polarity reversal to exercise the sync ambiguity.
        pcm=fm(render_if(bursts))
        info=replay("dmr-late-"+case,1,-pcm if case=="private" else pcm)
        if expected:
            assert info["rows"]==[expected] and info["samples"]==7*480,info
        else:
            assert not info["rows"] and not info["samples"],info
        result[case]=info
    return result

if __name__=="__main__":
    if sys.argv[1:]==["--late"]:
        (OUT/"dmr-late.json").write_text(json.dumps(check_dmr_late(),indent=2))
        sys.exit(0)
    result=check_p25() | check_fusion() | check_dmr()
    for name,cutoff in (("p25p1_c4fm_no_hdu_synth",200),("ysf_synth",200)):
        raw=discriminator(UP/"tests/fixtures/iq"/(name+".iq"))
        pcm=sosfilt(butter(1,cutoff,btype="high",fs=48000,output="sos"),raw)
        pcm=sosfilt(butter(2,3000,fs=48000,output="sos"),pcm)
        test=name+"-hp"+str(cutoff)
        result[test]=replay(test,3 if name.startswith("p25") else 2,np.rint(pcm).astype("<i2"))
        assert result[test]["samples"]>0
    (OUT/"call-types.json").write_text(json.dumps(result,indent=2))
