"""Build the regional four-function DAT with the APRS GPS selector and FM receive path."""
import argparse
from tools.replay_705_aprs_task import HOOKS, GPS_ACTION_REFERENCES
from tools.verify_705_aprs_overlay import LINK
from hashlib import md5, sha256
import json
from pathlib import Path
from struct import pack, unpack_from

from tools.build_705_cw_sim import PICKER_TABLE, PICKER_ID, PICKER_STRIDE, PICKER_REFERENCES, picker_table
from tools.build_705_ftx_rx import MENU, OUT as FT_OUT, pack_init_tail
from tools.build_705_sstv_full_name import BASELINES, FT_CANDIDATES
from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_main
from tools.emulate_705 import BASE, arm, machine
from tools.probe_705_sstv_picture import branch
from tools.replay_705_aprs_task import e140_rom
from tools.replay_705_nor_boot import with_pc_main
from tools.replay_705_stock_install import load_a
from tools.verify_705_aprs_overlay import build
from tools.verify_705_ftx_rx import symbols
from tools.replay_705_aprs_rx import build_target

FIRST_OFFSET, TAIL_OFFSET = 0x21ea00, 0x5fc220
FIRST_BYTES = 0xcc00
PREFIX_SLOTS = 20
MODE_PICKER = 143
ROOT = Path(".analysis/aprs-integration-base")


