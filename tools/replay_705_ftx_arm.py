"""Run the panel codec as a standalone Cortex-A9 ELF and measure its workspace."""
import json
from pathlib import Path
from struct import pack, unpack
import subprocess
import wave

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn import arm_const as arm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".analysis/ftx-station"
LIB = ROOT / ".analysis/ftx-lib"
SP = 0x400000
STOP = 0x4F0000
PCM = 0x300000
MESSAGE = 0x380000


def build():
    elf = OUT / "station-arm.elf"
    names = "rx_push rx_end tx_slot row_text row_hz row_score row_snr row_sender".split()
    keep = ["-u," + name for name in names]
    sources = [ROOT / "samples/ftx/station.c", LIB / "common/monitor.c",
               *sorted((LIB/"ft8").glob("*.c")), *sorted((LIB/"fft").glob("*.c"))]
    subprocess.run(["arm-none-eabi-gcc", "-Os", "-mthumb", "-mcpu=cortex-a9", "-mfpu=vfpv3-d16",
                    "-mfloat-abi=softfp", "-ffunction-sections", "-fdata-sections", "-DHAVE_STPCPY",
                    "-DLOG_PRINTF(...)=((void)0)", "-I", LIB, *sources, "-nostartfiles",
                    "--specs=nano.specs", "--specs=nosys.specs",
                    "-Wl,--gc-sections,-e,rx_begin,-Ttext=0x100000," + ",".join(keep),
                    "-o", elf, "-lm"], check=True)
    return elf


def replay(elf, mode):
    ft4 = int(mode=="FT4")
    cpu=Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    cpu.mem_map(0x100000,0x400000)
    with elf.open("rb") as f:
        image=ELFFile(f)
        symbols={s.name:s["st_value"] for s in image.get_section_by_name(".symtab").iter_symbols()}
        for ph in image.iter_segments():
            if ph["p_type"]=="PT_LOAD":
                cpu.mem_write(ph["p_vaddr"],ph.data())
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2,0xF00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC,0x40000000)
    regs=[arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3]

    def call(name,*args):
        for reg,value in zip(regs,args):
            cpu.reg_write(reg,value)
        cpu.reg_write(arm.UC_ARM_REG_SP,SP)
        if len(args)>4:
            cpu.mem_write(SP,pack("<I",args[4]))
        cpu.reg_write(arm.UC_ARM_REG_LR,STOP|1)
        cpu.emu_start(symbols[name],STOP,timeout=30_000_000)
        if cpu.reg_read(arm.UC_ARM_REG_PC)!=STOP:
            raise RuntimeError(f"{name} did not return")
        return cpu.reg_read(regs[0])

    text=b"JA1ABC K1ABC PM95"
    cpu.mem_write(MESSAGE,text+b"\0")
    slot=90000 if ft4 else 180000
    assert call("tx_slot",ft4,MESSAGE,1000,PCM,slot)==slot
    dest=OUT / mode / "arm"
    dest.mkdir(exist_ok=True, parents=True)
    with wave.open(str(dest/"261119_120000.wav"),"wb") as wav:
        wav.setparams((1,2,12000,0,"NONE","not compressed"))
        wav.writeframes(bytes(cpu.mem_read(PCM,2*slot)))
    cpu.mem_write(SP-65536,b"\xA5"*65536)
    call("rx_begin",ft4)
    for i in range(0,slot,480):
        call("rx_push",PCM+2*i,min(480,slot-i))
    count=call("rx_end")
    assert count==1
    ptr=call("row_text",0)
    assert bytes(cpu.mem_read(ptr,35)).split(b"\0")[0]==text
    stack=bytes(cpu.mem_read(SP-65536,65536))
    high=unpack("<I",cpu.mem_read(symbols["heap_end.0"],4))[0]
    return dict(message=text.decode(),rows=count,decoded_hz=call("row_hz",0),
                heap_growth_bytes=high-symbols["_end"],
                rx_stack_written_bytes=65536-next(i for i,b in enumerate(stack) if b!=0xA5))


if __name__=="__main__":
    OUT.mkdir(parents=True,exist_ok=True)
    elf=build()
    report={mode:replay(elf,mode) for mode in ("FT8","FT4")}
    report["arm_size"]=subprocess.check_output(["arm-none-eabi-size",elf],text=True).splitlines()[1].split()[:3]
    (OUT / "arm-check.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
