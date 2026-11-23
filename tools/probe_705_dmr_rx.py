"""Check a group voice header from an independent I/Q fixture on both release images."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
import wave

import numpy as np
from scipy.signal import hilbert

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT/".analysis/dmr-if-study"
UP = HERE/"dsd-neo"
sys.path[:0] = [str(ROOT), str(ROOT/".analysis/ic705-emulator/deps")]
from tools.decode_705_main import decode_main
from tools.emulate_705 import BASE, SCRATCH, machine, call
from tools.probe_705_rx_audio import DMAC, FRAMES, LAYOUTS, completed
sys.path.insert(0,str(HERE/"dmr-reference"))
from dmr_fixture import transform, write_wav

SYNC_PAIRS = {
    "BS":("DFF57D75DF5D","755FD7DF75F7"),
    "MS":("D5D7F77FD757","7F7D5DD57DFD"),
    "DIRECT1":("F7FDD5DDFD55","5D577F7757FF"),
    "DIRECT2":("D7557F5FF7F5","7DFFD5F55D5F"),
}


def arm_decoder():
    fec = UP/"src/fec"
    subprocess.run(["arm-none-eabi-gcc", "-Os", "-marm", "-mcpu=cortex-a9", "-ffunction-sections",
                    "-fdata-sections", "-nostartfiles", "--specs=nosys.specs",
                    "-Wl,--gc-sections,-e,group_header,-u,group_end,-u,embedded_signalling,-u,InitAllFecFunction,-Ttext=0x20005000",
                    "-I", UP/"include", ROOT/"samples/dmr-rx-header.c", fec/"bptc.c", fec/"fec.c", fec/"rs-12-9.c",
                    "-o", "rx_header.elf"], cwd=HERE, check=True)
    subprocess.run(["arm-none-eabi-objcopy","-O","binary","rx_header.elf","rx_header.bin"],cwd=HERE,check=True)
    table = subprocess.check_output(["arm-none-eabi-nm", "-n", HERE/"rx_header.elf"],text=True)
    syms = {row[2]:int(row[0],16) for line in table.splitlines() if len(row:=line.split())==3}
    cpu = machine((HERE/"rx_header.bin").read_bytes())
    call(cpu,syms["InitAllFecFunction"],timeout_us=0,instruction_limit=15000000)
    return cpu, syms


def sync_symbols(hex_word):
    bits = np.unpackbits(np.frombuffer(bytes.fromhex(hex_word),dtype=np.uint8)).reshape(-1,2)
    return bytes(bits[:,0]*2+bits[:,1])


def receive(pcm, decoder, voice=False, sync_pair=("DFF57D75DF5D","755FD7DF75F7")):
    cpu, syms = decoder
    # Twelve-kilohertz real IF; discriminator in Hz, evaluated at all ten symbol phases.
    analytic = hilbert(pcm.astype(float))
    hz = np.angle(analytic[1:]*analytic[:-1].conj()) * (48000/(2*np.pi)) - 12000
    centers = np.arange(4)*1296-1944
    level_to_dibit = np.array([3,2,0,1],dtype=np.uint8)
    sync = sync_symbols(sync_pair[0])
    hits = {}
    best = None
    for phase in range(10):
        levels = hz[phase::10]
        for polarity in (1,-1):
            symbols = level_to_dibit[abs(levels[:,None]*polarity-centers).argmin(axis=1)].tobytes()
            pos = symbols.find(sync)
            while pos >= 0:
                if pos >= 54 and pos+78 <= len(symbols):
                    dibits = np.frombuffer(symbols[pos-54:pos+78],dtype=np.uint8)
                    bits = np.column_stack((dibits >> 1,dibits & 1)).ravel().tobytes()
                    cpu.mem_write(syms["bits"],bits)
                    if call(cpu,syms["group_header"]):
                        fields = bytes(cpu.mem_read(syms["identity"],7))
                        hits.setdefault(fields,[]).append(phase+10*pos)
                        error = abs(levels[pos-54:pos+78,None]*polarity-centers).min(axis=1).mean()
                        if best is None or error < best[0]:
                            best = error, symbols, pos, fields
                pos = symbols.find(sync,pos+1)
    headers = [{"color_code": f[0], "source":int.from_bytes(f[4:],"big"),"talkgroup":int.from_bytes(f[1:4],"big"),
             "headers":1+sum(b-a>20 for a,b in zip(sorted(at),sorted(at)[1:]))} for f,at in hits.items()]
    if not voice:
        return headers
    payload = bytearray()
    if best is not None:
        _, symbols, header, fields = best
        voice_sync = sync_symbols(sync_pair[1])
        position = None
        # This bench follows one selected group call at a fixed symbol rate.
        for center in range(header+288,len(symbols)-77,288):
            mid = symbols[center:center+24]
            burst = np.frombuffer(symbols[center-54:center+78],dtype=np.uint8)
            bits = np.column_stack((burst>>1,burst&1)).ravel()
            cpu.mem_write(syms["bits"],bits.tobytes())
            if mid == sync:
                if call(cpu,syms["group_end"]) and bytes(cpu.mem_read(syms["identity"],7)) == fields:
                    break
                if call(cpu,syms["group_header"]) and payload:
                    break
                position = None
                continue
            if mid == voice_sync:
                position = 0
            elif position is not None and position < 5:
                position += 1
                emb = call(cpu,syms["embedded_signalling"])
                if (emb >> 3) != fields[0] or (emb & 3) != (0,1,3,3,2,0)[position]:
                    continue
            else:
                continue
            payload.extend(np.packbits(np.concatenate((bits[:108],bits[156:]))).tobytes())
    return headers, bytes(payload)


def firmware_if(region, samples):
    dat = (ROOT/f".analysis/release-v1.4.0/verified/705{region}140.dat").read_bytes()
    main = bytes(decode_main(dat)[1])
    stock = (ROOT/".analysis/main-decode/705J140/main.bin").read_bytes()
    layout = LAYOUTS["705J140"]
    def find(key):
        idx = layout[key]-BASE
        needle = stock[idx:idx+96]
        assert main.count(needle)==1
        return main.index(needle)+BASE
    dma, read = find("lan_dma"),find("lan_read")
    cpu = machine(main)
    cpu.mem_map(DMAC,4096)
    cpu.mem_write(0x2038026D,b"\x01")
    cpu.mem_write(layout["lan_ramp"]+2,struct.pack("<H",480))
    cpu.mem_write(layout["lan_slot"]+0x7b,b"\0")
    audio = bytearray()
    dst = SCRATCH-8192
    for start in range(0,len(samples),FRAMES):
        completed(cpu,dma,DMAC+0x524,layout["lan_bank"],start//FRAMES,
                  samples[start:start+FRAMES].tolist(),[0]*FRAMES,timeout_us=0)
        if (start+FRAMES)%2880==0:
            for _ in range(3):
                call(cpu,read,layout["lan_ring"],dst,960)
                stereo = np.frombuffer(cpu.mem_read(dst,3840),dtype="<i2")
                assert np.array_equal(stereo[::2],stereo[1::2])
                audio.extend(stereo[::2].tobytes())
    assert audio == samples.tobytes()
    return np.frombuffer(audio,dtype="<i2"),sha256(dat).hexdigest()


def real_if(path):
    iq = np.fromfile(path,dtype=np.uint8).astype(float).reshape(-1,2)-127.5
    z = iq[:,0]+1j*iq[:,1]
    return np.round(160*np.real(z*(1j**(np.arange(len(z))%4)))).astype("<i2")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-wav",type=Path,help="Inspect 48 kHz 16-bit PCM carrying a 12 kHz real IF")
    parser.add_argument("--channel",type=int,choices=[1,2],default=1,help="Input WAV channel, numbered from 1")
    parser.add_argument("--voice-out",type=Path,help="Write a new audio file for a single recognised group call")
    args = parser.parse_args()
    if args.voice_out and (not args.if_wav or args.voice_out.exists()):
        parser.error("--voice-out requires an IF capture and a new output filename")
    decoder = arm_decoder()
    if args.if_wav:
        with wave.open(str(args.if_wav),"rb") as wav:
            channels = wav.getnchannels()
            if channels not in (1,2) or args.channel>channels or (wav.getsampwidth(),wav.getframerate()) != (2,48000):
                parser.error("Expected 48 kHz, 16-bit mono/stereo IF with the selected channel present")
            audio = np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2")[args.channel-1::channels]
        if len(audio)<1320:
            parser.error("Capture shorter than one DMR burst")
        found = []
        for name,pair in SYNC_PAIRS.items():
            if args.voice_out:
                headers, frames = receive(audio,decoder,voice=True,sync_pair=pair)
                if headers:
                    found.append((headers,frames))
            else:
                headers = receive(audio,decoder,sync_pair=pair)
            print(name,headers)
        if args.voice_out:
            if len(found)!=1 or len(found[0][0])!=1 or found[0][0][0]["headers"]!=1 or not found[0][1]:
                parser.error("Audio export requires one verified group header and recoverable voice")
            write_wav(args.voice_out,transform(found[0][1],encode=False)[0])
        sys.exit(0)
    path = UP/"tests/fixtures/iq/dmr_voice_synth.iq"
    pcm = real_if(path)
    expected = [{"color_code":2,"source":1001,"talkgroup":100,"headers":1}]
    samples = len(pcm)
    pcm = np.pad(pcm,(0,(-len(pcm))%2880))
    results = {"fixture":path.name,"fixture_sha256":sha256(path.read_bytes()).hexdigest(),
               "upstream_revision":subprocess.check_output(["git","-C",UP,"rev-parse","HEAD"],text=True).strip(),
               "samples":samples,"method":"Independent synthetic BS group call shifted to real IF, zero-padded for the final read. Stock SSIF5 DMA/reader emulated. Host demodulation; separate ARM header and voice decoding. No RF or real-time scheduling.",
               "regions":{}}
    for region in "JE":
        recovered, digest = firmware_if(region,pcm)
        headers, frames = receive(recovered,decoder,voice=True)
        assert headers == expected,headers
        decoded, _, corrections = transform(frames,encode=False)
        n = len(frames)//9
        assert n == 162 and corrections == {0:n} and any(decoded), (n,corrections)
        results["regions"][region] = dict(dat_sha256=digest,headers=headers,voice_frames=n,
            clean_frames=n,pcm_sha256=sha256(decoded).hexdigest(),voice_sha256=sha256(frames).hexdigest())
    assert results["regions"]["J"]["pcm_sha256"] == results["regions"]["E"]["pcm_sha256"]
    write_wav(HERE/"rx-group-through-tail.wav",decoded)
    for control,signal in [("silence",np.zeros_like(pcm)),("noise",np.random.default_rng(705).normal(0,3000,len(pcm))),
                           ("truncated_before_call",pcm[:6000])]:
        assert not receive(signal,decoder),control
    results["controls_no_headers"] = ["silence","seeded white noise","truncated before call"]
    control_path = path.with_name("dmr_voice.iq")
    control_if = real_if(control_path)
    assert receive(control_if,decoder,voice=True) == ([],b"")
    results["off_air_control"] = dict(fixture=control_path.name,sha256=sha256(control_path.read_bytes()).hexdigest(),
        samples=len(control_if),group_voice_headers=0,voice_frames_output=0,
        provenance="Upstream identifies the recording as a control channel; the filename is historical.")
    (HERE/"rx-header-through-tail.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(results,indent=2))
