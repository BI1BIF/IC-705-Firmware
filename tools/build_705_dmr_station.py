"""Add digital voice reception to J140/E140 firmware based on v1.4.0."""
from decimal import Decimal, localcontext
from hashlib import md5, sha256
import json
from pathlib import Path
from struct import iter_unpack, pack, pack_into, unpack_from
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/".analysis/ic705-emulator/deps"),str(ROOT/".analysis/ftx-tools")]
from elftools.elf.elffile import ELFFile
from tools.build_705_aprs_slot import FIRST_OFFSET, FT_OUT, scatter
from tools.build_705_dmr_audio import build_payload
from tools.build_705_dmr_ui import compile_ui, ui_imports, apply_hooks
from tools.build_705_ft_log_timezone import BASELINES, apply_timezone
from tools.build_705_ftx_rx import pack_init_tail
from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_main
from tools.dmr_tx_guard import MAX_BYTES, install_guard
from tools.emulate_705 import BASE, machine
from tools.replay_705_aprs_task import e140_rom
from tools.replay_705_nor_boot import with_pc_main
from tools.replay_705_stock_install import load_a
from tools.verify_705_ftx_rx import symbols

RX11=ROOT/".analysis/digital-rx11/final"
OUT=ROOT/".analysis/digital-rx12/final"
RELEASE=ROOT/".analysis/release-v1.4.0"

def sha_constants():
    primes=[]
    i=2
    while len(primes)<64:
        if all(i%p for p in primes if p*p<=i): primes.append(i)
        i+=1
    with localcontext() as ctx:
        ctx.prec=60
        return [int((Decimal(p)**(Decimal(1)/3))*(1<<32))&0xffffffff for p in primes]

def resource(payload,folder,core_folder):
    data=payload["image"]
    raw=data+pack(f"<{len(payload['relocs'])}H",*payload["relocs"])
    assert len(data)%4==0 and len(raw)<=payload["mem_bytes"]
    (folder/"DMRRX.BIN").write_bytes(raw)
    layout=dict(RESOURCE_BYTES=len(raw),IMAGE_BYTES=len(data),RELOC_COUNT=len(payload["relocs"]),
                LINK_BASE=payload["link_base"], MEM_BYTES=payload["mem_bytes"])
    # Export the playback counter from this exact build of the card module.
    core_elf=core_folder/f"payload-{payload['link_base']:08x}.elf"
    position=symbols(core_elf)["produced"]-payload["link_base"]
    assert len(data)<=position<=payload["mem_bytes"]-4 and position%4==0
    layout["AUDIO_PRODUCED"]=position
    layout["CORE_MODE"]=symbols(core_elf)["digital_mode"]-payload["link_base"]
    layout["CORE_TUNE"]=symbols(core_elf)["frequency"]-payload["link_base"]
    for macro,name in (("CORE_INPUT","dmr_core_input"),("CORE_WORK","dmr_core_work"),
                       ("CORE_STATUS","dmr_core_status"),("AUDIO_PULL","dmr_audio_pull6"),("CORE_SWITCH","dmr_core_switch")):
        layout[macro]=payload["offsets"][name]
    defines="".join(f"#define {name} {v}u\n" for name,v in layout.items())
    for name,words in (("CONSTANTS",sha_constants()),("EXPECTED",unpack_from(">8I",sha256(raw).digest()))):
        defines+="#define DMR_SHA_"+name+" {"+",".join(hex(x)+"u" for x in words)+"}\n"
    (folder/"dmr-layout.h").write_text(defines,encoding="ascii")

def branch(site,target,link=True):
    delta=(target&~1)-site-8
    assert -(1<<25)<=delta<(1<<25)
    if target&1:
        assert link
        return 0xfa000000|((delta&2)<<23)|((delta>>2)&0xffffff)
    return (0xeb000000 if link else 0xea000000)|((delta>>2)&0xffffff)

