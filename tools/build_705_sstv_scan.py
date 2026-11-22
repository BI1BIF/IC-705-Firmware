"""Build and verify the SSTV thumbnail overlay in the native TX pane's footprint."""
from argparse import ArgumentParser
from pathlib import Path
from struct import pack, unpack_from
from subprocess import run
import json

from tools.build_705_e140_log_test import BASE, ROOT, digest, decode_main, load_a, offline_test_page, repack_main
from tools.build_705_sstv_full_name import branch
from tools.replay_705_stock_install import european_update_rom

def apply_scan(main, ref, rom, out, region):
    before = bytes(main)
    start, end = rom(0x2018f554), rom(0x2018f7bc)
    assert main[start-BASE:end-BASE] == ref[start-BASE:end-BASE]
    funcs = dict(clear_box=0x201430e4,frame_box=0x2018e660,photo=0x2018e7e8,
                 placeholder=0x2018e748,grid=0x2018e9cc,marker=0x2018e948,
                 clear_block=0x2018ec88,update_block=0x2018edd8,caption=0x20142104,
                 icon=0x20144528,lookup=0x201420b4,fill=0x20147678)
    ptr = lambda pc: unpack_from("<I",ref,rom(pc)-BASE)[0]
    symbols = {name:rom(pc) for name,pc in funcs.items()}
    symbols.update(display_config=ptr(0x2018fd5c),caption_fields=ptr(0x2018fd70),
                   caption_items=ptr(0x2018fd6c),current_page=ptr(0x2018fd88),
                   previous_page=ptr(0x2018fd8c),active=0x20828170,menu_id=0x203e84c9,
                   cursor=0x2082af80,tx_state=0x2082a9a4,displayed_line=0x2082819c)
    out.mkdir(exist_ok=True,parents=True)
    (out/"entry.s").write_text(""".syntax unified
.arm
.section .entry,"ax"
.global pane_entry, refresh_entry
pane_entry: b jump_thumb
refresh_entry:
    push {r0-r3,ip,lr}
    blx scan_refresh
    pop {r0-r3,ip,pc}
jump_thumb:
    ldr ip, =tx_pane
    bx ip
.ltorg
""", encoding="ascii")
    (out/"scan.ld").write_text("\n".join(f"{k} = {v:#x};" for k,v in symbols.items())+
        f"\nSECTIONS {{ .text {start:#x} : {{ *(.entry) *(.text*) *(.rodata*) }} }}",encoding="ascii")
    run(["arm-none-eabi-as","-mcpu=cortex-a9","entry.s","-o","entry.o"],cwd=out,check=True)
    run(["arm-none-eabi-gcc","-mcpu=cortex-a9","-mthumb","-Os","-ffreestanding","-c",
         ROOT/"samples/sstv-tx-scan.c","-o","scan.o"],cwd=out,check=True)
    run(["arm-none-eabi-ld","-T","scan.ld","entry.o","scan.o","-o","scan.elf"],cwd=out,check=True)
    run(["arm-none-eabi-objcopy","-j",".text","-O","binary","scan.elf","scan.bin"],cwd=out,check=True)
    code=(out/"scan.bin").read_bytes()
    assert len(code)<=end-start, (len(code),end-start)
    main[start-BASE:end-BASE]=code.ljust(end-start,b"\0")
    def replace(pc, old, new):
        assert unpack_from("<I",main,pc-BASE)[0]==old
        main[pc-BASE:pc-BASE+4]=pack("<I",new)
    # This was the removed peak meter's private cache. RX status still uses its own word.
    replace(0x20377e8c,0xe5907000,branch(0x20377e8c,start+4))
    replace(0x20377ebc,0xe5840000,0xe320f000)
    assert unpack_from("<I",main,0x20377e98-BASE)[0]==0xe1530002
    from tools.verify_705_sstv_scan import verify
    return verify(before,bytes(main),rom,symbols,start,out,region)

def build(source, out):
    region = {"705J140.dat":"J","705E140.dat":"E"}[source.name]
    dat = bytearray(source.read_bytes())
    original = digest(dat)
    stock = (ROOT/"firmware"/source.name).read_bytes()
    ref = bytes(decode_main(stock)[1])
    rom = (european_update_rom(decode_main((ROOT/"firmware/705J140.dat").read_bytes())[1],ref)
           if region=="E" else lambda pc:pc)
    main = bytearray(decode_main(bytes(dat))[1])
    _, flash = load_a(bytes(dat),digest(main))
    report=apply_scan(main,ref,rom,out,region)
    from tools.decode_705_main import BOOT_SIZE
    from tools.build_705_aprs_slot import FIRST_OFFSET
    from tools.build_705_sstv_full_name import BASELINES, FT_CANDIDATES
    ancestor_dir=(ROOT/".analysis/sstv-refresh-tx2j1" if region=="E" else ROOT/".analysis/ft-key-style"/region)
    ancestor=(ancestor_dir/source.name).read_bytes()
    assert (BASELINES if region=="E" else FT_CANDIDATES)[digest(ancestor)]==region
    _, original_flash=load_a(ancestor,digest(decode_main(ancestor)[1]))
    end_of_stream=BOOT_SIZE+8+unpack_from("<I",flash,BOOT_SIZE)[0]
    limit=min(FIRST_OFFSET,BOOT_SIZE+8+unpack_from("<I",original_flash,BOOT_SIZE)[0])
    assert end_of_stream<=limit and flash[end_of_stream:limit]==original_flash[end_of_stream:limit]
    flash=bytearray(flash)
    flash[BOOT_SIZE:BOOT_SIZE+4]=pack("<I",limit-BOOT_SIZE-8)
    repack_main(dat,flash,main,32)
    (out/source.name).write_bytes(dat)
    offline_test_page(out/"SSTV-scan.html",stock,dat,region,"SSTV · 发射扫描线测试")
    (out/"scan.json").write_text(json.dumps(dict(region=region,base_sha256=original,
                  dat_sha256=digest(dat),**report),indent=2))

if __name__=="__main__":
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("out",type=Path)
    args=parser.parse_args()
    build(args.source,args.out)
