"""Replay timing and separator defects at known positions in the Robot 36 field fixture."""
from array import array
import argparse
from hashlib import sha256
import json
from math import pi, sin
from pathlib import Path
import subprocess
import wave

from tools.decode_705_main import decode_main
from tools.probe_705_sstv_rx_levels import measure


def landscape_check(dat,nm):
    import numpy as np
    from PIL import Image
    from pysstv.color import Robot36
    path=Path(".analysis/j140-sstv-rx4-tx1/SSTV02.jpg")
    tones=np.array([complex(f,t) for f,t in Robot36(Image.open(path).convert("RGB"),8000,16).gen_freq_bits()])
    ends=np.rint(8*np.cumsum(tones.imag)).astype(int)
    clean=np.repeat(tones.real,np.diff(ends,prepend=0))
    original=np.rint(14000*np.sin(np.cumsum(clean)*(2*pi/8000))).astype("<i2")
    report={}
    from zipfile import ZipFile
    tx2=Path(".analysis/j140-sstv-rx4-tx2/705J140-CW-D6-SSTV-RX4-TX2.zip")
    for label,file in (("TX2",tx2),("TX3",dat)):
        if label=="TX2":
            with ZipFile(file) as z: package=z.read("IC-705/705J140.dat")
        else: package=file.read_bytes()
        image=bytes(decode_main(package)[1])
        lines=subprocess.check_output([str(nm),str(file.parent/"build/rx.elf")],text=True).splitlines()
        sym={s[2]:int(s[0],16) for line in lines if len(s:=line.split())==3}
        reference=bytearray()
        for case in ("clean","missing","opposite","sustained_opposite","fade","noise"):
            pcm=original.copy()
            if case not in ("clean","fade","noise"):
                for row in range(80,80+{"missing":5,"opposite":1,"sustained_opposite":3}[case]):
                    start=8*(910+150*row+100)
                    hz=1900 if case=="missing" else 1500 if row%2 else 2300
                    pcm[start:start+36]=np.rint(14000*np.sin(np.arange(36)*(hz*2*pi/8000)))
            if case in ("fade","noise"):
                span=pcm[8*(910+150*80):8*(910+150*104)]
                span[:]=0 if case=="fade" else np.random.default_rng(705).integers(-3000,3001,len(span))
            pcm=np.pad(pcm,(0,240))
            canvas=bytearray()
            r=measure(image,sym,pcm,15000,True,canvas)
            if case=="clean": reference=canvas
            same=canvas==reference
            r["matches_clean_pixels"]=same
            r["prefix_identical"]=canvas[:78*640]==reference[:78*640]
            r["suffix_identical"]=canvas[108*640:]==reference[108*640:]
            if case=="fade":
                pixels=np.frombuffer(canvas,"<u2").astype(int).reshape(240,320)
                rgb=np.stack(((pixels>>11)*255//31,((pixels>>5)&63)*255//63,
                              (pixels&31)*255//31),axis=-1).astype("uint8")
                Image.fromarray(rgb).save(dat.parent/f"landscape-fade-{label}.png")
            report[label+"_"+case]=r
            if label=="TX3" and case in ("fade","noise"):
                assert r["phase"]==2 and r["rows"]==240 and r["locks"]==1 and r["prefix_identical"] and r["suffix_identical"],r
            elif case=="clean" or label=="TX3":
                assert r["phase"]==2 and r["rows"]==240 and r["locks"]==1 and same,r
            else:
                assert r["locks"]>1 or r["rows"]<240,r
    return report


def exercise(dat, nm):
    root=dat.parent
    package=dat.read_bytes()
    image=bytes(decode_main(package)[1])
    lines=subprocess.check_output([str(nm),str(root/"build/rx.elf")],text=True).splitlines()
    symbols={s[2]: int(s[0],16) for line in lines if len(s:=line.split())==3}
    binary=(root/"build/rx.bin").read_bytes()
    assert image.count(binary)==1
    with wave.open(".analysis/sstv-robot36-v1/robot36.wav") as w:
        assert (w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,2,48000)
        source=array("h",w.readframes(w.getnframes()))[::6]
    rx3="robot_loss" in symbols
    rx4="sstv_archive_open" in symbols
    results={}
    for case in ("clean","split_sync","one_separator","split_and_separator","no_sync","two_separators","reversed"):
        samples=source[:]
        def replace(ms,count,hz):
            start=ms*8
            for i in range(count):
                samples[start+i]=round(14000*sin(2*pi*hz*i/8000))
        # First line starts at 1160 ms. The third begins at 1460 ms;
        # breaking its sync leaves exactly two decoded rows in RX2.
        if case in ("split_sync","split_and_separator"):
            for row in range(2,240):
                replace(1160+150*row+3,16,1900)
        if case in ("one_separator","two_separators","split_and_separator","reversed"):
            replace(1560,36,2300 if case=="reversed" else 1900)
        if case=="two_separators":
            replace(1710,36,1900)
        if case=="no_sync":
            replace(1460,72,1900)
        tolerates=b"REMOTE TX\0" in binary and case in ("two_separators","reversed","no_sync")
        if rx4 and not tolerates and case in ("no_sync","two_separators","reversed"):
            # Stop before the next four good lines can trigger deliberate late re-entry.
            stop={"no_sync":1580,"two_separators":1800,"reversed":1700}[case]
            samples=samples[:stop*8]
        full=tolerates or case=="clean" or (rx3 and case in ("split_sync","one_separator","split_and_separator"))
        canvas=bytearray()
        r=measure(image,symbols,samples,15000,full,canvas)
        print(dat.name,case,r,flush=True)
        if full:
            assert r["phase"]==2 and r["rows"]==240
            if case=="clean":
                reference=canvas
            else:
                import numpy as np
                def rgb(data):
                    v=np.frombuffer(data,"<u2").astype(int)
                    return np.array([(v>>11)*8,((v>>5)&63)*4,(v&31)*8])
                r["mae_vs_clean"]=float(np.abs(rgb(reference)-rgb(canvas)).mean())
                assert r["mae_vs_clean"]<5, r
        else:
            expected=1 if rx4 and case=="no_sync" else 3 if rx3 and case=="two_separators" else 2
            assert r["phase"]==3 and r["rows"]==expected
            if rx3: assert r["loss"]==(1 if case=="no_sync" else 2)
        results[case]=r
    if rx4:
        import numpy as np
        from scipy.signal import resample_poly
        def channels(data):
            v=np.frombuffer(data,"<u2").astype(int)
            return np.array([(v>>11)*8,((v>>5)&63)*4,(v&31)*8]).reshape(3,240,320)
        clean=channels(reference)
        for rate in (994,1006,980,1020):
            # Leave VIS intact and vary the receiver clock during the actual raster.
            i=1160*8
            skew=np.concatenate((source[:i],resample_poly(np.asarray(source[i:],dtype=float),rate,1000)))
            pcm=array("h",np.clip(np.rint(skew),-32768,32767).astype(np.int16).tobytes())
            canvas=bytearray()
            r=measure(image,symbols,pcm,15000,True,canvas)
            decoded=channels(canvas)
            # Relative horizontal displacements of the interior bar transitions.
            errors=[]
            for row in (20,60,100,140,180,220):
                dx=np.abs(np.diff(decoded[:,row],axis=1)).sum(axis=0)
                ref=np.abs(np.diff(clean[:,row],axis=1)).sum(axis=0)
                for x in (40,80,120,160,200,240,280):
                    win=slice(x-6,x+7)
                    errors.append(abs(int(dx[win].argmax())-int(ref[win].argmax())))
            r["max_bar_edge_delta_pixels"]=max(errors)
            r["mean_bar_edge_delta_pixels"]=float(np.mean(errors))
            r["mae_vs_clean"]=float(np.abs(decoded-clean).mean())
            assert r["phase"]==2 and r["rows"]==240 and r["max_bar_edge_delta_pixels"]<=4,r
            results[f"clock_{rate}_per_1000"]=r
    return dict(dat_sha256=sha256(package).hexdigest(),cases=results)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat",type=Path)
    parser.add_argument("--nm",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    args.out.write_text(json.dumps(exercise(args.dat,args.nm),indent=2))
