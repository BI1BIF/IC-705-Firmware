"""Replay the E140 FT receiver on a local virtual radio using J140 TX2j build artifacts."""
import argparse
import json
from hashlib import sha256
from struct import pack, pack_into, unpack_from

from tools.build_705_cw_sim import END, PICKER_REFERENCES, PICKER_TABLE
from tools.build_705_ftx_rx import (FT_DATA_OFFSET, FT_DATA_RAM, GLYPH_OFFSET, INDEX_OFFSET,
                                    KEY_OFFSET, MENU, DUP, OUT, PIXEL_OFFSET, ROOT, SITES, STRIDE,
                                    pack_init_tail, word)
from tools.decode_705_main import BOOT_SIZE, J140_MAIN_SHA, decode_main
from tools.emulate_705 import BASE, BOOT, SCRATCH, arm, call, machine, uc
from tools.probe_705_boot_selection import FIRST, SECOND, MARKER, NOR_BYTES
from tools.probe_705_rtx_audio import CURRENT, IDLE, LOOP, PCM_DONE, SEM_WAIT, TIMER, TIMERS_CLEARED, probe
from tools.probe_705_sstv_picture import branch
from tools.render_705_display import GRAPHICS_FLASH
from tools.replay_705_ftx_live import recording
from tools.replay_705_nor_boot import boot_from_nor, with_pc_main
from tools.replay_705_stock_install import A_PREFIX, SHARED, load_a
from tools.verify_705_ftx_rx import fixture, published_rows, symbols

REPORTS = ROOT / ".analysis/e140-port"
E_MAIN = "3df33f33de9b2754a86cc61608334e61364e409f5a8ce905f0fac0e42afd3b3c"
E_DAT = "132383f8388641d02d0fadaccf9878d01a1960fa77a028328f0eb33dcfbc147b"
TX2J = "8dcb44ae45c02d963d4eba6c9feca23d97f1e90b1f0409f75366de7d467c3c68"
E_KEYS = INDEX_OFFSET - 0x18000 + 704 + 352
AUDIO_SHIFT = 228

# Each location belongs to the known TX2j build. Only port the services exercised here.
SERVICE_LITERALS = (
    (0x200cd7dc, 228, (0x20371484,)),  # menu selection and deferred startup
    (0x200cd828, 228, (0x2037f7c8,)), (0x200f192c, 228, (0x2037f7cc,)),
    (0x200f1e48, 228, (0x2037f7dc,)), (0x200f1f04, 228, (0x2037f7e4, 0x20371328)),
    (0x20080a34, -152, (0x2037f7ec,)), (0x20080e50, -152, (0x2037f7f0,)),
    (0x202d48c1, 224, (0x2037f800,)),  # create, signal and wait
    (0x202d4851, 224, (0x2037016c,)), (0x202d488c, 224, (0x20372f38,)),
    (0x20127a28, 228, (0x2036f738,)), (0x20127a78, 228, (0x2036f744,)),  # heap
    (0x2023fec8, 228, (0x2037e858,)), (0x2023ff18, 228, (0x2037e85c,)),
    (0x2023ff00, 228, (0x2037e860,)), (0x2023fee4, 228, (0x2037e864,)),
    (0x20263191, 228, (0x2037c7e0, 0x2037ed80)),  # finish bitmap draw
    (0x20263b13, 228, (0x2037c6d4, 0x2037d148, 0x2037d7b0, 0x2037ed7c)),  # FT bitmap blits
)


def replace(image, address, original, new):
    assert word(image, address) == original, hex(address)
    pack_into("<I", image, address - BASE, new & 0xffffffff)