def slot_resources(folder, image, relocations):
    reloc = pack(f"<{len(relocations)}H",*(n//4 for n in relocations))
    fingerprint = 2166136261
    for value in image + reloc:
        fingerprint = ((fingerprint ^ value)*16777619) & 0xffffffff
    tail = image[FIRST_BYTES:]
    assert len(tail) > 0
    tail = bytes(pack_init_tail(tail,0))
    tail_hash=2166136261
    for byte in tail:
        tail_hash=((tail_hash^byte)*16777619)&0xffffffff
    reloc_offset = (len(tail)+1)&~1
    first=bytes(pack_init_tail(image[:FIRST_BYTES],0))
    first_hash=2166136261
    for byte in first:
        first_hash=((first_hash^byte)*16777619)&0xffffffff
    (folder/"first.bin").write_bytes(pack("<I",fingerprint)+first)
    (folder/"tail.bin").write_bytes(tail.ljust(reloc_offset,b"\0")+reloc)
    return dict(FIRST_OFFSET=FIRST_OFFSET,TAIL_OFFSET=TAIL_OFFSET,FIRST_BYTES=FIRST_BYTES,
                FIRST_PACKED=len(first),FIRST_HASH=first_hash,SLOT_HASH=fingerprint,RELOC_OFFSET=reloc_offset,PACKED_TAIL=len(tail),TAIL_HASH=tail_hash)


def scatter(cpu):
    cpu.emu_start(0x200052c9,0x200052a8,count=12_000_000)
    assert cpu.reg_read(arm.UC_ARM_REG_PC)==0x200052a8


def run(region, folder=None):
    dat_name=f"705{region}140.dat"
    baseline=ROOT/region
    folder=folder or baseline/"aprs-slot"
    folder.mkdir(parents=True,exist_ok=True)
    dat=(baseline/dat_name).read_bytes()
    assert sha256(dat).hexdigest()==json.loads((baseline/"evidence.json").read_text())["sha256"]
    main=bytearray(decode_main(dat)[1])
    _, flash=load_a(dat,sha256(main).hexdigest())
    european=region=="E"
    table=PICKER_TABLE+(224 if european else 0)
    manager=table+0xe00
    prefix=table+0x3300
    size=PICKER_ID*PICKER_STRIDE
    assert prefix+340*PREFIX_SLOTS<=table+size
    ft=symbols(FT_OUT/"rx.elf")
    sstv=symbols(FT_OUT/"sstv/rx.elf")
    entries=dict(UNPACK=ft["ft_restore_modes"]|1, FT_REQUEST=ft["ft_tx_requested_arm"], FT_SOURCE=ft["ft_tx_source_arm"], FT_MOD=ft["ft_tx_mod_block_arm"], FT_PREPARE=ft["ftx_prepare_frame"]|1, FT_STATE=ft["state"],FT_STAGE=ft["stage"],
                 SSTV_STAGE=sstv["tx_state"],SSTV_RX=sstv["sstv_rx_only"], MODE_PICKER=MODE_PICKER, MODE_ROWS=MENU+MODE_PICKER*PICKER_STRIDE,
                 MODE_TEMPLATE=table+0x2540, HISTORY_TAIL_BYTES=22*340,
                 HISTORY_LAST_BYTES=(64-PREFIX_SLOTS-22)*340)
    rom=e140_rom if european else lambda a:a
    for label,addr in dict(OPEN_MODE=0x200cd628,CLOSE_MODE=0x200cd828,APPLY_DV=0x200a27a4,
                           MODE_RESUME=0x200a34c0,HIGHLIGHT_RESUME=0x200a25e0,
                           OPEN_RESUME=0x200cd62c, DEFER=0x200cd7dc,DRAW_TEXT=0x20142698,DMA_RETURN=0x200ffd3c,NATIVE_COPY=0x200ff810,
                           NATIVE_PANEL=0x200964bc,NATIVE_RECORD=0x20110384).items():
        entries[label]=rom(addr)
    aliases=dict(ft_session_state=entries["FT_STATE"],ft_tx_stage=entries["FT_STAGE"],
                 sstv_tx_state=entries["SSTV_STAGE"],sstv_rx_only=entries["SSTV_RX"],aprs_history_prefix=prefix)
    for key in ("ft_tx_requested","ft_tx_source","ft_tx_mod_block"):
        aliases[key]=ft[key+"_arm"]
    flags=["-Os","-DAPRS_SLOT_UI",f"-DAPRS_NATIVE_MENU={MENU}", "-DAPRS_COMBINED","-DAPRS_HISTORY_SPLIT",f"-DAPRS_PREFIX_SLOTS={PREFIX_SLOTS}",
           f"-DAPRS_LAST_BANK_SLOTS={64-PREFIX_SLOTS-22}",
           *(f"-Wl,--defsym,{k}={v:#x}" for k,v in aliases.items())]
    # Displaced inline hooks fall through to exactly the original regional instruction.
    # Branching via the resident base leaves the other three modes usable when FM is unloaded.
    hooks = list(HOOKS[4:22]) + [HOOKS[29], HOOKS[30]]
    hooks += [(0x2007f104,0xe92d4070,"aprs_reply_touch",0xea000000),
              (0x200cd828,0xe92d4010,"aprs_reply_back",0xea000000),
              (0x20052fb0,0xe92d401c,"aprs_reply_keyboard",0xea000000),
              (*HOOKS[-1][:2],"aprs_ui_navigation",0xeb000000)]
    # Retain every external entry point used by a resident gate or the replay.
    roots={label for _,_,label,_ in hooks}
    roots.update(("aprs_beacon_reschedule","aprs_set_channel","aprs_note_dma","aprs_copy_pcm",
                  "aprs_record_receive","aprs_update_panel","aprs_slot_settings","aprs_ui_busy",
                  "aprs_ui_restore","aprs_ui_quick","aprs_tx_mod_block","aprs_tx_requested",
                  "aprs_tx_source","aprs_messages_disarm","aprs_config_poll","aprs_rx_feed","aprs_function_picker"))
    flags.extend(["-ffunction-sections","-fdata-sections","-Wl,--gc-sections","-Wa,--defsym,APRS_SLOT_BUILD=1",
                  *(f"-Wl,-u,{name}" for name in sorted(roots))])
    def gates(symbols):
        lines=[".syntax unified",".arm",".text","dispatch:",
               "push {r0,r1,ip}", "mrs r1,cpsr","ldr r0,=loaded","ldr r0,[r0]",
               "cmp r0,#0","ldrne ip,[lr]","addne ip,ip,r0","addeq ip,lr,#4",
               "msr cpsr_f,r1","str ip,[sp,#16]","pop {r0,r1,ip,lr,pc}"]
        for addr,expected,name,op in hooks:
            site=rom(addr)
            original=unpack_from("<I",main,site-BASE)[0]
            lines.extend([f".global gate_{name}",f"gate_{name}:"])
            if name=="aprs_reply_touch":
                lines.extend([f"ldr r0,={symbols[name]-LINK}","adr r1,1f","b aprs_slot_input","1:"])
            else:
                lines.extend(["sub sp,sp,#4","push {lr}","bl dispatch",f".word {symbols[name]-LINK}"])
            if op==0xeb000000:
                assert original>>24 in (0xeb,0xfa,0xfb),(hex(site),hex(original))
                disp=((original&0xffffff)^0x800000)-0x800000
                target=site+8+4*disp
                if original>>28==15:
                    target+=(original>>23&2)+1
                lines.append(f"ldr pc,={target}")
            else:
                assert original==expected,(hex(site),hex(original),hex(expected))
                if addr==0x200485a8:
                    assert unpack_from("<I",main,site+8+0x17c-BASE)[0]==0x203806f7
                    lines.append("ldr r5,=0x203806f7")
                else:
                    lines.append(f".word {original}")
                lines.append(f"ldr pc,={site+4}")
        file=folder/"gates.S"
        file.write_text("\n".join(lines)+"\n")
        return file
    _,_,_,sizes,code,ms=build(folder,european,flags,e140_rom if european else lambda a:a,
        slot=dict(manager=manager,entries=entries,restore=ft["ft_restore_modes"],gates=gates,write_resources=slot_resources))
    initial=machine(bytes(main))
    scatter(initial)
    reference=bytes(initial.mem_read(MENU,320*PICKER_STRIDE))
    at=table-BASE
    packed=pack_init_tail(main[at:at+size],0)
    extra=entries["MODE_TEMPLATE"]
    assert len(packed)<=manager-table and manager+len(code)<=ms["__bss_start__"]<ms["__bss_end__"]<=extra
    main[at:at+size]=bytes(size)
    main[at:at+len(packed)]=packed
    main[manager-BASE:manager-BASE+len(code)]=code
    desc=unpack_from("<I",main,0x2e8)[0]-32-BASE
    assert unpack_from("<4I",main,desc)==(table,MENU,size,0x200052ec)
    main[desc+12:desc+16]=pack("<I",ms["aprs_restore_picker"] & ~1)
    # The stock list has a single active selector. These three duplicate child rows
    # are lent to its GPS modal only, and restored before the next selector opens.
    original_child=reference[(MODE_PICKER-1)*72:MODE_PICKER*72]
    assert reference[MODE_PICKER*72:(MODE_PICKER+3)*72]==original_child*3
    stock=bytes(decode_main((Path("firmware")/dat_name).read_bytes())[1])
    rows=picker_table(stock,MENU,dict(cw_picker_select=ms["aprs_mode_choose"],
        cw_picker_choice=ms["mode_choice"]),labels=(b"APRS Mode",b"RX Only",b"RX & TX"),
        menu_id=320,code_shift=rom(PICKER_REFERENCES[0])-PICKER_REFERENCES[0],
        table_shift=table-PICKER_TABLE)
    extension=bytearray(rows[320*72:])
    extension[4:8]=pack("<I",ms["aprs_mode_initial"])
    extension[24:28]=pack("<I",ms["aprs_mode_closed"])
    for row,offsets in enumerate(((48,56,68),(52,60),(52,60))):
        for offset in offsets:
            pos=row*72+offset
            ptr=unpack_from("<I",extension,pos)[0]
            extension[pos:pos+4]=pack("<I",extra+ptr-MENU-320*72)
    extension[-4:]=pack("<2H",MODE_PICKER+1,MODE_PICKER+2)
    main[extra-BASE:extra-BASE+len(extension)]=extension
    tx=unpack_from("<I",main,rom(0x200a2640)-BASE)[0]+478*60-BASE
    assert unpack_from("<I",main,tx)[0]==0x203eb172 and unpack_from("<I",main,tx+16)[0]==2
    old=unpack_from("<I",main,tx+56)[0]-BASE
    old_labels=unpack_from("<6I",main,old)
    names=extra+0x100
    new_actions=names+32
    assert extra+len(extension)<=names
    main[names-BASE:names-BASE+32]=pack("<8I",*old_labels[:3],ms["aprs_name"],*old_labels[3:],ms["aprs_name"])
    main[tx+16:tx+20]=pack("<I",3)
    main[tx+56:tx+60]=pack("<I",names)
    def replace(addr,old,new):
        assert unpack_from("<I",main,addr-BASE)[0]==old,hex(addr)
        main[addr-BASE:addr-BASE+4]=pack("<I",new)
    replace(rom(0x200cd628),0xe92d4070,branch(rom(0x200cd628),ms["aprs_picker_open"],0xea000000))
    for a,op,target in ((0x200a34bc,0xe92d4070,"aprs_mode_tap"),(0x200a25dc,0xe5d07000,"aprs_mode_highlight"),
                        (0x2014b630,None,"aprs_mode_text"),(0x2014b810,None,"aprs_mode_text")):
        site=rom(a)
        old=op or branch(site,rom(0x20142698),0xeb000000)
        replace(site,old,branch(site,ms[target],0xea000000 if op else 0xeb000000))
    for a,target,prior in ((0x200ffd38,"aprs_slot_dma",None),(0x2010fe30,"aprs_slot_copy",0x200ff810),
                           (0x200d4f74,"aprs_slot_record",0x20110384),(0x200d5114,"aprs_slot_panel",0x200964bc)):
        site=rom(a)
        old=branch(site,rom(prior),0xeb000000) if prior else 0xe8bd4070
        replace(site,old,branch(site,ms[target],0xeb000000 if prior else 0xea000000))
    for addr,_,label,op in hooks:
        site=rom(addr)
        replace(site,unpack_from("<I",main,site-BASE)[0],branch(site,ms["gate_"+label],op))
    for site,label,old in ((rom(0x200817dc),"aprs_slot_quick",rom(0x200cd628)),
                           (rom(0x200ffeb0),"aprs_slot_mod",entries["FT_MOD"]),
                           (0x20379f84,"aprs_slot_request",entries["FT_REQUEST"]),
                           (0x20379fa4,"aprs_slot_source",entries["FT_SOURCE"])):
        replace(site,branch(site,old,0xeb000000),branch(site,ms[label],0xeb000000))
    gps_list=unpack_from("<I",main,rom(0x200a0a88)-BASE)[0]+144*12
    count,rows_address,style=unpack_from("<3I",main,gps_list-BASE)
    assert count==8 and style==1
    rows=bytes(main[rows_address-BASE:rows_address-BASE+3*count])
    assert rows[:6]==pack("<BHBH",1,219,2,478)
    actions=unpack_from("<I",main,rom(GPS_ACTION_REFERENCES[0])-BASE)[0]
    new_rows=new_actions+160*20
    assert new_rows+len(rows)+3<prefix
    data=bytes(main[actions-BASE:actions-BASE+159*20])
    data+=pack("<5I",ms["aprs_slot_settings"],0,0x10700,ms["aprs_name"],ms["aprs_name"])
    data+=rows[:6]+pack("<BH",3,159)+rows[6:]
    main[new_actions-BASE:new_actions-BASE+len(data)]=data
    for addr in GPS_ACTION_REFERENCES:
        replace(rom(addr),actions,new_actions)
    main[gps_list-BASE:gps_list-BASE+8]=pack("<2I",count+1,new_rows)
    # All factory action lookups now use the extended copy above. Use only the
    # unreferenced suffix of its previous location for the always-available UI.
    from struct import iter_unpack
    keypad=actions+0x300
    limit=actions+159*20
    for offset in range(4):
        words=memoryview(main)[offset:len(main)-(len(main)-offset)%4]
        assert not any(keypad<=value<limit for value, in iter_unpack("<I",words))
    sy=symbols(folder/"aprs-task.elf")
    functions={name:ms[name] for name in ("plain_fm","tx_enabled","bound_hz","pin_audio","unpin_audio","aprs_set_mode","aprs_overlay_load")}
    for name,addr in dict(stock_action=0x2007d360,stock_top=0x2015b024,stock_icon19=0x2015baf0,stock_clear=0x201430e4,stock_clear_span=0x20147678,
                          stock_focus=0x20144528,stock_bezel=0x2014429c,stock_text=0x20142698).items():
        functions[name]=rom(addr)
    options=[f"-Wl,--defsym,{k}={v:#x}" for k,v in functions.items()]
    for key,name in dict(FUNCTION_PICKER="aprs_function_picker",CONFIG_DIRTY="aprs_settings_dirty",
                         AUTO_ON="aprs_auto_beacon",AUTO_WAIT="auto_waiting",AUTO_INTERVAL="aprs_beacon_interval").items():
        options.append(f"-D{key}={sy[name]-LINK}")
    asm=folder/"function-end.S"
    asm.write_text(".arm\n.global function_end\nfunction_end:\nmov r0,r4\nmov r1,r6\nbl function_draw\nadd sp,sp,#76\npop {r4-r11,pc}\n")
    ui,labels=build_target(folder,"function",["samples/aprs-function.c",str(asm)],keypad,"function_end",
        includes=(folder,),flags=["-Os",f"-Wl,-Tdata={limit-16:#x}",*options])
    assert keypad+len(ui)<=limit and labels["__bss_end__"]<=limit
    main[keypad-BASE:keypad-BASE+len(ui)]=ui
    for a,prior,handler in ((0x2007ee44,0x2007d360,"function_action"),(0x201637a8,0x2015b024,"function_top"),
                            (0x201637f0,0x2015baf0,"function_top_labels")):
        site=rom(a)
        replace(site,branch(site,rom(prior),0xeb000000),branch(site,labels[handler],0xeb000000))
    site=rom(0x20138304)
    replace(site,0xe28dd04c,branch(site,labels["function_end"],0xea000000))
    site=ft["ftx_prepare_bridge"]+12
    assert unpack_from("<I",main,site-BASE)[0]==branch(site,ft["ftx_prepare_frame"] & ~1,0xfa000000)
    main[site-BASE:site-BASE+4]=pack("<I",branch(site,ms["aprs_overlay_prepare"],0xeb000000))
    cpu=machine(bytes(main))
    for _ in range(2):
        cpu.mem_write(ms["__bss_start__"],b"\xa5"*(ms["__bss_end__"]-ms["__bss_start__"]))
        cpu.mem_write(prefix,b"\xa5"*(340*PREFIX_SLOTS))
        cpu.mem_write(MENU,b"\xa5"*len(reference))
        scatter(cpu)
        assert bytes(cpu.mem_read(MENU,len(reference)))==reference
        assert not any(cpu.mem_read(ms["__bss_start__"],ms["__bss_end__"]-ms["__bss_start__"]))
    from tools.build_705_sstv_scan import apply_scan
    from tools.replay_705_stock_install import european_update_rom
    scan_rom=european_update_rom(decode_main(Path("firmware/705J140.dat").read_bytes())[1],stock) if european else rom
    scan=apply_scan(main,stock,scan_rom,folder/"sstv-scan",region)
    (folder/"sstv-scan"/"scan.json").write_text(json.dumps(scan,indent=2)+"\n")
    # Use the matching predecessor's compressed stream as the ownership bound.
    # E's key artwork starts just beyond the first resource.
    public=((Path(".analysis/sstv-refresh-tx2j1") if european else Path(".analysis/ft-key-style")/region)/dat_name).read_bytes()
    assert (BASELINES if european else FT_CANDIDATES)[sha256(public).hexdigest()]==region
    _,original=load_a(public,sha256(decode_main(public)[1]).hexdigest())
    envelope=BOOT_SIZE+8+unpack_from("<I",original,BOOT_SIZE)[0]
    previous=BOOT_SIZE+8+unpack_from("<I",flash,BOOT_SIZE)[0]
    assert previous<=envelope and flash[previous:envelope]==original[previous:envelope]
    staged=bytearray(flash)
    staged[BOOT_SIZE:BOOT_SIZE+4]=original[BOOT_SIZE:BOOT_SIZE+4]
    staged=bytearray(with_pc_main(staged,bytes(main),match_depth=32,lazy=True))
    end=BOOT_SIZE+8+unpack_from("<I",staged,BOOT_SIZE)[0]
    assert end<=FIRST_OFFSET
    changed=[(BOOT_SIZE,end)]
    for offset,part in ((FIRST_OFFSET,"first.bin"),(TAIL_OFFSET,"tail.bin")):
        chunk=(folder/part).read_bytes()
        stop=offset+len(chunk)
        assert stop <= (0x229420 if offset==FIRST_OFFSET else 0x600000)
        if offset < envelope:
            assert staged[offset:min(stop,envelope)]==original[offset:min(stop,envelope)]
        assert not staged[max(envelope,offset):stop].strip(b"\xff")
        staged[offset:stop]=chunk
        changed.append((offset,stop))
    _,group=checked_group_a(dat)
    begin,stop=group["offset"],group["end_exclusive"]
    candidate=bytearray(dat)
    for a,b in changed:
        for i in range(a,b+1):
            candidate[begin+i]=staged[i]^((staged[i-1]+begin+i-0x19)&255)
    candidate[stop:stop+16]=md5(candidate[begin:stop],usedforsecurity=False).digest()
    assert load_a(bytes(candidate),sha256(main).hexdigest())==(bytes(main),bytes(staged))
    (folder/dat_name).write_bytes(candidate)
    report=dict(region=region,sha256=sha256(candidate).hexdigest(),main_sha256=sha256(main).hexdigest(),
                manager=hex(manager),manager_bytes=len(code),history_prefix=hex(prefix),prefix_slots=PREFIX_SLOTS,
                tail_heap_bytes=(64-PREFIX_SLOTS)*340,cold_and_warm_scatter_menu_rows=320,
                first_bytes=(folder/"first.bin").stat().st_size,tail_bytes=(folder/"tail.bin").stat().st_size,
                module_bytes=sizes["IMAGE_BYTES"],entry=hex(site),gps_selector_connected=True)
    (folder/"package.json").write_text(json.dumps(report,indent=2)+"\n")
    print(region,report,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("region",choices=("J","E"))
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    run(args.region,args.output)