def build(region,payload,*,output=None,rx_lamp=True,aprs_base=None,ft_timezone=False):
    output=output or OUT
    folder=output/region
    folder.mkdir(parents=True,exist_ok=True)
    name=f"705{region}140.dat"
    aprs_meta={}
    if aprs_base is None:
        dat=bytearray((RELEASE/"verified"/name).read_bytes())
        assert BASELINES[sha256(dat).hexdigest()]==region
        aprs_base=RELEASE/"rebuild"/region
    else:
        dat=bytearray((aprs_base/name).read_bytes())
        aprs_meta=json.loads((aprs_base/"package.json").read_text())
        assert aprs_meta["region"]==region and aprs_meta["sha256"]==sha256(dat).hexdigest()
    original=bytes(decode_main(bytes(dat))[1])
    _,flash=load_a(bytes(dat),sha256(original).hexdigest())
    main=bytearray(original)
    resource(payload,folder,(OUT if rx_lamp else RX11)/"core")
    rom=e140_rom if region=="E" else lambda a:a
    ft=symbols(FT_OUT/"rx.elf")
    aprs=symbols(aprs_base/"manager.elf")
    desc=unpack_from("<I",main,0x2e4)[0]-BASE
    src,dst,n,copy=unpack_from("<4I",main,desc)
    legacy_src,legacy_dst,legacy_n,legacy_copy=unpack_from("<4I",main,0x30c)
    assert copy==legacy_copy==0x200052ec and (legacy_src,legacy_dst)==(src,dst) and n<=legacy_n
    assert {i*4 for i,(v,) in enumerate(iter_unpack("<I",main)) if src<=v<src+n}=={desc,0x30c}
    packed=pack_init_tail(main[src-BASE:src-BASE+n],0)
    if legacy_n!=n:
        packed+=pack_init_tail(main[src-BASE+n:src-BASE+legacy_n],0)
    code=(src+len(packed)+3)&~3
    imports=ui_imports(region,aprs)
    for key,a in dict(sd_open=0x2023fec8,sd_read=0x2023ff00,sd_close=0x2023fee4,
        radio_alloc=0x20127a28,radio_free=0x20127a78,make_thread=0x202d48c1,
        signal_thread=0x202d4851,wait_signal=0x202d488c,native_playback_read=0x200ff520,
        native_playback_queued=0x200ff4c4,stock_playback_page=0x200f1150).items(): imports[key]=rom(a)
    imports.update({k:aprs[k] for k in ("aprs_overlay_unload","aprs_slot_copy","aprs_slot_note")})
    fm=aprs["plain_fm"]
    assert unpack_from("<I",main,fm-BASE)[0]==0xe59f2078
    imports.update(restore_modes=ft["ft_restore_modes"]|1,fm_literal=unpack_from("<I",main,fm+128-BASE)[0],fm_resume=fm+4)
    ld="\n".join(f"{k} = {v:#x};" for k,v in imports.items())+f"""
SECTIONS {{
 .code {code:#x} : {{ *(.text*) *(.rodata*) *(.data*) }}
 .work ALIGN(4) (NOLOAD) : {{ __work_start = .; *(.bss*) *(COMMON) . = ALIGN(4); __work_end = .; }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) }}
}}"""
    (folder/"station.ld").write_text(ld,encoding="ascii")
    objects=[compile_ui(folder)]
    sources=["dmr-station.c","dmr-resource.c","dmr-station.S"]
    for stem in sources:
        obj=folder/(Path(stem).name+".o")
        subprocess.run(["arm-none-eabi-gcc","-c","-Oz","-mcpu=cortex-a9","-mthumb","-mlong-calls",
            "-mfloat-abi=softfp","-mfpu=vfpv3-d16","-ffreestanding","-fno-builtin","-Wall","-Werror",
            *(["-DDMR_LONG_INIT"] if legacy_n!=n else []),
            *(["-DDMR_RX_LAMP"] if rx_lamp else []),
            "-I",folder,ROOT/"samples"/stem,"-o",obj],check=True)
        objects.append(obj)
    elf=folder/"station.elf"
    subprocess.run(["arm-none-eabi-ld","-T",folder/"station.ld",*objects,"-o",elf],check=True)
    sy=symbols(elf)
    with elf.open("rb") as f: text=ELFFile(f).get_section_by_name(".code").data()
    guard=sy["__work_end"]
    assert guard+MAX_BYTES<=src+n,(hex(guard+MAX_BYTES),hex(src+n))
    main[src-BASE:src-BASE+n]=bytes(n)
    main[src-BASE:src-BASE+len(packed)]=packed
    main[code-BASE:code-BASE+len(text)]=text
    for record in (desc,0x30c): pack_into("<I",main,record+12,sy["dmr_restore"]&~1)
    if legacy_n!=n: pack_into("<I",main,0x30c+12,sy["dmr_restore_long"]&~1)
    apply_hooks(main,region,sy,aprs=aprs)
    if rx_lamp:
        site=rom(0x2006137c)
        # RX LED preference enabled, ordinary receive, replace only BFI bit 0.
        assert unpack_from("<5I",main,site-16-BASE)==(0xe5d113f1,0xe3510000,0x0a00000c,0xe5dd1000,0xe7c00011)
        pack_into("<I",main,site-BASE,branch(site,sy["dmr_rx_lamp"]))
    for site,target,old in ((rom(0x2010fe30),"dmr_input",aprs["aprs_slot_copy"]),
            (rom(0x200622e8),"dmr_monitor_page",rom(0x200f1150)),
            (rom(0x200ffd9c),"dmr_play",rom(0x200ff520)),
            (aprs["aprs_slot_dma"]+12,"dmr_note",aprs["aprs_slot_note"])):
        assert unpack_from("<I",main,site-BASE)[0]==branch(site,old)
        pack_into("<I",main,site-BASE,branch(site,sy[target]))
    pack_into("<I",main,fm-BASE,branch(fm,sy["aprs_fm_guard"],False))
    lock=install_guard(main,region,guard,sy["dmr_guard_active"])
    ref,cpu=machine(original),machine(bytes(main))
    # Exercise both descriptor lengths directly, including the byte after
    # each destination. A normal application boot only selects one table.
    from tools.emulate_705 import call
    for record in (desc,0x30c):
        for c,data in ((ref,original),(cpu,main)):
            source,dest,count,method=unpack_from("<4I",data,record)
            c.mem_write(dest-1,b"\xa5"*(legacy_n+2))
            call(c,method|1,source,dest,count)
        assert ref.mem_read(dst-1,legacy_n+2)==cpu.mem_read(dst-1,legacy_n+2)
    for _ in range(2):
        for c in (ref,cpu):
            c.mem_write(0x20380000,b"\xa5"*0x10000)
            scatter(c)
        assert ref.mem_read(0x20380000,0x4b0a40)==cpu.mem_read(0x20380000,0x4b0a40)
    if ft_timezone:
        apply_timezone(main,folder)
    envelope=bytearray(flash)
    pack_into("<I",envelope,BOOT_SIZE,FIRST_OFFSET-BOOT_SIZE-8)
    changed=with_pc_main(envelope,bytes(main),match_depth=32,lazy=True)
    end=BOOT_SIZE+8+unpack_from("<I",changed,BOOT_SIZE)[0]
    assert end<=FIRST_OFFSET and changed[end:]==flash[end:]
    _,group=checked_group_a(bytes(dat))
    start,stop=group["offset"],group["end_exclusive"]
    for i in range(BOOT_SIZE,end+1):
        dat[start+i]=changed[i]^((changed[i-1]+start+i-0x19)&255)
    dat[stop:stop+16]=md5(dat[start:stop],usedforsecurity=False).digest()
    digest=sha256(main).hexdigest()
    assert load_a(bytes(dat),digest)==(main,changed)
    (folder/name).write_bytes(dat)
    report=aprs_meta | dict(sha256=sha256(dat).hexdigest(),main_sha256=digest,baseline="v1.4.0",
        card_sha256=sha256((folder/"DMRRX.BIN").read_bytes()).hexdigest(),region=region,
        resident_bytes=len(text),resident_bss=guard-sy["__work_start"],guard=lock,dmr_playback_gain=2,
        native_initialization_equal_twice=True,flash_end=end)
    (folder/"package.json").write_text(json.dumps(report,indent=2)+"\n")
    print(region,report,flush=True)

if __name__=="__main__":
    payload=build_payload(OUT/"core")
    for r in (sys.argv[1:] or ["J","E"]): build(r,payload)
