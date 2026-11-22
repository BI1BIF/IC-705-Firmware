"""Replay J140 Flash font discovery and the first test row on a PC."""

import argparse
from contextlib import contextmanager
from collections import deque
from hashlib import sha256
import json
from pathlib import Path
from struct import iter_unpack, pack, unpack
from tempfile import TemporaryDirectory

from tools.emulate_705 import AXI_PAGE, AXI_REGS, BASE, BOOT, PROFILES, SCRATCH, SP, STOP, arm, call, machine, uc
from tools.probe_705_boot_selection import SECOND
from tools.probe_zh_cn_page import build_font
from tools.render_705_display import DAT_HASH, GRAPHICS_FLASH, load
from tools.render_705_stock_row import FONT_HEADER, SMALL_FONT_HEADER, TextSurface, png, require
from tools.replay_705_boot_surfaces import BootClears, boot_outline
from tools.replay_705_home_inputs import channel_index_fixture
from tools.replay_705_nor_boot import DSFR, POWER_KEY, POWER_LATCH, boot_from_nor, with_pc_main
from tools.virtual_705_display_catalog import FONT_SOURCE_SHA


RESOURCE_ENTRY, RESOURCE_CONTINUE = 0x2010490C, 0x201049AC
FONT_TABLE, UI_FONT_INIT, MEMORY_FACE = 0x2038089C, 0x20141DEC, 0x2025D1BC
DRAW_RUN, CHAR_INDEX = 0x20197A90, 0x2025B668
STOCK_TEXT, TEST_TEXT = "表示言語", "表设简显"
STBCR3, STBCR5, STBCR6 = 0xFCFE0420, 0xFCFE0428, 0xFCFE042C
MTU2_TCR4 = 0xFCFF0201
OSTM1_TT, OSTM1_CTL = 0xFCFEC418, 0xFCFEC420
DMA_DCTRL = (0xE8200300, 0xE8200700)
RESOURCE_BRANCH, RESOURCE_FLAG, RESOURCE_TAG = 0x20104948, 0x20380740, 0x18BF0000
EXPECTED_TAG = b"SX4075 V0.10-000\0"
RESOURCE_TASK, TASK_RETURN, BOARD_INIT = 0x20098334, 0x20098390, 0x2007BBA8
GICC = 0xE8202000
GPIO = 0xFCFE3000
RIIC0_ICCR2, RIIC0_BUSY_INSN, RIIC0_WAIT_INSN = 0xFCFEE004, 0x2005BC28, 0x2005BC8C
RIIC0 = 0xFCFEE000
RIIC1 = 0xFCFEE400
RIIC0_HANDLERS = {189: 0x2005BA70, 191: 0x2005B9A0, 192: 0x2005B94C, 193: 0x2005B8D8}
RIIC0_DESCRIPTOR = 0x20399F24
RIIC0_READ_WAIT, RIIC0_READ_HANDLER = 0x2005BD54, 0x2005BAE0
GPIO_I2C_READ = 0x2005E3CC
UI_CREATED, UI_HANDLE, STARTUP_TIMER_WRITE = 0x2007B2B0, 0x20380CC4, 0x2011EAB4
STARTUP_DMA, STARTUP_DMA_IRQ, STARTUP_DMA_BUSY = 0xE8200480, 51, 0x20380B5C
STARTUP_RSPI0, STARTUP_RSPI3, UI_ENTRY = 0xE800C800, 0xE800E000, 0x2013D564
BOARD_TIMER_IRQ, BOARD_RSPI_IRQ = 162, 280
AUDIO_FRAME_PIN = 0xFCFE3208  # P2.9, SSIF0 word select on the MAIN schematic.
AUDIO_FRAME_POLLS = (0x200FF0BC, 0x200FF0EC, 0x200FF11C, 0x200FF14C, 0x200FF17C,
                     0x200FF1AC, 0x200FF1DC, 0x200FF20C, 0x200FF23C, 0x200FF26C)
AUDIO_SSIF = (0xE820B000, 0xE820C800, 0xE820D800)
AUDIO_DMAC = (0xE82000C0, 0xE8200100, 0xE8200400, 0xE8200500)
EEPROM_VERSION = 0x202E27B9
EEPROM_VERSION_COMPARE = 0x2007B450
ADC_STATUS = 0xE8005860
SCIF3_SPTR = 0xE8008820
SCIF3 = SCIF3_SPTR-0x20
SCIF_REG_WIDTHS = {0: 2, 4: 1, 8: 2, 0x10: 2, 0x18: 2, 0x20: 2}
SCIF_START_IRQS = (56, 161, 235)
GPIO_CONFIG_GROUPS = (0, 3, 4, 5, 6, 10, 0x40, 0x41, 0x42)
RIIC_CONFIG_OFFSETS = (0, 8, 0x10, 0x14, 0x28, 0x34, 0x38, 0x400, 0x404, 0x408,
                       0x410, 0x418, 0x41C, 0x424, 0x434, 0x438)
RIIC_IRQS = (189, 190, 191, 192, 193, 194, 197, 198, 199, 200, 201, 202)
MTU2 = 0xFCFF0000
GICD = 0xE8201000
MTU2_REGISTERS = {
    **dict.fromkeys((0x200, 0x201, 0x202, 0x203, 0x204, 0x205, 0x206, 0x207,
                     0x208, 0x209, 0x280, 0x300, 0x301, 0x302, 0x303, 0x304, 0x381), 1),
    **dict.fromkeys((0x210, 0x212, 0x218, 0x21C, 0x306, 0x308, 0x30A, 0x30C, 0x30E, 0x320, 0x322, 0x386), 2),
}


def stop_at_first_missing(main):
    cpu = machine(main)
    faults = []

    def record(cpu, access, address, size, _value, _data):
        faults.append((access, cpu.reg_read(arm.UC_ARM_REG_PC), address, size))
        return False

    cpu.hook_add(uc.UC_HOOK_MEM_INVALID, record)
    try:
        call(cpu, RESOURCE_ENTRY)
    except uc.UcError as exc:
        require(exc.errno == uc.UC_ERR_READ_UNMAPPED, "unexpected resource entry fault")
    require(faults == [(uc.UC_MEM_READ_UNMAPPED, 0x20367B04, 0xFCFE042C, 1)],
            f"unexpected resource entry stop: {faults}")
    _, pc, address, size = faults[0]
    return {"entry": hex(RESOURCE_ENTRY), "read_pc": hex(pc), "address": hex(address), "size": size}


def trace_resource_mmio(main, initial_stbcr5, initial_stbcr6, *, stbcr3=None, allow_tcr4=False):
    cpu = machine(main)
    clocks = {STBCR5: initial_stbcr5, STBCR6: initial_stbcr6}
    if stbcr3 is not None:
        clocks[STBCR3] = stbcr3
    timer_stopped, timer_control = False, None
    dma_control = {}
    trace, fault = [], {}

    def access(kind, base, offset, size, value=0):
        nonlocal timer_stopped, timer_control
        address = base+offset
        supported = True
        if size == 1 and address in clocks:
            if kind == "read":
                value = clocks[address]
            else:
                clocks[address] = value
        elif size == 1 and kind == "write" and address == MTU2_TCR4 and allow_tcr4 and not clocks.get(STBCR3, 8) & 8:
            pass  # shortcut: records the setup write only; advance or read MTU2 after timer behavior is modeled.
        elif size == 1 and kind == "write" and not clocks[STBCR5] & 1:
            if address == OSTM1_TT and value == 1:
                timer_stopped = True
            elif address == OSTM1_CTL and timer_stopped and value == 2:
                timer_control = value
            else:
                supported = False
        elif size == 4 and kind == "write" and address in DMA_DCTRL and value == 1:
            dma_control[address] = value
        else:
            supported = False
        if not supported:
            record_stop(kind, address, size, value)
            cpu.emu_stop()
            return 0
        trace.append([kind, hex(cpu.reg_read(arm.UC_ARM_REG_PC)), hex(address), value])
        return value

    def record_stop(kind, address, size, value):
        fault.update(kind=kind, pc=hex(cpu.reg_read(arm.UC_ARM_REG_PC)), address=hex(address), size=size)
        if kind == "write":
            fault["value"] = value

    def unmapped(_cpu, kind, address, size, value, _data):
        record_stop("write" if kind == uc.UC_MEM_WRITE_UNMAPPED else "read", address, size, value)
        return False

    pages = (0xFCFE0000, 0xFCFEC000, 0xE8200000) + ((0xFCFF0000,) if allow_tcr4 else ())
    for base in pages:
        cpu.mmio_map(base, 0x1000, lambda _, off, size, page: access("read", page, off, size), base,
                     lambda _, off, size, value, page: access("write", page, off, size, value), base)
    cpu.hook_add(uc.UC_HOOK_MEM_READ_UNMAPPED | uc.UC_HOOK_MEM_WRITE_UNMAPPED, unmapped)
    try:
        call(cpu, RESOURCE_ENTRY)
    except uc.UcError as exc:
        require(fault and exc.errno in (uc.UC_ERR_READ_UNMAPPED, uc.UC_ERR_WRITE_UNMAPPED),
                f"unexpected MMIO exception: {exc}")
    except ValueError:
        if not fault:
            raise
    require(fault, "no unsupported MMIO access recorded")
    require(len(trace[:8]) == 8 and clocks[STBCR5] == initial_stbcr5 & ~1 and clocks[STBCR6] == initial_stbcr6 | 1
            and timer_stopped and timer_control == 2 and dma_control == dict.fromkeys(DMA_DCTRL, 1),
            "unexpected clock, timer or DMA setup")
    expected_tail = []
    if stbcr3 is not None:
        expected_tail = [["read", "0x20367b04", hex(STBCR3), stbcr3],
                         ["write", "0x20367b10", hex(STBCR3), stbcr3 & ~8]]
        if allow_tcr4:
            expected_tail.append(["write", "0x20005d80", hex(MTU2_TCR4), 0])
    require(trace[8:] == expected_tail, "unexpected MTU2 setup sequence")
    require(bytes(cpu.mem_read(FONT_TABLE+4, 16)) == bytes(16), "early MMIO path touched the font table")
    return {"entry": hex(RESOURCE_ENTRY), "fixture_initial_clocks": [initial_stbcr5, initial_stbcr6],
            "mmio": trace, "stop": fault, "font_table_written": False}


def replay_resource_branch(cpu, records, flag, tag):
    """Start after unrelated peripheral setup, using a synthetic caller frame and optional tag."""
    require(bytes(cpu.mem_read(FONT_TABLE+4, 16)) == bytes(16), "font table was already initialized")
    if tag is not None:
        require(len(tag) == len(EXPECTED_TAG), "unexpected tag fixture size")
        cpu.mem_map(RESOURCE_TAG, 0x1000, uc.UC_PROT_READ)
        cpu.mem_write(RESOURCE_TAG, tag)
    cpu.mem_write(RESOURCE_FLAG, bytes((flag,)))
    cpu.reg_write(arm.UC_ARM_REG_R4, FONT_TABLE)
    cpu.reg_write(arm.UC_ARM_REG_SP, SP-8)
    cpu.mem_write(SP-8, pack("<2I", 0, STOP))
    expected_end = STOP if flag else RESOURCE_CONTINUE
    cpu.emu_start(RESOURCE_BRANCH, expected_end, timeout=2_000_000, count=100_000)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == expected_end, "resource branch did not reach the expected boundary")
    words = unpack("<4I", cpu.mem_read(FONT_TABLE+4, 16))
    expected = (0, 0, 0, 0) if flag else tuple(word for addr, data in records for word in (addr+4, len(data)))
    status = cpu.mem_read(FONT_TABLE+1, 1)[0]
    require(words == expected and status == int(not flag and tag != EXPECTED_TAG), "unexpected resource branch result")
    return {"entry": hex(RESOURCE_BRANCH), "stop_pc": hex(expected_end), "caller_flag": flag,
            "flash_tag_fixture": None if tag is None else tag.hex(), "comparison_flag": status,
            "pointer_table": [[hex(words[i]), words[i+1]] for i in (0, 2)]}


def map_font_records(cpu, large, small):
    records = ((FONT_HEADER, large), (SMALL_FONT_HEADER, small))
    flash_end = (SMALL_FONT_HEADER+4+len(small)+0xFFF) & ~0xFFF
    cpu.mem_map(FONT_HEADER, flash_end-FONT_HEADER, uc.UC_PROT_READ)
    for address, data in records:
        require(0 < len(data) <= SMALL_FONT_HEADER-FONT_HEADER-4, "invalid font fixture size")
        cpu.mem_write(address, pack("<I", len(data))+data)
    return records


@contextmanager
def resource_peripherals(cpu, seed, board_io=None, *, track_board_irqs=False):
    clocks = (STBCR3, STBCR5, STBCR6)
    values = dict.fromkeys(clocks, seed)
    values.update(dict.fromkeys((MTU2+0x208, MTU2+0x209, MTU2+0x280), 0))
    gic_enable = 0
    trace, faults = [], []

    def mmio(kind, addr, width, value=0):
        nonlocal gic_enable
        pc = cpu.reg_read(arm.UC_ARM_REG_PC)
        if (addr in clocks and width == 1 or
                MTU2_REGISTERS.get(addr-MTU2) == width and not values[STBCR3] & 8):
            if kind == "write":
                values[addr] = value
            else:
                require(addr in values, f"uninitialized register read {addr:#x} from {pc:#x}")
                value = values[addr]
        elif kind == "write" and (
                (addr, width, value) in ((OSTM1_TT, 1, 1), (OSTM1_CTL, 1, 2)) and not values[STBCR5] & 1 or
                addr in DMA_DCTRL and width == 4 and value == 1 or
                addr-GICD in (0x49A, 0x49F, 0x89A, 0x89F) and width == 1):
            values[addr] = value
        elif kind == "write" and addr == GICD+0x110 and width == 4:
            if value in (1 << (159-128), 1 << (154-128)):
                gic_enable |= value  # GICD_ISENABLER4 is write-one-to-set.
            if track_board_irqs:
                board_io(kind, addr, width, value)
        elif board_io is not None:
            return board_io(kind, addr, width, value)
        else:
            raise ValueError(f"unmodeled {kind} at {addr:#x} from {pc:#x} ({width} bytes)")
        trace.append([kind, hex(pc), hex(addr), width, value])
        return value

    def unmapped(cpu, access, addr, width, _value, _data):
        faults.append((access, hex(cpu.reg_read(arm.UC_ARM_REG_PC)), hex(addr), width))
        return False

    handle = cpu.hook_add(uc.UC_HOOK_MEM_INVALID, unmapped)
    for base in (0xFCFE0000, 0xFCFEC000, 0xE8200000, MTU2, GICD):
        cpu.mmio_map(base, 0x1000,
                     lambda _, off, width, page: mmio("read", page+off, width), base,
                     lambda _, off, width, value, page: mmio("write", page+off, width, value), base)
    try:
        yield trace
    except uc.UcError as exc:
        raise ValueError(f"original resource entry stopped at {faults}") from exc
    finally:
        cpu.hook_del(handle)
    def setup_value(address):
        return (next((row[-1] for row in trace if row[0] == "write" and row[2] == hex(address)), None)
                if track_board_irqs else values[address])
    require((values[STBCR3] == seed & ~8 if board_io is None else not values[STBCR3] & 8) and
            setup_value(MTU2+0x21C) == 8000 and setup_value(MTU2+0x218) == 10000 and
            (any(row[0] == "write" and row[2:] == [hex(MTU2+0x280), 1, 0xC1] for row in trace)
             if track_board_irqs else values[MTU2+0x280] == 0xC1) and
            gic_enable == (1 << (159-128) | 1 << (154-128)),
            f"unexpected MTU2 or GIC setup: {values=} {gic_enable=:#x}")


def map_resource_tag(cpu, tag):
    require(len(tag) == len(EXPECTED_TAG), "invalid resource tag fixture")
    cpu.mem_map(RESOURCE_TAG, 0x1000, uc.UC_PROT_READ)
    cpu.mem_write(RESOURCE_TAG, tag)


def replay_resource_entry(cpu, records, seed, tag, flag=0):
    """Execute the original entry with a bounded, register-only peripheral fixture."""
    require(seed in (0, 255) and flag in (0, 1), "invalid resource fixture")
    require(bytes(cpu.mem_read(FONT_TABLE+4, 16)) == bytes(16), "font table was already initialized")
    map_resource_tag(cpu, tag)
    if flag:
        cpu.mem_write(RESOURCE_FLAG, bytes((flag,)))
    writes = []

    def observe(cpu, _access, addr, width, value, _data):
        writes.append([hex(cpu.reg_read(arm.UC_ARM_REG_PC)), hex(addr), width, value])

    expected_pc = STOP if flag else RESOURCE_CONTINUE
    handle = cpu.hook_add(uc.UC_HOOK_MEM_WRITE, observe, begin=FONT_TABLE+4, end=FONT_TABLE+19)
    cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)
    cpu.reg_write(arm.UC_ARM_REG_SP, SP)
    cpu.reg_write(arm.UC_ARM_REG_LR, STOP)
    try:
        with resource_peripherals(cpu, seed) as trace:
            cpu.emu_start(RESOURCE_ENTRY, expected_pc, timeout=2_000_000, count=100_000)
    finally:
        cpu.hook_del(handle)
    words = unpack("<4I", cpu.mem_read(FONT_TABLE+4, 16))
    expected_words = (0, 0, 0, 0) if flag else tuple(word for addr, data in records for word in (addr+4, len(data)))
    expected_writes = [] if flag else [
        [hex(pc), hex(FONT_TABLE+4*(i+1)), 4, expected_words[i]]
        for i, pc in enumerate((0x2010498C, 0x20104994, 0x201049A0, 0x201049A8))
    ]
    status = cpu.mem_read(FONT_TABLE+1, 1)[0]
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == expected_pc and words == expected_words and
            writes == expected_writes and status == int(not flag and tag != EXPECTED_TAG),
            "resource entry did not initialize the expected font records")
    return {"entry": hex(RESOURCE_ENTRY), "stop_pc": hex(expected_pc), "clock_seed": seed,
            "caller_flag": flag, "flash_tag_fixture": tag.hex(), "comparison_flag": status,
            "pointer_table": [[hex(words[i]), words[i+1]] for i in (0, 2)], "font_table_writes": writes,
            "gic_enabled_ids": [154, 159], "mmio": trace}


