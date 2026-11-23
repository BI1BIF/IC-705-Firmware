"""Build an MS-sourced test call and compare every recovered voice codeword, including the tail."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.probe_705_dmr_rx import HERE, ROOT, arm_decoder, call, firmware_if, machine, receive, transform, write_wav

MS = ("D5D7F77FD757","7F7D5DD57DFD")
CC, SOURCE, GROUP = 7, 1234567, 3100


def mobile_call(voice, target=GROUP, opcode=0):
    with tempfile.TemporaryDirectory() as work:
        return _mobile_call(voice,Path(work)/"mobile_fixture.elf",target,opcode)


def _mobile_call(voice, elf, target=GROUP, opcode=0):
    binary = elf.with_suffix(".bin")
    cmd = ["arm-none-eabi-gcc", "-Os", "-marm", "-mcpu=cortex-a9", "-ffunction-sections",
           "-fdata-sections", "-nostartfiles", "--specs=nosys.specs",
           "-Wl,--gc-sections,-e,fixture_init,-u,fixture_lc,-u,fixture_voice,-Ttext=0x20005000",
           "-Idsd-neo/include","-Idsd-neo/tests/protocol/dmr","-Idsd-neo/tests/test_support","-Imbelib-neo/include",
           ROOT/"tools/fixtures/dmr-mobile.c","dsd-neo/tests/test_support/dmr_rs_test_encoder.c",
           "dsd-neo/tests/test_support/dmr_bptc_test_encoder.c","dsd-neo/src/fec/fec.c","dsd-neo/src/fec/bptc.c",
           "-lm","-o",elf]
    build = subprocess.run(cmd,cwd=HERE,capture_output=True,text=True)
    if build.returncode:
        raise RuntimeError(build.stderr)
    subprocess.run(["arm-none-eabi-objcopy","-O","binary",elf,binary],check=True)
    table = subprocess.check_output(["arm-none-eabi-nm","-n",elf],text=True)
    syms = {row[2]:int(row[0],16) for line in table.splitlines() if len(row:=line.split())==3}
    cpu = machine(binary.read_bytes())
    def generate(name,*args):
        call(cpu,syms[name],*args,timeout_us=0,instruction_limit=20000000)
        return np.frombuffer(cpu.mem_read(syms["fixture_symbols"],576),dtype="<i4")[12:].copy()
    generate("fixture_init",CC,SOURCE,target,opcode)
    bursts = [generate("fixture_lc",1)]
    for number, start in enumerate(range(0,len(voice),27)):
        cpu.mem_write(syms["input_voice"],voice[start:start+27])
        bursts.append(generate("fixture_voice",1+number%6))
    bursts.append(generate("fixture_lc",2))
    return bursts


def render_if(bursts):
    # 4,800 symbols/s, 132-symbol active burst once per 60 ms; smooth RC fixture.
    step = 10
    deviations = np.array([648,1944,-648,-1944])
    active = np.zeros((len(bursts)+2)*288*step)
    impulses = np.zeros_like(active)
    for i,burst in enumerate(bursts,1):
        start = i*288*step
        impulses[start:start+132*step:step] = deviations[burst]
        # The power ramp belongs in the guard interval, outside the decision centres.
        end = start+132*step
        ramp = .5-.5*np.cos(np.linspace(0,np.pi,30))
        active[start-55:start-25] = ramp
        active[start-25:end+25] = 1
        active[end+25:end+55] = ramp[::-1]
    t = np.arange(-80,81)/step
    k = np.isclose(abs(t),2.5)
    h = np.empty_like(t)
    h[~k] = np.sinc(t[~k])*np.cos(np.pi*.2*t[~k])/(1-(.4*t[~k])**2)
    h[k] = np.pi*np.sinc(t[k])/4
    hz = np.convolve(impulses,h,mode="same")+12000
    return np.round(active*11000*np.cos(np.cumsum(hz)*(2*np.pi/48000))).astype("<i2")


def main():
    source = (HERE/"dmr-reference/voice9.bin").read_bytes()
    # Three voice frames per burst. Use an explicit pad codeword after frame 227.
    sent = source + source[-9:]
    assert len(sent) == 76*27
    bursts = mobile_call(sent)
    decoder = arm_decoder()
    pcm = render_if(bursts)
    reference = transform(source,encode=False)[0]
    groups = [{"color_code":CC,"source":SOURCE,"talkgroup":GROUP,"headers":1}]
    result = {"method":"MS-sourced bursts built with pinned dsd-neo test functions, known speech, synthetic 12 kHz IF, stock SSIF5 firmware replay, host demodulation and separate ARM codec.",
              "source_frames":227,"padding_frames":1,"bursts":76,"regions":{}}
    for region in "JE":
        recovered,dat_hash = firmware_if(region,pcm)
        headers,heard = receive(recovered,decoder,True,MS)
        assert headers == groups and heard == sent, (region,headers,len(heard),len(sent))
        speech,_,corrections = transform(heard[:-9],encode=False)
        assert speech == reference and corrections == {0:227}
        result["regions"][region] = dict(dat_sha256=dat_hash,headers=headers,frames=len(heard)//9,
            pcm_sha256=sha256(speech).hexdigest(),all_transmitted_bytes_match=True)
    write_wav(HERE/"rx-mobile-speech.wav",speech)
    # Exercise the same file interface used with a stereo USB IF capture.
    with tempfile.TemporaryDirectory() as folder:
        input_wav = Path(folder)/"stereo-if.wav"
        output_wav = Path(folder)/"voice.wav"
        with wave.open(str(input_wav),"wb") as wav:
            wav.setparams((2,2,48000,0,"NONE",""))
            wav.writeframes(np.column_stack((np.zeros_like(pcm),pcm)).tobytes())
        cmd = [sys.executable,ROOT/"tools/probe_705_dmr_rx.py","--if-wav",input_wav,
               "--channel","2","--voice-out",output_wav]
        subprocess.run(cmd,check=True,capture_output=True)
        with wave.open(str(output_wav),"rb") as wav:
            assert wav.getparams()[:4] == (1,2,8000,228*160)
            assert wav.readframes(wav.getnframes()) == transform(sent,encode=False)[0]
    result["stereo_if_wav_channel_2_pcm_matches_reference_including_pad"] = True
    # Stop during the last voice burst, then check that a following voice burst after a
    # valid terminator is ignored, and a call without its header is never attributed.
    last_start = (len(bursts)-1)*2880
    assert receive(pcm[:last_start+600],decoder,True,MS)[1] == sent[:-27]
    assert receive(render_if(bursts+[bursts[1]]),decoder,True,MS)[1] == sent
    assert receive(render_if(bursts[1:]),decoder,True,MS) == ([],b"")
    assert receive(pcm,decoder,True) == ([],b"")
    result["controls"] = ["incomplete burst omitted","ignored burst after terminator","missing header","wrong sync family"]
    (HERE/"rx-mobile-result.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