def connect_panel(image, sy):
    # Picker IDs 317..319 require the same halfword selection and blank-row handling as J.
    replace(image, 0x200cdcb0+228, 0xe5d52000, 0xe1d520b0)
    site = 0x200cdd08+228
    replace(image, site, 0xe3550047, branch(site, 0x2036a004))
    for name, delta, expected in (("touch", -152, 0xeb022599), ("input", -152, 0xebfff8d2),
                                  ("frame", 228, 0xe59f0330), ("prepare", 228, 0xe92d5ff0)):
        site = SITES[name]+delta
        replace(image, site, expected, branch(site, sy["ftx_"+name+"_bridge"]))
    # Resume stock polling/composition downstream from the existing CW/SSTV bridges.
    for api, delta, locations in (
        (0x200ce238,228,(0x2036a260,)), (0x200cdd0c,228,(0x2036a264,)),
        (0x2021300c,228,(0x2037177c,0x2037dc10)), (0x20212b64,228,(0x20371780,0x2037dc14)),
        (0x20212b80,228,(0x2037dc18,)),
        (0x2007f110, -152, (0x2036a26c,0x2037f8ec)), (0x201085fc,228,(0x2036a270,)),
        (0x2007f1a8,-152,(0x2036a274,)), (0x2007d4f4,-152,(0x2036a278,)),
        (0x2013d4ac,228,(0x2036a288,)), (0x2013c5ec,228,(0x2037a060,)),
        (0x2007d478,-152,(0x203744d4,)), (0x200f192c,228,(0x203744d8,)),
        (0x20090630,-152,(0x203744c8,)), (0x20090a80,-152,(0x203744cc,)),
        (0x20142698,228,(0x2037c9f0,)), (0x20263000,228,(0x2037c670,)),
        (0x202631f3,228,(0x2037c7e4,)), (0x20195188,228,(0x2037ca28,)),
        (0x20194c10,228,(0x2037ca2c,)), (0x201951ac,228,(0x2037c800,0x2037ca30)),
        (0x202632a1,228,(0x2037ca38,)), (0x20194c18,228,(0x2037c7ec,)),
        (0x20195190,228,(0x2037c7f4,)), (0x20148430,228,(0x2037cec4,)),
    ):
        for location in locations:
            replace(image, location, api, api+delta)
    # Compiler expressed the MODE picker call relative to the RAM menu state.
    replace(image, 0x2037442a, 0x639bf5a3, 0x33f4f2a3)


def connect_station(image, tx2j, sy):
    sstv = symbols(OUT/"sstv/rx.elf")
    bl = 0xeb000000
    for j, delta, expected, target, opcode in (
        (0x20060d28, -240, 0xe7d00001, sstv["sstv_tx_source_hook"], 0xea000000),
        (0x20109674, 228, 0xe1a012a0, sstv["sstv_tx_request_hook"], 0xea000000),
        (0x200ffeb0, 228, branch(0x200ffeb0, 0x201f644c, bl), sy["ft_tx_mod_block_arm"], bl),
    ):
        assert word(tx2j, j) == branch(j, target, opcode)
        replace(image, j+delta, expected, branch(j+delta, target, opcode))
    for api, delta, places in (
        (0x20109678, 228, (0x2037a070,)), (0x20060d2c, -240, (0x2037a074,)),
        (0x201031dc, 228, (0x203740e4, 0x2037b088)),  # native split TX frequency
        (0x202d48c1, 224, (0x2037ded0,)),  # ADIF worker
        (0x2023ff00, 228, (0x2037acf4,)), (0x2023ff64, 228, (0x2037acf8, 0x2037e470)),
        (0x2023fec8, 228, (0x2037e46c,)), (0x2023fee4, 228, (0x2037e474,)),
        (0x2023ff18, 228, (0x2037e48c,)),
        (0x20074650, -152, (0x2037ee80,)), (0x20073b70, -152, (0x2037ee70,)),
        (0x20073b58, -152, (0x2037ee74,)),
    ):
        for place in places:
            replace(image, place, api, api+delta)
    # Original modulation when neither FT nor SSTV owns the transmitter.
    replace(image, 0x20377038, 0xe306044c, 0xe3060530)