def replay_resource_task(main, large, small, *, fixture_return, loader=None, adc_sample=None, scif_wait=None,
                         vbus_high=False, power_key_released=None, riic0_idle=False, riic0_finish=None,
                         eeprom=None, startup_dma=None, scene_preview=None, after_lcd=False, settings_reload=False,
                         startup_flash=None, startup_panel_record=False, startup_home_probe=False,
                         no_power_on_check=False, startup_input=None, cw_extension=None, cw_rx_ready=False,
                         cw_rx_audio=None, cw_rx_record_gate=None, cw_rx_closed_sql=False, cw_canvas_audit=None,
                         cw_stock_state=False, stock_mmu=False,
                         cw_heap_offset=0, cw_image=None, startup_from_nor=False, nor_snapshot=None,
                         nor_missing_secondary=False, home_observer=None):
    """Run the caller and use the guest's real SVC vector; bracket the unmodeled board routine."""
    require(not startup_from_nor or (stock_mmu and startup_flash and loader and power_key_released is False and
                                    startup_dma == "format-current" and not cw_extension),
            "NOR replay requires the current-format startup without a host CW attachment")
    require(nor_snapshot is None or startup_from_nor, "a NOR snapshot requires startup from NOR")
    require(not nor_missing_secondary or nor_snapshot is not None, "the unreadable slot control needs a NOR snapshot")
    cpu = machine(b"" if startup_from_nor else main)
    if loader is not None:
        # The board fixture starts with Unicorn's floating-point unit enabled.
        cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
        cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    if nor_snapshot is None:
        records = map_font_records(cpu, large, small)
        map_resource_tag(cpu, EXPECTED_TAG)
    else:
        records = ((FONT_HEADER, large), (SMALL_FONT_HEADER, small))
        for address, data in records:
            start = address-BOOT
            require(nor_snapshot[start:start+4+len(data)] == pack("<I", len(data))+data,
                    "virtual NOR snapshot font differs from the stock reference")
    nor_boot = (boot_from_nor(cpu, startup_flash, main, snapshot=nor_snapshot, missing_main=nor_missing_secondary)
                if startup_from_nor else None)
    slot_adjust = int(nor_boot["source_slot"], 16)-SECOND if nor_boot else 0
    cpu.mem_write(RESOURCE_FLAG, b"\xa5")  # The original task must clear this itself.
    pmr = 0xF0
    gicc_enabled = 1
    svc, pmr_trace, flags, writes, calls, returns, faults, board_calls = ([] for _ in range(8))
    board_trace, boot_reads = [], []
    board_checkpoints, power_checks, boot_modes = [], [], []
    stored, counter, running = {}, 0, False
    timer_polls = 0
    scif_boundaries = []
    recent_blocks = deque(maxlen=36)
    board_full = scif_wait == "board_power"
    require(startup_input is None or no_power_on_check and startup_input in ("neutral", "close", "close-idle", "close-menu", "close-cw"),
            "startup input replay requires the Power ON Check OFF fixture")
    cw_startup = startup_input == "close-cw"
    cw_enabled = cw_extension is not None or cw_image is not None
    native_picker_id = cw_image.get("picker_id") if cw_image else None
    require(not cw_enabled or cw_startup, "CW decoder requires the stock CW startup fixture")
    require(not cw_image or stock_mmu and cw_extension is None and cw_canvas_audit == "stock" and cw_rx_audio,
            "PC image requires a stock MMU boot without host attachment")
    require(not cw_canvas_audit or cw_canvas_audit in ("stock", "fixed") and cw_rx_audio,
            "stock canvas audit requires cold-start receive")
    require(not cw_stock_state or cw_canvas_audit == "stock", "stock state requires the original canvas audit")
    require(not stock_mmu or no_power_on_check and cw_startup and (cw_extension is None or cw_stock_state),
            "stock address translation requires stock HOME or the fully allocated CW fixture")
    require(not cw_heap_offset or stock_mmu and cw_extension, "heap offset requires the mapped CW replay")
    require(not cw_rx_ready or cw_startup, "CW receive uses the stock CW startup fixture")
    if cw_rx_audio is not None:
        require(cw_enabled and cw_rx_ready and len(cw_rx_audio) >= 160 and not len(cw_rx_audio)%12,
                "CW audio requires the receive fixture and complete six-sample groups")
    require(cw_rx_record_gate is None or cw_rx_record_gate in (0, 2) and cw_image and cw_rx_audio,
            "alternate recording gate needs a packaged CW receive test")
    if cw_image:
        symbols = cw_image["symbols"]
        anchor = symbols["cw_state_anchor"]
        install_writes, worker_entries = [], []

        def observe_anchor(c, _access, _addr, size, value, _data):
            install_writes.append(dict(pc=hex(c.reg_read(arm.UC_ARM_REG_PC)), size=size, state=hex(value)))

        def observe_worker(c, address, *_):
            worker_entries.append(dict(pc=hex(address), sp=hex(c.reg_read(arm.UC_ARM_REG_SP))))

        cpu.hook_add(uc.UC_HOOK_MEM_WRITE, observe_anchor, begin=anchor, end=anchor+3)
        worker = symbols["cw_rtx_worker"]
        cpu.hook_add(uc.UC_HOOK_CODE, observe_worker, begin=worker, end=worker)
    require(not cw_rx_closed_sql or cw_image and cw_rx_audio and cw_rx_record_gate is None,
            "closed SQL requires packaged receive without a PCM bridge override")
    stock_audio_gate = 0 if cw_rx_closed_sql else 1
    rx_squelch = 255 if cw_rx_closed_sql else 0
    startup_settings = channel_index_fixture() if startup_input else {}
    wake_test = power_key_released is not None
    wake_stop = RIIC0_WAIT_INSN if riic0_idle else RIIC0_BUSY_INSN
    require(not riic0_idle or power_key_released is False, "RIIC idle control requires a held key")
    key_polls = 0
    wake_path = []
    wake_handoff = None
    riic_steps = []
    riic_return = followup_read = None
    riic_sent = []
    first_riic_request = None
    riic_read_trace = None
    riic_read_input = deque()
    rtc_bus = None
    late_panel_dma = None
    late_adc_reads = None
    eeprom_result = None
    eeprom_active = False
    eeprom_bits = iter(())
    eeprom_sent = []
    eeprom_samples = 0
    eeprom_nacks = 0
    startup_devices, startup_writes = {}, []
    board_spi_rx, board_spi_tx = deque(), []
    board_reply_ready = False
    settings_test = startup_dma == "settings-match"
    surfaces_test = startup_dma == "surfaces-match"
    openvg_test = startup_dma == "openvg-match" or surfaces_test
    display_test = startup_dma == "display-match" or openvg_test
    settings_test |= display_test
    standby_ack = iter((0x20, 0x20, 0))
    standby_steps = []
    current_format = startup_dma == "format-current"
    format_test = settings_test or startup_dma in ("format-blank", "format-match") or current_format
    riic_read_sample = 1 if format_test else {"riic-read-01": 1, "riic-read-ff": 0xFF}.get(startup_dma)
    record_test = startup_dma in ("records-match", "records-differ") or riic_read_sample is not None
    audio_boot = startup_dma == "audio" or record_test
    rspi_boot = startup_dma in ("rspi", "queue", "reply") or audio_boot
    queue_boot = startup_dma in ("queue", "reply") or audio_boot
    audio_stage = False
    audio_regs, audio_trace, frame_reads = {}, [], []
    post_lcd_io = None
    panel_dma_config = {
        0x2008D06C: (0xE82000AC, 0x00626402),
        0x2008D074: (0xE82000B0, 0x20),
        0x2008D07C: (0xE82000B4, 0),
    }
    panel_dma_writes = []
    frame_levels = iter(())
    require(startup_dma is None or (startup_dma in ("withheld", "complete") or rspi_boot) and eeprom,
            "startup DMA replay requires readable EEPROM and a completion control")
    require(eeprom is None or riic0_finish == "stop" and len(eeprom) in (0, 16), "invalid EEPROM fixture")
    require(riic0_finish in (None, "stop", "no_stop") and (riic0_finish is None or riic0_idle),
            "invalid RIIC completion fixture")
    if wake_test:
        require(board_full and loader is not None and vbus_high, "invalid wake fixture")
        stored[DSFR] = 0x8400  # Fixed wake latches for both controls; only P8.7 differs.
        if nor_boot:
            wake_handoff = nor_boot["wake_handoff"]
            stored[DSFR] = latches_after_loader = nor_boot["latches_after_loader"]
            stored[POWER_LATCH] = loader_latch = nor_boot["power_latch_after_loader"]
            key_polls = nor_boot["key_polls"]
            board_trace.extend(list(row) for row in nor_boot["early_registers"] if row[2] == hex(POWER_LATCH))
    complete = board_full or scif_wait == "rx_frame"
    rx_test = complete or scif_wait == "rx_prefix"
    irq_test = rx_test or scif_wait == "timer_irq"
    second_pass = fixture_return
    active_irq = None
    software_irq_pending = False
    release_boundary = None
    rtx_ticks = software_irqs = app_ticks = 0
    rx_fifo = bytearray()
    irq_trace, irq_checkpoints = [], []
    if adc_sample is not None:
        stored[ADC_STATUS] = 0x8000  # Control: conversion already completed before this poll.
    if scif_wait is not None:
        stored[SCIF3+0x10] = 0x60  # TEND and TDFE; the receive FIFO stays empty.

    def pc():
        return cpu.reg_read(arm.UC_ARM_REG_PC)

    mapping_checkpoints = []

    def cpr(crn, opc2=0):
        return cpu.cpr_read(15, 0, crn, 0, opc2, 0, False)

    def mapping_state(_cpu, _addr, _width, _data):
        mapping_checkpoints.append({"pc": hex(pc()), "sctlr": hex(cpr(1)), "ttbr0": hex(cpr(2)),
                                    "l1_sha256": sha256(bytes(cpu.mem_read(0x20000000, 0x4000))).hexdigest()})

    def exception(cpu, number, _):
        next_pc = pc()
        cpsr = cpu.reg_read(arm.UC_ARM_REG_CPSR)
        if stock_mmu and number != 2:
            raise ValueError(f"stock reset exception {number} at {next_pc:#x} {cpsr=:#x}; "
                             f"SCTLR={cpr(1):#x} TTBR0={cpr(2):#x} DFSR={cpr(5):#x} IFSR={cpr(5, 1):#x} "
                             f"DFAR={cpr(6):#x} IFAR={cpr(6, 2):#x} {board_trace[-8:]=}")
        is_thumb = bool(cpsr & 0x20)
        svc_instruction = int.from_bytes(cpu.mem_read(next_pc-(2 if is_thumb else 4), 2 if is_thumb else 4), "little")
        require(number == 2 and (cpsr & 0x1F) in (0x10, 0x1F) and
                (svc_instruction in (0xDF00, 0xEF000001) if board_full else
                 next_pc == 0x202D4936 and not svc and cpsr & 0x3F == 0x3F),
                f"unexpected guest exception {number} at {next_pc:#x} {cpsr=:#x} count={len(svc)} "
                f"{scif_boundaries[-12:]=} {board_trace[-8:]=}")
        svc.append({"next_pc": hex(next_pc), "vector": hex(BASE+8)})
        cpu.reg_write(arm.UC_ARM_REG_CPSR, (cpsr & ~0x3F) | 0x93)
        cpu.reg_write(arm.UC_ARM_REG_SPSR, cpsr)
        cpu.reg_write(arm.UC_ARM_REG_LR, next_pc)
        cpu.reg_write(arm.UC_ARM_REG_PC, BASE+8)

    def gicc_io(kind, off, width, value=0):
        nonlocal pmr, gicc_enabled
        if stock_mmu and (kind, off, width, pc(), value) == ("write", 8, 4, 0x20124584, 3):
            board_trace.append([kind, hex(pc()), hex(GICC+off), width, value])
            return value
        if board_full and off == 0 and width == 4:
            if kind == "write":
                gicc_enabled = value
            board_trace.append([kind, hex(pc()), hex(GICC), width, gicc_enabled])
            return gicc_enabled
        if active_irq is not None and off in (0x0C, 0x10, 0x18) and width == 4:
            require((kind == "write" and off == 0x10 and value == active_irq) or
                    (kind == "read" and off in (0x0C, 0x18)), "unexpected timer GICC access")
            irq_trace.append([kind, hex(pc()), hex(GICC+off), active_irq])
            return active_irq
        require(off == 4 and width == 4, f"unexpected GICC access at {off:#x} from {pc():#x}")
        if kind == "write":
            pmr = value & 0xFF
        pmr_trace.append([kind, hex(pc()), pmr])
        return pmr

    def note_flag(_cpu, _access, _addr, width, value, _):
        if board_full and pc() == 0x200052F2:
            return
        require(width == 1, f"unexpected task flag write size at {pc():#x}")
        flags.append([hex(pc()), value])

    def note_font(_cpu, _access, addr, width, value, _):
        if board_full and pc() == 0x200052F2:
            return  # The reset scatter copy precedes the task and initializes these words to zero.
        writes.append([len(calls), hex(pc()), hex(addr), width, value])

    def note_call(_cpu, _addr, _size, _):
        calls.append(cpu.mem_read(RESOURCE_FLAG, 1)[0])

    def note_return(_cpu, _addr, _size, _):
        returns.append(len(writes))
        if len(returns) == 2:
            cpu.emu_stop()

    def board(_cpu, _addr, _size, _):
        ret = cpu.reg_read(arm.UC_ARM_REG_LR)
        require(ret == 0x20098394 and not board_calls, "unexpected board call")
        board_calls.append(hex(ret))
        if fixture_return:
            cpu.reg_write(arm.UC_ARM_REG_PC, ret)

    def read_boot_flag(_cpu, _access, addr, width, _val, _data):
        require(pc() == 0x20004990 and addr == 0x20004F20 and width == 1, "unexpected boot flag access")
        boot_reads.append([hex(pc()), hex(addr), cpu.mem_read(addr, 1)[0]])

    def board_io(kind, addr, width, value):
        nonlocal counter, running, timer_polls, software_irq_pending, key_polls, eeprom_samples, eeprom_nacks
        if stock_mmu and pc() in (0x2011C030, 0x2011C03C, 0x2011C048, 0x2011C050, 0x2011C058, 0x2011C060):
            require(kind == "write" and width == 4 and addr-AXI_PAGE in AXI_REGS,
                    f"unexpected AXI setup at {pc():#x}/{addr:#x}")
            stored[addr] = value
            board_trace.append([kind, hex(pc()), hex(addr), width, value])
            return value
        if stock_mmu and 0x20124360 <= pc() <= 0x20124790:
            # RZ/A1H hardware manual, table 7.2. Model only setup accesses from reset.
            off = addr-GICD
            if width == 4 and off in (0, 4, 8):
                if kind == "write":
                    require(off == 0 and value in (0, 1), "unexpected distributor control")
                    stored[addr] = value
                return stored.get(addr, {0: 0, 4: 0xFC31, 8: 0x43B}[off])
            if width == 1 and off in (0x400, 0x800):
                if kind == "write":
                    stored[addr] = value
                return stored.get(addr, 0)
            if kind == "write" and width == 1 and (0x64B <= off <= 0x67F or 0xA4B <= off <= 0xA7F):
                # Startup rounds its loop to a group boundary. No simulated IRQs use these byte lanes.
                return 0
            if kind == "write" and width == 4 and 0xC04 <= off <= 0xC90 and off % 4 == 0:
                stored[addr] = value
                return value
        if late_adc_reads is not None and kind == "read" and width == 2 and ADC_STATUS-0x60 <= addr <= ADC_STATUS-0x52:
            # Idle simulated inputs for the first board sensor poll; reuse the existing power readings.
            expected = ((0x2011DEEC, 2), (0x2011DEF8, 14), (0x2011DF0C, 12),
                        (0x2011DF18, 8), (0x2011DF24, 10), (0x2011DF30, 0))
            offset = addr-(ADC_STATUS-0x60)
            require((pc(), offset) in expected, f"unexpected idle ADC poll: {pc():#x}/{addr:#x}")
            value = adc_sample << 6 if offset in (12, 14) else 0
            late_adc_reads.append([hex(pc()), hex(addr), width, value])
            return value
        if late_panel_dma is not None and 0xE8200080 <= addr <= 0xE82000A8:
            # Only the setup emitted by the first stock panel DMA2 request. No transfer or completion.
            origin = cpu.reg_read(arm.UC_ARM_REG_LR)
            if kind == "read":
                value = stored.get(addr, 0)
            row = (kind, pc(), addr, width, value, origin)
            expected = (
                ("write", 0x2008CF70, 0xE8200084, 4, 0xFCFE310C, 0x2008E5F4),
                ("write", 0x2008CF78, 0xE8200080, 4, 0x203DA4A0, 0x2008E5F4),
                ("write", 0x2008CF84, 0xE8200088, 4, 0x30, 0x2008E5F4),
                *((k, i, 0xE82000A8, 4, v, ret)
                  for ret, cmd in ((0x2008CFA0, 8), (0x2008CFB4, 4), (0x2008E5F4, 1))
                  for k, i, v in (("read", 0x20367B34, 0), ("write", 0x20367B40, cmd))),
            )
            require(len(late_panel_dma) < len(expected) and row == expected[len(late_panel_dma)],
                    f"unexpected panel DMA2 setup: {row}")
            if kind == "write" and addr != 0xE82000A8:
                stored[addr] = value  # CHCTRL is a command register; these bits strobe.
            late_panel_dma.append(row)
            return value
        if post_lcd_io is not None:
            # Stationary tuning encoder: MTU2 channel 1 TSR_1 has no overflow/underflow.
            if current_format and (kind, addr, width) == ("read", MTU2+0x385, 1) and pc() == 0x20367B48:
                require(cpu.reg_read(arm.UC_ARM_REG_LR) == 0x2000630C and
                        cpu.reg_read(arm.UC_ARM_REG_R2) in (0x10, 0x20), "unexpected encoder status poll")
                value = 0xC0  # RZ/A1H hardware manual §10.3.5 reset value.
                board_trace.append([kind, hex(pc()), hex(addr), width, value])
                return value
            if current_format and addr == 0xFCFE0444 and width == 1:  # STBCR12; zero low bits enable SDHI clocks.
                if kind == "write":
                    require(pc() == 0x20126354 and value == 0xF0, "unexpected SDHI clock enable")
                    stored[addr] = value
                else:
                    require(pc() == 0x20126358 and stored.get(addr) == 0xF0, "unexpected SDHI clock readback")
                    value = stored[addr]
                board_trace.append([kind, hex(pc()), hex(addr), width, value])
                return value
            if current_format and pc() in panel_dma_config:
                require((kind, width, (addr, value)) == ("write", 4, panel_dma_config[pc()]),
                        f"unexpected panel DMA2 configuration at {pc():#x}")
                panel_dma_writes.append([hex(pc()), hex(addr), width, value])
                return value
            if width == 4 and any(addr-base in (0x24, 0x28, 0x2C) for base in AUDIO_DMAC):
                offset = addr & 63
                if kind == "read":
                    return post_lcd_io.get(addr, 1 if offset == 0x24 else audio_regs.get(addr, 0))
                post_lcd_io[addr] = value
                if offset == 0x28 and value & 0x60:
                    post_lcd_io[addr-4] = 1
                return value
            if width == 1 and addr == MTU2+0x22C:
                if kind == "write":
                    post_lcd_io[addr] &= value
                return post_lcd_io[addr]
        if (settings_test or current_format) and width == 1 and 0x20199538 <= pc() <= 0x20199544:
            if addr == 0xFCFE0034:
                if kind == "write":
                    require(value == (stored.get(addr, 0x20) & ~0x20), "unexpected standby request write")
                    stored[addr] = value
                else:
                    value = stored.get(addr, 0x20)
            elif (kind, addr) == ("read", 0xFCFE0044):
                value = next(standby_ack, None)
                require(value is not None, "stock UI continued reading after standby acknowledged")
            else:
                raise ValueError(f"unexpected standby access {kind} {addr:#x}")
            standby_steps.append([kind, hex(pc()), hex(addr), value])
            return value
        if rtc_bus is not None and RIIC1 <= addr < RIIC1+0x44:
            off = addr-RIIC1
            require(width == 1 and 0x200E3800 <= pc() < 0x200E4700 and
                    off in (0, 4, 8, 0x10, 0x18, 0x1C, 0x24, 0x34, 0x38, 0x3C, 0x40),
                    f"unexpected RTC controller access at {pc():#x}: {kind} {addr:#x}/{width}")
            if off == 0x40:
                require(kind == "read" and active_irq == 198 and rtc_bus["receive"],
                        "unexpected RIIC1 receive-register access")
                value = rtc_bus["receive"].popleft()
            elif kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
            rtc_bus["mmio"].append([kind, hex(pc()), hex(addr), width, value, active_irq])
            return value
        if riic_read_trace is not None and RIIC0 <= addr < RIIC0+0x44:
            off = addr-RIIC0
            require(width == 1 and off in (4, 0x10, 0x1C, 0x24, 0x3C, 0x40) and
                    (active_irq in (*RIIC0_HANDLERS, 190) or 0x2005BCD4 <= pc() <= 0x2005BD6C),
                    f"unexpected RIIC0 read transaction access: {pc():#x} {addr:#x}")
            if off == 0x40:
                require(kind == "read" and active_irq == 190 and riic_read_input, "unexpected RIIC0 receive-register read")
                value = riic_read_input.popleft()
            elif kind == "read":
                value = stored.get(addr, 0)
            else:
                stored[addr] = value
            riic_read_trace.append([kind, hex(pc()), hex(addr), value])
            return value
        if audio_stage:
            if (kind, addr, width) == ("read", AUDIO_FRAME_PIN, 2) and pc() in AUDIO_FRAME_POLLS:
                value = next(frame_levels, None)
                require(value is not None, "guest sampled more than the supplied audio clock levels")
                frame_reads.append([hex(pc()), value >> 9])
                return value
            command = width == 4 and any(addr == base+0x28 for base in AUDIO_DMAC)
            if (width == 1 and addr in (0xFCFE0440, 0xFCFE0434, MTU2+0x305) or
                    width == 2 and addr in (MTU2+0x306, MTU2+0x308, 0xFCFE7108, 0xFCFE711C,
                                            0xFCFE7208, 0xFCFE721C, 0xFCFE341C, 0xFCFE351C,
                                            0xFCFE361C, 0xFCFE3A1C, 0xFCFE3408, 0xFCFE3508,
                                            0xFCFE3608, 0xFCFE3A08) or
                    width == 4 and (addr in (0xE8209700, 0xE820975C, 0xFCFE1004, 0xFCFE1008,
                                            0xFCFE1010, 0xFCFE1018) or
                                    any(addr-base in (0, 4, 0x10, 0x18) for base in AUDIO_SSIF) or
                                    any(addr-base in (0, 4, 8, 0xC, 0x10, 0x14, 0x28, 0x2C, 0x30, 0x34)
                                        for base in AUDIO_DMAC))):
                if kind == "write":
                    audio_regs[addr] = 0 if command else value
                else:
                    value = audio_regs.get(addr, stored.get(addr, 0))
                audio_trace.append([kind, hex(pc()), hex(addr), width, value])
                return value
        group, port = divmod(addr-GPIO, 0x100)
        gpio_port = width == 2 and port % 4 == 0 and port <= 0x2C
        if queue_boot and eeprom_result and addr == STARTUP_RSPI3+4 and width == 1:
            if kind == "write":
                board_spi_tx.append(value)
            else:
                require(active_irq == BOARD_RSPI_IRQ and board_spi_rx, "unexpected board SPI FIFO read")
                value = board_spi_rx.popleft()
            return value
        if queue_boot and eeprom_result and (addr, width) in (
                (MTU2+0x22D, 1), (MTU2+0x212, 2), (MTU2+0x22A, 2), (GICD+0xC82, 1)):
            if kind == "write":
                stored[addr] = value
            return stored.get(addr, 0)
        if rspi_boot and eeprom_result and (
                width == 1 and any(addr-base in (0, 1, 2, 8, 10, 11, 12, 13, 14, 0x20)
                                   for base in (STARTUP_RSPI0, STARTUP_RSPI3)) or
                width == 2 and addr in (STARTUP_RSPI0+0x10, STARTUP_RSPI3+0x10, 0xFCFE710C, 0xFCFE720C,
                                        0xFCFE340C, 0xFCFE350C, 0xFCFE360C, 0xFCFE3A0C) or
                width == 1 and addr in (MTU2+0x209, MTU2+0x240, MTU2+0x242) or
                width == 4 and addr in (0xE820016C, 0xE8200170, 0xE8200174, 0xE820054C, 0xE820056C,
                                        0xE8200570, 0xE8200574, 0xFCFE1008, 0xFCFE1018)):
            if kind == "write":
                startup_writes.append([hex(pc()), hex(addr), width, value])
                stored[addr] = value
            return stored.get(addr, 0)
        if startup_dma and eeprom_result and (
                width == 1 and addr-MTU2 in (0, 1, 2, 4, 5, 0x280) or
                width == 2 and addr-MTU2 in (6, 8) or width == 4 and (
                    addr-STARTUP_DMA in (0, 4, 8, 0x24, 0x28, 0x2C, 0x30, 0x34) or
                    addr in (0xFCFE1014, GPIO+0x118))):
            if kind == "write":
                startup_devices[addr] = value
                startup_writes.append([hex(pc()), hex(addr), width, value])
                if addr == STARTUP_DMA+0x28:
                    state = startup_devices.get(STARTUP_DMA+0x24, 0)
                    if value & 8:  # SWRST
                        state = 0
                    if value & 2:  # CLREN
                        state &= ~1
                    if value & 0x20:  # CLREND
                        state &= ~0x20
                    if value & 1:  # SETEN
                        state |= 1
                    startup_devices[STARTUP_DMA+0x24] = state
                    startup_devices[addr] = 0  # Command bits read back as zero.
            return startup_devices.get(addr, 0)
        if eeprom_active:
            if (kind, addr, width) == ("read", GPIO+0x204, 2):
                if pc() == 0x2005E2EC:
                    if not eeprom:
                        eeprom_nacks += 1
                        return 2  # Data line high: no EEPROM acknowledgement.
                    return 0  # Simulated EEPROM ACK.
                require(pc() == 0x2005D720, f"unexpected EEPROM pin read at {pc():#x}")
                bit = next(eeprom_bits, None)
                require(bit is not None, "firmware requested excess EEPROM bits")
                eeprom_samples += 1
                return bit << 1
            if addr in (GPIO+0x104, GPIO+0x304, GPIO+0x404, GPIO+0x804, GPIO+0x904, 0xFCFE7004):
                if kind == "read":
                    return stored.get(addr, 0)
                stored[addr] = value
                return value
        if board_full and group == 8 and port % 4 == 0 and port <= 0x2C and width == 4 and kind == "write":
            mask = value >> 16
            latch = addr-0x400
            stored[latch] = (stored.get(latch, 0) & ~mask) | (value & mask)
        elif addr == GPIO+0x104 and width == 4 and kind == "write":
            mask = value >> 16
            stored[GPIO+4] = (stored.get(GPIO+4, 0) & ~mask) | (value & mask)
        elif cw_rx_ready and (kind, addr, width) == ("read", GPIO+0x210, 2):
            value = stored.get(addr, 0) | 0x2000  # Released active-low PTT on P2_13.
        elif wake_test and addr == POWER_KEY and width == 2 and kind == "read":
            if pc() == 0x200048BC:
                key_polls += 1
            return 0x80 if power_key_released else 0
        elif gpio_port and group == 2 and kind == "read":
            value = 0x200 if vbus_high and port == 12 else 0  # USB VBUS at P3.9; SCACK stays low.
            if (board_reply_ready and port == 0x1C and active_irq == BOARD_TIMER_IRQ and
                    cpu.mem_read(0x20380B26, 1) == b"\x05"):
                value |= 0x40  # Companion ready after the poll word; synthetic pin response.
        elif gpio_port and group in GPIO_CONFIG_GROUPS:
            if kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
        elif wake_test and (addr, width) == (DSFR, 2):
            if kind == "write":
                stored[addr] &= value
            else:
                value = stored[addr]
        elif (addr, width) in ((0xFCFE0004, 2), (DSFR, 2)) and kind == "read":
            value = 0  # No wake source or retained standby state in this run.
        elif riic0_idle and addr == RIIC0_ICCR2 and width == 1 and pc() == (RIIC0_BUSY_INSN if kind == "read" else 0x2005BC74):
            if kind == "read":
                value = 0  # Control: bus idle. No ACK, data or interrupt is synthesized.
            else:
                require(value == 2, "unexpected RIIC0 request")
        elif riic0_finish is not None and width == 1 and RIIC0 <= addr < RIIC0+0x44 and (
                active_irq in RIIC0_HANDLERS or addr == RIIC0+0x24 and pc() in (0x2005BC98, 0x2005BCA0)):
            require(addr-RIIC0 in (4, 0x1C, 0x24, 0x3C), "unexpected RIIC0 register during first transfer")
            if kind == "read":
                value = stored.get(addr, 0)
            else:
                stored[addr] = value
                if addr == RIIC0+0x3C:
                    riic_sent.append(value)
        elif (width == 1 and addr in (0xFCFE0424, 0xFCFE0438) or
              board_full and width == 1 and addr in (0xFCFE0020, 0xFCFE0408, 0xFCFE0430, 0xFCFE043C) or
              width == 1 and (addr-0xFCFEE000 in RIIC_CONFIG_OFFSETS or board_full and addr == 0xFCFEE01C)):
            if kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
        elif kind == "write" and width == 1 and (addr-GICD)//0x400 in (1, 2) and (addr-GICD)%0x400 in RIIC_IRQS:
            stored[addr] = value
        elif kind == "write" and width == 4 and addr in (GICD+0x110, GICD+0x114, GICD+0x118):
            stored[addr] = stored.get(addr, 0) | value
        elif addr == 0xFCFEC414 and width == 1 and kind == "write" and value == 1:
            counter, running = 0, True
        elif addr == 0xFCFEC404 and width == 4 and kind == "read" and running:
            value, counter = counter, counter + 4096  # Virtual elapsed counts per poll, not calibrated time.
        elif board_full and addr == GICD+0xF00 and width == 4 and kind == "write" and value == 0x10000:
            software_irq_pending = True  # Original code targets CPU0 with software interrupt 0.
        elif board_full and addr == GICD+0x300 and width == 4 and kind == "read":
            value = int(active_irq == 0)
        elif board_full and (width == 1 and (0x400 <= addr-GICD <= 0x64A or 0x800 <= addr-GICD <= 0xA4A) or
                             addr == GICD+0x448 and width == 4):
            if kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
        elif board_full and 0x100 <= addr-GICD <= 0x178 and addr % 4 == 0 and width == 4 and kind == "write":
            stored[addr] = stored.get(addr, 0) | value
        elif board_full and 0x180 <= addr-GICD <= 0x1F8 and addr % 4 == 0 and width == 4 and kind == "write":
            stored[addr-0x80] = stored.get(addr-0x80, 0) & ~value
        elif board_full and 0x280 <= addr-GICD <= 0x2F8 and addr % 4 == 0 and width == 4 and kind == "write":
            stored[addr-0x80] = stored.get(addr-0x80, 0) & ~value  # GICD_ICPENDR
        elif board_full and addr == MTU2+0x384 and width == 1 and kind == "write":
            stored[addr] = value
        elif board_full and addr in (0xFCFEF800, 0xFCFEF802, 0xFCFEF804) and width == 2:
            if kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
        elif board_full and (addr, width) == (0x3FFFF000, 4) and kind == "read":
            value = 0  # No L2 cache ID exposed in the flat mapping fixture.
        elif board_full and (addr, width) in ((0x3FEFA00C, 4), (0x3FFFFF80, 4),
                                              (0xFCFF1802, 1), (0xFCFF1804, 2), (0xFCFF1806, 2)):
            if kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
        elif board_full and addr in (0xE800C800, 0xE800C804) and width == 1:
            if kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
        elif board_full and kind == "write" and (addr, width) in ((0xFCFEC000, 4), (0xFCFEC014, 1),
                                                                (0xFCFEC018, 1), (0xFCFEC020, 1)):
            stored[addr] = value
        elif adc_sample is not None and addr == ADC_STATUS and width == 2:
            if kind == "write":
                # For later conversions, present a completed sample on the next poll after ADST.
                stored[addr] = (value & ~0x2000 | 0x8000) if board_full and value & 0x2000 else value
            else:
                # The original ADC setup arms channel 2; the physical periodic trigger is outside this model.
                if (board_full and pc() == 0x201184E4 and
                        cpu.mem_read(0x20380B1B, 1)[0] == 2):
                    stored[addr] |= 0x8000
                value = stored[addr]
        elif adc_sample is not None and addr in (ADC_STATUS-0x54, ADC_STATUS-0x52) and width == 2 and kind == "read":
            require(stored.get(ADC_STATUS, 0) & 0x8000, "ADC data read before completion")
            value = adc_sample << 6
        elif board_full and width == 2 and any(addr-base in (0, 2, 8, 0x10, 0x12, 0x30, 0x32, 0x36, 0x38,
                                                           0x3A, 0x3C, 0x40, 0x42, 0x46, 0x48, 0x4A, 0x102)
                                               for base in (0xE8010000, 0xE8207000)):
            if kind == "write":
                stored[addr] = value
            else:
                value = stored.get(addr, 0)
        elif cw_enabled and addr == 0xE800800C and width == 1 and kind == "write":
            stored[addr] = value  # SCIF2 transmit FIFO; no peer is attached in this replay.
        elif (startup_input and (addr & ~0x7FF) in (0xE8008000, 0xE8009000) and
              (addr & 0x7FF, width) in ((0, 2), (4, 1), (8, 2), (0x10, 2), (0x18, 2), (0x1C, 2),
                                        (0x20, 2), (0x24, 2), (0x28, 2))):
            if kind == "read":
                value = stored.get(addr, 0x60 if addr & 0x7FF == 0x10 else 0)
            else:
                stored[addr] = value
        elif scif_wait is not None:
            offset = addr-SCIF3
            irq_offset = addr-GICD
            psr_port = addr in (GPIO+0x114, GPIO+0x11C) or board_full and group == 1 and port % 4 == 0 and port <= 0x2C
            mtu_halfword = addr in (MTU2+0x306, MTU2+0x30A, MTU2+0x228) or board_full and addr == MTU2+0x224
            mtu_status = addr in (MTU2+0x305, MTU2+0x22D)
            if (SCIF_REG_WIDTHS.get(offset) == width or
                    addr == GICD+0x194 and kind == "write" and width == 4 and irq_test or
                    rx_test and ((offset in (0x1C, 0x24) and width == 2) or
                                 (offset == 0x14 and width == 1 and kind == "read")) or
                    addr == 0xFCFE101C and width == 4 or mtu_halfword and width == 2 or mtu_status and width == 1 or
                    width == 4 and kind == "write" and
                    (psr_port or addr in (0xE82005C0, 0xE82005C4, 0xE82005EC, 0xE82005F0, 0xE82005F4,
                                          GICD+0x104, GICD+0x11C)) or
                    kind == "write" and width == 1 and irq_offset//0x400 in (1, 2) and
                    irq_offset%0x400 in SCIF_START_IRQS):
                if kind == "write":
                    if psr_port:
                        latch, mask = addr-0x100, value >> 16
                        stored[latch] = (stored.get(latch, 0) & ~mask) | (value & mask)
                    elif addr == GICD+0x194:
                        stored[addr-0x80] = stored.get(addr-0x80, 0) & ~value
                    elif addr in (GICD+0x100, GICD+0x104, GICD+0x110, GICD+0x11C):
                        stored[addr] = stored.get(addr, 0) | value
                    else:
                        stored[addr] = value
                else:
                    value = stored.get(addr, 0)
                    if offset == 0x1C:
                        value = len(rx_fifo)
                    elif offset == 0x14:
                        require(rx_fifo, "unexpected read from empty test RX FIFO")
                        value = rx_fifo.pop(0)
                    if addr == MTU2+0x305 and pc() == 0x20367B48:
                        timer_polls += 1
                        if scif_wait != "no_compare" and timer_polls >= 3:
                            stored[addr] = value = value | 2  # Supply the first compare flag, not elapsed cycles.
            else:
                raise ValueError(f"unmodeled serial-stage {kind} {addr:#x} from {pc():#x} ({width} bytes)")
        else:
            raise ValueError(f"unmodeled board {kind} {addr:#x} from {pc():#x} ({width} bytes)")
        board_trace.append([kind, hex(pc()), hex(addr), width, value])
        return value

    def missing(_cpu, access, addr, width, _value, _):
        faults.append([access, hex(pc()), hex(addr), width])
        return False

    def wake_boundary(_cpu, addr, _size, _data):
        if not wake_path or wake_path[-1] != hex(addr):
            wake_path.append(hex(addr))
        if addr == wake_stop and (active_irq is not None or not riic_steps):
            cpu.emu_stop()

    def serial_boundary(_cpu, addr, _size, _data):
        if addr in (0x20121DF4, 0x2007BE78, 0x2007BEF8, 0x2007BF08, 0x2007C318, 0x2007B858,
                    0x200788E0, 0x2007814C, 0x20078520,
                    0x2007C31C, 0x20098394):
            if not board_checkpoints or board_checkpoints[-1] != hex(addr):
                board_checkpoints.append(hex(addr))
        elif addr != 0x20078A74:
            scif_boundaries.append(hex(addr))
        if addr in (0x2007C1AC, 0x2007C27C):
            boot_modes.append([hex(addr), cpu.reg_read(arm.UC_ARM_REG_R8)])
        if addr == 0x200788E0:
            r6 = cpu.reg_read(arm.UC_ARM_REG_R6)
            power_checks.append([cpu.mem_read(0x20380736, 1)[0], hex(r6), cpu.mem_read(r6, 1)[0]])
        if (board_full and addr in (0x201254B0, 0x20078A74, 0x2007D0CC, 0x2007814C, 0x20078520) and addr != release_boundary or
                addr == 0x201208BC and scif_wait == "no_compare" and timer_polls == 4 or
                addr == 0x20121D54 and (scif_wait == "timeout" or
                                        irq_test and scif_boundaries.count(hex(addr)) in (1, 4)) or
                addr == 0x20121D60 and scif_wait == "rx_frame"):
            cpu.emu_stop()

    def deliver_irq(irq_id, resume, *, stop_at_return=False):
        nonlocal active_irq
        cpsr = cpu.reg_read(arm.UC_ARM_REG_CPSR)
        scheduling = irq_id in (0, 134)
        require(pc() == resume and not cpsr & 0xA0 and
                stored.get(GICD+0x100+4*(irq_id//32), 0) & 1 << (irq_id % 32),
                f"guest IRQ {irq_id} is not armed at {pc():#x} ({cpsr=:#x})")
        active_irq = irq_id
        # Set IRQ entry state; the original vector handles dispatch and return.
        cpu.reg_write(arm.UC_ARM_REG_CPSR, (cpsr & ~0x3F) | 0x92)
        cpu.reg_write(arm.UC_ARM_REG_SPSR, cpsr)
        cpu.reg_write(arm.UC_ARM_REG_LR, resume+4)
        if scheduling:
            cpu.emu_start(BASE+0x18, STOP, count=1_000_000)
        elif stop_at_return or irq_id in (STARTUP_DMA_IRQ, BOARD_TIMER_IRQ, BOARD_RSPI_IRQ):
            # Execute the original RFE without running past it into the interrupted block.
            irq_return = 0x20005284
            end_irq = cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: c.emu_stop(), begin=irq_return, end=irq_return)
            try:
                cpu.emu_start(BASE+0x18, STOP, count=20_000)
                require(pc() == irq_return, f"startup IRQ stopped at {pc():#x} before the original exception return")
            finally:
                cpu.hook_del(end_irq)
            cpu.emu_start(irq_return, STOP, count=1)
        else:
            # The GIC path has a bounded handler; stop at the interrupted PC with guest state restored.
            cpu.emu_start(BASE+0x18, resume, count=20_000)
        active_irq = None
        require(scheduling or pc() == resume and cpu.reg_read(arm.UC_ARM_REG_CPSR) == cpsr,
                f"IRQ {irq_id} did not return to {resume:#x} mode {cpsr:#x}: {pc():#x}, "
                f"mode {cpu.reg_read(arm.UC_ARM_REG_CPSR):#x}")

    def irq_state():
        return {"pc": hex(pc()), "scif_scr": stored[SCIF3+8], "busy": cpu.mem_read(0x2049953C, 1)[0]}

    def riic_descriptor():
        data = cpu.mem_read(RIIC0_DESCRIPTOR, 82)
        return {"descriptor": hex(RIIC0_DESCRIPTOR), "target_field": hex(unpack("<I", data[4:8])[0]),
                "pending": data[0], "bytes": data[10:10+data[8]].hex()}

    def finish_riic_transfer():
        nonlocal riic_return, followup_read, eeprom_result, eeprom_bits, eeprom_active, board_reply_ready
        nonlocal audio_stage, frame_levels, first_riic_request
        # Hold the CPU at its real completion poll and quiesce the bus after each guest interrupt.
        icier, icsr2 = RIIC0+0x1C, RIIC0+0x24
        request = riic_descriptor()
        require(cpu.reg_read(arm.UC_ARM_REG_R4) == RIIC0_DESCRIPTOR and request["pending"] == 1 and
                request["bytes"] == "8000", f"unexpected first RIIC0 descriptor: {request}")
        # START, four TX-ready events, TX end, then (positive control only) observed STOP.
        events = ((193, 4, 4, 2), (191, 0x80, 0x80, 3), (191, 0x80, 0x80, 5),
                  (191, 0x80, 0x80, 5), (191, 0x80, 0x80, 5), (189, 0x40, 0x40, 6), (192, 8, 8, 0))
        for irq, status, enable, next_state in (events if riic0_finish == "stop" else events[:-1]):
            handler = unpack("<I", cpu.mem_read(0x204BA014+4*irq, 4))[0]
            require(stored[icier] & enable and handler == RIIC0_HANDLERS[irq],
                    f"RIIC0 event {irq} was not armed by guest: {stored[icier]=:#x}, {handler=:#x}")
            stored[icsr2] = status
            deliver_irq(irq, RIIC0_WAIT_INSN)
            state = cpu.mem_read(RIIC0_DESCRIPTOR, 1)[0]
            require(state == next_state, f"unexpected RIIC0 IRQ {irq} state: {state}")
            riic_steps.append({"irq": irq, "handler": hex(handler), "status_input": status, "pending": state,
                               "bytes_sent": bytes(riic_sent).hex()})
        require(bytes(riic_sent) == b"\xa6\xfd\x80\x80\0", f"unexpected RIIC0 output: {riic_sent}")
        require(stored[RIIC0_ICCR2] == 8, "guest did not request a STOP condition")
        first_riic_request = riic_descriptor()
        if riic0_finish == "stop":
            return_pc, = unpack("<I", cpu.mem_read(cpu.reg_read(arm.UC_ARM_REG_SP)+28, 4))
            require(return_pc == 0x2005E5C0, f"unexpected RIIC0 caller: {return_pc:#x}")
            cpu.emu_start(RIIC0_WAIT_INSN, return_pc, count=1024)
            require(pc() == return_pc and cpu.reg_read(arm.UC_ARM_REG_R0) == 0, "guest did not complete RIIC0 return")
            riic_return = return_pc
            hook = cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: c.emu_stop(),
                                begin=GPIO_I2C_READ, end=GPIO_I2C_READ)
            cpu.emu_start(return_pc, STOP, count=20_000)
            cpu.hook_del(hook)
            require(pc() == GPIO_I2C_READ, f"did not reach the GPIO I2C reader: {pc():#x}")
            address, buffer, size = (cpu.reg_read(reg) for reg in
                                     (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))
            require((address, size) == (0x3FE40, 16), "unexpected GPIO I2C read request")
            followup_read = {"entry": hex(pc()), "address_field": hex(address), "size": size, "buffer": hex(buffer)}
            if eeprom is not None:
                eeprom_active = True
                eeprom_bits = iter((byte >> bit) & 1 for byte in eeprom for bit in range(7, -1, -1))
                def advance(start, target, limit=2_000_000, *, alternate=None, boundaries=(), target_filter=None):
                    stops_at = [addr for addr in (target, alternate, *boundaries) if addr is not None]

                    def stop(c, addr, *_):
                        if addr != target or target_filter is None or target_filter():
                            c.emu_stop()

                    stops = [cpu.hook_add(uc.UC_HOOK_CODE, stop, begin=addr, end=addr)
                             for addr in stops_at]
                    try:
                        cpu.emu_start(start, STOP, count=limit)
                        require(pc() in stops_at, f"startup stopped at {pc():#x} instead of {target:#x}")
                    finally:
                        for stop in stops:
                            cpu.hook_del(stop)

                def read_record(address, length, payload):
                    nonlocal eeprom_active, eeprom_bits
                    args = tuple(cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
                                                           arm.UC_ARM_REG_R2, arm.UC_ARM_REG_LR))
                    a, dest, n, ret = args
                    require((a, n, ret) == (address, length, 0x2005E528), f"unexpected EEPROM request: {args}")
                    require(len(payload) == n, "wrong record fixture length")
                    tx_bytes = []
                    tx = cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: tx_bytes.append(c.reg_read(arm.UC_ARM_REG_R0)),
                                      begin=0x2005D788, end=0x2005D788)
                    eeprom_bits = iter((b >> bit) & 1 for b in payload for bit in range(7, -1, -1))
                    eeprom_active, before = True, eeprom_samples
                    try:
                        advance(GPIO_I2C_READ, ret, 250_000)
                    finally:
                        eeprom_active = False
                        cpu.hook_del(tx)
                    b0 = 0xA0 | ((a >> 15) & 6)
                    require(tx_bytes == [b0, (a >> 8) & 255, a & 255, b0+1] and
                            bytes(cpu.mem_read(dest, n)) == payload and eeprom_samples-before == n*8,
                            f"original EEPROM read differed at {a:#x}")
                    return dict(logical_address=hex(a), chip_select=(b0 >> 2) & 3, i2c_address=hex(b0 >> 1),
                                chip_offset=hex(a & 0x1FFFF), wire=bytes(tx_bytes).hex(), bytes=n,
                                buffer=hex(dest), sha256=sha256(payload).hexdigest())

                def receive_riic(payload, *, address, buffer, exact_return=False):
                    nonlocal riic_read_trace
                    addr, dest, size, sp = (cpu.reg_read(r) for r in (arm.UC_ARM_REG_R7, arm.UC_ARM_REG_R8,
                                                                    arm.UC_ARM_REG_R6, arm.UC_ARM_REG_SP))
                    ret, = unpack("<I", cpu.mem_read(sp+20, 4))
                    require((pc(), addr, dest, size, ret) == (0x2005BCD4, address, buffer, len(payload), 0x2005E7E8),
                            f"unexpected RIIC0 descriptor/caller: {addr:#x} {dest:#x} {size} {ret:#x}")
                    initial = bytes(cpu.mem_read(dest, size))
                    riic_read_trace, steps = [], []
                    # START, offset, repeated START, dummy read, payload, STOP.
                    events = ((193, 4, 2, 2), (191, 0x80, 2, 3), (191, 0x80, 2, 3), (189, 0x40, 2, 4),
                              (193, 4, 4, 4), (190, 0x20, 4, 5), *((190, 0x20, 4, 5),)*(size-1),
                              (190, 0x20, 4, 6), (192, 8, 8, 0))
                    received = 0
                    dummy = True
                    try:
                        advance(pc(), RIIC0_READ_WAIT)
                        for irq, flag, command, pending in events:
                            handler, = unpack("<I", cpu.mem_read(0x204BA014+4*irq, 4))
                            enable = stored[icier]
                            require(enable & flag and stored[RIIC0_ICCR2] == command and
                                    handler == (RIIC0_READ_HANDLER if irq == 190 else RIIC0_HANDLERS[irq]),
                                    f"unexpected RIIC0 event {irq}: {enable:#x}, {handler:#x}")
                            stored[icsr2] = flag
                            if irq == 190:
                                riic_read_input.append(0xC3 if dummy else payload[received])
                                received += not dummy
                                dummy = False
                            deliver_irq(irq, RIIC0_READ_WAIT, stop_at_return=exact_return or size > 1)
                            observed = bytes(cpu.mem_read(dest, size))
                            require(cpu.mem_read(RIIC0_DESCRIPTOR, 1)[0] == pending and not riic_read_input and
                                    observed == payload[:received]+initial[received:],
                                    f"RIIC0 IRQ {irq} did not advance correctly: pending {pending}, buffer {observed.hex()}")
                            steps.append(dict(irq=irq, handler=hex(handler), enable=enable, control=command,
                                              pending=pending, **({"buffer_byte": observed[0]} if size == 1 else
                                                                 {"received_bytes": received})))
                        trace = riic_read_trace
                        wire = bytes(value for kind, _, reg, value in trace if kind == "write" and reg == hex(RIIC0+0x3C))
                        b0 = 0xA0 | ((addr >> 15) & 6)
                        require(wire == bytes((b0, (addr >> 8) & 255, addr & 255, b0+1)), "stock RIIC0 address/offset differed")
                        advance(pc(), ret)
                        require(cpu.reg_read(arm.UC_ARM_REG_R0) == 0, "stock RIIC0 caller did not get success")
                    finally:
                        riic_read_trace = None
                    return dict(logical_address=hex(addr), i2c_address=hex(wire[0] >> 1), chip_offset=hex(addr & 0x1FFFF),
                                wire=wire.hex(), buffer=hex(dest), return_pc=hex(ret), steps=steps, mmio=trace)

                def read_riic_record(sample):
                    result = receive_riic(bytes((sample,)), address=0x3FD9F, buffer=0x2038002C)
                    advance(pc(), 0x2007B4B8)
                    normalised = cpu.mem_read(0x2038002C, 1)[0]
                    require(normalised == (sample if sample <= 1 else 0), "stock consumer handled RIIC0 byte differently")
                    advance(pc(), GPIO_I2C_READ)
                    # The stock address translator maps the settings header 0x3FCE0 to wire offset 0x3FE60.
                    next_record = read_record(0x3FE60, 16, b"\xff"*16)
                    advance(pc(), 0x2007B4BC)
                    defaults = bytes(cpu.mem_read(0x202E279C, 6))
                    require(bytes(cpu.mem_read(0x20380752, 6)) == defaults, "missing stock default record")
                    defaults_return = pc()
                    scan_hash, read_bytes = sha256(), 0
                    # Synthetic receive settings, located by tracing stock GPIO reads into the VFO records.
                    vfo_records = {0x3D3C0: (0x0C, 7_030_000), 0x3D3E0: (0x11, 7_031_000),
                                   0x1D400: (0x15, 7_030_000), 0x1D420: (0x1A, 7_031_000)}
                    vfo_inputs = []
                    for count in range(725):
                        advance(pc(), GPIO_I2C_READ, alternate=0x2005BCD4)
                        if pc() != GPIO_I2C_READ:
                            break
                        a, n = (cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R2))
                        require(0 < n <= 64 and (a & 63)+n <= 64, f"unexpected startup read: {a:#x}, {n}")
                        payload = b"\xff"*n
                        if current_format and a in vfo_records:
                            offset, frequency = vfo_records[a]
                            encoded = pack("<IB", frequency, 0x20)  # The stock CW mode code.
                            require(offset+len(encoded) <= n, "invalid VFO record length")
                            payload = payload[:offset]+encoded+payload[offset+len(encoded):]
                            if cw_startup and a == 0x3D3C0:
                                # Stock VFO A bit 0 marks the channel unavailable when set.
                                payload = payload[:offset-1]+b"\0"+payload[offset:]
                            vfo_inputs.append(dict(address=hex(a), offset=offset, frequency_hz=frequency,
                                                   mode="CW", payload_sha256=sha256(payload).hexdigest()))
                        if (startup_panel_record or startup_home_probe) and a == 0x1BBC0:
                            require(n == 32 and cpu.reg_read(arm.UC_ARM_REG_R1) == 0x203E84BF,
                                    "unexpected storage record selecting the active stock slot")
                            payload = payload[:1]+b"\xf7"+payload[2:]  # Leave unrelated bits at their baseline fixture values.
                        if cw_startup and a == 0x3BBC0:
                            require(n == 32 and cpu.reg_read(arm.UC_ARM_REG_R1) == 0x203E84FF,
                                    "unexpected saved MENU tab record")
                            payload = b"\0"+payload[1:]  # Start on the stock first MENU page.
                        if startup_home_probe and a == 0x3AAC0:
                            require(n == 32 and cpu.reg_read(arm.UC_ARM_REG_R1) == 0x203E632F,
                                    "unexpected read for the previously observed stock settings comparison")
                            payload = b"\x01"+b"\xff"*18+b"\x02"+payload[20:]
                        if no_power_on_check and a == 0x1CB60:
                            require(n == 32 and cpu.reg_read(arm.UC_ARM_REG_R1) == 0x203EAE29,
                                    "unexpected read for the stock Power ON Check setting")
                            payload = payload[:0x13]+b"\0"+payload[0x14:]
                            if startup_input in ("close-idle", "close-menu", "close-cw"):
                                # EEPROM Screen Saver settings: default 5 min on battery, 60 min on DC.
                                payload = payload[:14]+bytes((3, 6))+payload[16:]
                        if cw_startup and a == 0x3D440:
                            require(n == 12 and cpu.reg_read(arm.UC_ARM_REG_R1) == 0x203EBC22,
                                    "unexpected VFO selector storage record")
                            payload = payload[:10]+b"\0"+payload[11:]  # Weather selection off.
                        if cw_rx_ready and a == 0x1CCC0:
                            require(n == 32 and cpu.reg_read(arm.UC_ARM_REG_R1) == 0x203EB109,
                                    "unexpected stock RF gain/squelch record")
                            payload = payload[:18]+bytes((rx_squelch,))+payload[19:]
                        if a in startup_settings:
                            payload = bytes(startup_settings.get(a+i, value) for i, value in enumerate(payload))
                        read_record(a, n, payload)
                        scan_hash.update(pack("<IB", a, n))
                        read_bytes += n
                    next_addr, next_dest, next_size = (cpu.reg_read(r) for r in
                                                       (arm.UC_ARM_REG_R7, arm.UC_ARM_REG_R8, arm.UC_ARM_REG_R6))
                    require((count, read_bytes, pc(), next_addr, next_dest, next_size) ==
                            (724, 23267, 0x2005BCD4, 0x3FE40, 0x2049B850, 16), "stock startup scan differed")
                    # Preserve the order of fields in the existing evidence artifact.
                    require(not current_format or len(vfo_inputs) == len(vfo_records), "missing synthetic VFO EEPROM reads")
                    return dict(**{k: result[k] for k in ("logical_address", "i2c_address", "chip_offset", "wire", "buffer")},
                                sample=sample, value_after_consumer=normalised,
                                **{k: result[k] for k in ("return_pc", "steps", "mmio")}, next_record=next_record, defaults=defaults.hex(),
                                defaults_return=hex(defaults_return), scan=dict(reads=count, bytes=read_bytes,
                                    address_size_sha256=scan_hash.hexdigest()), next_hardware_read=dict(
                                    address=hex(next_addr), buffer=hex(next_dest), size=next_size), stop_pc=hex(pc()),
                                **({"synthetic_vfo_reads": vfo_inputs} if current_format else {}))

                def follow_current_format(marker):
                    def physical(logical):
                        return ((logical & 64) << 11) + ((logical >> 7) << 6) + (logical & 63)

                    clone_marker, = unpack("<I", cpu.mem_read(0x202E2798, 4))
                    known = {physical(0x3FCC0): marker, physical(0x355A1): b"\x06",
                             physical(0x3D430): bytes(cpu.mem_read(clone_marker, 16))}
                    for logical in (0x3FB43, 0x3FB44, 0x3FB45, 0x3FB46):
                        known[physical(logical)] = b"\0"
                    checks, records = [], []
                    def read_result(c, instruction, *_):
                        checks.append([hex(instruction), c.reg_read(arm.UC_ARM_REG_R0)])

                    # Capture the verdicts at the original caller. Stop before persistent writes.
                    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, read_result, begin=a, end=a)
                             for a in (0x2007B554, 0x2007B564, 0x2007B570, 0x2007B57C, 0x2007B58C)]
                    pwm = 0x2011B338
                    try:
                        for _ in range(16):
                            advance(pc(), pwm, boundaries=(GPIO_I2C_READ, 0x2005BCD4, 0x2005E554, 0x201254B0, UI_ENTRY))
                            if pc() != GPIO_I2C_READ:
                                break
                            address, length = (cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R2))
                            data = known.get(address, b"\xff"*length)
                            records.append(read_record(address, length, data))
                    finally:
                        for hook in hooks:
                            cpu.hook_del(hook)
                    require(pc() == pwm and len(records) == 12 and checks == [[hex(a), 0] for a in
                            (0x2007B554, 0x2007B564, 0x2007B570, 0x2007B57C, 0x2007B58C)],
                            f"unexpected current-format startup: {pc():#x}, {len(records)}, {checks}")

                    pwm_base = 0xFCFF5000
                    # RZ/A1H hardware manual §52.3. Only the observed initialization is modeled.
                    regs = {0x06: (1, 0), 0xE0: (1, 0xC0), 0xE4: (1, 0),
                            0xE6: (2, 0xFFFF), 0xEE: (2, 0xEC00)}
                    pwm_trace = []

                    def pwm_access(offset, width, data=None):
                        require(offset in regs and width == regs[offset][0],
                                f"unexpected PWM access {pwm_base+offset:#x}/{width} from {pc():#x}")
                        reading = data is None
                        if reading:
                            data = regs[offset][1]
                        else:
                            regs[offset] = width, data
                        pwm_trace.append(["read" if reading else "write", hex(pc()), hex(pwm_base+offset), width, data])
                        return data

                    cpu.mmio_map(pwm_base, 0x1000, lambda _c, o, w, _: pwm_access(o, w), None,
                                 lambda _c, o, w, v, _: pwm_access(o, w, v), None)
                    require(startup_flash is not None and len(startup_flash) == RESOURCE_TAG-GRAPHICS_FLASH,
                            "expected original pre-tag Flash slice")
                    if not startup_from_nor:
                        cpu.mem_map(GRAPHICS_FLASH, len(startup_flash), uc.UC_PROT_READ)
                        cpu.mem_write(GRAPHICS_FLASH, startup_flash)
                    flash_reads = []
                    def flash_read(c, _kind, addr, width, _value, _data):
                        flash_reads.append([hex(pc()), hex(addr), c.mem_read(addr, width).hex()])
                    notice = 0x18852000+slot_adjust
                    hook = cpu.hook_add(uc.UC_HOOK_MEM_READ, flash_read, begin=notice, end=notice+3)
                    stops = (GPIO_I2C_READ, 0x2005BCD4, 0x2005E554, 0x201254B0, UI_ENTRY, 0x2007D0CC)
                    try:
                        advance(pc(), 0x2007B704, 8_000_000, boundaries=stops)
                    finally:
                        cpu.hook_del(hook)
                    require(pc() == 0x2007B704 and pwm_trace == [[kind, hex(insn), hex(pwm_base+offset), width, data]
                            for kind, insn, offset, width, data in (
                                ("write", 0x2011B338, 0xE4, 1, 0), ("write", 0x2011B33C, 0xE0, 1, 0),
                                ("write", 0x2011B344, 0xE6, 2, 511), ("write", 0x2011B348, 0xEE, 2, 65535),
                                ("write", 0x2011B350, 6, 1, 247), ("read", 0x20367B04, 0xE0, 1, 0),
                                ("write", 0x20367B10, 0xE0, 1, 8))] and
                            flash_reads == [["0x2006c2b4", hex(notice), startup_flash[0x262000:0x262004].hex()]],
                            f"unexpected current-format handoff at {pc():#x}: {pwm_trace}, {flash_reads}")
                    owner_address, request = 0x20381E90, 0x20380C8C
                    startup, = unpack("<I", cpu.mem_read(owner_address, 4))
                    advance(pc(), 0x2007B8B8, boundaries=stops)
                    require(pc() == 0x2007B8B8, "normal settings routine did not return to caller")
                    outer = []
                    for address, size in ((0x3FD87, 10), (0x3FD91, 11)):
                        advance(pc(), GPIO_I2C_READ, boundaries=stops[1:])
                        require(pc() == GPIO_I2C_READ, f"missing outer startup read at {address:#x}")
                        outer.append(read_record(address, size, b"\xff"*size))
                    advance(pc(), UI_ENTRY, boundaries=stops[:-2])
                    worker, = unpack("<I", cpu.mem_read(owner_address, 4))
                    require(pc() == UI_ENTRY and worker not in (0, startup) and
                            cpu.mem_read(owner_address, 4) == cpu.mem_read(UI_HANDLE, 4) and
                            cpu.mem_read(request, 4) == pack("<I", 2),
                            "normal settings path did not hand off to the original UI task")
                    ui = dict(startup_task=hex(startup), worker_task=hex(worker), worker_entry=hex(UI_ENTRY), pending=2,
                              **follow_ui_init(worker))
                    ui["display"] = follow_display(worker)
                    return dict(boot_path="current-format", legacy_conversion_requested=False,
                                validation=checks, records=records, no_persistent_write=True,
                                pwm=pwm_trace, flash_reads=flash_reads, caller="0x2007b8b8", outer_reads=outer,
                                ui=ui, stop_pc=hex(pc()))

                def read_format_record(matching):
                    table = 0x202E2050
                    reference, = unpack("<I", cpu.mem_read(table + (5*28 if current_format else 0), 4))
                    payload = bytes(cpu.mem_read(reference, 16)) if matching else b"\xff"*16
                    result = receive_riic(payload, address=0x3FE40, buffer=0x2049B850)
                    compared = []
                    def comparison(c, addr, *_):
                        if addr == 0x20068E44:
                            compared[-1]["equal"] = c.reg_read(arm.UC_ARM_REG_R0) == 0
                        else:
                            compared.append(dict(reference=hex(c.reg_read(arm.UC_ARM_REG_R1)),
                                                 size=c.reg_read(arm.UC_ARM_REG_R2)))
                    compare_hooks = [cpu.hook_add(uc.UC_HOOK_CODE, comparison, begin=a, end=a)
                                     for a in (0x20068E40, 0x20068E44)]
                    try:
                        advance(pc(), 0x20068E84 if matching and not current_format else 0x2007B4F4)
                    finally:
                        for h in compare_hooks:
                            cpu.hook_del(h)
                    require([c["equal"] for c in compared] == ([True] if matching and not current_format else [False]*5) and
                            all(c["size"] == 16 for c in compared), "unexpected comparison of the stock format record")
                    if current_format:
                        require(cpu.reg_read(arm.UC_ARM_REG_R0) == 0 and payload == b"SX4075 V4.51-J00",
                                "current marker was not routed through the normal startup branch")
                        handoff = follow_current_format(payload)
                    elif matching:
                        callback = cpu.reg_read(arm.UC_ARM_REG_R3)
                        require(callback == 0x200D6028, f"unexpected record reader: {callback:#x}")
                        outputs = [cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)]
                        fields = []
                        fixture = (2, 1, 0) if settings_test else (255, 255, 255)
                        for address, value in zip((0x38059, 0x38078, 0x38077), fixture):
                            advance(pc(), GPIO_I2C_READ)
                            physical = ((address & 64) << 11) + ((address >> 7) << 6) + (address & 63)
                            fields.append(read_record(physical, 1, bytes((value,))))
                        advance(pc(), 0x2007B4F4)
                        outputs = [cpu.mem_read(a, 1)[0] for a in outputs]
                        require(tuple(outputs) == fixture and cpu.reg_read(arm.UC_ARM_REG_R0) == 1,
                                "stock matched format did not deliver all three bytes")
                        handoff = dict(callback=hex(callback), reads=fields, outputs=outputs, verdict=1)
                        if settings_test:
                            handoff["consumer"] = follow_settings_task()
                    else:
                        verdict = cpu.reg_read(arm.UC_ARM_REG_R0)
                        require(verdict == 0, "blank record was treated as an existing layout")
                        advance(pc(), 0x2007B540)
                        branch = pc()
                        fields = []
                        for _ in range(4):
                            advance(pc(), 0x2005E554, boundaries=(GPIO_I2C_READ, 0x2005BCD4, 0x201254B0, UI_ENTRY))
                            if pc() != GPIO_I2C_READ:
                                break
                            a, n = (cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R2))
                            fields.append(read_record(a, n, b"\xff"*n))
                        # Stop before the original initialization calls a persistent write.
                        require((len(fields), pc(), cpu.reg_read(arm.UC_ARM_REG_R0), cpu.reg_read(arm.UC_ARM_REG_R2),
                                 cpu.reg_read(arm.UC_ARM_REG_LR)) == (3, 0x2005E554, 0x3FCC0, 16, 0x2007A250),
                                "blank-record path did not reach the expected first write boundary")
                        handoff = dict(verdict=verdict, branch=hex(branch), reads=fields,
                                       pending_write=dict(address="0x3fcc0", size=16, exercised=False))
                    return dict(**result, supplied_sha256=sha256(payload).hexdigest(),
                                reference_ascii=bytes(cpu.mem_read(reference, 16)).decode("ascii"),
                                matching=matching and not current_format,
                                compared=compared, handoff=handoff, stop_pc=hex(pc()))

                def follow_settings_task():
                    owner = 0x20381E90
                    req = 0x20380C8C
                    def word(addr):
                        return unpack("<I", cpu.mem_read(addr, 4))[0]
                    startup = word(owner)
                    advance(pc(), 0x20090D4C, boundaries=(GPIO_I2C_READ, 0x2005E554))
                    args = [cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1)]
                    require(pc() == 0x20090D4C and args == [1, 0], "settings arguments differed")
                    advance(pc(), UI_ENTRY, boundaries=(GPIO_I2C_READ, 0x2005E554))
                    worker = word(owner)
                    require(pc() == UI_ENTRY and worker == word(UI_HANDLE) and worker not in (0, startup) and
                            word(req) == 2, "stock scheduler did not run the established UI task")
                    evidence = dict(startup_task=hex(startup), worker_task=hex(worker), worker_entry=hex(UI_ENTRY),
                                setter_arguments=args, pending=word(req), **follow_ui_init(worker))
                    if display_test:
                        evidence["display"] = follow_display(worker)
                    return evidence

                def follow_ui_init(worker):
                    def owner():
                        return unpack("<I", cpu.mem_read(0x20381E90, 4))[0]
                    advance(pc(), 0x20199550, boundaries=(0x201254B0, GPIO_I2C_READ, 0x2005E554, 0x2005BCD4))
                    require(pc() == 0x20199550 and owner() == worker and
                            [(kind, value) for kind, _pc, _addr, value in standby_steps] ==
                            [("read", 0x20), ("write", 0), ("read", 0x20), ("read", 0x20), ("read", 0)],
                            "original UI initialization did not wait for the standby acknowledgement")
                    advance(pc(), 0x2012B4D0, boundaries=(0x201254B0, GPIO_I2C_READ, 0x2005E554, 0x2005BCD4))
                    next_register = cpu.reg_read(arm.UC_ARM_REG_R5)
                    require(pc() == 0x2012B4D0 and owner() == worker and next_register == 0xFCFF7A98,
                            "stock UI reached a different peripheral after standby")
                    return dict(standby=standby_steps,
                                next_access=dict(pc=hex(pc()), address=hex(next_register), width=2, kind="read"))

                def follow_display(worker):
                    base = 0xFCFF7400
                    registers, accesses = {}, []
                    # Live CW submits periodic audio frames, unlike the few frames of a boot-only test.
                    trace_limit = 4096 if cw_rx_audio else 1024
                    def display_reg(kind, off, width, value=0):
                        address = 0xFCFF7000 + off
                        require(base <= address <= base+0xFFC and
                                (width == 4 and off % 4 == 0 or (address, width) == (0xFCFF7A98, 2)),
                                f"unexpected VDC50 access {kind} {address:#x}/{width}")
                        require(len(accesses) < trace_limit, f"VDC50 trace limit ({trace_limit}) at {pc():#x}")
                        if kind == "write":
                            if base+0x680 <= address <= base+0x688:
                                registers[address] = registers.get(address, 0) & value  # Status is write-zero to clear.
                            else:
                                registers[address] = value
                        else:
                            value = registers.get(address, 0)
                        accesses.append([kind, hex(pc()), hex(address), width, hex(value)])
                        return value

                    cpu.mmio_map(0xFCFF7000, 0x1000, lambda _c, o, s, _: display_reg("read", o, s), None,
                                 lambda _c, o, s, v, _: display_reg("write", o, s, v), None)
                    advance(pc(), 0x201281F4)
                    require(pc() == 0x201281F4 and cpu.reg_read(arm.UC_ARM_REG_R4) == 0,
                            "stock VDC50 initialization did not report success")
                    advance(pc(), 0x2019AB5C, boundaries=(GPIO_I2C_READ, 0x2005E554, 0x2005BCD4, 0x201254B0))
                    address = cpu.reg_read(arm.UC_ARM_REG_R0)+(cpu.reg_read(arm.UC_ARM_REG_R1) & ~3)
                    require(pc() == 0x2019AB5C and address == 0xE8104004 and
                            unpack("<I", cpu.mem_read(0x20381E90, 4))[0] == worker,
                            "stock renderer did not continue from the LCD controller to the OpenVG processor")
                    vertical, horizontal = (registers.get(base+off, 0) for off in (0x118, 0x11C))
                    height, width = vertical & 0x7FF, horizontal & 0x7FF
                    panel_clock = registers.get(base+0x698, 0)
                    irq_mask, irq_enable = registers.get(base+0x68C, 0), stored.get(GICD+0x108, 0)
                    require((width, height) == (480, 272) and panel_clock == 0x3107 and
                            irq_mask & 0x1000 and irq_enable & (1 << (78-64)),
                            f"stock panel setup differed: {width=} {height=} {panel_clock=:#x} "
                            f"{irq_mask=:#x} {irq_enable=:#x} accesses={len(accesses)}")
                    evidence = dict(width=width, height=height, panel_clock=hex(panel_clock), vline_irq=78,
                                    interrupt_injected=False, vdc50=list(accesses),
                                    next_access=dict(pc=hex(pc()), address=hex(address), width=4, kind="write",
                                                     value=cpu.reg_read(arm.UC_ARM_REG_R2)))
                    if openvg_test or current_format:
                        evidence["openvg"] = follow_openvg(worker, registers, accesses)
                    return evidence

                def follow_openvg(worker, display, display_accesses):
                    nonlocal software_irq_pending
                    base, idle, next_read = 0xE8104000, 0x201254B0, 0x2019AB50
                    owner = 0x20381E90
                    def task():
                        return unpack("<I", cpu.mem_read(owner, 4))[0]

                    # shortcut: complete the first command list without rendering, until the draw path is modeled.
                    events, waits, gpu = [], [], {}
                    clears = BootClears(cpu, slot_adjust=slot_adjust) if surfaces_test or current_format else None
                    clearing = False
                    def device(kind, address, size, value=0):
                        limit = 500000 if cw_rx_audio else 45000 if current_format else 4096 if clears is not None else 512
                        require(size == 4 and len(events) < limit and address in (
                            base, base+4, base+0x0C, base+0x10, base+0x14, base+0x18, base+0x1C, base+0x20, base+0x24,
                            0xE8120040, 0xE8120044, 0xE8120064, 0xE8120068, 0xE8120110),
                            f"unexpected OpenVG {kind} at {address:#x}/{size}")
                        if kind == "read":
                            value = gpu.get(address, 0)
                        elif address == base+0x1C:
                            gpu[base+0x18] = gpu.get(base+0x18, 0) & ~value
                        else:
                            gpu[address] = value
                            if clearing and address == base:
                                clears.word(value)
                        events.append([kind, hex(pc()), hex(address), value])
                        return value

                    for page in (base, 0xE8120000):
                        cpu.mmio_map(page, 0x1000,
                                     lambda _c, o, s, p: device("read", p+o, s), page,
                                     lambda _c, o, s, v, p: device("write", p+o, s, v), page)
                    wait_call, wait_return = 0x2029D27A, 0x2029D27E
                    def record_wait(c, addr, *_):
                        waits.append([hex(addr), hex(task()), c.reg_read(arm.UC_ARM_REG_R0),
                                      c.reg_read(arm.UC_ARM_REG_R1), c.reg_read(arm.UC_ARM_REG_R2)])

                    handlers = []
                    mark = len(irq_trace)
                    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, record_wait, begin=a, end=a)
                             for a in (wait_call, wait_return)]
                    try:
                        advance(pc(), idle)
                        waiting = task()
                        handlers = [unpack("<I", cpu.mem_read(0x204BA014+4*i, 4))[0] for i in range(130, 134)]
                        commands = [e[3] for e in events if e[0] == "write" and e[2] == hex(base)]
                        require(waiting != worker and len(waits) == 1 and waits[0][3:] == [1, 0] and
                                gpu.get(base+0x18) == 0 and gpu.get(base+0x14) == 0x74F and
                                [gpu.get(a) for a in (0xE8120064, 0xE8120068)] == [0x1FF, 0xFB] and
                                handlers == [0x2019B5D4]*4 and stored.get(GICD+0x110, 0) & 0x3C == 0x3C and
                                len(commands) == 32 and commands[:2] == [0xA0000054, 1],
                                "stock OpenVG initialization did not wait for the first submitted list")
                        gpu[base+0x18] = 3  # Modeled completion of this observed command list, with both status bits.
                        deliver_irq(130, idle, stop_at_return=True)
                        require(task() == waiting and software_irq_pending and gpu[base+0x18] == 0 and
                                events[-2:] == [["read", "0x2019ab50", hex(base+0x18), 3],
                                                ["write", "0x2019ab5c", hex(base+0x1C), 3]],
                                "stock driver did not acknowledge OpenVG completion and request scheduling")
                        software_irq_pending = False

                        def stop_next(c, *_):
                            a, b = c.reg_read(arm.UC_ARM_REG_R0), c.reg_read(arm.UC_ARM_REG_R1)
                            if a+(b & ~3) == 0xE8103E80:
                                c.emu_stop()

                        hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, stop_next, begin=next_read, end=next_read))
                        deliver_irq(0, idle)
                        require(pc() == next_read and task() == worker and len(waits) == 2 and
                                waits[0][1] == waits[1][1] == hex(worker) and waits[1][2] == 0,
                                f"stock UI did not return from OpenVG wait: {waits}, {pc():#x}")
                    finally:
                        for hook in hooks:
                            cpu.hook_del(hook)
                    evidence = dict(waiting_task=hex(waiting), worker=hex(task()), handlers=[hex(a) for a in handlers],
                                    waits=waits, completion_status=3, irq=irq_trace[mark:], mmio=list(events),
                                    next_access=dict(pc=hex(pc()), address="0xe8103e80", width=4, kind="read"))
                    if clears is not None:
                        clearing = True
                        gpu_cut, display_cut = len(events), len(display_accesses)
                        surfaces = follow_boot_surfaces(worker, display, clears, gpu, events)
                        surfaces.update(openvg_mmio=events[gpu_cut:], lcd_mmio=display_accesses[display_cut:])
                        evidence["surfaces"] = surfaces
                    return evidence

                def follow_settings_reload(post_lcd_io, idle):
                    nonlocal software_irq_pending
                    bus, comparison, resumed = 0x2005BCD4, 0x20068EC0, 0x2007B518
                    stops = []

                    def mark(c, instruction, *_):
                        stops.append(instruction)
                        if instruction != resumed:
                            c.emu_stop()

                    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, mark, begin=a, end=a)
                             for a in (resumed, bus, GPIO_I2C_READ, 0x2005E554)]
                    try:
                        for line in (154, 134)*8:
                            if pc() != idle:
                                break
                            if line == 154:
                                post_lcd_io[MTU2+0x22C] = 1
                            deliver_irq(line, idle, stop_at_return=True)
                            if pc() == idle and software_irq_pending:
                                software_irq_pending = False
                                deliver_irq(0, idle)
                    finally:
                        for hook in hooks:
                            cpu.hook_del(hook)
                    require(stops == [resumed, bus] and pc() == bus, "stock startup did not begin the settings reload")

                    trace = sha256()
                    by_chip, reads, first, last = {}, 0, [], None
                    while pc() == bus:
                        address, destination, count = (cpu.reg_read(r) for r in (arm.UC_ARM_REG_R7, arm.UC_ARM_REG_R8,
                                                                                arm.UC_ARM_REG_R6))
                        require(reads < 3764 and 0 < count <= 64 and (address & 63)+count <= 64,
                                f"unexpected post-display EEPROM read: {reads}, {address:#x}, {count}")
                        # Use erased-state test data, not a backup or a real radio's settings.
                        trial = receive_riic(b"\xff"*count, address=address, buffer=destination, exact_return=True)
                        chip = trial["i2c_address"]
                        by_chip[chip] = by_chip.get(chip, 0)+count
                        trace.update(pack("<IIB", address, destination, count))
                        last = dict(address=hex(address), dest=hex(destination), bytes=count, wire=trial["wire"])
                        if reads < 2:
                            first.append(last)
                        reads += 1
                        advance(pc(), comparison, 12_000_000, boundaries=(bus, GPIO_I2C_READ, 0x2005E554, idle))
                    require(pc() == comparison and reads == 3764 and cpu.reg_read(arm.UC_ARM_REG_R0) == 0 and
                            by_chip == {"0x50": 65536, "0x52": 65536, "0x51": 54798, "0x53": 54766} and
                            [(r["address"], r["wire"]) for r in first] == [("0x0", "a00000a1"), ("0x20000", "a40000a5")],
                            f"unexpected post-display reload or conversion boundary: {pc():#x}, {reads}, {by_chip}")
                    advance(pc(), 0x2005E554, boundaries=(0x2007B534, bus, GPIO_I2C_READ, idle))
                    pending = tuple(cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_LR))
                    require(pc() == 0x2005E554 and pending == (0x3FCC0, 16, 0x20078068),
                            f"unexpected first write boundary after settings reload: {pc():#x}, {pending}")
                    return dict(startup_resumed=hex(resumed), reads=reads, bytes_by_i2c_address=by_chip, first=first,
                                last=last, address_destination_length_sha256=trace.hexdigest(),
                                fixture="erased data, with earlier boot records supplied separately",
                                comparison_pc=hex(comparison), comparison_r0=0, next_pc=hex(pc()),
                                pending_write=dict(address=hex(pending[0]), bytes=pending[1], caller_return=hex(pending[2]),
                                                   exercised=False))

                def follow_current_panel_startup(idle, worker, clears, display):
                    nonlocal software_irq_pending
                    # Read erased test data; never supply board calibration from a real radio.
                    descriptors = ((0x3FF80, 0x2049B840, 16), (0x5371, 0x203EC2E4, 4),
                                   (0x536D, 0x203EC2E8, 4), (0x5378, 0x203EC2EC, 8),
                                   (0x25340, 0x203EC2F4, 8), (0x530B, 0x2049B838, 4))
                    reads = []
                    safe_stops = (idle, GPIO_I2C_READ, 0x2005E554)
                    for address, dest, size in descriptors:
                        advance(pc(), 0x2005BCD4, boundaries=safe_stops)
                        read = receive_riic(b"\xff"*size, address=address, buffer=dest, exact_return=True)
                        reads.append(dict(address=hex(address), buffer=hex(dest), bytes=size, wire=read["wire"]))
                    advance(pc(), idle, boundaries=(0x2005BCD4, GPIO_I2C_READ, 0x2005E554))
                    require(pc() == idle and not software_irq_pending and panel_dma_writes == [
                                [hex(code), hex(address), 4, value]
                                for code, (address, value) in panel_dma_config.items()],
                            f"unexpected panel DMA2 configuration or idle checkpoint: {pc():#x}, {panel_dma_writes}")
                    frequency_lookup, irq_start = [], len(irq_trace)

                    def lookup(c, instruction, *_):
                        frequency_lookup.append([hex(instruction), c.reg_read(arm.UC_ARM_REG_R0)])

                    def stop(c, *_):
                        c.emu_stop()

                    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, lookup, begin=a, end=a)
                             for a in (0x20062764, 0x20062B00)]
                    hooks += [cpu.hook_add(uc.UC_HOOK_CODE, stop, begin=a, end=a)
                              for a in (GPIO_I2C_READ, 0x2005BCD4, 0x2005E554)]
                    try:
                        for line in (134, 0, 134):
                            require(pc() == idle and software_irq_pending == (line == 0),
                                    f"unexpected pending startup IRQ at {pc():#x}")
                            software_irq_pending = False
                            deliver_irq(line, idle, stop_at_return=True)
                    finally:
                        for hook in hooks:
                            cpu.hook_del(hook)
                    address, dest, size = (cpu.reg_read(r) for r in
                                           (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))
                    require(pc() == GPIO_I2C_READ and len(frequency_lookup) == 2 and
                            frequency_lookup[0] == ["0x20062764", 7_030_000] and
                            frequency_lookup[1][0] == "0x20062b00" and frequency_lookup[1][1] and
                            (address, dest, size) == (0x37C8F, 0x203E2499, 12),
                            f"unexpected VFO lookup or next GPIO read at {pc():#x}: {frequency_lookup}, {address:#x}")
                    vfo_resume = dict(pc=hex(pc()), address=hex(address), buffer=hex(dest), bytes=size)
                    resume_irq = irq_trace[irq_start:]
                    gpio_reads, flash_reads, flash_results = [], [], []

                    def read_optional_flash(c, offset, width, _):
                        require((pc(), offset, width, c.reg_read(arm.UC_ARM_REG_LR)) ==
                                (0x202C9078, 0xFF0, 1, 0x20091064),
                                f"unmodeled optional Flash read at {pc():#x}: {offset:#x}/{width}")
                        flash_reads.append(dict(pc=hex(pc()), address="0x18fffff0", bytes=width, value=0xFF))
                        return 0xFF

                    def forbid_flash_write(_c, offset, width, _value, _):
                        raise ValueError(f"forbidden startup Flash write at {pc():#x}: {offset:#x}/{width}")

                    # No source record is mapped from the DAT. Exercise only the stock absence branch.
                    if nor_snapshot is None:
                        cpu.mmio_map(0x18FFF000, 0x1000, read_optional_flash, None, forbid_flash_write, None)
                    else:
                        def observe_optional_flash(c, _access, addr, width, *_):
                            expected = read_optional_flash(c, addr-0x18FFF000, width, None)
                            require(c.mem_read(addr, width) == bytes((expected,)), "expected erased optional NOR record")

                        cpu.hook_add(uc.UC_HOOK_MEM_READ, observe_optional_flash, begin=0x18FFF000, end=0x18FFFFFF)
                    fifo, command, target = 0x2019AB5C, 0xDA000000, 0x2086BBA0

                    def before_draw():
                        a, b, value = (cpu.reg_read(r) for r in
                                       (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))
                        return a+(b & ~3) == 0xE8104000 and value == command and clears.registers.get(0x10) == target

                    def record_flash_result(c, *_):
                        compare = c.reg_read(arm.UC_ARM_REG_R0)
                        flash_results.append([compare, bytes(c.mem_read(0x20380730, 2)).hex()])

                    write_apis = (0x2005E554, 0x2005BC08)
                    hook = cpu.hook_add(uc.UC_HOOK_CODE, record_flash_result, begin=0x20091064, end=0x20091064)
                    try:
                        for expected in ((0x37C8F, 0x203E2499, 12), (0x3FD82, 0x2049B870, 1)):
                            a, dest, n = (cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
                                                                  arm.UC_ARM_REG_R2))
                            require(pc() == GPIO_I2C_READ and (a, dest, n) == expected,
                                    f"unexpected late GPIO EEPROM read at {pc():#x}: {a:#x}/{dest:#x}/{n}")
                            gpio_reads.append(read_record(a, n, b"\xff"*n))
                            next_pc = GPIO_I2C_READ if a == 0x37C8F else fifo
                            advance(pc(), next_pc, 15_000_000, boundaries=(0x2005BCD4, idle, *write_apis),
                                    target_filter=before_draw if next_pc == fifo else None)
                    finally:
                        cpu.hook_del(hook)
                    scene = bytes(cpu.mem_read(0x204BAB5C, 8)).hex()
                    pending_request, = unpack("<I", cpu.mem_read(0x20380C8C, 4))
                    owner, = unpack("<I", cpu.mem_read(0x20381E90, 4))
                    reg_keys = (0x10, 0x14, 0x18, 0x110, 0x208, 0x80C, 0x810, 0x814, 0x818)
                    registers = {hex(k): hex(clears.registers.get(k, 0)) for k in reg_keys}
                    require(pc() == fifo and cpu.reg_read(arm.UC_ARM_REG_R2) == command and
                            owner == worker and scene == "0104000100000000" and pending_request == 2 and
                            clears.destination_format_from_source and
                            (display[0xFCFF770C], display[0xFCFF7700]) == (0x208EDC00, 0) and
                            len(flash_reads) == 1 and flash_results == [[0xFF-ord("I"), "0000"]] and
                            [clears.registers.get(k) for k in reg_keys] ==
                            [target, 0xFFFFFFC0, 3, 0x80001000, 0xB, 0, 0x400CC, 0x210020, 0],
                            f"unexpected late startup graphics boundary at {pc():#x}: "
                            f"{scene=}, {pending_request=}, {gpio_reads=}, {flash_reads=}, {flash_results=}, {registers=}")
                    return dict(dma2_config=panel_dma_writes, eeprom_fixture="erased (0xff)", eeprom_reads=reads,
                                frequency_lookup=frequency_lookup, resume_irq=resume_irq, next_gpio_read=vfo_resume,
                                late_gpio_reads=gpio_reads, optional_flash=dict(fixture="unavailable (0xff)",
                                    reads=flash_reads, comparison=flash_results[0][0], stock_flags=flash_results[0][1]),
                                stop_pc=hex(pc()), openvg_boundary=dict(address="0xe8104000", command=hex(command),
                                    scene=scene, pending_request=pending_request, worker=hex(worker),
                                    lcd=dict(address=hex(display[0xFCFF770C]), control=hex(display[0xFCFF7700])),
                                    registers=registers,
                                    destination_format_from_source=clears.destination_format_from_source,
                                    executed=False))

                def follow_boot_surfaces(worker, display, clears, gpu, events):
                    nonlocal software_irq_pending, post_lcd_io, rtc_bus, late_panel_dma, late_adc_reads
                    tess = {}
                    launch = []
                    reads, glyphs, matrix = [], [], {}
                    resume_outline = False
                    draw_dialog = False
                    def tess_write(c, offset, size, value, _):
                        require(size == 4 and offset in (0, 0x70), f"unmodeled path write {offset:#x}")
                        tess[offset] = value
                        if offset == 0:
                            addr = tess[0x70]
                            require(value == 7, "unexpected path-program start")
                            if draw_dialog or current_format and launch:
                                words = bytes(c.mem_read(addr, 512*4))
                                length = next((i+1 for i, (w,) in enumerate(iter_unpack("<I", words))
                                               if w == 0x14000001), 0)
                                limit = 6400 if cw_rx_audio else 1600 if startup_input else 400 if startup_home_probe else 320 if current_format else 57
                                require(length, f"unterminated startup path {addr:#x}")
                                require(len(glyphs) < limit, f"startup path trace limit ({limit}) at {addr:#x}")
                                bounds, contours = boot_outline(words[:length*4], matrix)
                                clears.outline = bounds, contours, matrix[0x2078]
                                clears.cover_draw = None
                                glyphs.append(dict(words=length, bounds=bounds, address=hex(addr)))
                                return
                            if len(launch) == 2:
                                # Unicorn resumes on the MMIO write that stopped it.
                                require(resume_outline and addr == 0x2086BC00, "unexpected additional path-program start")
                                return
                            if launch:
                                require(addr == 0x2086BC00, "unexpected first scene path address")
                                words = bytes(c.mem_read(addr, 164*4))
                                bounds, contours = boot_outline(words, matrix)
                                require(bounds == [16, 148, 28, 164], f"unexpected first outline bounds {bounds}")
                                clears.outline = bounds, contours, matrix[0x2078]
                                launch.append(dict(address=hex(addr), words=len(words)//4,
                                                   sha256=sha256(words).hexdigest(), trigger=value,
                                                   calculated_bounds=bounds))
                                c.emu_stop()
                                return
                            require(addr == 0x20868B60, "unexpected boot path-program address")
                            words = bytes(cpu.mem_read(addr, 3017*4))
                            require(words[:8] == pack("<2I", 0x19003E80, 0x60000000) and
                                    words[-4:] == pack("<I", 0x14000001), "unexpected boot path program")
                            launch.append(dict(address=hex(addr), words=len(words)//4,
                                               sha256=sha256(words).hexdigest(), trigger=value))

                    def control_read(_c, offset, size, _):
                        require((offset, size) == (0xE80, 4), f"unexpected OpenVG auxiliary read {offset:#x}")
                        return 0

                    def tess_read(_c, offset, size, _):
                        require((len(launch) == 2 or current_format and glyphs) and size == 4 and
                                offset in (0xFC, 0x98, 0x9C),
                                f"unexpected first outline result read {offset:#x}")
                        x0, y0, x1, y1 = clears.outline[0]
                        value = {0xFC: 0, 0x98: x1 << 16 | y1, 0x9C: x0 << 16 | y0}[offset]
                        reads.append([hex(offset), hex(value)])
                        return value

                    cpu.mmio_map(0xE8103000, 0x1000, control_read, None, None, None)
                    # shortcut: the first path list initializes the accelerator; only the first UI outline is modeled.
                    cpu.mmio_map(0xE8102000, 0x1000, tess_read, None, tess_write, None)
                    frame_bytes = 480*272*2
                    for address in (0x208AE000, 0x208EDC00):
                        # A sentinel makes an actual write distinguishable from pre-zeroed SRAM.
                        cpu.mem_write(address, b"\xef\xbe"*(frame_bytes//2))
                    enable = 0x2012F4C8
                    advance(pc(), enable)
                    layer = 0xFCFF7700
                    addr = display[layer+0xC]
                    stride = (display[layer+0x10] >> 16) & 0x7FFF
                    height, width = ((display[layer+off] >> 16 & 0x7FF)+1 for off in (0x18, 0x1C))
                    require(len(launch) == 1 and not clears.remaining and len(clears.draws) == 21 and
                            [(d["start"], d["width"], d["height"], d["rgb565"], d["changed"])
                             for d in clears.draws[:2]] == [(hex(a), 480, 272, "0x0", True)
                                 for a in (0x208AE000, 0x208EDC00)] and
                            (addr, stride, width, height) == (0x208AE000, 960, 480, 272) and
                            display[layer+4] & 1 and display[layer+0x20] & 3 == 3 and
                            unpack("<I", cpu.mem_read(0x20381E90, 4))[0] == worker,
                            f"unexpected boot RGB565 surfaces: {launch}, {clears.draws[:2]}, {len(clears.draws)}")
                    raw = bytes(cpu.mem_read(addr, frame_bytes))
                    require(not any(raw), "boot LCD drawable buffer was not black after the stock clear")
                    lcd = dict(pc=hex(pc()),
                                address=hex(addr), stride=stride, width=width, height=height, format="RGB565",
                                rgb565_sha256=sha256(raw).hexdigest(), scanout=False)
                    def image_png(rows, width, height):
                        rgba = bytearray()
                        for row in rows:
                            for rgb, in iter_unpack("<H", row):
                                rgba.extend(((rgb >> 11)*255//31, ((rgb >> 5) & 63)*255//63, (rgb & 31)*255//31, 255))
                        return png(width, height, rgba)

                    dispatch = []
                    points = (0x2013D288, 0x2013D4A4)  # Return from font setup; enter scene dispatch.

                    def seen(c, code, *_):
                        dispatch.append([hex(code), c.reg_read(arm.UC_ARM_REG_R0)])

                    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, seen, begin=a, end=a) for a in points]
                    try:
                        if current_format:
                            idle = 0x201254B0
                            advance(enable, idle, 85_000_000, boundaries=(0x2005E554,))
                        else:
                            cpu.emu_start(enable, STOP, count=85_000_000)
                    finally:
                        for hook in hooks:
                            cpu.hook_del(hook)
                    if current_format:
                        page, request = 0x204BAB5C, 0x20380C8C
                        first_request = bytes(cpu.mem_read(request, 4))
                        page_state = bytes(cpu.mem_read(page, 8))
                        first_frame = bytes(cpu.mem_read(addr, frame_bytes))
                        require(pc() == idle and [code for code, _ in dispatch] == ["0x2013d288"] and
                                len(launch) == 1 and not clears.remaining and len(clears.draws) == 21 and
                                not clears.images and not clears.copies and page_state == b"\x01\0\0\x01\0\0\0\0" and
                                first_frame == raw and display[layer+0xC] == addr and display[layer] == 0x111 and
                                first_request == pack("<I", 2) and not software_irq_pending,
                                f"unexpected normal startup first frame at {pc():#x}: {dispatch}, {page_state.hex()}")
                        rgba = b"\0\0\0\xff"*(width*height)
                        rendered = png(width, height, rgba)
                        if scene_preview is not None:
                            scene_preview.append(rendered)

                        # Composition has one more pending GPU completion before the LCD waits for Vsync.
                        mark = len(irq_trace)
                        gpu[0xE8104018] = 3
                        deliver_irq(130, idle, stop_at_return=True)
                        require(software_irq_pending and gpu[0xE8104018] == 0,
                                "normal startup renderer did not finish composition")
                        software_irq_pending = False
                        deliver_irq(0, idle)
                        lcd_address = display[layer+0xC]
                        require(pc() == idle and lcd_address == 0x208EDC00 and display[layer] == 0x111 and
                                bytes(cpu.mem_read(lcd_address, frame_bytes)) == first_frame and
                                bytes(cpu.mem_read(request, 4)) == first_request and not software_irq_pending,
                                "normal startup did not submit the black frame to the LCD")

                        def vline(*, flip):
                            nonlocal software_irq_pending
                            if flip:
                                display[layer] &= ~0x111  # VDC5 hardware manual §35.2.1.
                            display[0xFCFF7A80] = display.get(0xFCFF7A80, 0) | 0x1000
                            deliver_irq(78, idle, stop_at_return=True)
                            require(not flip or software_irq_pending, "Vsync did not make the UI runnable")
                            if software_irq_pending:
                                software_irq_pending = False
                                deliver_irq(0, idle)

                        vline(flip=False)
                        require(bytes(cpu.mem_read(request, 4)) == first_request and display[layer] == 0x111,
                                "display line alone cleared the normal startup request")
                        vline(flip=True)
                        require(pc() == idle and bytes(cpu.mem_read(request, 4)) == bytes(4) and
                                bytes(cpu.mem_read(lcd_address, frame_bytes)) == first_frame,
                                "normal boot did not complete the first display request")
                        post_lcd_io = {MTU2+0x22C: 1}
                        startup_owner = 0x20381E90
                        checkpoints = []
                        timer_setup, dma_setup = 0x200062B8, 0x2008D06C
                        def observe(c, instruction, *_):
                            checkpoints.append([hex(instruction), hex(unpack("<I", c.mem_read(startup_owner, 4))[0])])
                            if instruction in (timer_setup, 0x2005E554):
                                c.emu_stop()
                        hooks = [cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=a, end=a)
                                 for a in (0x2007A720, timer_setup, 0x2005E554)]
                        after_vsync = len(irq_trace)
                        try:
                            deliver_irq(154, idle, stop_at_return=True)
                            require(software_irq_pending and not post_lcd_io[MTU2+0x22C],
                                    "original timer did not make startup runnable after Vsync")
                            software_irq_pending = False
                            deliver_irq(0, idle)
                        finally:
                            for hook in hooks:
                                cpu.hook_del(hook)
                        require(pc() == timer_setup and [a for a, _ in checkpoints] == ["0x2007a720", hex(timer_setup)] and
                                all(task == checkpoints[0][1] != hex(worker) for _, task in checkpoints),
                                f"normal boot did not resume on the expected startup task: {pc():#x}, {checkpoints}")
                        cut = len(mmio)
                        advance(pc(), dma_setup, boundaries=(0x2005E554, GPIO_I2C_READ, 0x2005BCD4, idle))
                        timer_io = [row for row in mmio[cut:] if row[2] in ("0xfcff0381", "0xfcff0386", "0xfcff0280")]
                        next_address = cpu.reg_read(arm.UC_ARM_REG_R0) + 0xAC
                        next_value = cpu.reg_read(arm.UC_ARM_REG_R1)
                        require(pc() == dma_setup and timer_io == [
                                    ["write", "0x200062b8", "0xfcff0381", 1, 4],
                                    ["write", "0x200062c4", "0xfcff0386", 2, 0],
                                    ["read", "0x20367b04", "0xfcff0280", 1, 0xC1],
                                    ["write", "0x20367b10", "0xfcff0280", 1, 0xC3]] and
                                (next_address, next_value) == (0xE82000AC, 0x00626402),
                                f"unexpected phase-counter setup at {pc():#x}: {timer_io}")
                        panel_startup = follow_current_panel_startup(idle, worker, clears, display)
                        color_before = bytes(cpu.mem_read(lcd_address, frame_bytes))
                        mask_target, pitch, draw_count = 0x2086BBA0, -64, len(clears.draws)
                        def mask_rows():
                            return [bytes(cpu.mem_read(mask_target+y*pitch, -pitch)) for y in range(33)]
                        mask_before = mask_rows()
                        advance(pc(), idle, 10_000_000, boundaries=(0x2005E554, 0x2005BC08))
                        require(pc() == idle and len(clears.draws) == draw_count+1 and
                                clears.draws[-1]["alpha8"] == "0x0" and clears.draws[-1]["width"] == 34 and
                                clears.draws[-1]["height"] == 33 and
                                bytes(cpu.mem_read(lcd_address, frame_bytes)) == color_before,
                                f"stock A8 clear did not reach its GPU wait with the LCD unchanged: "
                                f"{pc():#x} {software_irq_pending=} {draw_count=} {clears.draws[draw_count:]} "
                                f"{events[-5:]}")
                        mask_after = mask_rows()
                        alpha_clear = clears.draws[-1]
                        require(any(any(row[:34]) for row in mask_before) and
                                all(not any(after[:34]) and before[34:] == after[34:]
                                    for before, after in zip(mask_before, mask_after)),
                                "stock A8 clear did not preserve all row padding")
                        scene_irq = len(irq_trace)
                        if software_irq_pending:
                            software_irq_pending = False
                            deliver_irq(0, idle)
                            require(pc() == idle and not software_irq_pending, "unexpected work while the GPU was busy")
                        gpu[0xE8104018] = 3
                        deliver_irq(130, idle, stop_at_return=True)
                        require(software_irq_pending and not gpu[0xE8104018], "mask clear did not wake UI")
                        software_irq_pending = False
                        deliver_irq(0, idle)
                        require(pc() == idle and len(glyphs) == 1 and not software_irq_pending and
                                glyphs[0] == dict(words=54, bounds=[150, 175, 184, 208], address="0x2086bc00"),
                                f"unexpected first scene rectangle: {pc():#x} {glyphs}")
                        # Complete the observed batches and stop at the following outline wait.
                        for _ in range(3):
                            gpu[0xE8104018] = 3
                            deliver_irq(130, idle, stop_at_return=True)
                            require(software_irq_pending and not gpu[0xE8104018],
                                    "startup progress GPU batch did not wake UI")
                            software_irq_pending = False
                            deliver_irq(0, idle)
                            require(pc() == idle and not software_irq_pending,
                                    f"startup progress did not reach its next GPU wait: {pc():#x}")
                        require(len(clears.copies) == 1 and len(clears.images) == 3,
                                f"unexpected startup artwork sequence: {clears.copies} {clears.images}")
                        copy = clears.copies[0]
                        source, target, w, h = 0x18BDEFC0+slot_adjust, 0x208697A0, 126, 21
                        mask = b"".join(bytes(cpu.mem_read(source+128*y, w)) for y in range(h))
                        copied = b"".join(bytes(cpu.mem_read(target-128*y, w)) for y in range(h))
                        require(copy["source"] == hex(source) and copy["target"] == hex(target) and
                                (copy["width"], copy["height"]) == (w, h) and any(mask) and mask == copied and
                                copy["sha256"] == sha256(mask).hexdigest() and
                                bytes(cpu.mem_read(lcd_address, frame_bytes)) == color_before,
                                "stock startup artwork copy did not match the decoded Flash mask")
                        mask_png = png(w, h, b"".join(bytes((255, 255, 255, v)) for v in copied))
                        if scene_preview is not None:
                            scene_preview.append(mask_png)
                        startup_frames = []
                        cuts = len(events)-1  # Last verified step is waiting for a submitted outline.
                        params = 0x204BD244
                        tick = 0x2040204A
                        clock = []
                        fade_in = [[p, 0, 0, p] for p in range(0, 101, 20)]
                        middle = [[100, 0, 0, 100], *[[100, p, p, 100] for p in range(0, 101, 20)], [100]*4]
                        fade_out = [[p]*4 for p in (80, 60, 40, 20, 0, 0)]
                        expected_parameters = fade_in + middle + fade_out
                        after_fade = []
                        ui_handoff = []
                        late_io = len(board_trace)
                        sdhi_base = 0xE804E000
                        sdhi_trace, sdhi_late_polls = [], []
                        sdhi_regs = {0x1C: 0, 0x1E: 0, 0x36: 0}
                        # RZ/A1H §§50.2, 50.3.2: no card, no flag edge or completed transfer.
                        sdhi_steps = (
                            ("write", 0x202CADC0, 0x20, 0x031D),  # SD_INFO1_MASK
                            ("write", 0x202CADCC, 0x22, 0x8B7F),  # SD_INFO2_MASK
                            ("write", 0x202CADD8, 0x38, 0xC007),  # SDIO_INFO1_MASK
                            ("write", 0x202CADE0, 0x34, 0),       # SDIO_MODE
                            ("read", 0x202CADE8, 0x1C, 0),        # SD_INFO1
                            ("write", 0x202CADF0, 0x1C, 0),
                            ("write", 0x202CADF8, 0x1E, 0),       # SD_INFO2
                            ("write", 0x202CAE00, 0x36, 0),       # SDIO_INFO1
                            ("write", 0x202CAE0C, 0xE0, 6),       # SOFT_RST
                            ("write", 0x202CAE18, 0xE0, 7),
                            ("write", 0x202CAE24, 0x28, 0xBE),    # SD_OPTION
                            ("write", 0x202CAE2C, 0xF0, 0),       # EXT_SWAP
                            ("read", 0x202CA134, 0x1C, 0),
                            ("write", 0x202CA13C, 0x1C, 0),
                            ("write", 0x202CB124, 0x20, 0xFFE7),
                            ("write", 0x202CB134, 0x22, 0xFFFF),
                            ("read", 0x202CDF38, 0x28, 0xBE),
                            ("write", 0x202CDF48, 0x28, 0xB8),
                            ("read", 0x202CA1C4, 0x1C, 0),        # Main loop: no card present.
                        )

                        def sdhi(kind, off, width, value=None):
                            if kind == "read":
                                value = sdhi_regs.get(off)
                            step = kind, pc(), off, value
                            index = len(sdhi_trace)
                            if index == len(sdhi_steps) and width == 2 and step == sdhi_steps[-1]:
                                sdhi_late_polls.append([hex(pc()), value])
                                return value
                            require(width == 2 and index < len(sdhi_steps) and step == sdhi_steps[index],
                                    f"unmodeled SDHI0 access {width} bytes: {step} (step {index})")
                            if kind == "write":
                                if off in (0x1C, 0x1E, 0x36):
                                    sdhi_regs[off] &= value  # Status flags are cleared by writing zero.
                                else:
                                    sdhi_regs[off] = value
                            sdhi_trace.append([kind, hex(pc()), hex(sdhi_base+off), width, value])
                            return value

                        cpu.mmio_map(sdhi_base, 0x1000, lambda _c, o, w, _: sdhi("read", o, w), None,
                                     lambda _c, o, w, v, _: sdhi("write", o, w, v), None)

                        pending_settings_save = None
                        virtual_eeprom = {}
                        virtual_saves = []
                        settings_descriptors = tuple(iter_unpack("<4I", cpu.mem_read(0x202DE844, 5*16))) if cw_rx_audio else ()

                        def late_checkpoint(c, instruction, *_):
                            nonlocal pending_settings_save
                            after_fade.append([hex(instruction), cpu.mem_read(page+1, 1)[0]])
                            if instruction in (0x2007AE04, 0x2009657C, 0x200D4E1C):
                                ui_handoff.append([hex(instruction), unpack("<I", cpu.mem_read(request, 4))[0]])
                            if instruction in (0x2005E554, 0x2005BC08):
                                fields = (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_LR)
                                addr, src, count, caller = (c.reg_read(field) for field in fields)
                                # shortcut: mirror only stock VFO and settings saves in volatile host memory;
                                # model the EEPROM bus before adding any replay that reads these saves back.
                                if cw_rx_audio and instruction == 0x2005E554 and (
                                        caller in (0x200606CC, 0x200606FC) or caller == 0x2004E8FC and any(
                                            ram <= src and src+count <= ram+span and addr == eeprom+src-ram
                                            for ram, _, eeprom, span in settings_descriptors)):
                                    require(0 < count <= 32 and 0 <= addr <= 0x40000-count,
                                            f"unexpected simulated settings save: {addr:#x}, {count}")
                                    data = bytes(c.mem_read(src, count))
                                    virtual_eeprom.update(zip(range(addr, addr+count), data))
                                    virtual_saves.append(dict(address=hex(addr), length=count, caller=hex(caller),
                                                              sha256=sha256(data).hexdigest()))
                                    c.reg_write(arm.UC_ARM_REG_R0, 0)
                                    c.reg_write(arm.UC_ARM_REG_PC, caller)
                                    return
                                pending_settings_save = dict(pc=hex(instruction), address=hex(addr), source=hex(src),
                                                             length=count, return_pc=hex(caller), executed=False)
                                if instruction == 0x2005E554 and 0 < count <= 32:
                                    pending_settings_save["data"] = bytes(c.mem_read(src, count)).hex()
                                c.emu_stop()

                        points = (0x2007AAA0, 0x2012635C, 0x2007ADA8, 0x2007AE04, 0x2009657C,
                                  0x2007B970, 0x200D4E1C, 0x202CA1F0, 0x2005E554, 0x2005BC08)
                        for a in points:
                            cpu.hook_add(uc.UC_HOOK_CODE, late_checkpoint, begin=a, end=a)
                        for cycle in range(10100):
                            if pc() != idle:
                                break
                            require(pc() == idle and not software_irq_pending,
                                    f"startup scene was not idle at {pc():#x}")
                            pending, = unpack("<I", cpu.mem_read(request, 4))
                            if display[layer] & 0x111:
                                require(pending == 2, "no original startup frame request at LCD flip")
                                buffer = display[layer+0xC]
                                pixels = bytes(cpu.mem_read(buffer, frame_bytes))
                                progress = list(cpu.mem_read(params, 4))
                                vline(flip=False)
                                require(bytes(cpu.mem_read(request, 4)) == pack("<I", pending),
                                        "startup request cleared on a display line without Vsync")
                                vline(flip=True)
                                require(not any(cpu.mem_read(request, 4)) and not display[layer] & 0x111 and
                                        bytes(cpu.mem_read(buffer, frame_bytes)) == pixels, "startup flip did not finish")
                                colored = sum(p != 0 for p, in iter_unpack("<H", pixels))
                                startup_frames.append(dict(parameter=progress, address=hex(buffer), nonblack=colored,
                                                           sha256=sha256(pixels).hexdigest(), vsync_ack=0, cycle=cycle))
                                if len(startup_frames) in (6, 13) and scene_preview is not None:
                                    scene_preview.append(image_png((pixels[i:i+stride] for i in range(0, frame_bytes, stride)),
                                                                   width, height))
                                if len(startup_frames) == 21:
                                    break  # The stock UI acknowledged the outstanding last boot frame.
                            elif pending and len(events) > cuts:
                                require(pending == 2, f"unexpected startup draw request {pending}")
                                gpu[0xE8104018] = 3
                                deliver_irq(130, idle, stop_at_return=True)
                                require(software_irq_pending and not gpu[0xE8104018],
                                        "startup compositor did not wake on OpenVG completion")
                                cuts = len(events)
                            else:
                                before = unpack("<H", cpu.mem_read(tick, 2))[0]
                                stored[MTU2+0x22D] |= 1
                                post_lcd_io[0xE82000E4] = 1  # Running, with no completed DMA bank.
                                deliver_irq(159, idle, stop_at_return=True)
                                after = unpack("<H", cpu.mem_read(tick, 2))[0]
                                if software_irq_pending:
                                    software_irq_pending = False
                                    deliver_irq(0, idle)
                                if before != after and len(events) == cuts and not display[layer] & 0x111:
                                    post_lcd_io[MTU2+0x22C] = 1
                                    deliver_irq(154, idle, stop_at_return=True)
                                if before != after:
                                    clock.append([cycle, before, after])
                            if software_irq_pending:
                                software_irq_pending = False
                                deliver_irq(0, idle)
                        require([f["parameter"] for f in startup_frames] == [*expected_parameters, [0]*4] and
                                [f["nonblack"] for f in startup_frames] ==
                                [0, 3160, 3428, 3477, 3503, 3503, 3503, 3503, 7849, 7865,
                                 7865, 7865, 7865, 7865, 7865, 7839, 7790, 7506, 0, 0, 0] and
                                startup_frames[0]["sha256"] == startup_frames[-1]["sha256"] and
                                len({f["sha256"] for f in startup_frames[:6]}) == 6,
                                f"stock startup animation did not reach its final black frame: {startup_frames}, {pc():#x}")
                        encoder_sdhi = [row for row in board_trace[late_io:] if row[2] in ("0xfcff0385", "0xfcfe0444")]
                        require(pc() == idle and after_fade == [[hex(a), 4] for a in points[:-2]] and
                                encoder_sdhi == [["read", "0x20367b48", "0xfcff0385", 1, 0xC0]]*2 + [
                                    ["write", "0x20126354", "0xfcfe0444", 1, 0xF0],
                                    ["read", "0x20126358", "0xfcfe0444", 1, 0xF0]],
                                f"stock startup did not reach the main loop: {after_fade}, {encoder_sdhi}")
                        require(len(sdhi_trace) == len(sdhi_steps) and sdhi_regs[0x28] == 0xB8 and
                                not sdhi_regs[0x1C] & 0x20, "stock startup did not configure the empty SDHI0 host")
                        require(ui_handoff == [[hex(a), 2] for a in (0x2007AE04, 0x2009657C, 0x200D4E1C)] and
                                not any(cpu.mem_read(request, 4)), f"unexpected stock UI handoff: {ui_handoff}")
                        first_scene = dict(alpha_clear=alpha_clear, original_lcd_unchanged=True,
                                           mask_sha256_before=sha256(b"".join(mask_before)).hexdigest(),
                                           mask_sha256_after=sha256(b"".join(mask_after)).hexdigest(),
                                           irq=irq_trace[scene_irq:], rectangle=glyphs[0], artwork_mask=copy,
                                           image_batches=clears.images[:], artwork_png_sha256=sha256(mask_png).hexdigest(),
                                           scanouts=startup_frames, timer_ticks=clock,
                                           after_fade=after_fade, encoder_sdhi=encoder_sdhi,
                                           sdhi0=dict(card_present=False, accesses=sdhi_trace),
                                           ui_handoff=ui_handoff, stop_pc=hex(pc()), scene="04",
                                           main_loop=True, home=False)

                        # Only neutral acknowledgements for the already observed queued commands.
                        ring = 0x204988E0
                        board_events = []
                        def board_state():
                            return list(cpu.mem_read(ring+0x250, 2)), cpu.mem_read(0x20380B58, 1)[0]
                        require(board_state() == ([46, 42], 1) and not cpu.mem_read(0x20380B5C, 1)[0],
                                "unexpected board queue at the end of stock backlight animation")
                        for command in ("12000000", "30000500", "3100cb33", "020001a0", "01000201"):
                            for state, line in ((1, BOARD_TIMER_IRQ), (2, BOARD_RSPI_IRQ)):
                                require(cpu.mem_read(0x20380B26, 1)[0] == state, "unexpected stock serial state")
                                first_byte, before = len(board_spi_tx), board_state()
                                if state == 1:
                                    stored[MTU2+0x22D] |= 8
                                else:
                                    board_spi_rx.extend(bytes(4))
                                deliver_irq(line, idle, stop_at_return=True)
                                sent = bytes(board_spi_tx[first_byte:]).hex()
                                require(not board_spi_rx and sent == (command if state == 1 else ""),
                                        "stock board serial transfer differs from the neutral fixture")
                                board_events.append(dict(irq=line, before=before, after=board_state(), sent=sent))
                        require(board_state() == ([46, 46], 0) and not software_irq_pending,
                                "stock board task did not drain its own queue")

                        # Feed the RX8130CE over its original RIIC1 ISR, keeping all EEPROM write stops.
                        read_poll, write_poll, table_read = 0x200E3A80, 0x200E38F4, 0x20223CA0
                        rtc_points = (read_poll, write_poll, table_read)
                        rtc_bus = dict(receive=deque(), mmio=[])
                        late_panel_dma = []
                        if startup_home_probe:
                            late_adc_reads = []
                        ui_dispatch = []
                        page_writes = []
                        transfers = []
                        main_checkpoints = []
                        skip_stop = None

                        def rtc_stop(c, instruction, *_):
                            nonlocal skip_stop
                            if (startup_panel_record or startup_home_probe) and instruction == table_read and c.reg_read(arm.UC_ARM_REG_R0):
                                return  # Original slot 0 is initialized. The null guard remains enabled.
                            if skip_stop == instruction:
                                skip_stop = None
                            else:
                                c.emu_stop()

                        rtc_hooks = [cpu.hook_add(uc.UC_HOOK_CODE, rtc_stop, begin=a, end=a) for a in rtc_points]
                        def note_main(c, instruction, *_):
                            main_checkpoints.append([hex(instruction), c.mem_read(page+1, 1)[0], software_irq_pending])
                        for a in (0x2008CF70, 0x200D4F54, 0x200D50D4, 0x200D5114):
                            rtc_hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, note_main, begin=a, end=a))
                        if startup_home_probe:
                            def note_page(c, instruction, *_):
                                ui_dispatch.append([hex(instruction), c.mem_read(page+1, 1)[0],
                                                    c.mem_read(0x2038071C, 1)[0]])
                            for a in (0x20095A4C, 0x20095A90, 0x20095F78, 0x2013D4A4):
                                rtc_hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, note_page, begin=a, end=a))
                        if no_power_on_check:
                            def record_page(_cpu, _access, addr, size, value, _):
                                page_writes.append([hex(pc()), hex(addr), size, value])
                            rtc_hooks.append(cpu.hook_add(uc.UC_HOOK_MEM_WRITE, record_page, begin=page+1, end=page+1))
                        clock_registers = ((read_poll, 0x1D, b"\0"), (read_poll, 0x20, b"\0"),
                                           (read_poll, 0x10, bytes.fromhex("56341201151126")),
                                           (write_poll, 0x1E, b"\x20"))
                        flags = {197: 0x40, 198: 0x20, 199: 0x80, 200: 8, 201: 4}
                        def finish_riic1(poll, register, data):
                            nonlocal skip_stop
                            desc = bytes(cpu.mem_read(0x203EC1A4, 6+len(data)))
                            reading = poll == read_poll
                            require(pc() == poll and desc[:6] == bytes((1, reading, 0x64, len(data), 0, register)) and
                                    stored[RIIC1+4] == 2 and (reading or desc[6:] == data),
                                    f"unexpected stock RTC transaction at {pc():#x}: {desc.hex()}")
                            sequence = [201, 199]
                            if reading:
                                sequence += [197, 201]+[198]*(len(data)+1)
                                rtc_bus["receive"].extend(b"\0"+data)
                            else:
                                sequence += [199]*len(data)+[197]
                            trace_start = len(rtc_bus["mmio"])
                            for line in (*sequence, 200):
                                require(stored[RIIC1+0x1C] & flags[line], f"RTC IRQ {line} is not requested")
                                stored[RIIC1+0x24] = flags[line]
                                deliver_irq(line, poll, stop_at_return=True)
                            trace = rtc_bus["mmio"][trace_start:]
                            sent = bytes(row[4] for row in trace if row[0] == "write" and row[2] == hex(RIIC1+0x3C))
                            require(not rtc_bus["receive"] and not cpu.mem_read(0x203EC1A4, 1)[0] and
                                    sent == bytes((0x64, register))+(b"\x65" if reading else data),
                                    "stock RIIC1 transaction did not finish on the expected wire sequence")
                            transfers.append(dict(operation="read" if reading else "write", offset=hex(register),
                                                  data=data.hex(), wire=sent.hex(), irq=[*sequence, 200]))
                            skip_stop = poll
                            cpu.emu_start(poll, STOP, count=1)
                            cpu.emu_start(pc(), STOP, count=20_000_000 if startup_home_probe and not reading else 1_000_000)

                        def follow_panel_input(initial):
                            nonlocal software_irq_pending

                            def badge(frame):
                                return b"".join(frame[y*stride+130:y*stride+230] for y in range(62, 111))

                            reference = badge(initial)
                            scans, frames, actions, comparisons = [], [], [], []
                            menu_inputs, key_actions = [], []
                            picker_scanout = []
                            press_menu = startup_input in ("close-menu", "close-cw")
                            follow_menu = startup_input == "close-idle" or press_menu
                            last_gpu_event = len(events)
                            attach_ready = False
                            cw_thread = cw_frame = None
                            home_frame = None
                            rx_sent = rx_consumed = 0
                            rx_frame = rx_exit_scan = None
                            wave_rows, record_gate_before = 0, None
                            audio_gate_address = 0x2038026C
                            gate_fixture = None if cw_rx_record_gate is None else bytes((cw_rx_record_gate,))
                            stock_gate_writes = {}
                            code_evidence = None
                            if cw_canvas_audit:
                                from tools.probe_705_canvas_heap import CanvasAudit
                                canvas = CanvasAudit(cpu, stock=cw_canvas_audit == "stock")
                            else:
                                canvas = None

                            def consume_audio(c, *_):
                                nonlocal rx_consumed, record_gate_before
                                if rx_consumed < rx_sent:
                                    sp = c.reg_read(arm.UC_ARM_REG_SP)
                                    actual = bytes(c.mem_read(sp+8, 12))
                                    require(actual == cw_rx_audio[rx_consumed:rx_consumed+12],
                                            f"stock audio out of order at byte {rx_consumed}")
                                    rx_consumed += 12
                                    if cw_rx_closed_sql:
                                        require(c.mem_read(audio_gate_address, 1)[0] == stock_audio_gate,
                                                "natural audio gate changed before the CW bridge")
                                    if gate_fixture is not None:
                                        require(record_gate_before is None, "nested PCM bridge")
                                        # Exercise the CW copy without changing the following original recorder.
                                        record_gate_before = bytes(c.mem_read(audio_gate_address, 1))
                                        c.mem_write(audio_gate_address, gate_fixture)

                            def resume_recording(c, *_):
                                nonlocal record_gate_before
                                if record_gate_before is not None:
                                    require(bytes(c.mem_read(audio_gate_address, 1)) == gate_fixture,
                                            "recording gate changed while executing the CW bridge")
                                    c.mem_write(audio_gate_address, record_gate_before)
                                    record_gate_before = None

                            def observe_stock_gate(c, _kind, _address, size, value, _data):
                                if rx_sent:
                                    source = c.reg_read(arm.UC_ARM_REG_PC)
                                    require(size == 1 and value == stock_audio_gate,
                                            "unexpected audio gate written during closed SQL test")
                                    stock_gate_writes[hex(source)] = stock_gate_writes.get(hex(source), 0) + 1

                            def pause_for_attachment(c, *_):
                                nonlocal attach_ready
                                if closed and not attach_ready:
                                    attach_ready = True
                                    c.emu_stop()

                            def sample(c, _instruction, *_):
                                pressed = startup_input != "neutral" and len(scans) in (2, 5, 6)
                                menu_key = press_menu and not menu_committed and len(scans) >= 15
                                exit_key = menu_committed and (29 <= len(scans) < 41 if cw_enabled else 23 <= len(scans) < 34)
                                if cw_rx_audio:
                                    exit_key = rx_exit_scan is not None and rx_exit_scan <= len(scans) < rx_exit_scan+12
                                cw_key = cw_enabled and menu_committed and 22 <= len(scans) < 24
                                point = (240, 77) if cw_key and native_picker_id else (80, 247) if cw_key else None
                                if picker_scanout and picker_scanout[0]["scan"]+2 <= len(scans) < picker_scanout[0]["scan"]+4:
                                    point = (180,117)
                                c.mem_write(0x203E1F23, pack(">BHH", 0, *point) if point else
                                            pack(">BHH", 0, 358, 192) if pressed else b"\x01\0\0\0\0")
                                c.mem_write(0x203E1F1C, bytes((8 if menu_key else 0, 4 if exit_key else 0))+bytes(5))
                                scans.append([cycle, pressed])
                                if follow_menu:
                                    menu_inputs.append([cycle, menu_key, exit_key])

                            def observe(c, instruction, *_):
                                actions.append([cycle, hex(instruction), c.reg_read(arm.UC_ARM_REG_R0)])
                                if instruction == 0x2007F0A8:
                                    key_actions.append([cycle, c.reg_read(arm.UC_ARM_REG_R4)])

                            def compare(c, _instruction, *_):
                                a, b = (unpack("<I", c.mem_read(c.reg_read(reg), 4))[0]
                                        for reg in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1))
                                size = c.reg_read(arm.UC_ARM_REG_R2)
                                require(c.mem_read(a, size) == c.mem_read(b, size) or any(
                                    ram <= a and a+size <= ram+span and b-a == mirror-ram
                                    for ram, mirror, _, span in settings_descriptors), "stock settings changed during touch replay")
                                comparisons.append([hex(a), hex(b), size])

                            hooks = [cpu.hook_add(uc.UC_HOOK_CODE, fn, begin=a, end=a) for a, fn in (
                                (0x2007F104 if cw_enabled else 0x20108550, sample),
                                (0x2004E8C4, compare), (0x20108668, observe),
                                (0x201088F4, observe), (0x2007D574, observe))]
                            if follow_menu:
                                hooks.extend(cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=a, end=a)
                                             for a in (0x2007F0A8, 0x200927A4, 0x200927D0, 0x200908C0))
                            if cw_startup:
                                hooks.extend(cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=a, end=a)
                                             for a in (0x2006216C, 0x200622D8, 0x20092798, 0x20092804,
                                                       0x2009280C, 0x200928DC, 0x2010FEAC))
                            closed = menu_committed = exit_committed = False
                            home_hash = None
                            if cw_enabled:
                                from tools.probe_705_cw_session import read_session
                            if cw_image:
                                canvas.code_range = (cw_image["code_base"], cw_image["code_end"])
                                bridge = symbols["cw_pcm_bridge"]
                                hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, consume_audio, begin=bridge, end=bridge))
                                if cw_rx_closed_sql:
                                    hooks.append(cpu.hook_add(uc.UC_HOOK_MEM_WRITE, observe_stock_gate,
                                                              begin=audio_gate_address, end=audio_gate_address))
                                if gate_fixture is not None:
                                    hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, resume_recording,
                                                              begin=0x2010FEB0, end=0x2010FEB0))
                            elif cw_extension:
                                from tools.attach_705_cw_replay import allocate_heap, allocate_state, attach
                                from tools.probe_705_cw_pcm import TEST_STATE
                                cw_state = TEST_STATE
                                hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, pause_for_attachment,
                                                          begin=0x200D4EF0, end=0x200D4EF0))
                                if cw_rx_audio and not stock_mmu:
                                    bridge = cw_extension[2]["cw_pcm_bridge"]
                                    hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, consume_audio, begin=bridge, end=bridge))
                            try:
                                for cycle in range(28000 if cw_rx_audio else 6000 if cw_enabled else 4000 if cw_startup else
                                                   3600 if press_menu else 2400 if follow_menu else 1200):
                                    if cw_image and cw_thread is None:
                                        cw_state = canvas.word(anchor)
                                        if cw_state:
                                            cw_thread = canvas.word(cw_state+0x700)
                                            require(cw_thread and cpu.mem_read(cw_thread+2, 1) == b"\xe9" and
                                                    # D1-D4 use 4 KiB; D5 adds a fixed 1 KiB text page.
                                                    canvas.word(cw_state-4) in (4104, 5128), "invalid guest CW state or worker")
                                            canvas.state = cw_state
                                    require(pc() == idle and pending_settings_save is None,
                                            f"stock input stopped at {pc():#x}: {pending_settings_save}")
                                    if display[layer] & 0x111:
                                        buffer = display[layer+0xC]
                                        frame = bytes(cpu.mem_read(buffer, frame_bytes))
                                        vline(flip=False)
                                        vline(flip=True)
                                        require(not any(cpu.mem_read(request, 4)), "LCD did not acknowledge the input frame")
                                        warning = badge(frame) == reference
                                        frames.append(dict(cycle=cycle, sha256=sha256(frame).hexdigest(), warning=warning))
                                        if native_picker_id and menu_committed and not picker_scanout and (
                                                unpack("<H", cpu.mem_read(0x203E1A28, 2))[0] == native_picker_id):
                                            picker_scanout.append(dict(scan=len(scans), popup_id=native_picker_id, **frames[-1]))
                                        if not warning and not closed:
                                            home_hash = frames[-1]["sha256"]
                                            home_frame = frame
                                            if cw_startup:
                                                frequency, mode = unpack("<IB", cpu.mem_read(0x203EBC2F, 5))
                                                require((frequency, mode) == (7_030_000, 0x20) and
                                                        bytes(cpu.mem_read(0x20380714, 4)) == pack("<I", frequency) and
                                                        cpu.mem_read(0x203EBC2B, 2) == b"\0\0" and
                                                        cpu.mem_read(0x203EBC78, 1)[0] & 4 == 0 and
                                                        cpu.mem_read(0x203E2128, 1) == b"\x20" and
                                                        b"7030000" in cpu.mem_read(page, 0xC0),
                                                        "stock HOME did not restore VFO A and build its CW frequency label")
                                            require(startup_input != "neutral" and len(scans) == 8 and
                                                    (cw_startup or home_hash ==
                                                    "7d0c1e18a1ef35fe7ed8786c2a28403687167b2a0e91f49fd3d62f83b75bbacb") and
                                                    cpu.mem_read(page+1, 1) == b"\x01",
                                                    "warning region changed without the verified HOME frame")
                                            closed = True
                                            if home_observer is not None:
                                                home_observer(cpu, home_hash)
                                            if canvas:
                                                canvas.capture("stock-home-before-cw")
                                            if scene_preview is not None:
                                                scene_preview.append(image_png((frame[i:i+stride] for i in
                                                                                 range(0, frame_bytes, stride)), width, height))
                                            if not follow_menu:
                                                break
                                        if follow_menu and closed and not menu_committed and cpu.mem_read(page+1, 1) == b"\x02":
                                            require(press_menu and
                                                    {"0x200927a4", "0x200927d0"} <= {row[1] for row in actions} and
                                                    [action for _, action in key_actions] == [5] and
                                                    ("0x2009280c" in {row[1] for row in actions} and
                                                     cpu.mem_read(0x204BD240, 1) == b"\x01" if cw_startup else
                                                     frames[-1]["sha256"] == "b1b7c7811ae690a1695aa0407ebe60fd6ecb83200689234994086ce44bfc55f8"),
                                                    f"unexpected stock MENU selection or LCD frame: {key_actions}, "
                                                    f"{[row for row in actions if row[1].startswith('0x20092')]}, "
                                                    f"variant={cpu.mem_read(0x204BD240, 12).hex()}")
                                            menu_committed = True
                                            if scene_preview is not None:
                                                scene_preview.append(image_png((frame[i:i+stride] for i in
                                                                                 range(0, frame_bytes, stride)), width, height))
                                        if cw_thread and menu_committed and cw_frame is None and cpu.mem_read(page+1, 1) == b"\x01":
                                            state = read_session(cpu, cw_state)
                                            if state["active"]:
                                                require(not state["menu_two"] and frame[:140*stride] == home_frame[:140*stride]
                                                        and frame[149*stride:] != home_frame[149*stride:],
                                                        "CW must open on softkey page one over the stock VFO frame")
                                                cw_frame = dict(**frames[-1], softkey_page=1, audio_fed=state["fed"])
                                                if canvas:
                                                    canvas.capture("first-cw-frame", drawing=True)
                                                if scene_preview is not None:
                                                    scene_preview.append(image_png((frame[i:i+stride] for i in
                                                                                     range(0, frame_bytes, stride)), width, height))
                                        if (gate_fixture is not None or cw_rx_closed_sql) and cw_frame and rx_frame is None:
                                            rows = (frame[y*stride+291*2:y*stride+379*2] for y in range(181, 231))
                                            wave_rows = max(wave_rows, sum(any(pixel == 0x07e0 for pixel, in iter_unpack("<H", row))
                                                                          for row in rows))
                                        if cw_rx_audio and cw_frame and rx_frame is None and rx_consumed == len(cw_rx_audio):
                                            state = read_session(cpu, cw_state)
                                            if not state["queued"] and state["fed"] == len(cw_rx_audio)//160:
                                                require(state["text"] == state["shown_text"] == "CQ" and not state["drops"],
                                                        f"cold-start CW decode mismatch: {state['text']!r}")
                                                body = (frame[y*stride+2:y*stride+2*287] for y in range(166, 237))
                                                green = sum((rgb & 0xF81F) == 0 and (rgb & 0x07E0) >= 0x300
                                                            for row in body for rgb, in iter_unpack("<H", row))
                                                require(green > 0, "CW text did not reach the LCD")
                                                rx_frame = dict(**frames[-1], fed=state["fed"], shown_text=state["shown_text"],
                                                                pcm_sha256=sha256(cw_rx_audio).hexdigest(),
                                                                dma_groups=rx_consumed//12, green_text_pixels=green)
                                                if gate_fixture is not None or cw_rx_closed_sql:
                                                    require(wave_rows > 2, "the CW LCD waveform stayed flat")
                                                    rx_frame.update(cw_input_recording_gate=stock_audio_gate if cw_rx_closed_sql
                                                                    else cw_rx_record_gate, lcd_waveform_rows=wave_rows,
                                                                    dropped_dma_groups=state["drops"])
                                                if cw_rx_closed_sql:
                                                    require("0x200622d8" in stock_gate_writes, "original gate writer was not observed")
                                                    rx_frame.update(stock_gate_writes=dict(stock_gate_writes))
                                                rx_exit_scan = len(scans)+1
                                                if canvas:
                                                    canvas.capture("cw-receive", drawing=True)
                                                if scene_preview is not None:
                                                    scene_preview.append(image_png((frame[i:i+stride] for i in
                                                                                     range(0, frame_bytes, stride)), width, height))
                                        if menu_committed and cpu.mem_read(page+1, 1) == b"\x01" and (
                                                not cw_enabled or [action for _, action in key_actions] == [5, 9]):
                                            require([action for _, action in key_actions] == [5, 9] and not warning and
                                                    frames[-1]["sha256"] == home_hash,
                                                    "stock HOME resumed without a distinct frame and EXIT key")
                                            exit_committed = True
                                            if canvas:
                                                canvas.capture("stock-home-after-exit")
                                            if scene_preview is not None:
                                                scene_preview.append(image_png((frame[i:i+stride] for i in
                                                                                 range(0, frame_bytes, stride)), width, height))
                                            break
                                    elif any(cpu.mem_read(request, 4)) and len(events) > last_gpu_event:
                                        last_gpu_event = len(events)
                                        gpu[0xE8104018] = 3
                                        deliver_irq(130, idle, stop_at_return=True)
                                    elif (state := cpu.mem_read(0x20380B26, 1)[0]) in (1, 2, 3, 4, 5, 6):
                                        if state in (1, 3, 5):
                                            stored[MTU2+0x22D] |= 8
                                            line = BOARD_TIMER_IRQ
                                        else:
                                            board_spi_rx.extend(bytes(4))
                                            line = BOARD_RSPI_IRQ
                                        deliver_irq(line, idle, stop_at_return=True)
                                    elif cpu.mem_read(STARTUP_DMA_BUSY, 1)[0] and startup_devices.get(STARTUP_DMA+0x24) == 1:
                                        startup_devices[STARTUP_DMA+0x24] |= 0x20
                                        deliver_irq(STARTUP_DMA_IRQ, idle, stop_at_return=True)
                                    else:
                                        previous_tick = cpu.mem_read(tick, 2)
                                        stored[MTU2+0x22D] |= 1
                                        if cw_rx_audio and cw_frame and rx_sent < len(cw_rx_audio):
                                            require(cpu.mem_read(audio_gate_address, 1)[0] == stock_audio_gate,
                                                    "stock audio gate did not match the RX fixture")
                                            while rx_sent < len(cw_rx_audio) and rx_sent-rx_consumed < 72:
                                                write, read = cpu.mem_read(0x204016E2, 2)
                                                require((write+1)%8 != read, "stock audio ring would overrun")
                                                bank = rx_sent//12 % 2
                                                group = unpack("<6h", cw_rx_audio[rx_sent:rx_sent+12])
                                                words = [v for a in group for v in ((a & 0xFFFF) << 16, 0)*6]
                                                cpu.mem_write(0x20400800+bank*0x120, pack("<72I", *words))
                                                post_lcd_io[0xE82000E4] = 0x41 if bank else 0xC1
                                                rx_sent += 12
                                                deliver_irq(159, idle, stop_at_return=True)
                                        post_lcd_io[0xE82000E4] = 1
                                        deliver_irq(159, idle, stop_at_return=True)
                                        if software_irq_pending:
                                            software_irq_pending = False
                                            deliver_irq(0, idle)
                                        if ((cw_rx_audio and cw_frame and rx_frame is None or cpu.mem_read(tick, 2) != previous_tick)
                                                and not any(cpu.mem_read(request, 4))):
                                            post_lcd_io[MTU2+0x22C] = 1
                                            deliver_irq(154, idle, stop_at_return=True)
                                    if software_irq_pending:
                                        software_irq_pending = False
                                        deliver_irq(0, idle)
                                    if attach_ready and cw_thread is None:
                                        require(pc() == 0x200D4EF0, f"unexpected CW attach checkpoint {pc():#x}")
                                        def scheduling():
                                            return software_irq_pending

                                        if cw_stock_state:
                                            cw_state = allocate_state(cpu, schedule_marker=scheduling)
                                            canvas.state_allocated(cw_state)
                                        extension, code_base, code_request = cw_extension, None, 0
                                        if stock_mmu:
                                            from tools.probe_705_cw_session import RTX_CODE, build
                                            size = len(cw_extension[0])
                                            # Vary the next heap addresses without changing the program or stock allocator.
                                            code_request = ((size+8+63) & ~63)-8+cw_heap_offset
                                            before = canvas.free_list()
                                            code_base = allocate_heap(cpu, code_request, schedule_marker=scheduling)
                                            reserved = canvas.code_allocated(code_base, size, code_request, before)
                                            with TemporaryDirectory() as folder:
                                                extension = build(Path(folder), rtx=True, stock_canvas=True,
                                                                  stock_state=True, text_base=code_base)
                                            require(len(extension[0]) == size and cpr(1) & 1 and
                                                    not any(lo <= RTX_CODE <= hi for lo, hi, _ in cpu.mem_regions()),
                                                    "offline code relocated outside the stock-address test conditions")
                                            bridge = extension[2]["cw_pcm_bridge"]
                                            hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, consume_audio, begin=bridge, end=bridge))
                                            entry = unpack("<I", cpu.mem_read(0x20000000+(code_base>>20)*4, 4))[0]
                                            require(entry & 0xfff00013 == (code_base & 0xfff00000) | 2,
                                                    "original code-block address is not an executable identity section")
                                            code_evidence = dict(base=hex(code_base), end=hex(code_base+size), bytes=size,
                                                                 request_bytes=code_request, reserved_with_header=reserved,
                                                                 l1_entry=hex(entry),
                                                                 loader="host-only into a stock allocator reservation")
                                        cw_thread = attach(cpu, extension, draw=True, code_base=code_base,
                                                           code_request=code_request,
                                                           schedule_marker=scheduling,
                                                           stock_canvas=cw_canvas_audit == "stock", state=cw_state)
                                        if code_evidence:
                                            code_evidence["loaded_sha256"] = sha256(bytes(cpu.mem_read(code_base, size))).hexdigest()
                                            code_evidence["attachment_sctlr"] = hex(cpr(1))
                                        if canvas:
                                            canvas.state = cw_state
                                        cpu.emu_start(pc(), STOP, count=1_000_000)
                                    if (startup_input == "neutral" and len(scans) >= 8 and pc() == idle and
                                            stored[STARTUP_RSPI3] == stored[STARTUP_RSPI0] == 8 and
                                            (stored[STARTUP_RSPI3+0x10], stored[STARTUP_RSPI0+0x10]) == (0xE70C, 0xE78C)):
                                        break
                            finally:
                                for hook in hooks:
                                    cpu.hook_del(hook)
                            require(closed == (startup_input != "neutral") and len(scans) >= 8 and frames and comparisons and
                                    pending_settings_save is None and (not closed or
                                    {"0x20108668", "0x201088f4", "0x2007d574"} <= {row[1] for row in actions}),
                                    "stock panel replay did not reach its expected result")
                            result = dict(input=startup_input, warning_dismissed=closed, touch=scans, stock_actions=actions,
                                          settings_compared=comparisons, persistent_writes=0, scanout=frames)
                            if follow_menu:
                                visited = {row[1] for row in actions}
                                require(menu_committed == exit_committed == press_menu and
                                        "0x200908c0" not in visited and
                                        (menu_committed or len(scans) >= 20 and not {"0x200927a4", "0x200927d0"} & visited and
                                         cpu.mem_read(page+1, 1) == b"\x01"), "stock MENU control contradicted panel input")
                                result.update(menu_committed=menu_committed, exit_committed=exit_committed,
                                              key_samples=menu_inputs, key_actions=key_actions,
                                              screen_saver_settings=cpu.mem_read(0x203EAE37, 2).hex(), cycles=cycle+1)
                            if cw_startup:
                                result.update(vfo="A", frequency_hz=7_030_000, mode="CW", stock_menu="KEYER",
                                              audio_gate=cpu.mem_read(0x2038026C, 1)[0])
                                if cw_rx_ready:
                                    require(result["audio_gate"] == stock_audio_gate and not cpu.mem_read(0x203809C4, 1)[0] & 1
                                            and cpu.mem_read(0x203EB11B, 1)[0] == rx_squelch,
                                            "stock startup did not reflect the PTT and SQL fixture")
                                    result.update(rx_fixture=dict(ptt="released", squelch=rx_squelch))
                            if cw_enabled:
                                require(cw_thread and cw_frame and exit_committed and not read_session(cpu, cw_state)["active"],
                                        "CW did not enter and exit in the same startup")
                                result.update(cw_thread=hex(cw_thread), cw_frame=cw_frame)
                            if native_picker_id:
                                require(len(picker_scanout) == 1 and
                                        unpack("<H", cpu.mem_read(0x203E1A28, 2))[0] == 0,
                                        "original selector did not open and close on the packaged path")
                                result.update(cw_native_picker=picker_scanout[0])
                            if cw_image:
                                base, end = canvas.code_range
                                expected = main[base-BASE:end-BASE]
                                actual = bytearray(cpu.mem_read(base, end-base))
                                word_offset = anchor-base
                                if native_picker_id:
                                    choice_offset = cw_image["picker_choice"]-base
                                    require(actual[choice_offset:choice_offset+4] == b"\1\0\0\0",
                                            "native selector did not record the decode row")
                                    actual[choice_offset] = 0
                                require(cpr(1) & 1 and len(install_writes) == len(worker_entries) == 1 and
                                        install_writes[0]["size"] == 4 and install_writes[0]["state"] == hex(cw_state) and
                                        symbols["cw_sim_boot"] <= int(install_writes[0]["pc"], 16) < end and
                                        actual[:word_offset] == expected[:word_offset] and
                                        actual[word_offset+4:] == expected[word_offset+4:],
                                        "CW startup did not execute the packaged code with its own RTX worker")
                                result["cw_packaged_boot"] = dict(reset_entry="0x20005060",
                                                                  loader_entry=nor_boot["copied_stage_entry"] if nor_boot else "0x20004848",
                                                                  main_source="virtual NOR" if nor_boot else "preloaded RAM",
                                                                  host_attachment=False, guest_anchor_write=install_writes[0],
                                                                  worker_entry=worker_entries[0], exit_sctlr=hex(cpr(1)))
                            if cw_rx_audio:
                                require(rx_frame and rx_sent == rx_consumed == len(cw_rx_audio), "cold-start CW audio did not finish")
                                result.update(cw_receive=rx_frame, volatile_eeprom_writes=virtual_saves)
                            if canvas:
                                result["cw_stock_canvas"] = canvas.evidence(clears.copies)
                            if cw_stock_state:
                                old_state_mapped = any(lo <= TEST_STATE <= hi for lo, hi, _ in cpu.mem_regions())
                                require(not old_state_mapped, "fixed session address was mapped during the relocation test")
                                result["cw_old_state_mapped"] = old_state_mapped
                            if code_evidence:
                                require(cpr(1) & 1 and sha256(bytes(cpu.mem_read(code_base, size))).hexdigest() ==
                                        code_evidence["loaded_sha256"] and all(
                                            b+n <= code_base-4 or b >= code_base-4+reserved for b, n in canvas.free_list()),
                                        "original mapping or offline code block did not survive through EXIT")
                                code_evidence["exit_sctlr"] = hex(cpr(1))
                                result["cw_offline_code"] = code_evidence
                            return result

                        try:
                            clock_fifo = len(events)
                            post_lcd_io[MTU2+0x22C] = 1
                            deliver_irq(154, idle, stop_at_return=True)
                            require(software_irq_pending, "stock main loop did not wake for RTC setup")
                            software_irq_pending = False
                            deliver_irq(0, idle)
                            for poll, register, data in clock_registers:
                                finish_riic1(poll, register, data)
                            expected_handoff = ["0x2008cf70", "0x200d4f54", "0x200d50d4"]
                            require(len(late_panel_dma) == 9 and
                                    bytes(cpu.mem_read(0x2038079A, 7)).hex() == "26111501123456",
                                    f"stock clock or panel DMA setup did not finish at {pc():#x}")
                            if startup_home_probe:
                                expected_handoff += ["0x200d5114"]
                                selected_page, expected_completions = (1, 70) if no_power_on_check else (0x3D, 72)
                                expected_dispatch = ([["0x20095f78", 4, 0], ["0x2013d4a4", 1, 0]] if no_power_on_check else
                                                     [["0x20095a4c", 4, 2], ["0x20095a90", 4, 2], ["0x2013d4a4", 0x3D, 2]])
                                require(pc() == idle and not software_irq_pending and not pending_settings_save and
                                        len(late_adc_reads) == 6 and len(events)-clock_fifo == (42 if no_power_on_check else 74) and
                                        cpu.mem_read(request, 4) == pack("<I", 2) and not display[layer] & 0x111 and
                                        ui_dispatch == expected_dispatch,
                                        f"unexpected stock renderer handoff {pc():#x}: {ui_dispatch}, {late_adc_reads}")
                                if no_power_on_check:
                                    require(page_writes == [["0x20095f78", hex(page+1), 1, 1]] and
                                            not cpu.mem_read(0x203EAE3C, 1)[0],
                                            f"stock HOME was not selected after reading Power ON Check OFF: {page_writes}")
                                new_gpu_accesses = events[clock_fifo:]
                                copy_index, gpu_cycles = len(clears.copies), 0
                                packed_copy = None
                                for _ in range(160 if cw_startup else 100):
                                    if display[layer] & 0x111:
                                        break
                                    require(pc() == idle and not software_irq_pending and
                                            bytes(cpu.mem_read(request, 4)) == pack("<I", 2), "stock scene stopped before Vsync")
                                    gpu[0xE8104018] = 3
                                    deliver_irq(130, idle, stop_at_return=True)
                                    require(software_irq_pending and not gpu[0xE8104018], "scene GPU completion did not wake UI")
                                    software_irq_pending = False
                                    deliver_irq(0, idle)
                                    gpu_cycles += 1
                                    if not cw_startup and packed_copy is None and len(clears.copies) > copy_index:
                                        packed_copy = clears.copies[copy_index]
                                        if no_power_on_check:
                                            source, target, w, h, row_pitch = 0x18AE3D40, 0x2086BB40, 40, 19, 160
                                        else:
                                            source, target, w, h, row_pitch = 0x18AF81E0, 0x2086BBA0, 15, 60, 64
                                        source += slot_adjust
                                        stock_rows = b"".join(bytes(cpu.mem_read(source+row_pitch*y, w*4)) for y in range(h))
                                        copied_rows = b"".join(bytes(cpu.mem_read(target-row_pitch*y, w*4)) for y in range(h))
                                        require(packed_copy["source"] == hex(source) and packed_copy["target"] == hex(target) and
                                                stock_rows == copied_rows and any(stock_rows) and
                                                packed_copy["sha256"] == sha256(stock_rows).hexdigest(),
                                                "stock packed-color copy did not match the read-only resource")
                                require(pc() == idle and (gpu_cycles == (119 if cw_rx_ready and not cw_rx_closed_sql else 121) and
                                                         len(clears.copies) > copy_index if cw_startup
                                                         else gpu_cycles == expected_completions and packed_copy) and display[layer] == 0x11 and
                                        cpu.mem_read(page+1, 1)[0] == selected_page and not software_irq_pending,
                                        f"stock scene did not submit the expected display update: {pc():#x}, {gpu_cycles}")
                                buffer = display[layer+0xC]
                                require(buffer in (0x208AE000, 0x208EDC00), "unexpected stock LCD scanout address")
                                pixels = bytes(cpu.mem_read(buffer, frame_bytes))
                                require(any(pixels) and bytes(cpu.mem_read(request, 4)) == pack("<I", 2),
                                        "scene did not send pixels with its original request")
                                vline(flip=False)
                                require(display[layer] == 0x11 and bytes(cpu.mem_read(request, 4)) == pack("<I", 2),
                                        "ordinary display line changed the scene request")
                                vline(flip=True)
                                require(pc() == idle and not any(cpu.mem_read(request, 4)) and not display[layer] & 0x111 and
                                        display[layer+0xC] == buffer and pixels == bytes(cpu.mem_read(buffer, frame_bytes)),
                                        "original LCD request was not acknowledged after Vsync")
                                if scene_preview is not None:
                                    scene_preview.append(image_png((pixels[i:i+stride] for i in range(0, frame_bytes, stride)),
                                                                   width, height))
                                scanout = dict(address=hex(buffer), sha256=sha256(pixels).hexdigest(),
                                               nonblack=sum(p != 0 for p, in iter_unpack("<H", pixels)),
                                               line_request=2, vsync_request=0)
                                guard = dict(panel_record=dict(offset="0x1bbc0", byte_offset=1, data="f7"),
                                             stored_settings=dict(offset="0x3aac0", data="01"+"ff"*18+"02"),
                                             renderer=dict(steps=ui_dispatch, adc_reads=late_adc_reads, page=f"{selected_page:02x}",
                                                           new_gpu_accesses=new_gpu_accesses, gpu_completions=gpu_cycles,
                                                           packed_copy=packed_copy, lcd_scanout=scanout, stop_pc=hex(pc())))
                                if no_power_on_check:
                                    guard["renderer"].update(power_on_check=dict(offset="0x1cb60", byte_offset=0x13, data="00"),
                                                             page_writes=page_writes, home_page_committed=True)
                                if startup_input:
                                    initial_handoff = list(main_checkpoints)
                                    guard["startup_input"] = follow_panel_input(pixels)
                                    main_checkpoints[:] = initial_handoff
                            elif startup_panel_record:
                                expected_handoff += ["0x200d5114"]
                                require(pc() == 0x2005E554 and pending_settings_save == dict(
                                    pc="0x2005e554", address="0x355c0", source="0x203e632f", length=20,
                                    return_pc="0x2004e8fc", executed=False, data="01"+"ff"*18+"02") and
                                    cpu.mem_read(request, 4) == pack("<I", 2),
                                    f"unexpected stock settings save after normal UI update: {pending_settings_save}, {pc():#x}")
                                guard = dict(panel_record=dict(offset="0x1bbc0", byte_offset=1, data="f7"),
                                             settings_write_guard=pending_settings_save)
                            else:
                                require(pc() == table_read and not software_irq_pending and
                                        not any(cpu.mem_read(request, 4)) and cpu.reg_read(arm.UC_ARM_REG_R0) == 0,
                                        f"unexpected stock table read state at {pc():#x}")
                                guard = dict(table_read_guard=dict(pc=hex(pc()), pointer=0, byte_offset=3, executed=False))
                            require([row[0] for row in main_checkpoints] == expected_handoff,
                                    f"unexpected stock UI handoff: {main_checkpoints}")
                            late_board = dict(serial=board_events, rtc=dict(transactions=transfers, mmio=rtc_bus["mmio"],
                                              date="2026-11-15T12:34:56", chip="RX8130CE"),
                                              panel_dma=dict(accesses=[[k, hex(i), hex(a), w, v, hex(lr)]
                                                                      for k, i, a, w, v, lr in late_panel_dma],
                                                             transferred=False, irq=None),
                                              sdhi0_no_card_polls=sdhi_late_polls,
                                              main_checkpoints=main_checkpoints,
                                              **guard, eeprom_writes=0, home=False)
                        finally:
                            for hook in rtc_hooks:
                                cpu.hook_del(hook)
                            rtc_bus = None
                            late_panel_dma = None
                            late_adc_reads = None
                        return dict(path_program=launch[0], draws=clears.draws[:21], lcd=lcd,
                                    first_frame=dict(page=page_state.hex(), dispatch=dispatch, scene="black",
                                                     png_sha256=sha256(rendered).hexdigest()),
                                    vsync=dict(ui_request_before=2, ui_request_after=0, irq=irq_trace[mark:after_vsync]),
                                    startup_resume=dict(checkpoints=checkpoints, irq=irq_trace[after_vsync:], timer=timer_io,
                                                        panel_startup=panel_startup, first_startup_scene=first_scene,
                                                        main_loop_resume=late_board))
                    first_draws = clears.draws[21:]
                    require(len(launch) == 2 and not clears.remaining and len(first_draws) == 4 and
                            [entry[0] for entry in dispatch] == [hex(a) for a in points] and dispatch[-1][1] == 11 and
                            unpack("<I", cpu.mem_read(0x20381E90, 4))[0] == worker,
                            f"stock UI did not reach its first scene submission: {pc():#x}, {dispatch}")
                    coordinates = ((3, 3), (4, 4), (5, 5), (374, 174), (0, 0))
                    pixels = [unpack("<H", cpu.mem_read(0x2094EB00-768*y+2*x, 2))[0]
                              for x, y in coordinates]
                    require(pixels == [0xA514, 0xA514, 0, 0xA514, 0] and
                            display[layer+0xC] == addr and bytes(cpu.mem_read(addr, frame_bytes)) == raw,
                            "first scene did not paint the expected offscreen pixels")
                    first_path_pc = pc()
                    idle, fifo, status = 0x201254B0, 0xE8104000, 0xE8104018
                    resume_outline = True
                    advance(first_path_pc, idle)
                    resume_outline = False
                    require(not reads and not software_irq_pending and not gpu.get(status, 0),
                            "stock UI read outline results before graphics completion")
                    cut, irq_cut = len(events), len(irq_trace)
                    gpu[status] = 3
                    deliver_irq(130, idle, stop_at_return=True)
                    require(software_irq_pending and gpu[status] == 0, "outline completion did not wake the stock UI")
                    software_irq_pending = False

                    def stop_at_next_path(c, *_):
                        if c.reg_read(arm.UC_ARM_REG_R0)+(c.reg_read(arm.UC_ARM_REG_R1) & ~3) == 0xE8102070:
                            c.emu_stop()

                    hook = cpu.hook_add(uc.UC_HOOK_CODE, stop_at_next_path, begin=first_path_pc, end=first_path_pc)
                    try:
                        deliver_irq(0, idle)
                    finally:
                        cpu.hook_del(hook)
                    commands = [v for kind, _, address, v in events[cut:] if kind == "write" and int(address, 16) == fifo]
                    x0, y0, x1, y1 = launch[1]["calculated_bounds"]
                    require(pc() == first_path_pc and reads == [["0xfc", "0x0"], ["0x98", hex(x1 << 16 | y1)],
                                                               ["0x9c", hex(x0 << 16 | y0)]] and
                            commands.count(0xD8000000) == 1, "stock UI did not issue the first outline draw")
                    cover = commands.index(0xD8000000)
                    require(commands[cover+1:cover+3] == [x0 << 16 | y0, x1 << 16 | y1] and
                            clears.cover_draw is not None and clears.cover_draw["address"] == "0x2094eb00" and
                            not clears.remaining and clears.cover_words is None and
                            bytes(cpu.mem_read(addr, frame_bytes)) == raw, "unexpected first outline draw bounds")
                    first_completion = dict(reads=list(reads), irq=irq_trace[irq_cut:],
                                            cover_words=[hex(w) for w in commands[cover:cover+3]],
                                            rasterized=clears.cover_draw)

                    def preview():
                        return image_png((cpu.mem_read(0x2094EB00-768*y, 380*2) for y in reversed(range(178))), 380, 178)

                    first_png = preview()
                    draw_dialog = True
                    advance(pc(), idle)
                    for index in range(55):
                        require(pc() == idle and len(glyphs) == index+1 and not software_irq_pending and
                                not gpu[status] and clears.cover_draw is None, "startup text did not wait for a path")
                        gpu[status] = 3
                        deliver_irq(130, idle, stop_at_return=True)
                        require(software_irq_pending and not gpu[status], "startup text completion did not wake UI")
                        software_irq_pending = False
                        deliver_irq(0, idle)
                    require(pc() == idle and len(glyphs) == 55 and clears.cover_draw and
                            bytes(cpu.mem_read(addr, frame_bytes)) == raw, "unexpected end of startup dialog draw")
                    dialog_png = preview()
                    require(dialog_png != first_png, "startup dialog did not add text")
                    dialog_paths = glyphs[:]
                    for _ in range(7):
                        require(pc() == idle and not software_irq_pending and not gpu[status] and
                                display[layer+0xC] == addr, "stock startup did not wait for a compositor event")
                        gpu[status] = 3
                        deliver_irq(130, idle, stop_at_return=True)
                        require(software_irq_pending, "composition completion did not wake stock task")
                        software_irq_pending = False
                        deliver_irq(0, idle)
                    lcd_address = display[layer+0xC]
                    require(lcd_address == 0x208EDC00 and len(clears.copies) == 3 and len(clears.images) == 1 and
                            clears.copies[-1]["changed"], "stock LCD did not select the composed startup frame")
                    lcd_frame = bytes(cpu.mem_read(lcd_address, frame_bytes))
                    x, y, w, h = 50, 47, 380, 178
                    for row in range(height):
                        src = (bytes(cpu.mem_read(0x2094EB00-768*(h-1-(row-y)), 2*w))
                               if y <= row < y+h else b"")
                        expected = b"\0"*(2*x)+src+b"\0"*(stride-2*x-len(src))
                        require(lcd_frame[row*stride:(row+1)*stride] == expected,
                                f"LCD pixels differ from the original startup dialog on row {row}")
                    nonzero = sum(value != 0 for value, in iter_unpack("<H", lcd_frame))
                    require(nonzero > 0 and not any(cpu.mem_read(addr, frame_bytes)),
                            "stock LCD did not switch from a black to a nonblack buffer")
                    rendered = image_png((lcd_frame[i:i+stride] for i in range(0, len(lcd_frame), stride)), width, height)
                    after = {}
                    if after_lcd:
                        post_lcd_io = {}
                        rings, cursors = (0x204014A2, 0x20401928), 0x204016E2
                        timeline, groups, wake_checks, request_writes = [], [], [], []
                        application_tick, request = 0x2038074A, 0x20380C8C
                        start_count = cpu.mem_read(application_tick, 1)[0]
                        irq_cut = len(irq_trace)

                        def check_lcd_wake(c, instruction, *_):
                            wake_checks.append([hex(instruction), c.reg_read(arm.UC_ARM_REG_R0)])

                        def request_write(_c, _access, address, size, data, _user):
                            request_writes.append([hex(pc()), hex(address), size, data])

                        hooks = [cpu.hook_add(uc.UC_HOOK_CODE, check_lcd_wake, begin=a, end=a)
                                 for a in (0x2013CDD8, 0x2013CDF8, 0x2013CE04, 0x2013D540)]
                        hooks.append(cpu.hook_add(uc.UC_HOOK_MEM_WRITE, request_write, begin=request, end=request+3))
                        for line in (78, 154, 154, 159, 134)*8:
                            if line == 78:
                                display[0xFCFF7A80] = display.get(0xFCFF7A80, 0) | 0x1000
                            elif line == 154:
                                post_lcd_io[MTU2+0x22C] = 1
                            elif line == 159:
                                stored[MTU2+0x22D] |= 1
                                write, read = cpu.mem_read(cursors, 2)
                                bank = len(groups) % 2
                                # Distinct banks and channels; the nonzero low halfword must not become PCM.
                                samples = [1234+len(groups)*257+i*37 for i in range(72)]
                                cpu.mem_write(0x20400800+bank*0x120, pack("<72I", *(v << 16 | 0x5A5A for v in samples)))
                                post_lcd_io[0xE82000E4] = 0x41 if bank else 0xC1
                            require(pc() == idle and not software_irq_pending, "post-LCD event did not start from idle")
                            deliver_irq(line, idle, stop_at_return=True)
                            if line == 154:
                                require(not post_lcd_io[MTU2+0x22C], "guest left the timer compare flag set")
                            elif line == 159:
                                pair = list(cpu.mem_read(cursors, 2))
                                data = b"".join(bytes(cpu.mem_read(ring+write*72, 72)) for ring in rings)
                                require(pair == [(write+1)%8, read] and
                                        data == pack("<72h", *(samples[::2]+samples[1::2])),
                                        "cold-start DMA did not copy the complete stereo group")
                                groups.append(dict(bank=bank, slot=write, cursors=pair, sha256=sha256(data).hexdigest()))
                            timeline.append([line, software_irq_pending, cpu.mem_read(application_tick, 1)[0]])
                            if software_irq_pending:
                                software_irq_pending = False
                                deliver_irq(0, idle)
                        require(pc() == idle and cpu.mem_read(application_tick, 1)[0] == (start_count+16)%256 and
                                bytes(cpu.mem_read(request, 4)) == pack("<I", 2) and
                                display[layer+0xC] == lcd_address and bytes(cpu.mem_read(lcd_address, frame_bytes)) == lcd_frame,
                                "unexpected change in startup dialog or timer cadence")
                        require(not request_writes and [v for a, v in wake_checks if a == "0x2013cdf8"] == [0x111]*8 and
                                not any(a in ("0x2013ce04", "0x2013d540") for a, _ in wake_checks),
                                "display line alone unexpectedly finished the pending flip")
                        control_irq = irq_trace[irq_cut:]
                        control_cut = len(irq_trace)
                        first_ack = len(wake_checks)
                        # RZ/A1H section 35.2.1: model the pending GR2 transfer completing at Vsync.
                        update_before = display[layer]
                        display[layer] &= ~0x111
                        display[0xFCFF7A80] = display.get(0xFCFF7A80, 0) | 0x1000
                        deliver_irq(78, idle, stop_at_return=True)
                        require(software_irq_pending, "LCD completion did not make the UI runnable")
                        software_irq_pending = False
                        deliver_irq(0, idle)
                        for hook in hooks:
                            cpu.hook_del(hook)
                        ack = wake_checks[first_ack:]
                        require(update_before == 0x111 and pc() == idle and
                                [a for a, _ in ack] == ["0x2013cdd8", "0x2013cdf8", "0x2013ce04", "0x2013d540"] and
                                ack[1][1] == 0 and request_writes == [["0x2013d614", hex(request), 4, 0]] and
                                bytes(cpu.mem_read(request, 4)) == bytes(4) and
                                bytes(cpu.mem_read(lcd_address, frame_bytes)) == lcd_frame,
                                "the stock UI did not finish the first LCD transfer on Vsync")
                        after["post_lcd"] = dict(timeline=timeline, dma_groups=groups, irq=control_irq,
                                                 ui_request_before_vsync=2, lcd_wake_checks=wake_checks[:first_ack],
                                                 vsync=dict(update_before=update_before, update_seen=ack[1][1],
                                                            ui_request=0, request_writes=request_writes, lcd_wake_checks=ack,
                                                            irq=irq_trace[control_cut:]))
                        if settings_reload:
                            after["post_lcd"]["settings_reload"] = follow_settings_reload(post_lcd_io, idle)
                    if scene_preview is not None:
                        scene_preview.extend((first_png, dialog_png, rendered))
                    return dict(path_program=launch[0], draws=clears.draws[:21], lcd=lcd,
                                first_scene=dict(pc=hex(first_path_pc), checkpoints=dispatch, path_program=launch[1],
                                                 draws=first_draws, surface="0x2094eb00", pitch=-768,
                                                 pixels=[[x, y, hex(p)] for (x, y), p in zip(coordinates, pixels)],
                                                 outline_completion=first_completion, lcd_unchanged=True),
                                dialog=dict(glyph_count=1+len(dialog_paths), paths=dialog_paths,
                                            offscreen_png_sha256=sha256(dialog_png).hexdigest()),
                                composition=dict(copies=clears.copies, images=clears.images, line_events=[],
                                                 stop_pc=hex(pc()), lcd_address=hex(lcd_address),
                                                 dialog_rectangle=[x, y, w, h], nonzero_pixels=nonzero,
                                                 rgb565_sha256=sha256(lcd_frame).hexdigest(),
                                                 png_sha256=sha256(rendered).hexdigest()), **after)

                caller = cpu.reg_read(arm.UC_ARM_REG_LR)
                hook = cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: eeprom_sent.append(c.reg_read(arm.UC_ARM_REG_R0)),
                                    begin=0x2005D788, end=0x2005D788)
                if not eeprom:
                    stop_pc = 0x2005E3F0  # The original code retries at the same branch after each NACK.

                    def stop_after_retries(c, *_):
                        if eeprom_nacks == 4:
                            c.emu_stop()

                    stop = cpu.hook_add(uc.UC_HOOK_CODE, stop_after_retries, begin=stop_pc, end=stop_pc)
                    cpu.emu_start(GPIO_I2C_READ, STOP, count=100_000)
                    cpu.hook_del(stop)
                    cpu.hook_del(hook)
                    require(pc() == stop_pc and eeprom_nacks == 4 and not eeprom_samples and
                            bytes(eeprom_sent) == b"\xa6"*4 and not any(cpu.mem_read(UI_HANDLE, 4)),
                            "EEPROM NACK did not exercise the original retry")
                    eeprom_result = dict(next_pc=hex(stop_pc), nacks=eeprom_nacks, data_bits=eeprom_samples,
                                         guest_tx_bytes=bytes(eeprom_sent).hex())
                    return
                advance(GPIO_I2C_READ, caller, 250_000)
                cpu.hook_del(hook)
                copied = bytes(cpu.mem_read(buffer, size))
                require(copied == eeprom and eeprom_samples == 128 and bytes(eeprom_sent) == b"\xa6\xfe\x40\xa7",
                        "stock EEPROM read did not return intact")
                advance(caller, UI_CREATED)
                eeprom_active = False
                ui, = unpack("<I", cpu.mem_read(UI_HANDLE, 4))
                current, = unpack("<I", cpu.mem_read(0x20381E90, 4))
                require(ui != current and cpu.mem_read(ui+2, 1) == b"\xee" and
                        cpu.mem_read(current+2, 1) == b"\xf4", "stock RTX did not create a separate UI task")
                # Stop before issuing writes to the next unmodeled timer peripheral.
                advance(UI_CREATED, STARTUP_TIMER_WRITE)
                eeprom_result = dict(return_pc=hex(caller), data_bits=eeprom_samples, received=copied.hex(),
                                     guest_tx_bytes=bytes(eeprom_sent).hex(), next_pc=hex(STARTUP_TIMER_WRITE),
                                     ui_created_pc=hex(UI_CREATED), ui_task=hex(ui), current_task=hex(current))
                if startup_dma:
                    dma_wait, dma_isr, dma_status = 0x2011F19C, 0x2011EE90, STARTUP_DMA+0x24
                    advance(STARTUP_TIMER_WRITE, 0x2011F1F4)
                    advance(0x2011F1F4, dma_wait)
                    transfers = []

                    def observe_transfer(resume, size=None):
                        descriptor = tuple(startup_devices[STARTUP_DMA+x] for x in (0, 4, 8))
                        require(pc() == resume and descriptor[:2] == (0x20498B60, GPIO+0x118) and
                                descriptor[2] > 0 and descriptor[2] % 4 == 0 and (size is None or descriptor[2] == size) and
                                startup_devices[dma_status] == 1 and cpu.mem_read(STARTUP_DMA_BUSY, 1) == b"\x01" and
                                unpack("<I", cpu.mem_read(0x204BA014+4*STARTUP_DMA_IRQ, 4))[0] == dma_isr,
                                f"unexpected stock DMA request at {pc():#x}: {descriptor}")
                        transfers.append(dict(source=hex(descriptor[0]), destination=hex(descriptor[1]), size=descriptor[2],
                                              wait_pc=hex(resume), completed=False))

                    def finish_transfer(resume):
                        first_write = len(startup_writes)
                        # shortcut: signal the end without driving GPIO waveforms until board traces are available.
                        startup_devices[dma_status] |= 0x20
                        deliver_irq(STARTUP_DMA_IRQ, resume)
                        require((startup_devices[dma_status], cpu.mem_read(STARTUP_DMA_BUSY, 1)[0]) in ((0, 0), (1, 1)) and
                                any(w[1] == hex(STARTUP_DMA+0x28) and w[3] == 0x62
                                    for w in startup_writes[first_write:]),
                                f"stock DMA ISR did not retire transfer at {resume:#x}: {startup_writes[first_write:]}")
                        transfers[-1]["completed"] = True

                    observe_transfer(dma_wait, 332)
                    if startup_dma == "withheld":
                        first_write = len(startup_writes)
                        cpu.emu_start(dma_wait, STOP, count=5000)
                        require(pc() in range(dma_wait, dma_wait+12, 4) and startup_devices[dma_status] == 1 and
                                cpu.mem_read(STARTUP_DMA_BUSY, 1) == b"\x01" and len(startup_writes) == first_write,
                                "guest left the first wait without a DMA completion")
                    else:
                        finish_transfer(dma_wait)
                        advance(dma_wait, 0x2011F208)
                        observe_transfer(0x2011F208, 204)
                        finish_transfer(0x2011F208)
                        dma_polls = (0x2011F428, 0x2011F534, 0x2011F300, 0x2011F374, 0x2011F270, 0x2011F2AC)

                        def armed_poll(c, *_):
                            if startup_devices[dma_status] == 1:
                                c.emu_stop()

                        hooks = [cpu.hook_add(uc.UC_HOOK_CODE, armed_poll, begin=wait, end=wait) for wait in dma_polls]
                        next_stage = 0x2007B308
                        try:
                            for _ in range(32):
                                if not startup_devices[dma_status] or pc() not in dma_polls:
                                    cpu.emu_start(pc(), next_stage, count=2_000_000)
                                if pc() == next_stage:
                                    break
                                require(pc() in dma_polls, f"no armed DMA poll at {pc():#x}")
                                observe_transfer(pc())
                                finish_transfer(pc())
                            require(pc() == next_stage and not startup_devices[dma_status],
                                    "startup did not reach the end of the GPIO initialization")
                        finally:
                            for hook in hooks:
                                cpu.hook_del(hook)
                        require(unpack("<I", cpu.mem_read(0x20381E90, 4))[0] == current,
                                "unexpected task switch during startup I/O")
                        require([transfer["size"] for transfer in transfers] ==
                                [332, 204] + [108]*6 + [864]*2 + [204]*2,
                                "stock GPIO initialization transfer sequence changed")
                        if rspi_boot:
                            ui_visits = []
                            hook = cpu.hook_add(uc.UC_HOOK_CODE, lambda _c, addr, *_: ui_visits.append(addr),
                                                begin=UI_ENTRY, end=UI_ENTRY)
                            try:
                                advance(next_stage, 0x2007B30C)
                                advance(0x2007B30C, 0x2007B338)
                                advance(0x2007B338, 0x2007B380)
                                advance(0x2007B380, GPIO_I2C_READ)
                                address, dest, size, caller = (cpu.reg_read(reg) for reg in (arm.UC_ARM_REG_R0,
                                                               arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_LR))
                                require((address, size, caller) == (0x550F, 18, 0x2005E528),
                                        "unexpected first startup data read after RSPI setup")
                                sample = bytes.fromhex("9621f3e8017c2df314ab40c5d7698a30be52")
                                eeprom_active = True
                                eeprom_bits = iter((byte >> bit) & 1 for byte in sample for bit in range(7, -1, -1))
                                wire, before = [], eeprom_samples
                                tx = cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: wire.append(c.reg_read(arm.UC_ARM_REG_R0)),
                                                  begin=0x2005D788, end=0x2005D788)
                                try:
                                    advance(GPIO_I2C_READ, caller, 250_000)
                                finally:
                                    eeprom_active = False
                                    cpu.hook_del(tx)
                                data_bits = eeprom_samples-before
                                require(bytes(cpu.mem_read(dest, size)) == sample and data_bits == size*8 and
                                        bytes(wire) == b"\xa0\x55\x0f\xa1",
                                        "stock startup did not copy the next EEPROM sample")
                                advance(caller, GPIO_I2C_READ)
                                next_address, next_size = (cpu.reg_read(reg) for reg in (arm.UC_ARM_REG_R0,
                                                                                       arm.UC_ARM_REG_R2))
                                require((next_address, next_size) == (0x5539, 6), "stock EEPROM page split changed")
                                # Continue the stock scan with an erased fixture for all other board records.
                                read_digest, read_sizes = sha256(), {}
                                entries, tail = [], deque(maxlen=4)
                                config_wait = 0x2011AF7C
                                for count in range(1, 12001):
                                    address2, dest2, size2, caller2 = (cpu.reg_read(reg) for reg in (
                                        arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_LR))
                                    require(0 < size2 <= 64 and (address2 & 63)+size2 <= 64 and caller2 == 0x2005E528,
                                            f"unexpected startup EEPROM continuation at {address2:#x}, {size2}")
                                    eeprom_bits = iter((1,)*(8*size2))
                                    eeprom_active = True
                                    before2 = eeprom_samples
                                    try:
                                        advance(GPIO_I2C_READ, caller2, 250_000)
                                    finally:
                                        eeprom_active = False
                                    require(bytes(cpu.mem_read(dest2, size2)) == b"\xff"*size2 and
                                            eeprom_samples-before2 == 8*size2, "stock EEPROM continuation lost data")
                                    read_digest.update(pack("<IB", address2, size2))
                                    read_sizes[size2] = read_sizes.get(size2, 0)+1
                                    row = [hex(address2), size2]
                                    if count <= 4:
                                        entries.append(row)
                                    tail.append(row)
                                    advance(caller2, GPIO_I2C_READ, alternate=config_wait)
                                    if pc() == config_wait:
                                        break
                                require(pc() == config_wait and cpu.mem_read(0x20380B58, 1)[0],
                                        "stock did not enter the post-scan hardware wait")
                                config_snapshot = dict(pc=hex(config_wait), pending=cpu.mem_read(0x20380B58, 1)[0],
                                                       dma_status=startup_devices[dma_status],
                                                       dma_busy=cpu.mem_read(STARTUP_DMA_BUSY, 1)[0],
                                                       last_dma_size=startup_devices[STARTUP_DMA+8])
                                cpu.emu_start(config_wait, STOP, count=5000)
                                require(pc() in range(config_wait, config_wait+12, 4) and
                                        cpu.mem_read(0x20380B58, 1)[0] == config_snapshot["pending"],
                                        "stock left the post-scan wait without a hardware event")
                                if queue_boot:
                                    def getbyte(addr):
                                        return cpu.mem_read(addr, 1)[0]

                                    def irq_enabled(irq):
                                        return bool(stored.get(GICD+0x100+4*(irq//32), 0) & 1 << (irq % 32))
                                    def irq_handler(irq):
                                        return unpack("<I", cpu.mem_read(0x204BA014+4*irq, 4))[0]
                                    ring = 0x204988E0
                                    head, tail_slot = getbyte(ring+0x251), getbyte(ring+0x250)
                                    require(head < 74 and tail_slot < 74, "stock board queue has invalid indices")
                                    config_snapshot.update(command_queue=dict(head=head, tail=tail_slot,
                                                           type=getbyte(ring+head*8), payload=cpu.mem_read(ring+head*8+4, 4).hex(),
                                                           spi_state=getbyte(0x20380B26),
                                                           irq={str(i): [irq_enabled(i), hex(irq_handler(i))] for i in (51,162,280,521)}))
                                    events = []
                                    require((getbyte(0x20380B26), irq_handler(BOARD_TIMER_IRQ), irq_handler(BOARD_RSPI_IRQ)) ==
                                            (1, 0x20118D84, 0x20119058), "unexpected initial board queue state")
                                    def board_event(response=bytes(4)):
                                        state = getbyte(0x20380B26)
                                        consumed = getbyte(ring+0x251)
                                        new_bytes = len(board_spi_tx)
                                        if state in (1, 3, 5):
                                            irq = BOARD_TIMER_IRQ
                                            stored[MTU2+0x22D] = stored.get(MTU2+0x22D, 0) | 8
                                        elif state in (2, 4, 6):
                                            irq = BOARD_RSPI_IRQ
                                            board_spi_rx.extend(response)
                                        else:
                                            require(startup_devices[dma_status] == 1, f"queue stalled in SPI state {state}")
                                            irq = STARTUP_DMA_IRQ
                                            startup_devices[dma_status] |= 0x20
                                        deliver_irq(irq, pc())
                                        require(not board_spi_rx, "stock board interrupt did not drain RX FIFO")
                                        return dict(irq=irq, state_before=state, state_after=getbyte(0x20380B26),
                                                    head_before=consumed, head_after=getbyte(ring+0x251),
                                                    sent=bytes(board_spi_tx[new_bytes:]).hex())

                                    for turn in range(128):
                                        if not getbyte(0x20380B58):
                                            break
                                        events.append(board_event())
                                        if turn == 0:
                                            cpu.emu_start(pc(), STOP, count=5000)
                                            require(pc() in range(config_wait, config_wait+12, 4) and
                                                    getbyte(0x20380B58) == 1 and getbyte(0x20380B26) == 2 and
                                                    getbyte(ring+0x251) == head,
                                                    "timer alone incorrectly advanced the stock board queue")
                                            config_snapshot["timer_without_rx_stop_pc"] = hex(pc())
                                    require(not getbyte(0x20380B58) and getbyte(ring+0x251) == getbyte(ring+0x250),
                                            "stock board did not drain its commands")
                                    require([event["irq"] for event in events] == [BOARD_TIMER_IRQ, BOARD_RSPI_IRQ]*27 and
                                            events[1]["head_after"] == head+1, "stock timer/receive sequence changed")
                                    advance(pc(), 0x2007B3E8)
                                    config_snapshot.update(events=events, queue_drained=True, next_pc=hex(pc()))
                                    advance(pc(), 0x201194F4)
                                    require(getbyte(0x20380B58) == 1 and getbyte(0x20380B26) == 1 and
                                            irq_enabled(BOARD_TIMER_IRQ), "stock did not arm the next board request")
                                    command, = unpack("<I", cpu.mem_read(0x20380B34, 4))
                                    require(command >> 24 == 0xE0, f"unexpected next board command {command:#x}")
                                    config_snapshot["next_board_request"] = dict(pc=hex(pc()), word=hex(command),
                                                                                 irq=BOARD_TIMER_IRQ)
                                    if startup_dma == "reply" or audio_boot:
                                        version_poll, readback_poll, version_parser = 0x201194F4, 0x20119514, 0x20119478
                                        response_flag = 0x204987B1
                                        readbacks = []
                                        for index, command_byte in enumerate((2, 3, 0, 1, 4, 5)):
                                            sent = board_event()
                                            require(sent["sent"] == f"e00000{command_byte:02x}", "unexpected stock query order")
                                            require(board_event()["irq"] == BOARD_RSPI_IRQ and not getbyte(0x20380B58),
                                                    "stock query did not complete")
                                            advance(pc(), readback_poll)
                                            if not index:
                                                no_ready = [board_event(), board_event(), board_event()]
                                                require([row["state_after"] for row in no_ready] == [4, 5, 0] and
                                                        not getbyte(response_flag) and not getbyte(0x20380B58),
                                                        "stock companion-ready control did not take its no-data branch")
                                                advance(pc(), 0x20119520)
                                                advance(pc(), readback_poll, alternate=version_parser)
                                                require(pc() == readback_poll, "stock parsed a response without ready")
                                                readbacks.append(dict(query=sent["sent"], result="retry_without_ready",
                                                                      events=no_ready))
                                            packets = (bytes.fromhex("00313233"), bytes.fromhex("f0313233")) if not index else (
                                                bytes.fromhex("f0313233"),)
                                            for response in packets:
                                                board_reply_ready = True
                                                try:
                                                    trace = [board_event(), board_event(), board_event(), board_event(response)]
                                                finally:
                                                    board_reply_ready = False
                                                require([(row["irq"], row["state_before"]) for row in trace] == [
                                                    (BOARD_TIMER_IRQ, 3), (BOARD_RSPI_IRQ, 4),
                                                    (BOARD_TIMER_IRQ, 5), (BOARD_RSPI_IRQ, 6)] and
                                                    not getbyte(0x20380B58), "stock response polling sequence changed")
                                                accepted = response[0] == 0xF0
                                                require(getbyte(response_flag) == int(accepted), "stock response flag mismatch")
                                                advance(pc(), 0x20119520)
                                                if not accepted:
                                                    advance(pc(), readback_poll, alternate=version_parser)
                                                    require(pc() == readback_poll, "stock firmware parsed a rejected response")
                                                    readbacks.append(dict(query=sent["sent"], response=response.hex(), result="retry"))
                                                    continue
                                                advance(pc(), version_parser)
                                                b, word, target = (cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0,
                                                                    arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))
                                                ret = cpu.reg_read(arm.UC_ARM_REG_LR)
                                                require(word == int.from_bytes(response, "big") and b in (0, 1),
                                                        "stock formatter did not receive the original response")
                                                advance(version_parser, ret)
                                                rendered = bytes(cpu.mem_read(target+6*b, 6))
                                                require(rendered == b"1.2300", f"stock version field differed: {rendered!r}")
                                                readbacks.append(dict(query=sent["sent"], response=response.hex(),
                                                                      result="formatted", output=rendered.decode("ascii")))
                                            if index != 5:
                                                advance(pc(), version_poll)
                                        advance(pc(), 0x2007B3F4)
                                        config_snapshot["readbacks"] = readbacks
                                        if audio_boot:
                                            audio_stage = True
                                            # Held-low control: original polls the second checkpoint repeatedly.
                                            frame_levels = iter((0, 0, 0))
                                            def no_edges(c, *_):
                                                if len(frame_reads) == 3:
                                                    c.emu_stop()

                                            poll_hook = cpu.hook_add(uc.UC_HOOK_CODE, no_edges,
                                                                     begin=AUDIO_FRAME_POLLS[1], end=AUDIO_FRAME_POLLS[1])
                                            try:
                                                cpu.emu_start(pc(), STOP, count=400_000)
                                            finally:
                                                cpu.hook_del(poll_hook)
                                            require(pc() == AUDIO_FRAME_POLLS[1] and frame_reads ==
                                                    [[hex(a), 0] for a in (AUDIO_FRAME_POLLS[0], AUDIO_FRAME_POLLS[1],
                                                                         AUDIO_FRAME_POLLS[1])], "stock did not wait for audio clock")
                                            def enable_writes(base):
                                                return [row[-1] for row in audio_trace if row[0] == "write" and
                                                        row[2] == hex(base+0x28)]

                                            require(all(enable_writes(base) == [8] for base in AUDIO_DMAC),
                                                    "stock DMA enabled while audio clock was held low")
                                            # Supply only the word-select pin transitions, not the audio state or PC.
                                            frame_levels = iter((0x200, 0)*4 + (0x200,))
                                            advance(pc(), 0x2007B43C)
                                            require(all(enable_writes(base) == [8, 1] for base in AUDIO_DMAC),
                                                    "stock DMA did not enable after the frame edges")
                                            channels = [tuple(audio_regs[base+off] for off in (0, 4, 8, 0xC, 0x10, 0x14))
                                                        for base in AUDIO_DMAC]
                                            require(channels == [(0xE820B01C, 0x20400800, 288, 0xE820B01C, 0x20400920, 288),
                                                                 (0x20400A40, 0xE820B018, 288, 0x20400B60, 0xE820B018, 288),
                                                                 (0xE820C81C, 0x20400C80, 288, 0xE820C81C, 0x20400DA0, 288),
                                                                 (0xE820D81C, 0x20400EC0, 288, 0xE820D81C, 0x20400FE0, 288)],
                                                    "stock DMA descriptors diverged from the audio replay")
                                            eeprom_result["audio_start"] = dict(wait_pc=hex(AUDIO_FRAME_POLLS[1]),
                                                return_pc=hex(pc()), pin_reads=frame_reads, mmio=audio_trace,
                                                dma_descriptors=[[hex(base), *(hex(v) for v in row)]
                                                                 for base, row in zip(AUDIO_DMAC, channels)])
                                            if record_test:
                                                advance(pc(), GPIO_I2C_READ)
                                                record_reads = []
                                                for i, address_field in enumerate((0x1FFC0, 0x3FFC0)):
                                                    expected_record = bytes(cpu.mem_read(EEPROM_VERSION+64*i, 64))
                                                    payload = expected_record
                                                    if i == 1 and startup_dma == "records-differ":
                                                        payload = payload[:-1]+bytes((payload[-1] ^ 1,))
                                                    record_reads.append(read_record(address_field, 64, payload))
                                                    record_reads[-1]["expected_sha256"] = sha256(expected_record).hexdigest()
                                                    advance(pc(), GPIO_I2C_READ if i == 0 else EEPROM_VERSION_COMPARE)
                                                expected_match = startup_dma != "records-differ"
                                                compare = unpack("<i", pack("<I", cpu.reg_read(arm.UC_ARM_REG_R0)))[0]
                                                require(compare == (0 if expected_match else -1),
                                                        f"unexpected EEPROM compare: {compare}")
                                                branch = 0x2007B4A0 if expected_match else 0x2007B458
                                                advance(pc(), branch)
                                                following = []
                                                if expected_match:
                                                    for field, width in ((0x1FE80, 64), (0x3FE80, 64), (0x1FEC0, 64),
                                                                         (0x3FEC0, 64), (0x1FF00, 64), (0x3FF00, 64),
                                                                         (0x1FF40, 20), (0x3FD9C, 1)):
                                                        advance(pc(), GPIO_I2C_READ)
                                                        following.append(read_record(field, width, b"\xff"*width))
                                                    advance(pc(), 0x2005BCD4)  # Next use of the hardware RIIC0 bus.
                                                eeprom_result["version_records"] = dict(reads=record_reads, compare=compare,
                                                    branch=hex(branch), following_reads=following, stop_pc=hex(pc()))
                                                if riic_read_sample is not None:
                                                    eeprom_result["riic_read"] = read_riic_record(riic_read_sample)
                                                if format_test:
                                                    eeprom_result["format_record"] = read_format_record(startup_dma != "format-blank")
                            finally:
                                cpu.hook_del(hook)
                            require(stored[STARTUP_RSPI3] == stored[STARTUP_RSPI0] == 8 and
                                    (stored[STARTUP_RSPI3+0x10], stored[STARTUP_RSPI0+0x10]) == (0xE70C, 0xE78C) and
                                    (set(ui_visits) == {UI_ENTRY} if settings_test or current_format else not ui_visits and
                                     unpack("<I", cpu.mem_read(0x20381E90, 4))[0] == current),
                                    f"stock startup RSPI configuration or task owner changed: {ui_visits=}")
                            eeprom_result.update(rspi_config={"0": "0xe78c", "3": "0xe70c"}, ui_entry_observed=bool(ui_visits),
                                                 post_rspi_gpio_read=dict(address_field=hex(address), size=size,
                                                                         return_pc=hex(caller), buffer=hex(dest),
                                                                         data_bits=data_bits,
                                                                         received=sample.hex(),
                                                                         guest_tx_bytes=bytes(wire).hex()),
                                                 continuation_reads=dict(count=count, bytes=sum(n*k for n,k in read_sizes.items()),
                                                                         first=entries, last=list(tail),
                                                                         address_size_sha256=read_digest.hexdigest()),
                                                 config_wait=config_snapshot)
                    eeprom_result.update(next_pc=hex(pc()), startup_writes=startup_writes, dma_irq=STARTUP_DMA_IRQ,
                                         dma_handler=hex(dma_isr), completion_control=startup_dma, transfers=transfers)

    cpu.mmio_map(GICC, 0x1000,
                 lambda _, off, width, _data: gicc_io("read", off, width), None,
                 lambda _, off, width, value, _data: gicc_io("write", off, width, value), None)
    cpu.hook_add(uc.UC_HOOK_INTR, exception)
    cpu.hook_add(uc.UC_HOOK_MEM_INVALID, missing)
    cpu.hook_add(uc.UC_HOOK_MEM_WRITE, note_flag, begin=RESOURCE_FLAG, end=RESOURCE_FLAG)
    cpu.hook_add(uc.UC_HOOK_MEM_WRITE, note_font, begin=FONT_TABLE+4, end=FONT_TABLE+19)
    for addr, note in ((RESOURCE_ENTRY, note_call), (TASK_RETURN, note_return), (BOARD_INIT, board)):
        cpu.hook_add(uc.UC_HOOK_CODE, note, begin=addr, end=addr)
    if loader is not None:
        require(len(loader) == 0x9BC and not fixture_return and
                (adc_sample is None or 0 <= adc_sample <= 1023), "invalid board fixture")
        if not startup_from_nor:
            cpu.mem_write(0x20004000, loader)
        cpu.hook_add(uc.UC_HOOK_MEM_READ, read_boot_flag, begin=0x20004F20, end=0x20004F20)
        if wake_test:
            for addr in (0x2007BAD0, 0x2007BAE4, RIIC0_BUSY_INSN, RIIC0_WAIT_INSN):
                cpu.hook_add(uc.UC_HOOK_CODE, wake_boundary, begin=addr, end=addr)
        board_pages = (0xFCFE3000, 0xFCFE7000, 0xFCFF1000, 0xFCFEE000)
        if adc_sample is not None:
            board_pages += (0xE8005000,)
        if scif_wait is not None:
            require(adc_sample is not None and (irq_test or scif_wait in ("no_compare", "timeout")),
                    "invalid serial test mode")
            board_pages += (0xE8008000, 0xFCFE1000)
            if startup_input:
                board_pages += (0xE8009000,)
            boundaries = (0x20120FE0, 0x20121CF4, 0x201208BC, 0x2012096C, 0x20120B80, 0x20121D54)
            if irq_test:
                # Minimum interrupt table bound in this fixture. The guest still registers its handlers.
                if not board_full:
                    cpu.mem_write(0x20380C30, pack("<I", 236))
                boundaries += (BASE+0x18, 0x200051C8, 0x20120658, 0x20005284, 0x20121D60,
                               0x20120BC8, 0x20120CAC, 0x20120DCC)
            if board_full:
                boundaries += (0x20121DF4, 0x2007BE78, 0x2007BEF8, 0x2007BF08, 0x2007C318, 0x2007B858,
                               0x200788E0, 0x2007814C, 0x20078520,
                               0x2007C31C, 0x20098394, 0x201254B0, 0x20078A74, 0x2007D0CC, 0x2007C1AC, 0x2007C27C)
                cpu.hook_add(uc.UC_HOOK_BLOCK, lambda _c, addr, _size, _: recent_blocks.append(hex(addr)))
                board_pages += (0xE8010000, 0xE8207000, 0xFCFEF000, 0xE800C000, 0x3FEFA000, 0x3FFFF000)
                if rspi_boot:
                    board_pages += (STARTUP_RSPI3,)
                if audio_boot:
                    board_pages += (0xE8209000, 0xE820B000, 0xE820C000, 0xE820D000)
                def keep_flat_mapping(_c, _addr, _size, _):
                    # This fixture supplies physical-address MMIO and does not install the guest page tables.
                    cpu.reg_write(arm.UC_ARM_REG_R0, cpu.reg_read(arm.UC_ARM_REG_R0) & ~1)
                if not stock_mmu:
                    cpu.hook_add(uc.UC_HOOK_CODE, keep_flat_mapping, begin=0x20125560, end=0x20125560)
            for addr in boundaries:
                cpu.hook_add(uc.UC_HOOK_CODE, serial_boundary, begin=addr, end=addr)
        for page in dict.fromkeys(board_pages):
            cpu.mmio_map(page, 0x1000,
                         lambda _c, off, width, base: board_io("read", base+off, width, 0), page,
                         lambda _c, off, width, val, base: board_io("write", base+off, width, val), page)
    if not startup_from_nor:
        cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x13)
        cpu.reg_write(arm.UC_ARM_REG_SP, SP-0x1000)
        cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)
        cpu.reg_write(arm.UC_ARM_REG_SP, SP)
    hardware_stop = 0x2011D514 if loader is None else 0x201184E4
    fault_address = GPIO+12 if loader is None else ADC_STATUS
    if adc_sample is not None:
        hardware_stop, fault_address = 0x20120DFC, SCIF3_SPTR
    wait_pc = 0x20121D54
    if scif_wait is not None:
        hardware_stop = {"no_compare": 0x201208BC, "rx_frame": 0x20121D60,
                         "board_power": 0x20078520 if vbus_high else 0x2007814C}.get(scif_wait, wait_pc)
    with resource_peripherals(cpu, 0, board_io if loader is not None else None, track_board_irqs=board_full) as mmio:
        try:
            if wake_test and not startup_from_nor:
                cpu.emu_start(0x20004848, 0x20004914, count=8_000_000)
                require(pc() == 0x20004914, f"loader stopped before its handoff at {pc():#x}")
                wake_handoff = cpu.mem_read(0x20004F20, 1)[0]
                latches_after_loader = stored[DSFR]
                loader_latch = stored.get(POWER_LATCH, 0)
            if board_full and not stock_mmu:
                # The firmware scatter table copies this initialized data before creating its first task.
                call(cpu, 0x200052ED, 0x20367B78, 0x20380000, 0x1F44)
                cpu.mem_write(RESOURCE_FLAG, b"\xa5")
            if stock_mmu:
                if not startup_from_nor:
                    cpu.reg_write(arm.UC_ARM_REG_CPSR, 0xD3)
                for checkpoint in (0x200052A0, 0x200052A8, 0x20125568, wait_pc):
                    cpu.hook_add(uc.UC_HOOK_CODE, mapping_state, begin=checkpoint, end=checkpoint)
                cpu.emu_start(BASE if startup_from_nor else 0x20005060, STOP, timeout=8_000_000, count=8_000_000)
            else:
                cpu.emu_start(0x200052A8 if board_full else RESOURCE_TASK, STOP, timeout=4_000_000, count=1_000_000)
            if irq_test and not (wake_test and pc() == wake_stop):
                require(unpack("<I", cpu.mem_read(0x204BA014+4*161, 4))[0] == 0x20120658 and
                        stored[MTU2+0x228] == 1600 and irq_state() ==
                        {"pc": hex(wait_pc), "scif_scr": 0, "busy": 2},
                        f"timer not configured by the guest: {irq_state()} {mapping_checkpoints=} {scif_boundaries[-8:]=}")
                irq_checkpoints.append(irq_state())
                stored[MTU2+0x22D] |= 4
                deliver_irq(161, wait_pc)
                require(irq_state() == {"pc": hex(wait_pc), "scif_scr": 0x50, "busy": 2} and
                        not stored[MTU2+0x22D] & 4 and
                        not stored[GICD+0x114] & 2,
                        f"timer IRQ: {irq_state()=} "
                        f"SCR={stored[SCIF3+8]:#x} TSR={stored[MTU2+0x22D]:#x} "
                        f"enabled={stored[GICD+0x114]:#x} {irq_trace=} {scif_boundaries=}")
                irq_checkpoints.append(irq_state())
                if rx_test:
                    require(unpack("<I", cpu.mem_read(0x204BA014+4*235, 4))[0] == 0x20120BC8,
                            "RX interrupt handler was not registered by the guest")
                    # Synthetic parser controls, with the same byte count and only the last byte changed.
                    rx_fifo.extend(bytes((0xFC, 0, 0x39, 0xFE if complete else 0)))
                    stored[SCIF3+0x10] |= 2
                    deliver_irq(235, wait_pc)
                    require(not rx_fifo and not stored[SCIF3+0x10] & 2, "guest did not consume the test bytes")
                    irq_checkpoints.append(irq_state())
                cpu.emu_start(wait_pc, STOP, timeout=5_000_000 if board_full else 1_000_000,
                              count=3_000_000 if board_full else 20_000)
                if board_full:
                    while pc() in (0x201254B0, 0x20078A74, 0x2007D0CC) and rtx_ticks + software_irqs < 1024:
                        resume = pc()
                        if resume == 0x20078A74:
                            require(unpack("<I", cpu.mem_read(0x204BA014+4*159, 4))[0] == 0x20005C48,
                                    "MTU2 application tick handler was not registered by the guest")
                            if cpu.mem_read(0x203808D0, 1)[0] < 35 and app_ticks < 16_000:
                                app_ticks += 1
                                stored[MTU2+0x22D] |= 1
                                deliver_irq(159, resume)
                            else:
                                require(app_ticks < 16_000, "MTU2 application tick did not reach the startup threshold")
                                release_boundary = resume
                                cpu.emu_start(resume, STOP, timeout=1_000_000, count=1_000_000)
                                release_boundary = None
                        elif resume == 0x2007D0CC:
                            require(stored.get(GICD+0x114, 0) & 2,
                                    f"later SCIF wait without timer IRQ armed: {irq_state()} {board_trace[-25:]}")
                            stored[MTU2+0x22D] |= 4
                            deliver_irq(161, resume)
                            if irq_state()["busy"] == 2:
                                rx_fifo.extend(b"\xfc\0\x39\xfe")
                                stored[SCIF3+0x10] |= 2
                                deliver_irq(235, resume)
                            require(irq_state()["busy"] == 0, f"later SCIF wait did not clear: {irq_state()}")
                            release_boundary = resume
                            cpu.emu_start(resume, STOP, count=1_000_000)
                            release_boundary = None
                        elif software_irq_pending:
                            software_irq_pending = False
                            software_irqs += 1
                            deliver_irq(0, 0x201254B0)
                        else:
                            require(stored.get(0xFCFEC014) == 1 and stored.get(0xFCFEC000, 0) > 0,
                                    "RTX tick timer was not started by the guest")
                            rtx_ticks += 1
                            deliver_irq(134, 0x201254B0)
            if riic0_finish is not None:
                require(pc() == RIIC0_WAIT_INSN, f"did not reach RIIC0 wait: {pc():#x}")
                finish_riic_transfer()
        except uc.UcError as exc:
            require(not fixture_return and exc.errno == uc.UC_ERR_READ_UNMAPPED and
                    faults == [[uc.UC_MEM_READ_UNMAPPED, hex(hardware_stop), hex(fault_address), 2]],
                    f"unexpected task stop at {pc():#x}: {exc}, {faults}; {scif_boundaries[-13:]=} {list(recent_blocks)=}")
            # The expected board read is outside the shared font peripheral fixture.
            mmio_fault_handled = True
        else:
            mmio_fault_handled = False
    expected = tuple(word for addr, data in records for word in (addr+4, len(data)))
    require(unpack("<4I", cpu.mem_read(FONT_TABLE+4, 16)) == expected and
            [write[0] for write in writes] == [1]*4 and [write[-1] for write in writes] == list(expected) and
            flags == ([["0x20098348", 0], ["0x20098394", 1]] if second_pass else [["0x20098348", 0]]) and
            calls == ([0, 1] if second_pass else [0]) and returns == ([4, 4] if second_pass else [4]) and
            pc() == (int(eeprom_result["next_pc"], 16) if eeprom_result else GPIO_I2C_READ if riic_return else
                     wake_stop if power_key_released is False else
                     TASK_RETURN if fixture_return else hardware_stop) and
            mmio_fault_handled == (not fixture_return and scif_wait is None) and
            (len(mmio) >= 60 if loader is not None else len(mmio) == (120 if fixture_return else 60)) and
            pmr == (0xFF if stock_mmu else 0xF0) and
            (not stock_mmu or ["write", "0x20124574", 0xFF] in pmr_trace) and
            (len(svc) > 1 if board_full else len(svc) == 1) and len(board_calls) == 1,
            f"unexpected resource task lifecycle at {pc():#x}: {flags=} {calls=} {returns=} {pmr=:#x} {faults=} "
            f"{writes=} {scif_boundaries[-24:]=} {board_trace[-8:]=} {rtx_ticks=} {software_irqs=} "
            f"{len(svc)=} {list(recent_blocks)=} {board_checkpoints=}")
    result = {"entry": hex(RESOURCE_TASK), "stop_pc": hex(pc()), "svc": svc, "gicc_pmr": pmr_trace,
            "board_init": hex(BOARD_INIT), "board_return_fixture": fixture_return,
            "resource_entry_flags": calls, "task_flag_writes": flags, "font_table_writes": writes,
            "writes_at_each_return": returns, "faults": faults, "resource_mmio_count": len(mmio)}
    mapping_evidence = {}
    if stock_mmu:
        mapping_state(cpu, pc(), 0, None)
        require(any(int(row["sctlr"], 16) & 1 for row in mapping_checkpoints[:-1]) and cpr(1) & 1,
                "the stock reset did not keep its own MMU enabled")
        mapping_evidence = {"stock_mapping": mapping_checkpoints}
        result.update(mapping_evidence)
    if wake_test:
        latch_writes = [row for row in board_trace if row[0] == "write" and row[2] == hex(POWER_LATCH)]
        bus_stop = power_key_released is False
        bus_trace = [row for row in board_trace if row[2] == hex(RIIC0_ICCR2) or row[1] == "0x2005bc6c"]
        bus_path = [hex(RIIC0_BUSY_INSN)] if bus_stop else []
        expected_bus = []
        request = None
        if riic0_idle:
            bus_path.append(hex(RIIC0_WAIT_INSN))
            expected_bus = [["read", hex(RIIC0_BUSY_INSN), hex(RIIC0_ICCR2), 1, 0],
                            ["write", "0x2005bc6c", "0xfcfee01c", 1, 20],
                            ["write", "0x2005bc74", hex(RIIC0_ICCR2), 1, 2]]
            request = first_riic_request if riic0_finish is not None else riic_descriptor()
            require(request["pending"] == {"stop": 0, "no_stop": 6, None: 1}[riic0_finish] and
                    request["bytes"] == "8000", f"unexpected RIIC0 request: {request}")
            if riic0_finish is not None:
                expected_bus.append(["write", "0x2005bad0", hex(RIIC0_ICCR2), 1, 8])
        require(wake_handoff == 1 and latches_after_loader == 0x0400 and
                key_polls == (1 if power_key_released else 0x4E000) and
                bool(loader_latch & 8) == bus_stop and
                wake_path == ["0x2007bad0", "0x2007bae4"] + bus_path and
                boot_reads == [["0x20004990", "0x20004f20", 1]]*2 and
                board_checkpoints[:2] == ["0x20121df4", "0x2007be78"] and
                ("0x20078520" in board_checkpoints) == power_key_released and
                "0x20098394" not in board_checkpoints and
                bus_trace == expected_bus,
                f"unexpected power-key outcome: {wake_handoff=} {latches_after_loader=:#x} {key_polls=} "
                f"{wake_path=} {loader_latch=:#x} {latch_writes=} {board_checkpoints=}")
        return {**mapping_evidence, **({"eeprom": eeprom_result} if eeprom_result else {}),
                **({"nor_boot": nor_boot} if nor_boot else {}),
                "p8_7": int(power_key_released), "key_polls": key_polls, "wake_latches": "0x8400",
                "loader_handoff": wake_handoff, "latches_after_loader": hex(latches_after_loader),
                "p10_3_after_loader": int(bool(loader_latch & 8)),
                "p10_3_writes": latch_writes, "main_handoff_reads": boot_reads, "wake_path": wake_path,
                "board_checkpoints": board_checkpoints, "stop_pc": hex(pc()), "board_return_observed": False,
                "riic0_mmio": bus_trace, "riic0_request": request, "riic0_steps": riic_steps,
                "riic0_return_pc": hex(riic_return) if riic_return is not None else None,
                "gpio_read_request": followup_read,
                "outcome": ("ui_task_created" if "ui_task" in eeprom_result else "eeprom_nack_retry") if eeprom_result else
                           "riic0_returned_to_caller" if riic_return else
                           "waiting_for_riic0_completion" if riic0_idle else
                           "before_riic0_iccr2_read" if bus_stop else "standby_wait"}
    if loader is not None:
        boot_read = ["0x20004990", "0x20004f20", 0]
        require(boot_reads == [boot_read] or board_full and boot_reads == [boot_read, boot_read],
                f"unexpected boot guard reads: {boot_reads}")
        require(
                any(row[:4] == ["read", "0x2011d514", "0xfcfe300c", 2] for row in board_trace) and
                any(row[2] == "0xfcfec404" and row[-1] > 0 for row in board_trace), "missing board startup checkpoints")
        result.update(boot_reads=boot_reads, board_mmio=board_trace)
    if adc_sample is not None:
        require(any(row[0] == "read" and row[2] in ("0xe800580c", "0xe800580e") and row[-1] == adc_sample << 6
                    for row in board_trace), "missing completed ADC result")
        result["adc_sample"] = adc_sample
    if scif_wait is not None:
        serial_trace = [row for row in board_trace if SCIF3 <= int(row[2], 16) < SCIF3+0x40]
        busy = cpu.mem_read(0x2049953C, 1)[0]
        received = bytes(row[-1] for row in serial_trace if int(row[2], 16)-SCIF3 == 0x14)
        frame = b"\xfc\0\x39\xfe" if complete else b"\xfc\0\x39\0" if rx_test else b""
        require("0x20121cf4" in scif_boundaries and not faults and
                all(int(row[2], 16)-SCIF3 != 0xC for row in serial_trace) and
                received == frame * (2 if board_full and not vbus_high else 1) and
                busy == (0 if complete else 1 if scif_wait == "no_compare" else 2) and
                (timer_polls >= 5 if board_full else timer_polls == (4 if scif_wait == "no_compare" else 5)) and
                ("0x20120b80" in scif_boundaries) == (scif_wait != "no_compare"),
                f"unexpected SCIF3 startup: {busy=} {timer_polls=} {scif_boundaries=}")
        result.update(scif_control=scif_wait, scif3_mmio=serial_trace, scif3_busy=busy,
                      scif_boundaries=scif_boundaries, timer_polls=timer_polls)
        if irq_test:
            handshakes = [[kind, address, register, irq_id] for irq_id in ((161, 235) if rx_test else (161,))
                                  for kind, address, register in (("read", "0x200051f8", "0xe8202018"),
                                                                 ("read", "0x200051fc", "0xe820200c"),
                                                                 ("write", "0x20005264", "0xe8202010"))]
            require((irq_trace[:len(handshakes)] if board_full else irq_trace) == handshakes and
                    all(hex(addr) in scif_boundaries for addr in (BASE+0x18, 0x20120658, 0x20005284)) and
                    ("0x20120bc8" in scif_boundaries) == rx_test and
                    all((hex(addr) in scif_boundaries) == complete for addr in (0x20120CAC, 0x20120DCC, 0x20121D60)) and
                    scif_boundaries.count("0x20121d54") == (2 if complete else 4) and
                    (not complete or board_full or cpu.mem_read(0x20499553, 1)[0] == 0x39),
                    f"unexpected interrupt trace: {irq_trace} {scif_boundaries}")
            result.update(irq_gicc=irq_trace, irq_checkpoints=irq_checkpoints, rx_bytes=received.hex())
        if board_full:
            require(board_checkpoints[:2] == ["0x20121df4", "0x2007be78"] and
                    ("0x2007c318" in board_checkpoints) == (not vbus_high) and
                    ("0x2007b858" in board_checkpoints) == (not vbus_high) and
                    board_checkpoints[-2:] == ["0x200788e0", hex(hardware_stop)] and
                    not any(addr in board_checkpoints for addr in ("0x2007c31c", "0x20098394")) and
                    boot_modes == [["0x2007c1ac", 2], ["0x2007c27c", 2 if vbus_high else 3]] and
                    power_checks == [[0, "0x2038041f", int(not vbus_high)]],
                    f"unexpected board outcome: {board_checkpoints=} {boot_modes=} {power_checks=}")
            acknowledged = [row[-1] for row in irq_trace if row[0] == "write"]
            require((rtx_ticks, software_irqs, app_ticks) == ((0, 0, 0) if vbus_high else (2, 1, 14000)),
                    "unexpected number of modeled events")
            require(acknowledged == ([161, 235] if vbus_high else [161, 235, 134, 0, 134] + [159]*app_ticks + [161, 235])
                    and len(irq_trace) % 3 == 0 and all(
                irq_trace[i:i+3] == [["read", "0x200051f8", hex(GICC+0x18), irq_id],
                                      ["read", "0x200051fc", hex(GICC+0x0C), irq_id],
                                      ["write", {0: "0x20005948", 134: "0x200059ac"}.get(irq_id, "0x20005264"),
                                       hex(GICC+0x10), irq_id]]
                for i in range(0, len(irq_trace), 3) for irq_id in (irq_trace[i][-1],)), "GIC IRQ did not complete")
            outcome = "standby_wait" if vbus_high else "watchdog_reset_entry"
            result.update(board_checkpoints=board_checkpoints, vbus_p3_9=int(vbus_high), outcome=outcome,
                          boot_modes=boot_modes,
                          power_checks=power_checks, rtx_ticks=rtx_ticks, software_irqs=software_irqs,
                          app_ticks=app_ticks, board_return_observed=False, board_flag=flags[-1][-1])
    return result


