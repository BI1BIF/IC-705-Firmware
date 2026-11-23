"""Link the DMR UI to the native v1.4.0 MODE panel. Addresses are AAPCS code pointers."""
from pathlib import Path
from struct import pack_into, unpack_from
from subprocess import run

from elftools.elf.elffile import ELFFile

BASE = 0x20005000
ROOT = Path(__file__).resolve().parents[1]
HOOKS = {
    0x2037f838: ("dmr_ui_input", 0xfaffc803),
    0x2037f878: ("dmr_ui_touch", 0xfaffd2af),
    0x2037f8c4: ("dmr_ui_frame", 0xfaffc846),
}


def ui_imports(region, aprs=None):
    assert region in ("J", "E")
    early, late = (0, 0) if region == "J" else (-152, 228)
    prepare_raw = 0xebfda1b4 if region == "J" else 0xebfda1ec
    signed_offset = ((prepare_raw & 0xffffff) ^ 0x800000) - 0x800000
    imports = dict(
        stock_row_prepare=0x2004b7f4-(240 if region=="E" else 0), stock_row_draw=0x20162f50+late,
        element_layout=0x201420b4+late, element_text=0x20142698+late, text_width=0x20141e88+late,
        aprs_strip_visible=0x202e81c8 if region=="J" else 0x202e82a8,
        ft_input=0x2037184d, ft_touch=0x2037433d, ft_frame=0x203719e5,
        previous_prepare=0x2037f858 + 8 + signed_offset*4,
        paint_begin=0x2037c9f5, paint_finish=0x2037c6d9,
        fill=0x2037c625, label=0x2037c999, mode_close=0x200f192c+late,
        stock_mode_text=0x20178938+late,
        mode_select=0x20080a34+early, data_toggle=0x20080e50+early, beep=0x2007d478+early,
    )
    if aprs is not None:
        imports.update(aprs_strip_visible=aprs["gate_aprs_strip_visible"],
                       previous_prepare=aprs["aprs_overlay_prepare"])
    return imports


def compile_ui(folder):
    folder = Path(folder).resolve()
    folder.mkdir(exist_ok=True, parents=True)
    obj = folder/"dmr-ui.o"
    run(["arm-none-eabi-gcc", "-c", "-std=c11", "-Oz", "-mcpu=cortex-a9", "-mthumb",
         "-mfpu=vfpv3-d16", "-mfloat-abi=softfp", "-mlong-calls", "-ffreestanding", "-fno-builtin",
         "-fno-unwind-tables", "-Wall", "-Wextra", "-Werror",
         ROOT/"samples/dmr-ui.c", "-o", obj], check=True)
    return obj


def apply_hooks(main, region, symbols, *, aprs=None):
    badge = 0x2015c8b4 + (228 if region=="E" else 0)
    imports=ui_imports(region,aprs)
    early,late=(-152,228) if region=="E" else (0,0)
    hooks=HOOKS | {badge: ("dmr_mode_text",0xeb00701f)}
    for at,new,old in ((0x2009639c+early,"digital_strip_visible","aprs_strip_visible"),
                       (0x200963b0+early,"digital_row_prepare","stock_row_prepare"),
                       (0x20163600+late,"digital_row_draw","stock_row_draw")):
        hooks[at]=(new,0xeb000000|(((imports[old]-at-8)>>2)&0xffffff))
    for at, (name, expected) in hooks.items():
        if expected is None:
            expected = 0xebfda1b4 if region == "J" else 0xebfda1ec
        assert unpack_from("<I",main,at-BASE)[0] == expected, hex(at)
        addr = symbols[name]
        assert addr & 1, f"{name} requires a Thumb symbol"
        offset = (addr & ~1) - at - 8
        assert -(1<<25) <= offset < (1<<25)
        opcode = 0xfa000000 | ((offset & 2) << 23) | ((offset>>2) & 0xffffff)
        pack_into("<I",main,at-BASE,opcode)


def link_ui(folder, region, code, bss, backend):
    obj = compile_ui(folder)
    imports = ui_imports(region) | backend
    names = ("dmr_rx_set_enabled", "dmr_ui_get_status")
    assert all(imports.get(n) for n in names)
    text = "\n".join(f"{key} = 0x{value:x};" for key,value in imports.items()) + f"""
    SECTIONS {{
      .ui {code:#x} : {{ *(.text .text.* .rodata .rodata.* .data .data.*) }}
      .work {bss:#x} (NOLOAD) : {{ *(.bss .bss.* COMMON) }}
      /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) }}
    }}
    """
    ld = obj.with_suffix(".ld")
    elf = obj.with_suffix(".elf")
    ld.write_text(text, encoding="ascii")
    run(["arm-none-eabi-ld", "-T", ld, obj, "-o", elf], check=True)
    with elf.open("rb") as f:
        e=ELFFile(f)
        assert e.get_section_by_name(".ui")["sh_addr"] == code
        payload=e.get_section_by_name(".ui").data()
        state_size=e.get_section_by_name(".work")["sh_size"]
        sy={s.name:s["st_value"] for s in e.get_section_by_name(".symtab").iter_symbols()}
    return payload,state_size,sy
