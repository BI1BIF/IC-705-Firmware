"""Install the APRS replay hooks and verify the stock J140 RTX consumer."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from struct import pack, pack_into, unpack

from tools.build_705_cw_sim import PICKER_ID, PICKER_REFERENCES, PICKER_STRIDE, PICKER_TABLE, picker_table
from tools.emulate_705 import BASE as MAIN_BASE, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_rtx_audio import (CURRENT, DMA_TIMER, IDLE, LOOP, PCM_DONE, PCM_STEP,
                                       TIMER, TIMERS_CLEARED, UI_UPDATE_CALL, probe)
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC, FRAMES
from tools.probe_705_sstv_picture import branch
from tools.replay_705_aprs_fm import LAYOUT, load_aprs_panel, read_wav, require
from tools.replay_705_aprs_rx import FRAME_MAX, FRAME_STRIDE, build_target, monitor


BASE = 0x21000000
MENU_TABLE, APRS_RX_MENU = 0x21100000, 277
QUICK_HISTORY, APRS_HISTORY, HISTORY_ROW = 280, 281, 282
HISTORY_ROWS, QUICK_ROWS = 64, 15
SETTINGS_THIRD, QUICK_BEACON, APRS_SSID_MENU, FIRST_SSID = 283, 284, 285, 286
SSID_LABELS = tuple(f"{n}\0".encode() for n in range(16))
SETTINGS_PATH = FIRST_SSID + len(SSID_LABELS)
SETTINGS_SYMBOL = SETTINGS_PATH + 1
SETTINGS_AUTO, SETTINGS_INTERVAL = SETTINGS_SYMBOL + 1, SETTINGS_SYMBOL + 2
APRS_SYMBOL_LIST, SYMBOL_ROW = SETTINGS_INTERVAL + 1, SETTINGS_INTERVAL + 2
SETTINGS_ROWS = (APRS_RX_MENU+1, APRS_RX_MENU+2, SETTINGS_THIRD, SETTINGS_PATH,
                 SETTINGS_SYMBOL, SETTINGS_AUTO, SETTINGS_INTERVAL)
SYMBOL_ROWS = 94
APRS_PICKER_BYTES = (SYMBOL_ROW + 1)*PICKER_STRIDE + (
    2*(len(SETTINGS_ROWS) + QUICK_ROWS+1 + QUICK_ROWS+2 + HISTORY_ROWS + len(SSID_LABELS) + SYMBOL_ROWS) +
    sum(map(len, SSID_LABELS)))
GPS_ACTION_TABLE = MENU_TABLE + 0x8000
GPS_ACTION_REFERENCES = (0x200A3670, 0x200A6AC0, 0x200AB674, 0x2014BA38, 0x201558D4)
FM_HZ = 144_390_000
SOURCES = ("samples/aprs-j140-task.s", "samples/aprs-j140-task.c", "samples/aprs-rx-arm.c",
           "samples/aprs-j140-panel.s", "samples/aprs-j140-panel.c",
           "samples/aprs-j140-popup.s", "samples/aprs-j140-popup.c", "samples/aprs-j140-menu.c",
           "samples/aprs-j140-history.c", "samples/aprs-j140-beacon.c", "samples/aprs-j140-alert.c")
HOOKS = (
    (0x200FFD38, 0xE8BD4070, "aprs_j140_dma_done", 0xEA000000),
    (0x2010FE30, 0xEBFFBE76, "aprs_copy_pcm", 0xEB000000),
    (PCM_STEP, 0xEB00ED02, "aprs_j140_record_step", 0xEB000000),
    (0x200D5114, 0xEBFF04E8, "aprs_j140_panel_step", 0xEB000000),
    (0x2004A90C, 0xE5D00002, "aprs_strip_valid", 0xEA000000),
    (0x2004A92C, 0xE5D11006, "aprs_strip_kind", 0xEA000000),
    (0x2004A960, 0xE5D21006, "aprs_strip_icon", 0xEA000000),
    (0x2004B810, 0xE5D40003, "aprs_strip_draw", 0xEA000000),
    (0x2004A0B0, 0xE3530000, "aprs_strip_clear", 0xEA000000),
    (0x2004A0E8, 0xE3C11004, "aprs_strip_keep_position", 0xEA000000),
    (0x2009639C, 0xEBFED156, "aprs_strip_visible", 0xEB000000),
    (0x2016334C, 0xE5D41001, "aprs_strip_caption", 0xEA000000),
    (0x2004853C, 0xE5C0404F, "aprs_position_request", 0xEA000000),
    (0x200485A8, 0xE59F517C, "aprs_position_timer_state", 0xEA000000),
    (0x20048614, 0xE5D003E9, "aprs_position_timer_limit", 0xEA000000),
    (0x2004937C, 0xE5C1004F, "aprs_position_clear", 0xEA000000),
    (0x2004938C, 0xE5D1104F, "aprs_position_reason", 0xEA000000),
    (0x2004972C, 0xE5D0004F, "aprs_position_leave", 0xEA000000),
    (0x20049464, 0xE5D70000, "aprs_position_prepare", 0xEA000000),
    (0x201884E8, 0xE3A0202B, "aprs_position_draw", 0xEA000000),
    (0x2004800C, 0xE92D47F0, "aprs_position_dv_data", 0xEA000000),
    (0x200801C0, 0xE92D4010, "aprs_position_reopen", 0xEA000000),
    (0x200CDD08, 0xE3550047, "aprs_menu_empty_row", 0xEA000000),
    (0x200CD828, 0xE92D4010, "aprs_selector_back", 0xEA000000),
    (0x2014B630, 0xEBFFDC18, "aprs_gps_text", 0xEB000000),
    (0x2014B810, 0xEBFFDBA0, "aprs_gps_text", 0xEB000000),
    (0x200A34BC, 0xE92D4070, "aprs_gps_mode_select", 0xEA000000),
    (0x200A25DC, 0xE5D07000, "aprs_gps_mode_highlight", 0xEA000000),
    (0x200817DC, 0xEB012F91, "aprs_quick_open", 0xEB000000),
    (0x20140FBC, 0xEB0005B5, "aprs_history_text", 0xEB000000),
    (0x20145754, 0xFB0478A3, "aprs_compass_arrow_upload", 0xEB000000),
    (0x20060D28, 0xE7D00001, "aprs_tx_source_hook", 0xEA000000),
    (0x20109674, 0xE1A012A0, "aprs_tx_request_hook", 0xEA000000),
    (0x200FFEB0, branch(0x200FFEB0, 0x201F644C, 0xEB000000), "aprs_tx_mod_block", 0xEB000000),
    (0x20052FB0, 0xE92D401C, "aprs_comment_editor_hook", 0xEA000000),
    (0x200F05F0, branch(0x200F05F0, 0x200EBDF4, 0xEB000000), "aprs_after_editor_navigation", 0xEB000000),
)


def e140_rom(address):
    """Translate the stock routine addresses used by the APRS hooks."""
    if address in (0x2000E73C, 0x2001DEA8, 0x2002E850):
        return address - 244
    if address == 0x2002EAFC:
        return address - 228
    if address >= 0x202D4000:
        return address + 224
    if address >= 0x200A0000:
        return address + 228
    if address == 0x20098B50:
        return address + 192
    if address >= 0x20070000:
        return address - 152
    return address - 240


def build_task(output, *, european=False, base=BASE, flags=()):
    sources = SOURCES
    if "-DAPRS_SLOT_UI" in flags:
        sources += ("samples/aprs-slot-ui.c","samples/aprs-slot-ui.S","samples/aprs-slot-config.c","samples/aprs-slot-messages.c")
    if european:
        generated = output / "e140-sources"
        generated.mkdir(exist_ok=True)
        sources_to_translate = sources
        sources = []
        for source in map(Path, sources_to_translate):
            target = generated / source.name
            original = source.read_text(encoding="utf-8")
            target.write_text(re.sub(r"\b0x20[0-2][0-9a-fA-F]{5}\b",
                                     lambda m: hex(e140_rom(int(m[0], 16))), original), encoding="utf-8")
            sources.append(target)
    return build_target(output, "aprs-task", sources, base, "aprs_j140_record_step",
                        float_abi="softfp", includes=("samples",), flags=flags)


def install_gps_entry(cpu, symbols, rom, table, *, map_region):
    def word(address):
        return unpack("<I", cpu.mem_read(address, 4))[0]

    gps_list = word(rom(0x200A0A88)) + 144*12
    row_count, row_pointer, page_style = unpack("<3I", cpu.mem_read(gps_list, 12))
    rows = bytes(cpu.mem_read(row_pointer, 3*row_count))
    require(row_count == 8 and page_style == 1 and rows[:6] == pack("<BHBH", 1, 219, 2, 478),
            "unexpected stock GPS list")

    action_count, action_stride = 159, 20
    references = [rom(address) for address in GPS_ACTION_REFERENCES]
    action_table = word(references[0])
    require(all(word(address) == action_table for address in references), "unexpected GPS action table")
    actions = bytes(cpu.mem_read(action_table, action_count*action_stride))
    new_rows = table + len(actions) + action_stride
    new_label = new_rows + len(rows) + 3
    new_action = pack("<5I", symbols["aprs_menu_open"], 0, 0x10700, new_label, new_label)
    data = actions + new_action + rows[:6] + pack("<BH", 3, action_count) + rows[6:] + b"APRS\0"
    tx_mode = word(rom(0x200A2640)) + 478*60
    require(word(tx_mode) == 0x203EB172 and word(tx_mode+16) == 2, "unexpected GPS TX Mode descriptor")
    labels = unpack("<6I", cpu.mem_read(word(tx_mode+56), 24))
    require(tuple(bytes(cpu.mem_read(x, 6)).split(b"\0")[0] for x in labels) ==
            (b"OFF", b"D-PRS", b"NMEA")*2, "unexpected GPS TX Mode labels")
    data += bytes(-(table+len(data)) % 4)
    expanded_labels = table + len(data)
    data += pack("<8I", *labels[:3], new_label, *labels[3:], new_label)
    if map_region:
        cpu.mem_map(table, 4096)
    cpu.mem_write(table, data)
    for address in references:
        cpu.mem_write(address, pack("<I", table))
    cpu.mem_write(gps_list, pack("<II", row_count + 1, new_rows))
    cpu.mem_write(tx_mode+16, pack("<I", 3))
    cpu.mem_write(tx_mode+56, pack("<I", expanded_labels))
    return table + len(data)


def install_task(cpu, code, symbols, *, european=False, layout=None):
    rom = e140_rom if european else lambda address: address
    base, menu_table, action_table = (BASE, MENU_TABLE, GPS_ACTION_TABLE) if layout is None else layout
    if layout is None:
        end = (symbols["__bss_end__"] + 4095) & ~4095
        cpu.mem_map(base, end - base)
    cpu.mem_write(base, code)
    for site, original, label, opcode in HOOKS:
        if european and original >> 24 == 0xEB:
            displacement = ((original & 0xffffff) ^ 0x800000) - 0x800000
            original = branch(rom(site), rom(site + 8 + 4*displacement), 0xEB000000)
        site = rom(site)
        require(unpack("<I", cpu.mem_read(site, 4))[0] == original, f"expected original instruction at {site:#x}")
        cpu.mem_write(site, pack("<I", branch(site, symbols[label], opcode)))
        cpu.ctl_remove_cache(site, site + 4)
    table_shift = 224 if european else 0
    main = cpu.mem_read(MAIN_BASE, PICKER_TABLE + table_shift - MAIN_BASE + (PICKER_ID + 1)*PICKER_STRIDE)
    table = bytearray(picker_table(main, menu_table, {"cw_picker_select": symbols["aprs_menu_select"],
                                                    "cw_picker_choice": symbols["aprs_menu_choice"]},
                                   labels=(b"APRS", b"", b""), menu_id=APRS_RX_MENU,
                                   code_shift=rom(PICKER_REFERENCES[0])-PICKER_REFERENCES[0],
                                   table_shift=table_shift))
    for offset in (48, 56):
        pack_into("<I", table, APRS_RX_MENU*PICKER_STRIDE + offset, symbols["aprs_menu_title"])
    pack_into("<I", table, APRS_RX_MENU*PICKER_STRIDE + 4, symbols["aprs_menu_initial_choice"])
    for record, label in ((APRS_RX_MENU+1, "aprs_menu_mode"), (APRS_RX_MENU+2, "aprs_menu_channel")):
        for offset in (52, 60):
            pack_into("<I", table, record*PICKER_STRIDE + offset, symbols[label])
    del table[(APRS_RX_MENU + 3)*PICKER_STRIDE:]
    row_lists = menu_table + (SYMBOL_ROW + 1)*PICKER_STRIDE
    quick = PICKER_STRIDE
    stock_quick = bytes(table[quick:quick+PICKER_STRIDE])
    quick_saved = unpack("<I", stock_quick[36:40])[0]
    quick_rows = unpack("<I", stock_quick[68:72])[0]
    require(stock_quick[1] == QUICK_ROWS-1, "unexpected native QUICK row count")
    quick_entries = bytes(cpu.mem_read(quick_rows, QUICK_ROWS*2))
    quick_rx = row_lists + 2*len(SETTINGS_ROWS)
    quick_tx = quick_rx + (QUICK_ROWS+1)*2
    history_entries = quick_tx + (QUICK_ROWS+2)*2
    ssid_entries = history_entries + HISTORY_ROWS*2
    symbol_entries = ssid_entries + len(SSID_LABELS)*2
    ssid_strings = symbol_entries + SYMBOL_ROWS*2
    pack_into("<I", table, APRS_RX_MENU*PICKER_STRIDE+68, row_lists)
    pack_into("<I", table, quick+20, symbols["aprs_quick_hide"])
    child = table[93*PICKER_STRIDE:94*PICKER_STRIDE]
    quick_child = child[:]
    pack_into("<I", quick_child, 8, symbols["aprs_quick_history"])
    for offset in (52, 60):
        pack_into("<I", quick_child, offset, symbols["aprs_history_title"])
    table.extend(quick_child)
    history = bytearray(stock_quick)
    history[1] = 0
    history[28] |= 1
    for offset, pointer in ((4, symbols["aprs_history_initial"]), (12, symbols["aprs_history_select"]),
                            (20, symbols["aprs_history_hide"]), (32, symbols["aprs_history_choice"]),
                            (36, 0), (48, symbols["aprs_history_title"]), (56, symbols["aprs_history_title"]),
                            (68, history_entries)):
        pack_into("<I", history, offset, pointer)
    table.extend(history)
    for offset in (52, 60):
        pack_into("<I", child, offset, symbols["aprs_history_title"])
    table.extend(child)

    for title, action in (("aprs_menu_beacon", None), ("aprs_beacon_title", "aprs_quick_beacon")):
        extra = child[:]
        for offset in (52, 60):
            pack_into("<I", extra, offset, symbols[title])
        pack_into("<I", extra, 8, symbols[action] if action else 0)
        table.extend(extra)

    ssid = history[:]
    ssid[1] = len(SSID_LABELS)-1
    for offset, value in ((4, symbols["aprs_ssid_initial"]), (12, symbols["aprs_ssid_select"]),
                          (32, symbols["aprs_ssid_choice"]), (48, symbols["aprs_ssid_title"]),
                          (56, symbols["aprs_ssid_title"]), (68, ssid_entries)):
        pack_into("<I", ssid, offset, value)
    table.extend(ssid)
    title = ssid_strings
    for label in SSID_LABELS:
        for offset in (52, 60):
            pack_into("<I", child, offset, title)
        table.extend(child)
        title += len(label)

    for label in ("aprs_settings_path", "aprs_settings_symbol", "aprs_settings_auto", "aprs_settings_interval"):
        for offset in (52, 60):
            pack_into("<I", child, offset, symbols[label])
        table.extend(child)
    catalog = history[:]
    for offset, label in ((4, "aprs_symbol_initial_choice"), (12, "aprs_symbol_list_select"),
                          (32, "aprs_menu_choice"), (48, "aprs_symbol_title"),
                          (56, "aprs_symbol_title")):
        pack_into("<I", catalog, offset, symbols[label])
    pack_into("<I", catalog, 68, symbol_entries)
    table.extend(catalog)
    table.extend(child)
    table.extend(pack(f"<{len(SETTINGS_ROWS)}H", *SETTINGS_ROWS))
    table.extend(pack("<H", QUICK_HISTORY) + quick_entries)
    table.extend(pack("<2H", QUICK_HISTORY, QUICK_BEACON) + quick_entries)
    table.extend(pack("<H", HISTORY_ROW) * HISTORY_ROWS)
    table.extend(pack(f"<{len(SSID_LABELS)}H", *range(FIRST_SSID, FIRST_SSID+len(SSID_LABELS))))
    table.extend(pack("<H", SYMBOL_ROW) * SYMBOL_ROWS)
    table.extend(b"".join(SSID_LABELS))
    require(len(table) == APRS_PICKER_BYTES, "inconsistent APRS picker layout")
    cpu.mem_write(symbols["aprs_quick_menu"], pack("<5I", menu_table+quick, quick_rows, quick_rx, quick_tx, quick_saved))
    cpu.mem_write(symbols["aprs_history_descriptor"], pack("<I", menu_table+APRS_HISTORY*PICKER_STRIDE))
    cpu.mem_write(symbols["aprs_settings_descriptor"], pack("<I", menu_table+APRS_RX_MENU*PICKER_STRIDE))
    cpu.mem_write(symbols["aprs_symbol_descriptor"], pack("<I", menu_table+APRS_SYMBOL_LIST*PICKER_STRIDE))
    require(menu_table + len(table) <= action_table, "APRS selector overlaps GPS actions")
    if layout is None:
        cpu.mem_map(menu_table, (len(table)+4095) & ~4095)
    cpu.mem_write(menu_table, bytes(table))
    for site in PICKER_REFERENCES:
        cpu.mem_write(rom(site), pack("<I", menu_table))
    site = rom(0x200CDCB0)
    require(cpu.mem_read(site, 4) == pack("<I", 0xE5D52000), "unexpected native selector ID load")
    cpu.mem_write(site, pack("<I", 0xE1D520B0))
    cpu.ctl_remove_cache(site, site + 4)
    return install_gps_entry(cpu, symbols, rom, action_table, map_region=layout is None)


def replay(images, code, symbols, clean, clean_expected, bad, *, european=False, application=None):
    rom = e140_rom if european else lambda address: address

    def exercise(cpu, run, irq, _sub, value):
        if application is None:
            install_task(cpu, code, symbols, european=european)
        else:
            require(cpu.mem_read(symbols["__bss_start__"], symbols["__bss_end__"] - symbols["__bss_start__"]) ==
                    bytes(symbols["__bss_end__"] - symbols["__bss_start__"]), "APRS state was not zero after startup")

        def write_word(address, word):
            cpu.mem_write(address, pack("<I", word))

        def station(hz):
            for address in (0x20380714, 0x203EBC2F):
                write_word(address, hz)

        def counter(name):
            return value(symbols["aprs_" + name])

        station(FM_HZ)
        for address in (MODE_UI_A, MODE_VFO_A):
            cpu.mem_write(address, b"\x70")
        cpu.mem_write(AUDIO_GATE, b"\0")
        cpu.mem_write(0x20380874, b"\1")
        for offset in (0x124, 0x424, 0x524):
            write_word(DMAC + offset, 1)

        task = value(CURRENT)
        task_calls, ui_calls = 0, 0

        def on_record_step(*_):
            nonlocal task_calls
            require(value(CURRENT) == task, "APRS record consumer left the stock main task")
            task_calls += 1

        cpu.hook_add(uc.UC_HOOK_CODE, on_record_step,
                     begin=symbols["aprs_record_receive"], end=symbols["aprs_record_receive"])

        def on_panel_step(*_):
            nonlocal ui_calls
            require(value(CURRENT) == task, "APRS display service left the stock main task")
            ui_calls += 1

        cpu.hook_add(uc.UC_HOOK_CODE, on_panel_step,
                     begin=symbols["aprs_update_panel"], end=symbols["aprs_update_panel"])

        run(rom(TIMERS_CLEARED), rom(PCM_STEP))
        background, dma_blocks = rom(PCM_STEP), 0

        def deliver(data):
            nonlocal dma_blocks
            require(len(data) % FRAMES == 0, "partial SSI0 block")
            for offset in range(0, len(data), FRAMES):
                left = data[offset:offset + FRAMES]
                words = [word for sample in left for word in ((sample & 65535) << 16, 0)]
                bank = dma_blocks & 1
                cpu.mem_write(LAYOUT["rec_bank"] + 288 * bank, pack("<72I", *words))
                write_word(DMAC + 0xE4, 0x41 if bank else 0xC1)
                irq(DMA_TIMER, background)
                dma_blocks += 1
            write_word(DMAC + 0xE4, 1)

        def poll(*, test_ui_call=False):
            nonlocal background
            if background == rom(IDLE):
                for target in (rom(IDLE), rom(PCM_STEP)):
                    irq(TIMER, rom(IDLE))
                    irq(0, rom(LOOP))
                    run(rom(LOOP), target)
            run(rom(PCM_STEP), rom(PCM_DONE))
            if test_ui_call:
                # Delimit the stock UI call on the final turn. Downstream board
                # housekeeping needs peripherals outside this scheduler fixture.
                run(rom(UI_UPDATE_CALL), rom(UI_UPDATE_CALL) + 4, limit=2_000_000)
            else:
                run(rom(LOOP), rom(IDLE), limit=2_000_000)
                background = rom(IDLE)

        def stream(data):
            data += (0,) * (-len(data) % FRAMES)
            for offset in range(0, len(data), 6 * FRAMES):
                deliver(data[offset:offset + 6 * FRAMES])
                poll()

        cases = {}

        def snapshot():
            return dict(records=counter("record_count"), samples=counter("rx_samples"),
                        bad_fcs_candidates=counter("rx_bad_fcs"), lost_blocks=counter("lost_pcm_blocks"),
                        uncertain_blocks=counter("uncertain_pcm_blocks"))

        def evidence(name, before, expected):
            after = snapshot()
            frames = []
            for index in range(before["records"], after["records"]):
                address = counter("records") + index % 64 * FRAME_STRIDE
                time, length = unpack("<II", cpu.mem_read(address, 8))
                require(18 <= length <= FRAME_MAX, "invalid native record length")
                raw = bytes(cpu.mem_read(address + 8, length))
                frames.append(dict(text=monitor(raw), octets=raw[:-2].hex(), fcs_wire=raw[-2:].hex(),
                                   end_sample=time))
            fields = ("text", "octets", "fcs_wire")
            require([tuple(frame[k] for k in fields) for frame in frames] ==
                    [tuple(frame[k] for k in fields) for frame in expected], f"{name}: unexpected frames {frames}")
            cases[name] = dict(frames=frames, **{key: after[key] - before[key] for key in before})
            return cases[name]

        # Run a complete packet while APRS is disabled and again after dialing away.
        first = clean[:clean_expected[0]["end_sample"] + 144]
        before = snapshot()
        stream(first)
        require(evidence("disabled", before, [])["samples"] == 0, "disabled APRS accepted audio")

        write_word(symbols["aprs_channel_hz"], FM_HZ)
        before = snapshot()
        stream(clean)
        intact = evidence("same_pcm_as_previous_replay", before, clean_expected)
        require(intact["lost_blocks"] == intact["uncertain_blocks"] == 0, "unexpected normal loss")

        before = snapshot()
        station(FM_HZ + 10_000)
        stream(first)
        deliver((1200,) * (6 * FRAMES))  # Off-channel blocks already queued at the instant of retune.
        station(FM_HZ)
        poll()
        require(evidence("off_channel_including_queued_audio", before, [])["samples"] == 0,
                "off-channel samples crossed the retune")

        before = snapshot()
        stream(bad)
        require(evidence("bad_fcs_after_retune", before, [])["bad_fcs_candidates"] > 0,
                "bad FCS fixture did not reach the checksum")

        before = snapshot()
        cut = 22032  # Within the first AX.25 frame, on a 36-sample boundary.
        stream(clean[:cut])
        deliver(clean[cut:cut + 8 * FRAMES])
        require(value(0x204016E2, 1) == value(0x204016E3, 1), "stock ring did not wrap")
        poll()
        stream(clean[cut + 8 * FRAMES:])
        loss = evidence("eight_block_ring_wrap_then_next_packets", before, clean_expected[1:])
        require(loss["lost_blocks"] == 8 and loss["uncertain_blocks"] == 0, "missing PCM not detected")
        require(counter("rx_read") == counter("rx_written") == counter("record_count") and
                counter("rx_overrun") == 0, "AX.25 handoff queue was not drained by ARM")
        deliver((0,) * FRAMES)
        poll(test_ui_call=True)
        require(ui_calls == 1 and task_calls > 0, "original main task failed to dispatch the APRS panel")
        return dict(stock_main_task=hex(task), native_record_turns=task_calls, native_ui_turns=ui_calls,
                    stock_dma_blocks=dma_blocks,
                    final=snapshot(), cases=cases)

    if european and application is None:
        application_for_probe = images[0]
    else:
        application_for_probe = application
    return probe(images[0], audio_experiment=exercise, application=application_for_probe)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dat = args.firmware.read_bytes()
    images, european = load_aprs_panel(dat)
    previous = json.loads((args.previous / "replay.json").read_text(encoding="utf-8"))
    require(european or previous["stock_main_sha256"] == images[3], "reference from different firmware")
    expected = previous["cases"]["continuous"]["frames"][:3]
    clean = read_wav(args.fixtures / "continuous-source48.wav")[:expected[-1]["end_sample"] + 144]
    bad = read_wav(args.fixtures / "bad-fcs-source48.wav")
    code, symbols = build_task(args.output, european=european)
    result = replay(images, code, symbols, clean, expected, bad, european=european)
    result.update(scope="stock RTX and SSIF0 interrupt, emulator clock and dial state, native ARM record consumer",
                  region="E140" if european else "J140", stock_dat_sha256=sha256(dat).hexdigest(),
                  arm_sha256=sha256(code).hexdigest(), code_bytes=len(code),
                  record_storage_bytes=64 * FRAME_STRIDE)
    (args.output / "task.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["final"], indent=2))


if __name__ == "__main__":
    main()