def panel_and_init(stock, tx2j, image, sy):
    """Keep E's RAM defaults while fitting the complete FT panel at its linked address."""
    src, dest, size, copier = unpack_from("<4I", stock, 0x30c)
    defaults = stock[src-BASE:src-BASE+size]
    panel = 0x20369ac0
    panel_end = 0x20369fa8
    assert src + size == BASE + len(stock) == panel + 796
    split = panel-src
    table = word(tx2j, BASE+0x2e4)-BASE
    assert table+80 == len(image)
    image[0x2e4:0x2ec] = pack("<II", BASE+table, BASE+table+112)
    records = bytearray(pack("<4I", src, dest, split, copier))
    # Store two short streams in padding outside every linked code/data section.
    second = split+208
    streams = ((panel_end, split, second), (BASE+table+112, second, size))
    image[panel-BASE:panel_end-BASE] = tx2j[panel-BASE:panel_end-BASE]
    assert not any(image[panel_end-BASE:0x2036a000-BASE])
    for address, begin, end in streams:
        data = pack_init_tail(defaults[:end], begin)
        limit = 0x2036a000 if begin == split else END
        assert address+len(data) <= limit
        records.extend(pack("<4I", address, dest+begin, 0, sy["ft_restore_modes"]))
        if begin == split:
            image[address-BASE:address-BASE+len(data)] = data
        else:
            tail = data
    records.extend(stock[0x31c:0x33c])
    records.extend(tx2j[table+48:table+80])
    pack_into("<I", records, 80, PICKER_TABLE+224)
    image[table:] = records + tail
    assert BASE+len(image) <= END
    return src, dest, defaults


