"""Install the second-generation FT8/FT4 panel on verified J140/E140 candidates."""
import argparse
from hashlib import md5, sha256
import json
from pathlib import Path
from shutil import copyfile
from struct import pack_into, unpack_from
from subprocess import run

from elftools.elf.elffile import ELFFile
from tools.build_705_aprs_slot import FIRST_OFFSET, scatter
from tools.build_705_ft_wide_view import EDITS as WIDE_EDITS, assemble
from tools.build_705_ft_panel_assets import coverage_palette, glyph_masks
from tools.build_705_ftx_rx import FT_DATA_OFFSET, FT_DATA_RAM, LIB, OUT as NATIVE_FT
from tools.decode_705_main import BOOT_SIZE, checked_group_a
from tools.emulate_705 import BASE, machine
from tools.replay_705_nor_boot import with_pc_main
from tools.replay_705_stock_install import load_a
from tools.verify_705_ftx_rx import symbols

ROOT = Path(__file__).resolve().parents[1]
CAPACITY = 0x2800
RAM = FT_DATA_RAM-CAPACITY
SCRATCH = 0x20382000
STUB_BYTES = 128
LABELS = {
    "manual":"手动", "semi":"半自动", "full":"全自动", "listen":"守听",
    "queued":"等发", "on_air":"发射", "pick":"选台", "confirm":"确认",
    "scan":"找台", "wait_rx":"等应答", "completed":"已通联",
    "mode":"操作模式", "tries":"最多发送", "multi":"多台来叫", "start_as":"启动方式",
    "limit":"超限处理", "first":"接首台", "choose":"点选", "stop":"停止",
    "next":"换台", "history":"历史报文", "target":"指定呼号",
}
ORIGINAL = {
    "J": "8b08b6ec552d0bdb0151d2478e002222359961c2e7bf4bb0510fd18f3346e2ed",
    "E": "1367712890fda27c88f939c78d0cf9ce9013c35496ffa6d4f28cc467c2e0d691",
}
# Fixed columns on the ten-row live and history pages, including the
# worked-callsign underline, overflow marker and missing-value paths.
LIST_LAYOUT = {
    0x2037D502:"movs r1,#214", 0x2037D510:"movw r1,#280", 0x2037D520:"movw r1,#310",
    0x2037D684:"cmp r6,#22", 0x2037D72C:"cmp r3,#22", 0x2037D732:"cmp r4,#21",
    0x2037D738:"rsb.w r0,r4,#22", 0x2037D6F2:"movw r1,#352",
    0x2037D6F6:"bl resident_number", 0x2037D84E:"movw r1,#352",
    0x2037D872:"movw r1,#280", 0x2037D876:"bl resident_number",
    0x2037D882:"movw r1,#310", 0x2037D88A:"bl resident_number", 0x2037D980:"movw r1,#280",
    0x20826AAE:"add.w r3,r1,#22", 0x20826AD6:"movs r5,#203",
    0x20826AD8:"movs r1,#203", 0x20826AF0:"cmp r5,#212", 0x20826B14:"movs r1,#214",
}
HOOKS = {
    0x203744A2: ("bl", "operating_touch", 4),
    0x203712DA: ("bl", "operating_close", 4),
    0x203718AE: ("bl", "operating_tick", 4),
    0x2037F6F0: ("bl", "operating_open", 4),
    0x2037D314: ("bl", "operating_receive", 4),
    0x2037D1A4: ("b.w", "operating_list_page", 8),
    0x2037D1C6: ("bl", "operating_draw_page", 4),
    0x2037D474: ("bl", "operating_draw_slot", 4),
    0x2037D4B2: ("bl", "operating_slot_bar", 4),
    0x2037D6F6: ("bl", "operating_distance_number", 4),
    0x2037D852: ("bl", "operating_distance_text", 4),
    0x2037D548: ("bl", "operating_distance_heading", 4),
    0x2037D8BE: ("b.w", "operating_list_rail", 4),
}
# The pinned base already redirects both draws to the QTH renderer.
EXISTING_EDITS = {
    0x2037D474: bytes.fromhex("a9f0b0f2"),
    0x2037D4B2: bytes.fromhex("a9f091f2"),
}
# Enlarge the native QTH, dB and Hz headings.
HEADER_EDITS = {
    0x2037D4FE: bytes.fromhex("0d23"),
    0x2037D500: bytes.fromhex("5822"),
    0x2037D50C: bytes.fromhex("0d23"),
    0x2037D51A: bytes.fromhex("0d23"),
    0x2037D51E: bytes.fromhex("5822"),
}
IMPORTS = {
    "pref", "partner", "outgoing", "kind", "parity", "audio_hz", "attempts", "tx_frequency",
    "last_air", "sequence_on", "has_sent", "from_list", "outcome", "cached", "stage",
    "return_rx", "notice", "mode_ok", "foreign_tx", "arm_next", "halt", "rectangle",
    "ft_page", "ftx_ft4", "ft_station_open", "ft_station_close", "ft_return_live",
    "ft_auto_armed", "ft_row_eligible", "ft_history_action", "ft_history_enabled",
    "ft_is_history", "ft_choose_row", "ft_choice_row", "ft_row_at", "ft_worked",
    "ft_panel_touch", "ft_panel_draw", "ft_receive_row", "ft_label", "ft_key",
    "ft_blank", "view_invalidate", "ft_clock", "ft_listen", "ft_station_tick", "draw_glyph", "is_call",
    "memcpy", "memset", "strcmp", "strncmp", "strlen", "__aeabi_uidiv", "__aeabi_uidivmod",
}


