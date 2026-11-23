"""Link the single-worker DMR speech decoder for an explicitly placed J/E image."""
import argparse
from pathlib import Path
import json
import re
from shutil import copyfile
import struct
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / ".analysis/dmr-if-study"
OUT = ROOT / ".analysis/dmr-audio"
LIB = STUDY / "mbelib-neo"
ARCHIVE = STUDY / "arm-build"
UPSTREAM = "071f478d1736206d1c39b6edb5cfe0f0c7454233"


def _compile_codec(folder):
    folder.mkdir(parents=True, exist_ok=True)
    assert subprocess.check_output(["git", "-C", LIB, "rev-parse", "HEAD"], text=True).strip() == UPSTREAM
    flags = ["-mcpu=cortex-a9", "-marm", "-mfpu=vfpv3-d16", "-mfloat-abi=softfp",
             "-ffunction-sections", "-fdata-sections", "-Os", "-DNDEBUG", "-std=gnu99",
             "-DMBE_BUILDING=1", "-DPFFFT_SIMD_DISABLE=1", "-DPFFFT_STATIC_DEFINE"]
    includes = [LIB/"include", ARCHIVE/"include", LIB, LIB/"src/internal",
                ARCHIVE/"_deps/mbelib_pffft-src/include/pffft", LIB/"tools/quality"]
    flags += ["-I" + str(path) for path in includes]
    # Only the decoder thread calls these routines. Its largest synthesis
    # temporaries live in the module's BSS, allocated once per reception.
    objects = []
    modified = ("ambe/ambe3600x2450.c", "core/mbe_subframe.c")
    with TemporaryDirectory() as temporary:
        tree = Path(temporary)
        for src in modified:
            dest = tree/"src"/src
            dest.parent.mkdir(parents=True, exist_ok=True)
            copyfile(LIB/"src"/src, dest)
        subprocess.run(["git", "apply", "--no-index", ROOT/"samples/dmr-codec-workspace.patch"], cwd=tree, check=True)
        for src in (*modified, "imbe/imbe7200x4400.c", "core/mbelib.c", "core/mbe_adaptive.c", "core/mbe_unvoiced_fft.c"):
            original = LIB/"src"/src
            source = tree/"src"/src if src in modified else original
            obj = folder/(original.stem+".o")
            subprocess.run(["arm-none-eabi-gcc", *flags, "-I"+str(original.parent),
                            "-D__thread=", "-c", source, "-o", obj], check=True)
            objects.append(obj)
    return flags, objects


