"""Run known DMR speech through a linked ARM codec and the v1.4.0 playback DMA."""
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/".analysis/ic705-emulator/deps")]
from tools.build_705_dmr_audio import build, build_payload, LINK_BASE, OUT, STUDY
from tools.decode_705_main import decode_main
from tools.emulate_705 import BASE, SCRATCH, SP, arm, call, machine

TEST_BASE = 0x20800000


def verify(region, voice, reference):
    folder = OUT / region
    sym = build(region, TEST_BASE, folder)
    package = ROOT / ".analysis/aprs-hop/smart-final" / region
    dat = (package/f"705{region}140.dat").read_bytes()
    manifest = json.loads((package/"package.json").read_text())
    main = bytes(decode_main(dat)[1])
    assert sha256(dat).hexdigest() == manifest["sha256"]
    assert sha256(main).hexdigest() == manifest["main_sha256"]
    delta = 0 if region == "J" else 228
    cpu = machine(main)
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xf00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    cpu.mem_map(0xe8200000, 0x1000)
    cpu.mem_write(TEST_BASE, (folder/"audio.bin").read_bytes())
    def native(pc, *args):
        return call(cpu, pc+delta, *args, timeout_us=0)
    def codec(name, *args):
        return call(cpu, sym[name], *args, timeout_us=0, instruction_limit=10_000_000)
    def u32(p):
        return int.from_bytes(cpu.mem_read(p, 4), "little")
    def write32(p, n):
        cpu.mem_write(p, struct.pack("<I", n))
    irq_call = 0x200ffd9c + delta
    assert u32(irq_call) == 0xebfffddf
    target = sym["dmr_audio_dma_read"]
    write32(irq_call, 0xeb000000 | (((target - irq_call - 8) // 4) & 0xffffff))
    # Execute the stock initialization fragment which builds both SSIF0 TDMA descriptors.
    cpu.reg_write(arm.UC_ARM_REG_R4, 0xe8200000)
    cpu.reg_write(arm.UC_ARM_REG_R5, 288)
    cpu.emu_start(0x200fef1c+delta, 0x200fef40+delta)
    banks = [struct.unpack("<III", cpu.mem_read(0xe8200100+i*12, 12)) for i in range(2)]
    assert banks == [(0x20400a40,0xe820b018,288),(0x20400b60,0xe820b018,288)]
    n = 0
    def dma():
        nonlocal n
        bank = n % 2
        n += 1
        write32(0xe8200124, 0x41 if bank else 0xc1)
        native(0x200ffd48)
        slots = struct.unpack("<72i", cpu.mem_read(banks[bank][0], 288))
        # Native interpolation format puts each 8 kHz sample first, then five zeros.
        assert all(slots[i] == 0 for i in range(72) if i % 12)
        return struct.pack("<6h", *(word >> 16 for word in slots[::12]))
    def decode_frame(frame):
        cpu.mem_write(SCRATCH, frame)
        return codec("dmr_audio_frame", SCRATCH)

    cpu.mem_write(SP-0x8000, b"\xa5"*0x8000)
    codec("dmr_audio_reset")
    assert decode_frame(voice[:9]) == 0
    assert dma() == bytes(12)  # menu off
    write32(sym["dmr_audio_active"], 1)
    marker = struct.pack("<6h", 101,-102,103,-104,105,-106)
    cpu.mem_write(SCRATCH, marker)
    native(0x200ff4d8, SCRATCH)
    assert dma() == marker and dma() == bytes(12)
    for address, value in ((0x203806f4,0x20),(0x203806f4,0x80),(0x203809a1,0x10),
                           (0x203809ac,1),(0x203809b0,1)):
        assert decode_frame(voice[9:18]) == 0
        cpu.mem_write(address, bytes([value]))
        assert dma() == bytes(12)
        cpu.mem_write(address, bytes(1))
        assert dma() == bytes(12)
    codec("dmr_audio_reset")
    for i in range(6):
        assert decode_frame(voice[9*i:9*i+9]) == 0
    assert decode_frame(voice[54:63]) == 0xffffffff
    codec("dmr_audio_reset")
    output = bytearray()
    frames = len(voice)//9
    for start in range(0, frames, 3):
        count = min(3, frames-start)
        for i in range(start, start+count):
            assert decode_frame(voice[9*i:9*i+9]) == 0
        for _ in range((count*160+5)//6):
            output.extend(dma())
    assert output[:len(reference)] == reference and not any(output[len(reference):])
    assert dma() == bytes(12)
    trace_stack = bytes(cpu.mem_read(SP-0x8000,0x8000))
    used = 0x8000 - next(i for i,b in enumerate(trace_stack) if b != 0xa5)
    return dict(region=region, base_dat_sha256=manifest["sha256"], placement="emulator-only injected image",
                image_base=hex(TEST_BASE), compiled_bytes=(folder/"audio.bin").stat().st_size,
                memory_span=sym["_end"]-TEST_BASE, heap_peak=u32(sym["dmr_audio_heap_peak"]),
                observed_stack_watermark=used, hooked_call=hex(irq_call), dma_fifo=hex(banks[0][1]),
                speech_frames=frames, pcm_samples=len(reference)//2,
                all_native_playback_slot_samples_match=True, all_modulation_slot_samples_zero=True,
                pcm_sha256=sha256(reference).hexdigest(), waveform_at_speaker="requires radio and IF DSP",
                controls=["inactive menu","native playback wins and clears pending audio",
                          "remote TX","stock TX","DSP TX","PTT request","filtered request",
                          "full queue retry","empty queue","alternating native DMA banks"])


def relocated(voice, reference):
    folder = OUT / "core"
    payload = build_payload(folder)
    elf = folder/f"payload-{LINK_BASE:08x}.elf"
    table = subprocess.check_output(["arm-none-eabi-readelf","-sW",elf],text=True)
    syms = {w[7]:int(w[1],16)-LINK_BASE for line in table.splitlines()
            if len(w:=line.split())>=8 and w[0][:-1].isdigit() and w[4]=="GLOBAL"}
    result = []
    for region, base in (("J",0x207a5040), ("E",0x208718c0)):
        cpu = machine()
        cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xf00000)
        cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
        data = bytearray(payload["image"])
        for index in payload["relocs"]:
            word, = struct.unpack_from("<I",data,4*index)
            struct.pack_into("<I",data,4*index,word+base-LINK_BASE)
        cpu.mem_write(base,bytes(data))
        cpu.mem_write(SP-0x8000,b"\xa5"*0x8000)
        def run(name,*args):
            return call(cpu,base+syms[name],*args,instruction_limit=10000000,timeout_us=0)
        run("dmr_audio_reset")
        output=bytearray()
        for frame in range(0,len(voice)//9,3):
            n=min(3,len(voice)//9-frame)
            for i in range(frame,frame+n):
                cpu.mem_write(SCRATCH,voice[i*9:i*9+9])
                assert run("dmr_audio_frame",SCRATCH)==0
            samples=n*160
            while samples:
                count=run("dmr_audio_pull6",SCRATCH)
                assert count==min(6,samples)
                output.extend(cpu.mem_read(SCRATCH,count*2))
                samples-=count
        assert output==reference
        stack=bytes(cpu.mem_read(SP-0x8000,0x8000))
        result.append(dict(layout=region,base=hex(base),frames=len(voice)//9,
                           pcm_sha256=sha256(output).hexdigest(),
                           heap_peak=int.from_bytes(cpu.mem_read(base+syms["dmr_audio_heap_peak"],4),"little"),
                           stack_watermark=0x8000-next(i for i,b in enumerate(stack) if b!=0xa5)))
    return result


if __name__ == "__main__":
    voice = (STUDY/"dmr-reference/voice9.bin").read_bytes()
    with wave.open(str(STUDY/"dmr-reference/reference.wav"),"rb") as wav:
        reference = wav.readframes(wav.getnframes())
    result = [verify(region,voice,reference) for region in "JE"]
    (OUT/"results.json").write_text(json.dumps(result, indent=2)+"\n")
    relocated_result=relocated(voice,reference)
    (OUT/"relocated-results.json").write_text(json.dumps(relocated_result,indent=2)+"\n")
    print(json.dumps(result, indent=2))
