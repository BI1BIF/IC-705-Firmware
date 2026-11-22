"""Build the region's relocatable APRS image and replay a quiescent mode handoff."""
from hashlib import sha256
from struct import pack, unpack_from

from elftools.elf.elffile import ELFFile
from tools.replay_705_aprs_task import FM_HZ, build_task
from tools.replay_705_aprs_rx import build_target


LINK = 0x20760000
# Fixture locations for the resident dispatcher and the immutable input image.
MANAGER, SOURCE = 0x21000000, 0x21200000


def finish_robot36(c, sub, value, sstv, image, folder):
    from array import array
    from PIL import Image
    from tools.sstv_robot36 import decode_rows
    # The caller already collected the first block after DSP granted PTT.
    pcm = bytearray(c.mem_read(0x20401c14,72))
    samples = 1771680  # 910 ms header and 240 lines of 150 ms at 48 kHz
    for start in range(36,samples,36):
        if start % (36*256) == 0:
            assert sub(sstv["sstv_tx_requested"],0) & 32
        assert sub(sstv["sstv_tx_mod_block"]) == 4
        pcm.extend(c.mem_read(0x20401c14,72))
    assert not any(pcm[2*samples:]) and value(sstv["tx_state"]) == 5
    for _ in range(2):
        sub(sstv["sstv_tx_mod_block"])
        assert not any(c.mem_read(0x20401c14,72))
    assert not sub(sstv["sstv_tx_requested"],0) and value(sstv["tx_state"]) == 3
    rows = list(decode_rows(array("h",pcm+bytes(48000)),48000))
    assert [index for index,_ in rows] == list(range(0,240,2))
    rgb = b"".join(pair for _,pair in rows)
    expected = bytearray()
    for pixel in array("H",image):
        expected.extend(((pixel>>11)*255//31, (pixel>>5 & 63)*255//63, (pixel & 31)*255//31))
    errors = [abs(a-b) for a,b in zip(expected,rgb,strict=True)]
    mae = sum(errors)/len(errors)
    assert mae < 8 and sum(errors[-320*3:])/(320*3) < 8
    Image.frombytes("RGB",(320,240),rgb).save(folder/"robot36.png")
    return dict(mode="Robot 36",samples=samples,decoded_rows=240,rgb_mean_error=round(mae,3),
                pcm_sha256=sha256(pcm[:samples*2]).hexdigest(),ptt_request_released=True)


def build(folder, european, flags, rom, *, slot=None):
    flags = [*flags, "-DAPRS_OVERLAY", "-mword-relocations", "-Wl,--emit-relocs"]
    image, sy = build_task(folder, european=european, base=LINK, flags=flags)
    absolute, branches = [], []
    with (folder / "aprs-task.elf").open("rb") as f:
        elf = ELFFile(f)
        keep = elf.get_section_by_name("aprs_keep")
        keep_offset, keep_size = keep["sh_addr"] - LINK, keep["sh_size"]
        for section in elf.iter_sections():
            if section["sh_type"] != "SHT_REL" or not elf.get_section(section["sh_info"])["sh_flags"] & 2:
                continue
            symbols = elf.get_section(section["sh_link"])
            for reloc in section.iter_relocations():
                offset = reloc["r_offset"] - LINK
                kind = reloc["r_info_type"]
                internal = symbols.get_symbol(reloc["r_info_sym"])["st_shndx"] != "SHN_ABS"
                if kind == 2:  # R_ARM_ABS32
                    if internal:
                        absolute.append(offset)
                elif kind in (28, 29):  # ARM call / tail branch
                    if not internal:
                        op, = unpack_from("<I", image, offset)
                        assert op >> 28 != 15 and op >> 25 & 7 == 5
                        branches.append(offset)
                elif kind == 30 and internal:  # Thumb branch within libgcc
                    continue
                else:
                    raise ValueError(f"unsupported relocation {kind} at {offset:#x}")
    assert all(0 <= n <= min(262140 if slot else 65535, len(image)-4) and n % 4 == 0 for n in absolute + branches)
    sizes = dict(LINK_BASE=LINK, KEEP_OFFSET=keep_offset, KEEP_BYTES=keep_size, IMAGE_BYTES=len(image),
                 MEMORY_BYTES=sy["__bss_end__"]-LINK)
    for name, symbol in (("TIMER_RESET","aprs_beacon_reschedule"), ("TX_STAGE","stage"),
                         ("POPUP_OWNED","aprs_popup_owned"), ("RX_READ","aprs_rx_read"),
                         ("RX_WRITTEN","aprs_rx_written")):
        sizes[name] = sy[symbol] - LINK
    sizes.update(ABS_COUNT=len(absolute), BRANCH_COUNT=len(branches))
    header = []
    sources = ["samples/aprs-overlay.c"]
    address = MANAGER
    options = ["-Os"]
    if slot:
        sizes.update(slot["write_resources"](folder, image, absolute + branches))
        sizes.update(slot["entries"], SET_CHANNEL=sy["aprs_set_channel"]-LINK,
                     TX_ENABLED=sy["aprs_tx_enabled"]-LINK, AUTO_ENABLE=sy["aprs_auto_beacon"]-LINK, NOTE_DMA=sy["aprs_note_dma"]-LINK,
                     COPY_PCM=sy["aprs_copy_pcm"]-LINK, RECORD_RX=sy["aprs_record_receive"]-LINK,
                     HISTORY_TAIL_PTR=sy["aprs_records"]-LINK, HISTORY_LAST_PTR=sy["aprs_history_last_bank"]-LINK)
        sizes.update({key:sy[name]-LINK for key,name in
                      (("RECORD_COUNT","aprs_record_count"),("CONFIG_POLL","aprs_config_poll"),("MSG_DISARM","aprs_messages_disarm"),("PANEL_UPDATE","aprs_update_panel"),("UI_BUSY","aprs_ui_busy"),("UI_RESTORE","aprs_ui_restore"),("UI_SETTINGS","aprs_slot_settings"),
                       ("UI_QUICK","aprs_ui_quick"),("TX_MOD","aprs_tx_mod_block"),("TX_REQUEST","aprs_tx_requested"),("TX_SOURCE","aprs_tx_source"))})
        sources.append(str(slot["gates"](sy)))
        address = slot["manager"]
        sources.append("samples/aprs-overlay-init.S")
        options.extend(["-DAPRS_SLOT_IMAGE", f"-Wl,-Tdata={address+0x11b0:#x}",
                        f"-Wl,--defsym,restore_picker_thumb={slot['restore']|1:#x}"])
    else:
        for name, offsets in (("absolute",absolute), ("branches",branches)):
            header.append(f"static const uint16_t {name}[] = {{{','.join(map(str,offsets))}}};")
    header.extend(f"#define {name} {n}u" for name, n in sizes.items())
    (folder/"aprs-overlay-layout.h").write_text("\n".join(header)+"\n", encoding="ascii")
    manager, ms = build_target(folder, "manager", sources, address,
        "aprs_overlay_prepare" if slot else "aprs_overlay_load", includes=(folder,), flags=(*options, f"-Wl,--defsym,radio_alloc={rom(0x20127a28):#x}",
        f"-Wl,--defsym,radio_free={rom(0x20127a78):#x}"))
    return image, sy, flags, sizes, manager, ms


def replay(folder, european, flags, rom, c, sub, value, away):
    from tools.verify_705_aprs_resident import populate
    image, linked, flags, sizes, manager, ms = build(folder, european, flags, rom)
    for addr, data, length in ((MANAGER,manager,ms["__bss_end__"]-MANAGER),(SOURCE,image,len(image))):
        c.mem_map(addr, (length+4095)&~4095)
        c.mem_write(addr, data)
    keep = sizes["KEEP_OFFSET"]
    n = sizes["KEEP_BYTES"]
    def load(saved=None):
        base = sub(ms["aprs_overlay_load"], SOURCE)
        assert base and base % 32 == 0 and sub(ms["aprs_overlay_load"], SOURCE) == base
        reference = folder/f"at-{base:x}"
        reference.mkdir(exist_ok=True)
        expected, actual_symbols = build_task(reference, european=european, base=base, flags=flags)
        expected = bytearray(expected)
        if saved is not None:
            expected[keep:keep+n] = saved
        actual = bytes(c.mem_read(base,len(expected)))
        assert actual == expected, [(hex(i),a,b) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b][:10]
        return base, actual_symbols

    base, sy = load()
    sub(sy["aprs_set_channel"],FM_HZ)
    c.mem_write(0x2038079a, bytes.fromhex("26112207123456"))
    parts = populate(c,sub,value,sy)
    def records():
        return b"".join(bytes(c.mem_read(addr,slots*340)) for addr,slots in parts)
    history = records()
    fields = dict(aprs_beacon_ssid=b"\x05", aprs_tx_enabled=b"\x01", aprs_tx_path=b"\x02",
                  aprs_auto_beacon=b"\x01", aprs_beacon_interval=b"\x04", selected_hz=pack("<I",FM_HZ),
                  saved_comment=b"IC-705 overlay test\0", comment_saved=b"\x01",saved_symbol=b"/>")
    for name, data in fields.items():
        c.mem_write(sy[name], data)
    arrival = bytes(c.mem_read(sy["arrival"],64*12))
    assert all(arrival[i+6:i+12]==bytes.fromhex("261122123456") for i in range(0,len(arrival),12))
    saved = bytes(c.mem_read(base+keep,n))
    for name in ("stage","aprs_popup_owned","aprs_rx_written"):
        addr = sy[name]
        original = bytes(c.mem_read(addr,1))
        c.mem_write(addr,bytes([original[0]^1]))
        assert sub(ms["aprs_overlay_unload"]) == 0
        c.mem_write(addr,original)
    assert sub(ms["aprs_overlay_unload"]) == 1 and sub(ms["aprs_overlay_unload"]) == 1
    # Reallocate and overwrite the same physical pages, so stale bytes cannot pass.
    alloc = rom(0x20127a28)
    scratch = sub(alloc,sizes["MEMORY_BYTES"]+31)
    assert (scratch+31)&~31 == base
    c.mem_write(base,b"\xa5"*sizes["MEMORY_BYTES"])
    sub(rom(0x20127a78),scratch)
    playback = away()
    filler = sub(alloc,sizes["MEMORY_BYTES"]+31)
    assert filler
    # Exhaust the remaining overlay-sized blocks, then retry after freeing them.
    pressure = []
    while ptr := sub(alloc,sizes["MEMORY_BYTES"]+31):
        pressure.append(ptr)
    assert not sub(ms["aprs_overlay_load"],SOURCE)
    for ptr in reversed(pressure):
        sub(rom(0x20127a78),ptr)
    c.mem_write(0x20380714,pack("<I",FM_HZ))
    c.mem_write(0x203e2128,b"\x70\x00")
    c.mem_write(0x20381e08,pack("<I",0x12345678))
    second, restored = load(saved)
    assert second != base and value(restored["beacon_cycle_started"]) == 0x12345678
    assert value(restored["aprs_records"]) == parts[-1][0] and value(restored["aprs_record_count"]) == 64
    assert records() == history and bytes(c.mem_read(restored["arrival"],len(arrival))) == arrival
    for name,data in fields.items():
        assert bytes(c.mem_read(restored[name],len(data))) == data
    assert value(restored["aprs_channel_hz"]) == sub(restored["aprs_active_frequency"]) == FM_HZ
    assert bytes(c.mem_read(sub(restored["aprs_beacon_comment"]),len(fields["saved_comment"]))) == fields["saved_comment"]
    assert bytes(c.mem_read(sub(restored["aprs_beacon_symbol"]),2)) == b"/>"
    from tools.replay_705_aprs_fm import ax25_burst
    wave = ax25_burst("!3532.00N/13931.00E>after reload",45,source="K1ABC-9")
    pcm = 0x21400000
    c.mem_map(pcm,(len(wave)*2+4095)&~4095)
    c.mem_write(pcm,pack(f"<{len(wave)}h",*wave))
    for start in range(0,len(wave),288):
        sub(restored["aprs_rx_feed"],pcm+start*2,min(288,len(wave)-start))
    sub(restored["aprs_record_receive"])
    assert value(restored["aprs_record_count"]) == 65
    updated = records()
    assert b"after reload" in updated[:340] and updated[340:] == history[340:]
    assert value(restored["arrival"]) == 65
    c.mem_unmap(pcm,(len(wave)*2+4095)&~4095)
    sub(rom(0x20127a78),filler)
    return dict(first_base=hex(base),second_base=hex(second),heap_requested=sizes["MEMORY_BYTES"]+31,
                saved_bytes=n,manager_bytes=len(manager),history_sha256=sha256(history).hexdigest(),
                records=64,arrival_times=64,both_loads_match_independent_links=True,
                resumed_bound_fm_hz=FM_HZ,received_after_reload="K1ABC-9",oldest_slot_replaced=True,
                retried_after_allocation_failure=True,
                unload_refused_during=["TX","popup","queued frame"],modes_while_unloaded=playback)