def connect_other_receivers(image, tx2j):
    """Connect KEYER, PICTURE and its SSTV photo, history and transmit controls."""
    from tools.build_705_cw_sstv_rx import D6
    cw = json.loads((D6/"CW-RX3-WAKE2-PC/symbols.json").read_text())
    sstv = symbols(OUT/"sstv/rx.elf")
    for addr, delta, expected, target, opcode in (
        (0x200d4ef0,228,branch(0x200d4ef0+228,0x2011df40+228,0xeb000000),cw["cw_sim_boot"],0xea000000),
        (0x20087990,-152,0xe3a0000d,cw["cw_picker_open"],0xea000000),
        (0x2010fe34,228,0xe59d0004,cw["cw_diag_raw_bridge"],0xea000000),
        (0x2008744c,-152,branch(0x2008744c-152,0x200801e4-152,0xeb000000),sstv["sstv_picker_open"],0xeb000000),
        (0x200c4620,228,0xe92d4010,sstv["sstv_pict_tx"],0xea000000),
        (0x200c46cc,228,0xe92d4008,sstv["sstv_tx_all"],0xea000000),
        (0x200c493c,228,0xe92d4010,sstv["sstv_archive_button"],0xea000000),
        (0x200c4d90,228,0xe92d403e,sstv["sstv_tx_mode_button"],0xea000000),
        (0x20190150,228,branch(0x20190150,0x2018e7e8,0xeb000000),sstv["sstv_tx_detail_draw"],0xeb000000),
        (0x2018e838,228,0xe59f4430,sstv["sstv_image_hook"],0xea000000),
        (0x2018f818,228,0xe5d4001d,sstv["sstv_thumbnail_hook"],0xea000000),
    ):
        assert word(tx2j,addr) == branch(addr,target,opcode)
        replace(image,addr+delta,expected,branch(addr+delta,target,opcode))
    for addr in (0x2018fd0c,0x201911d0,0x20191268,0x2018f104,0x2018f240,0x20190bc8,0x20190e30,0x20190e74,
                 0x201903f8,0x201905e8,0x20190778,0x20190808,0x201908a0):
        e = addr+228
        replace(image,e,branch(e,0x20142698+228,0xeb000000),branch(e,sstv["sstv_picture_label"],0xeb000000))
    for api,delta,places in (
        (0x200c4624,228,(0x2037a078,)), (0x200c46d0,228,(0x2037a07c,)),
        (0x2018e7e8,228,(0x2037a080,)), (0x201901c0,228,(0x2037a084,)),
        (0x200c4d94,228,(0x2037a088,)), (0x200c4940,228,(0x2037a08c,)),
        (0x20060448,-240,(0x2036de48,)), (0x2007d478,-152,(0x2036c920,)),
        (0x200801e4,-152,(0x2036b1e4,0x2036cc84)), (0x20090630,-152,(0x2036c910,)),
        (0x20090a80,-152,(0x2036c914,)), (0x200cd628,228,(0x2036cc90,)),
        (0x200cd7dc,228,(0x2036cc18,)), (0x200cd828,228,(0x2036b1dc,0x2036b858)),
        (0x200d4ef4,228,(0x2036a2a4,)), (0x200efe64,228,(0x2036b86c,0x2036cc88)),
        (0x200f0fdc,228,(0x2036c8fc,0x2036cbd8)), (0x200f192c,228,(0x2036b864,)),
        (0x2010fe38,228,(0x2036a280,)), (0x2011df40,228,(0x2036a2a8,)),
        (0x20127a28,228,(0x2036a294,0x2036e7a8)), (0x20127a78,228,(0x2036a2a0,0x2036e7d8)),
        (0x20142698,228,(0x2036a570,0x2036a5f0,0x2037a06c)), (0x2014289c,228,(0x2036a9c8,)),
        (0x20145454,228,(0x2036d620,)), (0x20148238,228,(0x2036d724,)), (0x20148430,228,(0x2036d720,)),
        (0x2018e83c,228,(0x2037a064,)), (0x2018f81c,228,(0x2037a068,)),
        (0x20194c10,228,(0x2036e798,)), (0x20194c18,228,(0x2036e7cc,)),
        (0x20195188,228,(0x2036e794,)), (0x20195190,228,(0x2036e7d0,)),
        (0x201951ac,228,(0x2036e7ac,)), (0x20263191,228,(0x2036e7c4,)),
        (0x20263000,228,(0x2036a8e8,)), (0x202631f3,228,(0x2036e7b8,)), (0x202632a1,228,(0x2036e7b4,)),
        (0x20263b13,228,(0x2036a93c,0x2036e7c0)), (0x202d4851,224,(0x2036cdc4,)),
        (0x202d488c,224,(0x2036e80c,)), (0x202d48c1,224,(0x2036a29c,)),
    ):
        for loc in places:
            replace(image,loc,api,api+delta)
    # In these named receive routines clang split each API address into movw/movt.
    for address,delta,places in (
        (0x200cd828,228,(0x203760f0,0x20378cbc)), (0x200cd7dc,228,(0x203760d0,0x20378c98)),
        (0x200cd628,228,(0x20376208,0x20379578)), (0x200c27c0,228,(0x20376604,0x20376840)),
        (0x20127a28,228,(0x203766bc,)), (0x202c8f51,228,(0x203766e0,)),
        (0x20127a78,228,(0x20379148,0x203791b0,0x203792e4)),
        (0x2023fee4,228,(0x20378d78,0x20378eb0)), (0x200c490c,228,(0x20379364,)),
        (0x200c27e8,228,(0x20379378,)), (0x2023fec8,228,(0x203793e8,0x20379448)),
        (0x201909e8,228,(0x20378bfc,)), (0x2018f84c,228,(0x20378c18,)),
        (0x202d48c1,224,(0x20374874,)), (0x20127a28,228,(0x203748bc,)),
        (0x202d488c,224,(0x20374a20,)), (0x202d4851,224,(0x20374c80,)),
        (0x200cd828,228,(0x20374ac8,0x20378bdc)), (0x200801e4,-152,(0x20374ad4,0x20378be8)),
        (0x20127a78,228,(0x20377cac,0x20377e20)), (0x200efe64,228,(0x20378b4c,)),
        (0x200cd628,228,(0x20378b60,)), (0x200cd7dc,228,(0x20378bac,)),
    ):
        for loc in places:
            ins = word(image,loc)
            imm = (ins >> 4 & 0xf000) | (ins & 0xfff)
            assert ins >> 20 == 0xe30 and imm == address & 0xffff
            imm += delta
            assert 0 <= imm <= 0xffff
            replace(image,loc,ins,(ins & ~0xf0fff) | ((imm & 0xf000)<<4) | (imm & 0xfff))


def region_menu(image, stock, tx2j):
    """Re-encode custom rows against the E records that the scatter loader actually copies."""
    c = machine(tx2j)
    c.emu_start(0x200052c9, 0x200052a8, count=12000000)
    assert c.reg_read(arm.UC_ARM_REG_PC) == 0x200052a8
    japanese = bytes(c.mem_read(MENU, 320*STRIDE))
    table = PICKER_TABLE+224-BASE
    records = bytearray(stock[table:table+277*STRIDE])
    for row in range(277, 320):
        fields = list(unpack_from("<18I", japanese, row*STRIDE))
        for field, ptr in enumerate(fields):
            if BASE <= ptr < 0x20369ac0:
                offsets = [i*STRIDE+field*4 for i in range(277)]
                matches = {unpack_from("<I", records, off)[0] for off in offsets
                           if unpack_from("<I", japanese, off)[0] == ptr}
                assert len(matches) == 1, (row, field, hex(ptr))
                fields[field] = matches.pop()
        records.extend(pack("<18I", *fields))
    stream = pack_init_tail(records, 277*STRIDE)
    end = DUP+317*STRIDE
    descriptor = word(image, BASE+0x2e8)-16
    old = word(image, descriptor)
    assert old <= end-len(stream) and old > 0x203744ec
    image[end-len(stream)-BASE:end-BASE] = stream
    replace(image, descriptor, old, end-len(stream))
    return records