def write_labels(folder,font):
    chars = sorted(set("".join(LABELS.values())))
    masks = glyph_masks(chars,str(font.resolve()))
    entries = []
    for start in range(0,len(masks),120):
        normalized = [(value+2)//5 for pair in masks[start:start+120]
                      for value in (pair&15,pair>>4)]
        packed = [sum(normalized[i+j]<<(2*j) for j in range(4)) for i in range(0,240,4)]
        entries.append("    {"+",".join(str(byte) for byte in packed)+"}")
    labels = [f'static const unsigned char v2_{key}[] = {{'
              +",".join(str(chars.index(char)+1) for char in word)+",0};"
              for key,word in LABELS.items()]
    palette = unpack_from("<32H",coverage_palette())
    palettes = ["{"+",".join(map(str,palette[index:index+16]))+"}" for index in (0,16)]
    (folder/"v140_operating_labels.h").write_text(
        "/* LCD masks from Noto Sans SC. See font/Noto-OFL.txt. */\n"
        +"static const unsigned char v2_masks[][60] = {\n"+",\n".join(entries)+"};\n"
        +"static const uint16_t v2_palette[][16] = {"+",".join(palettes)+"};\n"
        +"\n".join(labels)+"\n",encoding="ascii")


def link(folder):
    base = symbols(NATIVE_FT/"rx.elf")
    data = {"pref","partner","outgoing","kind","parity","audio_hz","attempts","tx_frequency",
            "last_air","sequence_on","has_sent","from_list","outcome","cached","stage",
            "return_rx","notice","ft_page","ft_auto_armed","ftx_ft4","cq_only","edit"}
    layout = [f"{name} = {base[name]:#x};" for name in sorted(data)]
    imports = {name:base[name] for name in IMPORTS-data-{"ft_panel_touch"}}
    imports.update(stock_ft_touch=base["ft_panel_touch"],
                   view_page_compare=0x2037d1ad,view_finish=0x2037d1cf)
    veneers = ".section .text.operating_imports,\"ax\"\n"
    for name, address in sorted(imports.items()):
        veneers += f".global {name}\n.thumb_func\n{name}:\nldr.w pc, ={address:#x}\n"
    layout += [
        f"operating_payload = {SCRATCH+STUB_BYTES:#x};",
        f"operating_ram = {RAM:#x};", f"operating_end = {FT_DATA_RAM:#x};",
        "SECTIONS {",
        f".operating {RAM:#x} : {{ *(.text.operating_bridge .text.operating_imports) "
        "operating-c.o(.text .text.*) *(.rodata*) *(.data*) }",
        ".work (NOLOAD) : { *(.bss .bss.* COMMON) __operating_end = .; }",
        f".boot {SCRATCH:#x} : {{ *(.text.operating_boot) }}",
    ]
    patches = ".syntax unified\n.cpu cortex-a9\n.thumb\n"
    for site, (op, name, size) in HOOKS.items():
        section = f".hook_{site:x}"
        patches += f'.section {section},"ax"\n{op} {name}\n'+"nop\n"*((size-4)//2)
        layout.append(f"{section} {site:#x} : {{ *({section}) }}")
    layout += ["/DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) }", "}"]
    (folder/"operating.ld").write_text("\n".join(layout)+"\n",encoding="ascii")
    (folder/"operating-hooks.S").write_text(patches+veneers,encoding="ascii")
    options = ["arm-none-eabi-gcc","-c","-mcpu=cortex-a9","-mthumb"]
    source = ROOT/"samples/ftx"
    run([*options,"-Oz","-std=gnu11","-ffreestanding","-fno-builtin","-fdata-sections",
         "-ffunction-sections","-mfloat-abi=softfp","-mfpu=vfpv3-d16","-Wall","-Wextra","-Werror",
         "-I",folder,"-I",NATIVE_FT,"-I",LIB,source/"v140_operating.c",
         "-o","operating-c.o"],cwd=folder,check=True)
    run([*options,source/"v140_operating.S","-o","operating-asm.o"],cwd=folder,check=True)
    run([*options,"operating-hooks.S","-o","operating-hooks.o"],cwd=folder,check=True)
    run(["arm-none-eabi-ld","-T","operating.ld","operating-asm.o","operating-c.o",
         "operating-hooks.o","-o","operating.elf"],cwd=folder,check=True)
    with (folder/"operating.elf").open("rb") as stream:
        elf = ELFFile(stream)
        code = elf.get_section_by_name(".operating").data()
        stub = elf.get_section_by_name(".boot").data()
        patches = {site:elf.get_section_by_name(f".hook_{site:x}").data() for site in HOOKS}
    new_symbols = symbols(folder/"operating.elf")
    assert new_symbols["__operating_end"] <= FT_DATA_RAM and len(stub) <= STUB_BYTES
    return code, stub, patches


def build(source, folder):
    folder.mkdir(parents=True,exist_ok=True)
    dat = bytearray(source.read_bytes())
    old_meta = json.loads((source.parent/"package.json").read_text())
    region = old_meta["region"]
    assert sha256(dat).hexdigest() == old_meta["sha256"] == ORIGINAL[region]
    original, original_flash = load_a(bytes(dat),old_meta["main_sha256"])
    main, flash = bytearray(original),bytearray(original_flash)
    instructions = {site:(WIDE_EDITS[site][1],op) for site,op in LIST_LAYOUT.items()}
    before_layout,_ = assemble(folder,0,instructions)
    after_layout,_ = assemble(folder,1,instructions)
    card_edits = []
    for site, patch in after_layout.items():
        target,offset = (main,site-BASE) if site < FT_DATA_RAM else (flash,FT_DATA_OFFSET+site-FT_DATA_RAM)
        assert target[offset:offset+len(patch)] == before_layout[site], hex(site)
        target[offset:offset+len(patch)] = patch
        if target is flash:
            card_edits.append(range(offset,offset+len(patch)+1))
    code, stub, patches = link(folder)
    with (NATIVE_FT/"rx.elf").open("rb") as stream:
        elf = ELFFile(stream)
        sections = [(s["sh_addr"],s.data()) for s in elf.iter_sections() if s["sh_flags"] & 4]
        for site, patch in (patches | HEADER_EDITS).items():
            expected = [data[site-address:site-address+len(patch)] for address,data in sections
                        if address<=site and site+len(patch)<=address+len(data)]
            before = main[site-BASE:site-BASE+len(patch)]
            assert len(expected)==1 and before==EXISTING_EDITS.get(site,expected[0]), (
                hex(site),before.hex(),expected)
            main[site-BASE:site-BASE+len(patch)] = patch
    heap_site = (0x202d3b44 if region=="E" else 0x202d3a64)-BASE
    assert unpack_from("<I",main,heap_site)[0] == FT_DATA_RAM
    pack_into("<I",main,heap_site,RAM)
    table_begin, table_end = unpack_from("<II",main,0x2e4)
    seen=0
    for offset in (0x31c,*range(table_begin-BASE,table_end-BASE,16)):
        _, dest, length, method = unpack_from("<4I",main,offset)
        if dest == 0x20381f44 and dest+length == 0x20830e40 and method == 0x200052fc:
            pack_into("<I",main,offset+12,SCRATCH|1)
            seen+=1
    assert seen == 2 and BASE+len(main) <= SCRATCH
    payload = code.ljust(CAPACITY,b"\0")
    main.extend(bytes(SCRATCH-BASE-len(main))+stub.ljust(STUB_BYTES,b"\0")+payload)
    before, after = machine(original), machine(bytes(main))
    scatter(before)
    scatter(after)
    assert after.mem_read(RAM,CAPACITY) == payload
    for begin, end in ((0x20380000,RAM),(FT_DATA_RAM,0x208b0a40)):
        assert after.mem_read(begin,end-begin) == before.mem_read(begin,end-begin)
    pack_into("<I",flash,BOOT_SIZE,FIRST_OFFSET-BOOT_SIZE-8)
    packed = with_pc_main(flash, bytes(main), match_depth=32, lazy=True)
    end = BOOT_SIZE+8+unpack_from("<I",packed,BOOT_SIZE)[0]
    assert end <= FIRST_OFFSET and packed[end:]==flash[end:]
    _,group = checked_group_a(bytes(dat))
    start,stop = group["offset"], group["end_exclusive"]
    for span in [range(BOOT_SIZE,end+1),*card_edits]:
        for offset in span:
            dat[start+offset] = packed[offset] ^ ((packed[offset-1]+start+offset-0x19)&255)
    dat[stop:stop+16] = md5(dat[start:stop],usedforsecurity=False).digest()
    main_hash = sha256(main).hexdigest()
    assert load_a(bytes(dat),main_hash)==(main,packed)
    target = folder/source.name
    target.write_bytes(dat)
    for name in ("DMRRX.BIN","station.elf","manager.elf","aprs-task.elf"):
        copyfile(source.parent/name,folder/name)
    meta = old_meta|dict(sha256=sha256(dat).hexdigest(),main_sha256=main_hash,flash_end=end,
                         ft_operating_size=len(code),ft_operating_address=hex(RAM),
                         ft_previous_main_size=len(original))
    (folder/"package.json").write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    print(target,meta["sha256"],"FT overlay",len(code),"bytes",flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("dest",type=Path)
    args = parser.parse_args()
    build(args.source.resolve(),args.dest.resolve())