def build(region, base, folder):
    flags, objects = _compile_codec(folder)
    elf = folder / "audio.elf"
    delta = 0 if region == "J" else 228
    read = 0x200ff520 + delta
    used = 0x200ff4c4 + delta
    link = (f"-Wl,--gc-sections,-e,dmr_audio_reset,-u,dmr_audio_dma_read,-u,dmr_audio_frame,"
            f"--defsym,native_playback_read={read:#x},--defsym,native_playback_queued={used:#x},"
            f"-Ttext={base:#x},-Map={folder/'audio.map'}")
    with (folder/"compile.log").open("w") as log:
        subprocess.run(["arm-none-eabi-gcc", *flags, "-nostartfiles", "--specs=nosys.specs", link,
                        ROOT/"samples/dmr-audio.c", ROOT/"samples/dmr-audio-arena.c", *objects,
                        ARCHIVE/"libmbe-neo.a", "-lm", "-o", elf], check=True, stdout=log, stderr=log)
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", elf, folder/"audio.bin"], check=True)
    symbols = {}
    for line in subprocess.check_output(["arm-none-eabi-nm", "-n", elf], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    assert not any(x.startswith("__emutls") for x in symbols)
    return symbols


ENTRY = ("dmr_core_input", "dmr_core_work", "dmr_core_status", "dmr_audio_pull6", "dmr_core_switch")
LINK_BASE = 0x20700000


def _link_payload(folder, flags, objects, base, core):
    dsd = STUDY/"dsd-neo"
    name = f"payload-{base:08x}"
    script = folder / (name+".ld")
    script.write_text(f"""
SECTIONS {{
 . = {base:#x};
 .text : {{ *(.text .text.* .gnu.linkonce.t.*) }}
 .rodata : {{ *(.rodata .rodata.* .gnu.linkonce.r.*) }}
 .ARM.exidx : {{ *(.ARM.exidx*) }}
 .data : {{ *(.got .got.* .data .data.* .sdata .sdata.*) }}
 .bss (NOLOAD) : {{ *(.bss .bss.* .sbss .sbss.* COMMON) }}
 _end = .;
 /DISCARD/ : {{ *(.comment .note .note.*) }}
}}
""", encoding="ascii")
    elf = folder/(name+".elf")
    link = ["-Wl,--gc-sections,--emit-relocs,-e,dmr_core_input", *["-Wl,-u,"+e for e in ENTRY],
            "-T", script]
    # ARMv5TE/VFP softfp math and C libraries use relocatable literal-pool
    # words. The ARMv7 Thumb builds encode absolute addresses across MOVW/MOVT
    # immediates, which the resident word-only relocator cannot adjust.
    runtime = [subprocess.check_output(["arm-none-eabi-gcc", "-marm","-march=armv5te+fp","-mfloat-abi=softfp",
                                        "-print-file-name="+lib],text=True).strip()
               for lib in ("libm.a","libc.a","libgcc.a","libnosys.a")]
    assert all(Path(path).is_file() for path in runtime)
    with (folder/(name+".log")).open("w") as log:
        subprocess.run(["arm-none-eabi-gcc", *flags, "-I"+str(dsd/"include"), "-I"+str(ROOT/"samples"),
                        "-nostdlib", *link, core,
                        ROOT/"samples/dmr-audio.c", ROOT/"samples/dmr-audio-arena.c", ROOT/"samples/dmr-radio.c",
                        ROOT/"samples/dmr-digital.c", ROOT/"samples/dmr-rx-header.c", *[dsd/"src/fec"/f for f in ("bptc.c","fec.c","rs-12-9.c")],
                        *objects, ARCHIVE/"libmbe-neo.a", "-Wl,--start-group", *runtime, "-Wl,--end-group",
                        "-o", elf], check=True, stdout=log, stderr=log)
    binary = folder/(name+".bin")
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", elf, binary], check=True)
    table = subprocess.check_output(["arm-none-eabi-readelf", "-sW", elf], text=True)
    symbols = {parts[7]:int(parts[1],16) for line in table.splitlines()
               if len(parts:=line.split())>=8 and parts[0][:-1].isdigit() and parts[4]=="GLOBAL"}
    assert {"native_playback_read", "native_playback_queued", "dmr_audio_dma_read"}.isdisjoint(symbols)
    assert not any(x.startswith("__emutls") for x in symbols)
    data = binary.read_bytes()
    return data.ljust((len(data)+3)//4*4,b"\0"), symbols, elf


def build_payload(folder):
    """Return a BSS-zeroed, 64-byte-aligned load image with relative entry offsets."""
    folder = Path(folder).resolve()
    flags, objects = _compile_codec(folder)
    core = ROOT / "samples/dmr-core.c"
    image, syms, elf = _link_payload(folder, flags, objects, LINK_BASE, core)
    mem_bytes = syms["_end"] - LINK_BASE
    offsets = {e:syms[e]-LINK_BASE for e in ENTRY}
    relocation_text = subprocess.check_output(["arm-none-eabi-readelf","-rW",elf],text=True)
    absolute = set()
    target_section = ""
    for line in relocation_text.splitlines():
        section = re.match(r"Relocation section '[.]rela?([^']+)'", line)
        if section:
            target_section = section[1]
            continue
        if target_section not in (".text",".rodata",".data",".ARM.exidx"):
            continue
        parts = line.split()
        if len(parts)<3 or not re.fullmatch(r"[0-9a-fA-F]{8}",parts[0]):
            continue
        kind = parts[2]
        if kind in ("R_ARM_ABS32","R_ARM_TARGET1"):
            address = int(parts[0],16) - LINK_BASE
            assert address%4 == 0 and 0 <= address < len(image), (hex(address),kind)
            absolute.add(address//4)
        elif kind not in {"R_ARM_CALL","R_ARM_JUMP24","R_ARM_THM_CALL","R_ARM_THM_JUMP24","R_ARM_THM_JUMP11",
                          "R_ARM_THM_JUMP8","R_ARM_REL32","R_ARM_PREL31","R_ARM_V4BX","R_ARM_GOTOFF32",
                          "R_ARM_BASE_PREL","R_ARM_GOT_BREL","R_ARM_NONE"}:
            raise ValueError(f"unhandled payload ELF relocation {kind} at {parts[0]}")
    relocs = set()
    for adjustment in (0x10000,0x24c0):
        check, shifted, _ = _link_payload(folder,flags,objects,LINK_BASE+adjustment,core)
        assert len(check) == len(image) and shifted["_end"]-syms["_end"]==adjustment
        assert all(shifted[e]==syms[e]+adjustment for e in ENTRY)
        changed = set()
        for i,(a,b) in enumerate(zip(struct.iter_unpack("<I",image),struct.iter_unpack("<I",check),strict=True)):
            if a==b:
                continue
            assert b[0]-a[0]==adjustment and LINK_BASE <= a[0] <= LINK_BASE+mem_bytes, (i,a,b)
            assert i<=0xffff
            changed.add(i)
        if relocs and relocs!=changed:
            raise ValueError("storage relocations differ between 64 KiB and 64-byte-aligned links")
        relocs=changed
    # Runtime GOT entries can be linker-generated absolute words without an ELF relocation.
    assert absolute <= relocs, sorted(absolute-relocs)
    indices = tuple(sorted(relocs))
    (folder/"payload.bin").write_bytes(image)
    (folder/"reloc.u16").write_bytes(struct.pack(f"<{len(indices)}H",*indices))
    info = dict(link_base=LINK_BASE, mem_bytes=mem_bytes, offsets=offsets, image_bytes=len(image),
                reloc_words=len(indices), explicit_abs32_words=len(absolute), alignment=64)
    (folder/"payload.json").write_text(json.dumps(info,indent=2)+"\n")
    return dict(image=image, relocs=indices, offsets=offsets, mem_bytes=mem_bytes, link_base=LINK_BASE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("region", choices=["J", "E"])
    parser.add_argument("--base", type=lambda x: int(x, 0), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.region, args.base, args.output)