def prepare(sy):
    package = (ROOT/"firmware/705E140.dat").read_bytes()
    assert sha256(package).hexdigest() == E_DAT
    stock, flash = load_a(package, E_MAIN)
    j_stock = bytes(decode_main((ROOT/"firmware/705J140.dat").read_bytes())[1])
    package = (OUT/"bench-rx.dat").read_bytes()
    assert sha256(j_stock).hexdigest() == J140_MAIN_SHA and sha256(package).hexdigest() == TX2J
    tx2j = bytes(decode_main(package)[1])
    image = bytearray(stock + tx2j[len(stock):])
    _, dest, defaults = panel_and_init(stock, tx2j, image, sy)
    for address in PICKER_REFERENCES:
        replace(image, address+228, PICKER_TABLE+224, MENU)
    for api, delta, refs in SERVICE_LITERALS:
        i = (api & ~1)-BASE
        assert sum(a == b for a,b in zip(j_stock[i:i+32], stock[i+delta:i+delta+32])) >= 23
        for address in refs:
            replace(image, address, api, api+delta)
    replace(image, 0x202d3a64+224, 0x20830a40, FT_DATA_RAM)
    pcm = SITES["pcm"]+AUDIO_SHIFT
    replace(image, pcm, 0xe3a04000, branch(pcm, sy["ftx_pcm_bridge"]))
    replace(image, 0x2036a27c, SITES["pcm"]+4, pcm+4)
    expected_records = region_menu(image, stock, tx2j)
    connect_panel(image, sy)
    connect_other_receivers(image, tx2j)
    connect_station(image, tx2j, sy)
    # ft_key folds one scanline (-352) into the tile offset. Only its upper add changes.
    replace(image, 0x2037d0ae, 0x3003f500, 0x30c0f5a0)
    replace(image, 0x2037d7a8, 0x26ae0, 0x26ae0+E_KEYS-KEY_OFFSET)

    cpu = machine(bytes(image))
    cpu.mem_write(dest, b"\xa5"*len(defaults))
    cpu.emu_start(0x200052c9, 0x200052a8, count=12000000)
    assert cpu.reg_read(arm.UC_ARM_REG_PC) == 0x200052a8
    assert cpu.mem_read(dest, len(defaults)) == defaults
    assert cpu.mem_read(MENU, len(expected_records)) == expected_records

    image = bytes(image)
    resources = bytearray(with_pc_main(flash[:A_PREFIX], image, match_depth=20))
    slot = SECOND-GRAPHICS_FLASH
    packed_end = slot+8+unpack_from("<I", resources, slot)[0]
    assert packed_end <= E_KEYS
    atlas = (OUT/"countries.bin").read_bytes()
    split = unpack_from("<I", atlas, 16)[0]
    assets = ((E_KEYS, (OUT/"key-faces.bin").read_bytes()),
              (FT_DATA_OFFSET, (OUT/"ftdata.bin").read_bytes()),
              (GLYPH_OFFSET, (OUT/"glyphs.bin").read_bytes()),
              (INDEX_OFFSET, atlas[:split]), (PIXEL_OFFSET, atlas[split:]))
    for at, data in assets:
        assert resources[at:at+len(data)+1] == b"\xff"*(len(data)+1)
        resources[at:at+len(data)] = data
    assert resources[KEY_OFFSET:KEY_OFFSET+len(assets[0][1])] == flash[KEY_OFFSET:KEY_OFFSET+len(assets[0][1])]
    checks = dict(factory_init_bytes=len(defaults), factory_records=277,
                  packed_slot_end=hex(packed_end), keys=hex(E_KEYS), key_bytes=len(assets[0][1]))
    return stock, flash, image, bytes(resources), checks


