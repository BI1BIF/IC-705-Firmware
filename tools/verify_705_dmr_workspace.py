"""Compare the old and small-stack card codecs through speech, tone and mute."""
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_705_dmr_station import OUT, ROOT, symbols
from tools.emulate_705 import SCRATCH, SP, arm, call, machine

# Parameter vectors from mbelib-neo/tests/test_ambe2450_frame_types.c,
# packed MSB first with seven padding bits. The tone uses ID 37, AD 127.
VOICE, NEXT, TONE, ERASE, SILENCE = (
    0x51F32544D80F00, 0x72A64B8A742F00, 0xFFF25252525800,
    0xF0000000010000, 0xF801A99F8CE080,
)
CASES = [VOICE, NEXT, TONE, TONE, VOICE, NEXT, *([ERASE]*6), VOICE, SILENCE, NEXT]


def replay(folder):
    core = folder/"core"
    layout = json.loads((core/"payload.json").read_text())
    base = layout["link_base"]
    sy = symbols(core/f"payload-{base:08x}.elf")
    card = (folder/"J/DMRRX.BIN").read_bytes()
    assert card == (folder/"E/DMRRX.BIN").read_bytes()
    c = machine()
    c.mem_write(base, card[:layout["image_bytes"]])
    c.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xf00000)
    c.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    c.mem_write(SP-32768, b"\xa5"*32768)
    call(c,sy["dmr_audio_reset"])
    output = bytearray()
    flags = []
    for frame in CASES * 3:
        c.mem_write(SCRATCH, bytes((frame >> bit) & 1 for bit in range(55,6,-1)))
        result, pcm = SCRATCH+64, SCRATCH+128
        call(c,sy["mbe_initProcessResult"],result)
        assert call(c,sy["mbe_processAmbe2450Dataf"],pcm,result,SCRATCH,
                    sy["current"],sy["previous"],sy["enhanced"],instruction_limit=4_000_000)==0
        flags.append(int.from_bytes(c.mem_read(result+16,4),"little"))
        output.extend(c.mem_read(pcm,640))
    for flag in (0x10,0x20,0x40,0x80,0x100):
        assert any(v & flag for v in flags)
    paint = c.mem_read(SP-32768,32768)
    return dict(card=sha256(card).hexdigest(), float_pcm=sha256(output).hexdigest(),
                flags=flags, codec_stack_writes=32768-next(i for i,b in enumerate(paint) if b!=0xa5))


if __name__=="__main__":
    before = replay(ROOT/".analysis/dmr-rx5-start/final")
    after = replay(OUT)
    assert before["float_pcm"]==after["float_pcm"] and before["flags"]==after["flags"]
    assert after["codec_stack_writes"]<before["codec_stack_writes"]
    report = dict(frames=len(after["flags"]),old=before,new=after)
    (OUT/"codec-transitions.json").write_text(json.dumps(report,indent=2)+"\n")
    print(before["codec_stack_writes"],after["codec_stack_writes"],after["float_pcm"])