def replay(main, profile, large, small, *, alternate, output, continuous=False):
    cpu = machine(main)
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    records = map_font_records(cpu, large, small)
    surface = TextSurface(cpu, 480, 272)

    # Both fixtures use the same matching tag; only the large font record differs.
    if continuous:
        resource = replay_resource_entry(cpu, records, 0, EXPECTED_TAG)
    else:
        resource = replay_resource_branch(cpu, records, 0, EXPECTED_TAG)
    words = unpack("<4I", cpu.mem_read(FONT_TABLE+4, 16))

    faces, draw_entries = [], []
    test_run = False
    buffer = SCRATCH+0x400

    def memory_face(_cpu, _pc, _size, _data):
        faces.append((surface.reg("R1"), surface.reg("R2"), surface.reg("R3")))

    def draw_entry(cpu, _pc, _size, _data):
        slot, text, count = (surface.reg(reg) for reg in ("R0", "R1", "R2"))
        draw_entries.append((slot, bytes(cpu.mem_read(text, count*2)).decode("utf-16le")))
        if test_run:
            require(count == len(TEST_TEXT), "unexpected diagnostic run length")
            cpu.reg_write(arm.UC_ARM_REG_R1, buffer)

    cpu.hook_add(uc.UC_HOOK_CODE, memory_face, begin=MEMORY_FACE, end=MEMORY_FACE)
    cpu.hook_add(uc.UC_HOOK_CODE, draw_entry, begin=DRAW_RUN, end=DRAW_RUN)
    call(cpu, UI_FONT_INIT, instruction_limit=5_000_000)
    require(faces == [(words[2*i], words[2*i+1], 0) for i in (0, 1, 1, 1, 0)], "unexpected FreeType inputs")
    require(not surface.events and not draw_entries, "unexpected draw during font initialization")

    # Call the same menu row with both fonts; no change to its source text or conversion.
    cpu.mem_write(SCRATCH+12, pack("<BxH", 2, 0xA7))
    call(cpu, profile.draw_row, SCRATCH, 0, 1, 0, instruction_limit=2_000_000)
    require(len(surface.events) == len(draw_entries) == 1, "missing stock row draw")
    slot, text = draw_entries[0]
    require(text == STOCK_TEXT, "stock menu text changed")
    require("".join(chr(g["key"]) for g in surface.events[0]["glyphs"]) == STOCK_TEXT,
            "stock row did not reach OpenVG")
    frame = png(surface.width, surface.height, surface.pixels)
    (output / "menu-row.png").write_bytes(frame)

    glyphs = []
    for i in range(len(faces)):
        wrapper, = unpack("<I", cpu.mem_read(0x204C1774+0x2214*i, 4))
        face, = unpack("<I", cpu.mem_read(wrapper+4, 4))
        glyphs.append({ch: call(cpu, CHAR_INDEX, face, ord(ch)) for ch in "A"+TEST_TEXT})
    require(slot == 0x204C9FC4 and glyphs[0] == glyphs[4] and glyphs[1] == glyphs[2] == glyphs[3],
            "unexpected glyph lookup for the stock font slots")
    require(all(g["A"] > 0 for g in glyphs) and [glyphs[1][ch] for ch in TEST_TEXT] == [0, 0, 0, 0],
            "small font control changed")
    require((all(glyphs[4][ch] for ch in TEST_TEXT) if alternate else
             [glyphs[4][ch] for ch in TEST_TEXT] == [3136, 0, 0, 0]), "unexpected large font coverage")

    # The observation hook passes the diagnostic run only after stock layout and paint setup.
    surface.pixels[:] = bytes(len(surface.pixels))
    surface.events.clear()
    cpu.mem_write(buffer, TEST_TEXT.encode("utf-16-le"))
    test_run = True
    call(cpu, profile.draw_row, SCRATCH, 0, 1, 0, instruction_limit=2_000_000)
    pixels = sum(a > 0 for a in surface.pixels[3::4])
    require(draw_entries == [(slot, STOCK_TEXT)]*2 and len(surface.events) == int(alternate)
            and bool(pixels) == alternate, "unexpected diagnostic run result")
    if alternate:
        require("".join(chr(g["key"]) for g in surface.events[0]["glyphs"]) == TEST_TEXT
                and all(g["segments"] for g in surface.events[0]["glyphs"]), "missing diagnostic glyph outline")
        (output / "unicode-row.png").write_bytes(png(surface.width, surface.height, surface.pixels))
    return {"pointer_table": resource["pointer_table"], "resource_branch": resource,
            "flash_records": [{"header": hex(addr), "bytes": len(data), "sha256": sha256(data).hexdigest()}
                              for addr, data in records],
            "freetype_calls": [[hex(address), size, index] for address, size, index in faces],
            "glyphs_by_slot": glyphs, "original_row": STOCK_TEXT, "original_png_sha256": sha256(frame).hexdigest(),
            "unicode_probe": {"text": TEST_TEXT, "success": bool(pixels), "covered_pixels": pixels}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="original J140 DAT or, with --startup-cw-image, a PC image")
    parser.add_argument("font_source", type=Path, nargs="?", help="verified NotoSansSC-VF.ttf for the font tests")
    parser.add_argument("output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--power-key", action="store_true", help="compare released and held power-key wake paths only")
    mode.add_argument("--riic0", action="store_true", help="compare the first I2C transfer with and without its STOP event")
    mode.add_argument("--eeprom", action="store_true", help="follow original startup through the first GPIO EEPROM read")
    mode.add_argument("--startup-dma", action="store_true", help="continue original startup into timer and DMA setup")
    mode.add_argument("--startup-rspi", action="store_true", help="continue beyond startup DMA into stock RSPI setup")
    mode.add_argument("--startup-queue", action="store_true", help="trace the stock post-EEPROM board command queue")
    mode.add_argument("--startup-reply", action="store_true", help="compare rejected and accepted replies to stock SPI queries")
    mode.add_argument("--startup-audio", action="store_true", help="follow stock startup through audio DMA bring-up")
    mode.add_argument("--startup-records", action="store_true", help="compare the two post-audio EEPROM version records")
    mode.add_argument("--startup-riic-read", action="store_true", help="follow the post-version hardware I2C read and consumer")
    mode.add_argument("--startup-format", action="store_true", help="compare blank and recognized EEPROM format records")
    mode.add_argument("--startup-current-format", action="store_true", help="follow the normal J140 settings format branch")
    mode.add_argument("--startup-cw-image", action="store_true", help="boot a .ic705sim and verify CW audio, LCD and EXIT")
    mode.add_argument("--startup-settings", action="store_true", help="follow the stock task that consumes matched settings")
    mode.add_argument("--startup-display", action="store_true", help="follow stock LCD controller initialization")
    mode.add_argument("--startup-openvg", action="store_true", help="follow stock OpenVG command completion and UI wakeup")
    mode.add_argument("--startup-surfaces", action="store_true", help="render the boot clears and the first UI fills")
    parser.add_argument("--after-lcd", action="store_true", help="continue past the first LCD frame into receive DMA")
    parser.add_argument("--settings-reload", action="store_true", help="replay the original EEPROM reads after LCD completion")
    parser.add_argument("--startup-panel-record", action="store_true",
                        help="with --startup-current-format, select the initialized table slot through synthetic EEPROM")
    parser.add_argument("--startup-home-probe", action="store_true",
                        help="with --startup-current-format, follow the stock dispatcher using known idle inputs")
    parser.add_argument("--no-power-on-check", action="store_true",
                        help="with --startup-home-probe, boot with the stock Power ON Check setting off (simulated EEPROM)")
    parser.add_argument("--startup-input", choices=("neutral", "close", "close-idle", "close-menu", "close-cw"),
                        help="after the cold-start warning, replay idle or MENU/EXIT; close-cw restores VFO A/CW")
    parser.add_argument("--startup-cw-decode", action="store_true", help="with close-cw, replay the CW overlay and EXIT")
    parser.add_argument("--startup-cw-rx-ready", action="store_true",
                        help="with close-cw, boot with PTT released and minimum squelch in simulated hardware")
    parser.add_argument("--startup-cw-rx-test", action="store_true",
                        help="with --startup-cw-decode, replay CQ audio after cold start and verify the LCD and EXIT")
    parser.add_argument("--startup-cw-canvas-audit", choices=("stock", "fixed"),
                        help="with --startup-cw-rx-test, compare original heap usage with a fixed canvas control")
    parser.add_argument("--startup-cw-stock-state", action="store_true",
                        help="with --startup-cw-canvas-audit stock, allocate the CW state from the stock heap")
    parser.add_argument("--startup-stock-mmu", action="store_true",
                        help="run the stock reset and address map; with CW, load lab code only into a guest heap reservation")
    parser.add_argument("--startup-from-nor", action="store_true",
                        help="start with empty application RAM; use the original reset and simulated read-only NOR")
    parser.add_argument("--startup-cw-heap-offset", type=int, choices=(0, 8, 16, 24), default=0,
                        help="change the guest heap placement for the mapped CW canvas test")
    args = parser.parse_args()
    cw_image = None
    if args.startup_cw_image:
        if args.font_source or args.startup_cw_decode or args.startup_cw_stock_state or args.startup_cw_heap_offset:
            parser.error("--startup-cw-image uses no external font or host CW attachment")
        from tools.build_705_cw_sim import load_image
        image_sha = sha256(args.dat.read_bytes()).hexdigest()
        (main_image, large, graphics, digest, small), cw_image = load_image(args.dat)
        args.startup_current_format = args.startup_home_probe = args.no_power_on_check = True
        args.startup_stock_mmu = args.startup_cw_rx_test = True
        args.startup_input, args.startup_cw_canvas_audit = "close-cw", "stock"
    cw_enabled = args.startup_cw_decode or args.startup_cw_image
    if args.after_lcd and not args.startup_surfaces:
        parser.error("--after-lcd requires --startup-surfaces")
    if args.settings_reload and not args.after_lcd:
        parser.error("--settings-reload requires --after-lcd")
    if args.startup_panel_record and not args.startup_current_format:
        parser.error("--startup-panel-record requires --startup-current-format")
    if args.startup_home_probe and not args.startup_current_format:
        parser.error("--startup-home-probe requires --startup-current-format")
    if args.no_power_on_check and not args.startup_home_probe:
        parser.error("--no-power-on-check requires --startup-home-probe")
    if args.startup_input and not args.no_power_on_check:
        parser.error("--startup-input requires --no-power-on-check")
    if args.startup_cw_decode and args.startup_input != "close-cw":
        parser.error("--startup-cw-decode requires --startup-input close-cw")
    if args.startup_cw_rx_ready and args.startup_input != "close-cw":
        parser.error("--startup-cw-rx-ready requires --startup-input close-cw")
    if args.startup_cw_rx_test and not cw_enabled:
        parser.error("--startup-cw-rx-test requires CW")
    if args.startup_cw_canvas_audit and not args.startup_cw_rx_test:
        parser.error("--startup-cw-canvas-audit requires --startup-cw-rx-test")
    if args.startup_cw_stock_state and args.startup_cw_canvas_audit != "stock":
        parser.error("--startup-cw-stock-state requires --startup-cw-canvas-audit stock")
    if args.startup_stock_mmu and (args.startup_input != "close-cw" or
                                  args.startup_cw_decode and not args.startup_cw_stock_state):
        parser.error("--startup-stock-mmu requires --startup-input close-cw and, with CW, --startup-cw-stock-state")
    if args.startup_cw_heap_offset and not (args.startup_stock_mmu and args.startup_cw_decode):
        parser.error("--startup-cw-heap-offset requires --startup-stock-mmu and --startup-cw-decode")
    if args.startup_from_nor and not (args.startup_current_format and args.startup_stock_mmu and
                                      not args.startup_cw_decode and not args.startup_panel_record):
        parser.error("--startup-from-nor requires the stock MMU HOME replay or --startup-cw-image")
    if not cw_image:
        dat = args.dat.read_bytes()
        main_image, large, graphics, digest, small = load(dat)
    if any((args.eeprom, args.startup_dma, args.startup_rspi, args.startup_queue, args.startup_reply,
            args.startup_audio, args.startup_records, args.startup_riic_read, args.startup_format, args.startup_current_format,
            args.startup_settings, args.startup_display, args.startup_openvg, args.startup_surfaces)):
        loader = graphics[0x4000:0x49BC]
        startup_flash = graphics[:RESOURCE_TAG-GRAPHICS_FLASH] if args.startup_current_format else None
        if args.startup_from_nor and cw_image:
            startup_flash = with_pc_main(startup_flash, main_image)
        trials = ([(b"\xff"*16, "surfaces-match" if args.startup_surfaces else "openvg-match" if args.startup_openvg else
                    "display-match" if args.startup_display else "settings-match")]
                  if args.startup_settings or args.startup_display or args.startup_openvg or args.startup_surfaces else
                  [(b"\xff"*16, "format-current")] if args.startup_current_format else
                  [(b"\xff"*16, f"format-{case}") for case in ("blank", "match")] if args.startup_format else
                  [(b"\xff"*16, f"riic-read-{case}") for case in ("01", "ff")] if args.startup_riic_read else
                  [(b"\xff"*16, f"records-{case}") for case in ("match", "differ")] if args.startup_records else
                  [(b"\xff"*16, "audio")] if args.startup_audio else [(b"\xff"*16, "reply")] if args.startup_reply else
                  [(b"\xff"*16, "queue" if args.startup_queue else "rspi")] if args.startup_rspi or args.startup_queue else
                  [(b"\xff"*16, "withheld"), (b"\xff"*16, "complete")] if args.startup_dma else
                  [(data, None) for data in (b"", b"\xff"*16, bytes.fromhex("96e8017c2df314ab40c5d7698a30be52"))])
        previews = []
        cw_extension = None
        cw_rx_audio = None
        if args.startup_cw_decode:
            from tools.probe_705_cw_session import build
            with TemporaryDirectory() as folder:
                cw_extension = build(Path(folder), rtx=True, stock_canvas=args.startup_cw_canvas_audit == "stock",
                                     stock_state=args.startup_cw_stock_state)
        if args.startup_cw_rx_test:
            from tools.probe_705_cw_break_in import audio
            # Give cold AUTO the full 400 ms letter gap before checking the transcript.
            cw_rx_audio = audio("CQ", trim_leading=True) + bytes(3204)
        controls = [replay_resource_task(main_image, large, small, fixture_return=False, loader=loader,
                                         adc_sample=0x180, scif_wait="board_power", vbus_high=True,
                                         power_key_released=False, riic0_idle=True, riic0_finish="stop", eeprom=data,
                                         startup_dma=completion,
                                         scene_preview=previews if args.startup_surfaces or args.startup_current_format else None,
                                         after_lcd=args.after_lcd, settings_reload=args.settings_reload,
                                         startup_panel_record=args.startup_panel_record,
                                         startup_home_probe=args.startup_home_probe,
                                         no_power_on_check=args.no_power_on_check,
                                         startup_input=args.startup_input,
                                         cw_extension=cw_extension,
                                         cw_image=cw_image,
                                         cw_rx_ready=args.startup_cw_rx_ready or args.startup_cw_rx_test,
                                         cw_rx_audio=cw_rx_audio,
                                         cw_canvas_audit=args.startup_cw_canvas_audit,
                                         cw_stock_state=args.startup_cw_stock_state,
                                         stock_mmu=args.startup_stock_mmu,
                                         cw_heap_offset=args.startup_cw_heap_offset,
                                         startup_flash=startup_flash, startup_from_nor=args.startup_from_nor)
                    for data, completion in trials]
        if args.startup_dma:
            withheld, completed = (control["eeprom"] for control in controls)
            prefix = withheld["startup_writes"]
            require(completed["startup_writes"][:len(prefix)] == prefix,
                    "DMA controls differed before the first completion")
        if args.startup_riic_read:
            first, second = (control["eeprom"]["riic_read"] for control in controls)
            require(first["scan"] == second["scan"], "the test flag changed the startup read sequence")
        if cw_image:
            require(sha256(args.dat.read_bytes()).hexdigest() == image_sha, "PC image changed")
        else:
            require(args.dat.read_bytes() == dat, "official DAT changed")
        args.output.mkdir(parents=True, exist_ok=True)
        destination = args.output / ("startup-after-lcd.json" if args.after_lcd else
                                     "startup-surfaces.json" if args.startup_surfaces else
                                     "startup-openvg.json" if args.startup_openvg else
                                     "startup-display.json" if args.startup_display else
                                     "startup-settings.json" if args.startup_settings else
                                     "startup-current-format.json" if args.startup_current_format else
                                     "startup-format.json" if args.startup_format else
                                     "startup-riic-read.json" if args.startup_riic_read else
                                     "startup-records.json" if args.startup_records else
                                     "startup-audio.json" if args.startup_audio else "startup-reply.json" if args.startup_reply else
                                     "startup-queue.json" if args.startup_queue else "startup-rspi.json" if args.startup_rspi else
                                     "startup-dma.json" if args.startup_dma else "eeprom.json")
        report = dict(dat_sha256=DAT_HASH, main_sha256=digest, controls=controls)
        if args.startup_from_nor and not cw_image:
            missing = machine()
            map_resource_tag(missing, EXPECTED_TAG)
            report["nor_missing_main_control"] = boot_from_nor(missing, startup_flash, main_image, missing_main=True)
        if cw_image:
            report["pc_image"] = dict(sha256=image_sha, manifest=cw_image)
        destination.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        if args.startup_surfaces:
            require(len(previews) == 3, "expected first outline, dialog and LCD previews")
            for filename, data in zip(("first-offscreen-outline.png", "boot-offscreen-dialog.png", "boot-lcd.png"), previews):
                (args.output / filename).write_bytes(data)
            phase = ("LCD, receive DMA and post-display EEPROM reads" if args.settings_reload else
                     "LCD and receive DMA" if args.after_lcd else "LCD frame")
            print(f"J140 stock startup {phase} verified: {destination}")
        elif args.startup_openvg:
            print(f"J140 stock OpenVG completion resumed the UI task: {destination}")
        elif args.startup_display:
            print(f"J140 configured the stock LCD controller and reached OpenVG: {destination}")
        elif args.startup_settings:
            print(f"J140 scheduled the stock UI task after reading EEPROM settings: {destination}")
        elif args.startup_current_format:
            filenames = ["boot-first-lcd.png", "boot-progress-mask.png", "boot-progress-lcd.png", "boot-full-lcd.png"]
            if args.startup_home_probe:
                filenames.append("boot-home-with-warning.png" if args.no_power_on_check else "boot-page-3d.png")
            if args.startup_input and args.startup_input != "neutral":
                filenames.append("boot-home-after-close.png")
            if args.startup_input in ("close-menu", "close-cw"):
                filenames.append("boot-stock-menu.png")
                if cw_enabled:
                    filenames.append("boot-cw.png")
                if args.startup_cw_rx_test:
                    filenames.append("boot-cw-decoded.png")
                filenames.append("boot-home-after-exit.png")
            require(len(previews) == len(filenames), "unexpected number of startup previews")
            for filename, data in zip(filenames, previews):
                (args.output / filename).write_bytes(data)
            if args.startup_home_probe:
                phase = ("VFO A/CW, MENU, CW overlay and EXIT" if cw_enabled else
                         "VFO A/CW, KEYER in MENU, and return to HOME" if args.startup_input == "close-cw" else
                         "MENU and return to HOME after cold startup" if args.startup_input == "close-menu" else
                         "HOME after dismissing sub-CPU warning" if args.startup_input in ("close", "close-idle") else
                         "HOME with sub-CPU warning" if args.no_power_on_check else "page 0x3D; HOME not seen")
                print(f"J140 committed original {phase}: {destination}")
            else:
                boundary = "an EEPROM write" if args.startup_panel_record else "a null table read"
                print(f"J140 stock RTC and panel DMA setup completed; stopped before {boundary}, HOME not seen: {destination}")
        elif args.startup_format:
            print(f"J140 compared blank and recognized EEPROM format records: {destination}")
        elif args.startup_riic_read:
            print(f"J140 completed the EEPROM hardware read and applied stock startup defaults: {destination}")
        elif args.startup_records:
            print(f"J140 stock EEPROM checks compared matching and one-byte-different records: {destination}")
        elif args.startup_audio:
            print(f"J140 stock boot waited for audio clock and enabled DMA: {destination}")
        elif args.startup_reply:
            print(f"J140 stock board replies compared; version fields formatted: {destination}")
        elif args.startup_queue:
            print(f"J140 stock board command queue traced: {destination}")
        elif args.startup_rspi:
            print(f"J140 stock boot configured both RSPI controllers and completed its EEPROM scan: {destination}")
        elif args.startup_dma:
            print(f"J140 startup waited without DMA; stock IRQ retired the GPIO setup transfers: {destination}")
        else:
            print(f"J140 retried missing EEPROM; both readable fixtures created the stock UI task: {destination}")
        return
    if args.power_key or args.riic0:
        loader = graphics[0x4000:0x49BC]
        controls = [replay_resource_task(main_image, large, small, fixture_return=False, loader=loader,
                                         adc_sample=0x180, scif_wait="board_power", vbus_high=True,
                                         power_key_released=released, riic0_idle=idle, riic0_finish=finish)
                    for released, idle, finish in (((False, True, "no_stop"), (False, True, "stop")) if args.riic0 else
                                                   ((True, False, None), (False, False, None), (False, True, None)))]
        args.output.mkdir(parents=True, exist_ok=True)
        report = {"dat_sha256": DAT_HASH, "main_sha256": digest, "loader_sha256": sha256(loader).hexdigest(),
                  "fixture": {"usb_vbus_p3_9": 1, "adc_sample": 0x180}, "controls": controls}
        destination = args.output / ("riic0.json" if args.riic0 else "power-key.json")
        destination.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        for control in controls:
            if control["riic0_return_pc"]:
                print(f"RIIC0 returned at {control['riic0_return_pc']}; next GPIO I2C read at {control['stop_pc']}.")
            else:
                print(f"P8.7={control['p8_7']}: {control['outcome']} at {control['stop_pc']}")
        print(f"J140 startup checks passed: {destination}")
        return
    if args.font_source is None:
        parser.error("font_source is required unless using --power-key, --riic0 or --eeprom")
    require(sha256(args.font_source.read_bytes()).hexdigest() == FONT_SOURCE_SHA, "unexpected font source")
    for case in ("stock", "alternate", "continuous-stock"):
        (args.output / case).mkdir(parents=True, exist_ok=True)
    subset = args.output / "alternate/font.ttf"
    build_font(args.font_source, subset, "".join(map(chr, range(32, 127)))+STOCK_TEXT+TEST_TEXT)
    report = {"dat_sha256": DAT_HASH, "main_sha256": digest, "resource_stop": stop_at_first_missing(main_image)}
    report["resource_mmio"] = [trace_resource_mmio(main_image, a, b) for a, b in ((0x03, 0x40), (0x02, 0x41))]
    report["mtu2_controls"] = []
    for seed in (0, 255):
        gate_only = trace_resource_mmio(main_image, seed, seed, stbcr3=seed)
        control = trace_resource_mmio(main_image, seed, seed, stbcr3=seed, allow_tcr4=True)
        require(gate_only["stop"] == {"kind": "write", "pc": "0x20005d80", "address": hex(MTU2_TCR4), "size": 1, "value": 0}
                and control["stop"] == {"kind": "write", "pc": "0x20005d84", "address": "0xfcff0203", "size": 1, "value": 0}
                and control["mmio"][:-1] == gate_only["mmio"], "unexpected cross-model MTU2 stop")
        report["mtu2_controls"].append({"seed": seed, "gate_only": gate_only, "gate_and_tcr4": control})
    mismatch = machine(main_image)
    skip = machine(main_image)
    report["resource_branch_controls"] = {
        "mismatch": replay_resource_branch(mismatch, map_font_records(mismatch, large, small), 0, b"SX4075 V1.00-000\0"),
        "skip": replay_resource_branch(skip, (), 1, None),
    }
    for name, font in (("stock", large), ("alternate", subset.read_bytes())):
        report[name] = replay(main_image, PROFILES[digest], font, small,
                              alternate=name == "alternate", output=args.output / name)
    continuous = replay(main_image, PROFILES[digest], large, small, alternate=False,
                        output=args.output / "continuous-stock", continuous=True)
    require(all(continuous[key] == report["stock"][key] for key in
                ("pointer_table", "freetype_calls", "glyphs_by_slot", "original_png_sha256")),
            "continuous resource initialization changed the stock row")
    report["continuous_stock"] = continuous
    report["continuous_controls"] = {}
    for name, flag, tag in (("matching", 0, EXPECTED_TAG), ("mismatch", 0, b"SX4075 V1.00-000\0"),
                            ("already_initialized", 1, EXPECTED_TAG)):
        cpu = machine(main_image)
        records = () if flag else map_font_records(cpu, large, small)
        report["continuous_controls"][name] = replay_resource_entry(cpu, records, 255, tag, flag)
    report["task_replay"] = {
        name: replay_resource_task(main_image, large, small, fixture_return=fixture)
        for name, fixture in (("board_boundary", False), ("second_iteration_control", True))
    }
    report["board_replay"] = replay_resource_task(main_image, large, small, fixture_return=False,
                                                  loader=graphics[0x4000:0x49BC])
    report["board_adc_controls"] = [
        replay_resource_task(main_image, large, small, fixture_return=False,
                             loader=graphics[0x4000:0x49BC], adc_sample=sample)
        for sample in (0x180, 0x280)
    ]
    report["board_scif_controls"] = [
        replay_resource_task(main_image, large, small, fixture_return=False,
                             loader=graphics[0x4000:0x49BC], adc_sample=0x180, scif_wait=condition)
        for condition in ("no_compare", "timeout", "timer_irq", "rx_prefix", "rx_frame")
    ]
    report["board_power_controls"] = [
        replay_resource_task(main_image, large, small, fixture_return=False, loader=graphics[0x4000:0x49BC],
                             adc_sample=0x180, scif_wait="board_power", vbus_high=vbus_high)
        for vbus_high in (False, True)
    ]
    (args.output / "font-boot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"J140 replay checks passed: {args.output / 'font-boot.json'}")
    for control in report["board_power_controls"]:
        print(f"P3.9={control['vbus_p3_9']}: SCIF returned to 0x2007be78; "
              f"{control['outcome']} at {control['stop_pc']}; board return not observed.")


if __name__ == "__main__":
    main()