def capture_cq_key(c, sy, delta):
    """Collect RGB565 at the OpenVG device boundary. The guest paints the key and label."""
    width, height = 78, 32
    pixels = bytearray(width * height * 2)
    covered = set()

    def draw(cpu, *_):
        source, stride, _, x = [cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
            arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)]
        y, w, h = unpack_from("<3I", cpu.mem_read(cpu.reg_read(arm.UC_ARM_REG_SP), 12))
        assert stride & 0x80000000
        for line in range(h):
            row = 272-y-line-1-89
            column = x-398
            assert 0 <= row < height and 0 <= column <= width-w
            offset = 2*(row*width+column)
            pixels[offset:offset+2*w] = cpu.mem_read(source+(stride-2**32)*line, 2*w)
            covered.update(range(offset//2, offset//2+w))
        cpu.reg_write(arm.UC_ARM_REG_PC, cpu.reg_read(arm.UC_ARM_REG_LR))

    def finish(cpu, *_):
        cpu.reg_write(arm.UC_ARM_REG_PC, cpu.reg_read(arm.UC_ARM_REG_LR))

    for target, handler in ((0x20263b12, draw), (0x20263190, finish)):
        c.hook_add(uc.UC_HOOK_CODE, handler, begin=target+delta, end=target+delta)
    assert call(c, sy["ft_data_ready"]) != 0
    c.mem_write(SCRATCH, bytes((127, 1, 0)))
    call(c, sy["ft_key"], SCRATCH, 398, 89, width, height, instruction_limit=500000)
    assert len(covered) == width*height and len(set(pixels)) > 16
    return bytes(pixels)


def check_banks(image, flash, resources, sy):
    snapshot = bytearray(b"\xff"*NOR_BYTES)
    snapshot[:BOOT_SIZE] = flash[:BOOT_SIZE]
    snapshot[SHARED:SHARED+len(flash)-A_PREFIX] = flash[A_PREFIX:]
    j_main, j_flash = load_a((OUT/"bench-rx.dat").read_bytes(),
        "7cb2d6a9bf078550346531c9c1f007bc13edf48fbbb0ca96735c7269e97ce0ed")
    ref = machine(j_main)
    ref.mem_map(GRAPHICS_FLASH, A_PREFIX, uc.UC_PROT_READ)
    ref.mem_write(GRAPHICS_FLASH, j_flash[:A_PREFIX])
    key = capture_cq_key(ref, sy, 0)
    banks = {}
    for address in (FIRST, SECOND):
        offset = address-BOOT
        snapshot[offset:offset+A_PREFIX-BOOT_SIZE] = resources[BOOT_SIZE:]
        if address == SECOND:
            snapshot[MARKER-BOOT:MARKER-BOOT+16] = flash[0x47e8:0x47f8]
        c = machine()
        boot = boot_from_nor(c, None, image, snapshot=bytes(snapshot))
        assert int(boot["source_slot"],16) == address and boot["application_sha256"] == sha256(image).hexdigest()
        # Supply the active-bank selector and execute the real FT Chinese-label width reader.
        c.mem_write(0x2038089d, bytes([address == FIRST]))
        widths = [call(c, sy["panel_word"], i, 0, 0, 0, 0) for i in (1, 2, 3)]
        assert all(widths) and (not banks or widths == next(iter(banks.values()))["label_widths"])
        assert capture_cq_key(c, sy, 228) == key
        banks[hex(address)] = dict(main_sha256=boot["application_sha256"], label_widths=widths,
                                   cq_key_rgb565_sha256=sha256(key).hexdigest())
    return banks

def replay(stock, image, resources, sy, mode, slots):
    ft4 = mode == "FT4"
    samples = 60000 if ft4 else 120000
    wav = (ROOT/".analysis/ftx-station/FT4/busy/000000_000001.wav" if ft4 else
           ROOT/".analysis/ftx-lib/test/wav/websdr_test1.wav")
    audio = recording(wav, samples)
    if ft4:
        expected = {line.split(maxsplit=5)[5].strip() for line in wav.with_name("generated.txt").read_text().splitlines() if line.strip()}
    else:
        # Same thirteen decodes obtained from the previous TX2j replay on this WebSDR recording.
        expected = {line.split("~", 1)[1].strip().split("   ", 1)[0] for line in wav.with_suffix(".txt").read_text().splitlines()[:13]}

    def exercise(c, run, irq, sub, value):
        idle, loop = IDLE+AUDIO_SHIFT, LOOP+AUDIO_SHIFT
        c.mem_map(GRAPHICS_FLASH, len(resources), uc.UC_PROT_READ)
        c.mem_write(GRAPHICS_FLASH, resources)
        c.mem_write(0x2038089d, b"\0")
        c.mem_write(0x203e2128, b"\x10\x01")  # USB-D
        c.mem_write(0x204bab5d, b"\x01")      # awake on HOME, no SD card
        c.mem_write(sy["ftx_choice"], pack("<I", ft4))

        def enter():
            frame = c.context_save()
            assert sub(value(MENU+317*STRIDE+12)) == 2
            start = value(0x203e1b10)
            assert start == sy["start"]
            sub(start)
            c.context_restore(frame)
            assert value(sy["state"]) == 1
            return value(sy["thread"])

        def tick():
            irq(TIMER, idle)
            irq(0, loop)

        task = enter()
        stack = value(task+0x26, 2)
        assert task and stack == 4096
        # The virtual board has no downstream physical sound sink.
        def skip_sink(cpu, *_):
            cpu.reg_write(arm.UC_ARM_REG_PC, 0x200d5230+AUDIO_SHIFT)

        c.hook_add(uc.UC_HOOK_CODE, skip_sink, begin=PCM_DONE+AUDIO_SHIFT, end=PCM_DONE+AUDIO_SHIFT)
        run(TIMERS_CLEARED+AUDIO_SHIFT, SEM_WAIT+AUDIO_SHIFT, limit=10000000)
        run(SEM_WAIT+AUDIO_SHIFT, idle, limit=10000000)
        memory = value(sy["ftx_memory"])
        assert value(sy["state"]) == 2 and memory
        feed = fixture(c, map_dma=False, e140=True)
        c.mem_write(sy["ftx_rtc"], pack("<I", 1))
        c.mem_write(0x180000, audio)
        c.mem_write(0x1c0000, bytes(samples*2))
        stats, owners = {}, set()
        last_second = None

        def observe_owner(cpu, *_):
            owners.add(value(CURRENT))

        step = sy["ftx_step"] & ~1
        c.hook_add(uc.UC_HOOK_CODE, observe_owner, begin=step, end=step)
        end = samples*slots+24000
        for pos in range(-48000, end, 576):
            tick()
            frame = c.context_save()
            stop = min(pos+576, end)
            while pos < stop:
                slot, index = divmod(pos, samples)
                second = pos//8000
                if second != last_second:
                    day = second % 86400
                    clock = f"{day//3600:02}{day//60%60:02}{day%60:02}"
                    c.mem_write(0x2038079e, bytes.fromhex(clock))
                    last_second = second
                until = min(stop, (slot+1)*samples, ((second+1)*8000+5)//6*6)
                source = 0x180000 if 0 <= slot < slots else 0x1c0000
                sub(feed, source+index*2, (until-pos)//6)
                pos = until
            c.context_restore(frame)
            run(loop, idle, limit=500000000)
            mid = value(sy["middle"])
            if mid & 4:
                batch = memory+32768+(mid & 3)*(8+48*44)
                rows, _ = published_rows(c, batch)
                if rows:
                    stats[value(batch+4) % (86400*8000//samples)] = rows
        assert owners == {task} and set(stats) == set(range(slots))
        assert not value(sy["gaps"]) and not value(sy["overruns"])
        assert all(set(rows) == expected and len(rows) == len(expected) for rows in stats.values())
        result = dict(task=hex(task), stack=stack, worker_memory=hex(memory), slots=stats, gaps=0, overruns=0,
                      adc=value(sy["adc"]), main_sha256=sha256(image).hexdigest())

        exits = []
        for attempt in range(2):
            tick()
            frame = c.context_save()
            c.mem_write(0x20380431, b"\x09")
            sub(sy["ftx_input"])
            c.mem_write(0x20380431, b"\0")
            c.context_restore(frame)
            run(loop, idle, limit=10000000)
            cleared = {name:value(sy[name]) for name in ("state","thread","ftx_memory")}
            assert not any(cleared.values())
            exits.append(cleared)
            if attempt == 0:
                tick()
                enter()
                run(loop, idle, limit=10000000)
                assert value(sy["state"]) == 2 and value(sy["ftx_memory"])
        result["exit_reopen_exit"] = exits
        return result

    return probe(stock, application=image, audio_experiment=exercise)


def check_other_receivers(image):
    """Replay the two sibling decoders directly to isolate regressions in the FT port."""
    from array import array
    import wave
    from tools.build_705_cw_sim import load_image
    from tools.build_705_cw_sstv_rx import D6
    from tools.probe_705_cw_field_audio import STATE, audio as cw_audio, bl_target
    from tools.probe_705_cw_session import read_session
    from tools.probe_705_sstv_arm import counters

    def reset():
        c = machine(image)
        c.emu_start(0x200052c9, 0x200052a8, count=12000000)
        assert c.reg_read(arm.UC_ARM_REG_PC) == 0x200052a8
        return c

    c = reset()
    _, meta = load_image(D6/"CW-RX3-WAKE2-PC/CW-RX3-WAKE2-PC.ic705sim")
    sy = meta["symbols"]
    c.mem_write(sy["cw_state_anchor"], pack("<I", STATE))
    c.mem_write(STATE, pack("<2I", 1, 1))
    c.mem_write(STATE+1692, pack("<I", 350))
    c.mem_write(0x203e2128, b"\x20")
    pcm = bl_target(image, sy["cw_pcm_bridge"]+32)
    work = bl_target(image, sy["cw_rtx_worker"]+28)
    sound = cw_audio("CQ", trim_leading=True)+bytes(3204)
    for offset in range(0, len(sound)-11, 12):
        c.mem_write(SCRATCH, sound[offset:offset+12])
        call(c, pcm, SCRATCH, timeout_us=0)
        call(c, work, 1, timeout_us=0)
    text = read_session(c, STATE)["text"].strip()
    assert text == "CQ"

    c = reset()
    sy = symbols(OUT/"sstv/rx.elf")
    canvas = 0x20700000
    c.mem_write(sy["canvas_owner"], pack("<I", canvas))
    c.mem_write(sy["sstv_thread"], pack("<I", 1))
    c.mem_write(0x203e84c9, pack("<H", 21))
    call(c, sy["sstv_begin"])
    c.mem_write(sy["sstv_thread"], bytes(4))
    assert counters(c, sy)["active"] == 1
    with wave.open(str(ROOT/".analysis/sstv-robot36-v1/robot36.wav")) as f:
        assert (f.getnchannels(), f.getsampwidth(), f.getframerate()) == (1, 2, 48000)
        sound = array("h", f.readframes(f.getnframes()))[::6].tobytes()
    for offset in range(0, len(sound), 12*18):
        buf = sound[offset:offset+12*18]
        c.mem_write(SCRATCH, buf)
        for n in range(0, len(buf), 12):
            call(c, sy["sstv_capture"], SCRATCH+n, timeout_us=0)
        call(c, sy["sstv_worker"], timeout_us=0)
    stats = counters(c, sy)
    pixels = sha256(c.mem_read(canvas, 320*240*2)).hexdigest()
    reference = json.loads((ROOT/".analysis/sstv-auto-rx/evidence.json").read_text())
    assert stats["rows"] == 240 and not stats["dropped"] and pixels == reference["image_rgb565_sha256"]
    return dict(cw=text, robot36_rows=stats["rows"], dropped=stats["dropped"],
                rgb565_sha256=pixels, main_sha256=sha256(image).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("FT4","FT8","banks","cw-sstv","panel-ft4","panel-ft8"))
    args = parser.parse_args()
    sy = symbols(OUT/"rx.elf")
    stock, flash, image, resources, checks = prepare(sy)
    if args.mode == "banks":
        result = dict(layout=checks, banks=check_banks(image, flash, resources, sy))
    elif args.mode.startswith("panel-"):
        from tools.replay_705_e140_panel import panel
        result = panel(stock, flash, image, resources, sy, args.mode[6:].upper())
    elif args.mode == "cw-sstv":
        result = check_other_receivers(image)
    else:
        result = replay(stock, image, resources, sy, args.mode, 8 if args.mode == "FT4" else 6)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS/f"native-rx-{args.mode.lower()}.json"
    path.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
