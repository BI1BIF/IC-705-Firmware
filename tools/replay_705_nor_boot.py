"""Run the original J140 NOR reset and decompressor on a fresh emulator CPU."""

from hashlib import sha256
from struct import pack, unpack_from

from tools.decode_705_main import BOOT_SIZE, lzss
from tools.emulate_705 import BASE, BOOT, BOOT_HASH, arm, uc
from tools.probe_705_boot_selection import FIRST, SECOND, MARKER, LZSS, HANDOFF, NOR_BYTES
from tools.render_705_display import GRAPHICS_FLASH
from tools.render_705_stock_row import require


DSFR, POWER_KEY, POWER_LATCH = 0xFCFF1808, 0xFCFE3220, 0xFCFE3028


def with_pc_main(flash, main, *, deeper=False):
    """Build the PC-only compressed slot in memory, preserving the other NOR data."""
    stream = bytearray()
    last, pos = {}, 0
    previous = [-4097] * 4096 if deeper else None
    while pos < len(main):
        flag, flags = len(stream), 0
        stream.append(0)
        for bit in range(8):
            length, prior = 0, last.get(main[pos:pos+3], -4097)
            if pos-prior <= 4096 and pos+3 <= len(main):
                length = 3
                while length < min(18, len(main)-pos) and main[prior+length] == main[pos+length]:
                    length += 1
                if deeper and length < 18:
                    other = previous[prior & 4095]
                    if pos - other <= 4096:
                        end = 3
                        while end < min(18, len(main)-pos) and main[other+end] == main[pos+end]:
                            end += 1
                        if end > length:
                            prior, length = other, end
            if length:
                index = (prior+0xFEE) & 0xFFF
                stream.extend((index & 0xFF, (index >> 4 & 0xF0) | (length-3)))
            else:
                length, flags = 1, flags | 1 << bit
                stream.append(main[pos])
            for n in range(pos, pos+length):
                old = n-4096
                if old >= 0 and last.get(main[old:old+3]) == old:
                    del last[main[old:old+3]]
                key = main[n:n+3]
                if deeper:
                    previous[n & 4095] = last.get(key, -4097)
                last[key] = n
            pos += length
            if pos == len(main):
                break
        stream[flag] = flags
    decoded, consumed = lzss(stream, len(main))
    require(decoded == main and consumed == len(stream), "PC NOR stream did not round-trip")
    at = SECOND-GRAPHICS_FLASH
    old_size, = unpack_from("<I", flash, at)
    end = at+8+len(stream)
    require(end <= len(flash) and not flash[at+8+old_size:end].strip(b"\xff"),
            "PC stream overlaps unrelated virtual NOR data")
    return flash[:at]+pack("<II", len(stream), len(main))+stream+flash[end:]


def boot_from_nor(cpu, flash, main, *, missing_main=False, snapshot=None, power_key_probe=None):
    """Boot guest-loaded RAM; the secondary header page can be made unreadable as a fault control."""
    require(snapshot is None or len(snapshot) == NOR_BYTES, "invalid virtual NOR snapshot")
    require(power_key_probe is None or (snapshot is not None and 0 <= power_key_probe <= 0x4E000),
            "power-key probe needs a snapshot and a bounded held-poll count")
    boot = (snapshot if snapshot is not None else flash)[:BOOT_SIZE]
    require(sha256(boot).hexdigest() == BOOT_HASH and bytes(cpu.mem_read(BASE, len(main))) == bytes(len(main)),
            "expected the original bootstrap and empty application RAM")
    source = SECOND
    if snapshot is not None and snapshot[MARKER-BOOT:MARKER-BOOT+16] != boot[0x47E8:0x47F8]:
        source = FIRST
    regions = ((BOOT, boot, uc.UC_PROT_READ | uc.UC_PROT_EXEC),)
    if snapshot is None:
        regions += ((FIRST, b"\xff"*4096, uc.UC_PROT_READ), (GRAPHICS_FLASH, flash, uc.UC_PROT_READ))
    else:
        regions += ((BOOT+BOOT_SIZE, snapshot[BOOT_SIZE:], uc.UC_PROT_READ),)
    for base, data, protection in regions:
        cpu.mem_map(base, len(data), protection)
        cpu.mem_write(base, data)
    if missing_main:
        cpu.mem_unmap(SECOND, 4096)

    # Only the early register accesses used by reset: default readback and two ready bits.
    widths = {0x3FFFFF80: (4,), 0xFCFE0010: (2, 4), 0xFCFE0014: (2, 4),
              0xFCFE0408: (1, 4), 0xFCFF1800: (1, 4), DSFR: (2,),
              **dict.fromkeys((POWER_KEY, POWER_LATCH, 0xFCFE3328, 0xFCFE7020,
                               0xFCFE7024, 0xFCFE7124, 0xFCFE7224, 0xFCFE3324,
                               0xFCFE3424, 0xFCFE3524, 0xFCFE3624, 0xFCFE3A24), (2,)),
              **{0x3FEFA000+n: (4,) for n in (0, 4, 8, 12, 16, 20, 28, 32, 36, 48, 56,
                                               72, 80, 88, 92, 104)}}
    pages = sorted({address & ~0xFFF for address in widths})
    values = {0x3FEFA048: 1, 0x3FEFA038: 0x40, DSFR: 0x8400}
    registers, faults, stages = [], [], []
    key_polls = 0

    def access(c, address, width, value=None):
        nonlocal key_polls
        pc = c.reg_read(arm.UC_ARM_REG_PC)
        require(width in widths.get(address, ()), f"unmodeled reset register {address:#x}/{width} at {pc:#x}")
        if address == POWER_KEY:
            require(value is None and pc == 0x200048BC, "unexpected power key access in original reset")
            key_polls += 1
            return 0x80 if power_key_probe is not None and key_polls > power_key_probe else 0
        if value is None:
            value, kind = values.get(address, 0), "read"
        else:
            values[address], kind = value, "write"
        registers.append((kind, hex(pc), hex(address), width, value))
        return value

    def observe(c, pc, *_):
        stages.append((pc, *(c.reg_read(reg) for reg in
                             (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))))
        if power_key_probe is not None and pc == LZSS:
            c.emu_stop()

    def key_evidence():
        require(power_key_probe is not None and key_polls == min(power_key_probe+1, 0x4E000),
                "stock power-key polling did not reach the expected boundary")
        require(bool(values.get(POWER_LATCH, 0) & 8) == (power_key_probe == 0x4E000),
                "unexpected stock power latch")
        return dict(held_polls=power_key_probe, polls_read=key_polls,
                    power_latch_set=bool(values.get(POWER_LATCH, 0) & 8))

    def invalid(c, _kind, address, width, *_):
        faults.append((c.reg_read(arm.UC_ARM_REG_PC), address, width))
        return False

    for page in pages:
        cpu.mmio_map(page, 4096, lambda c, o, w, p: access(c, p+o, w), page,
                     lambda c, o, w, v, p: access(c, p+o, w, v), page)
    second_stage = 0x20004840
    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=pc, end=pc) for pc in (second_stage, LZSS, HANDOFF)]
    hooks.append(cpu.hook_add(uc.UC_HOOK_MEM_INVALID, invalid))
    try:
        cpu.reg_write(arm.UC_ARM_REG_CPSR, 0xD3)
        cpu.emu_start(BOOT, BASE, count=160_000_000)
    except uc.UcError as error:
        if not (missing_main and source == SECOND and error.errno == uc.UC_ERR_READ_UNMAPPED and
                faults == [(0x20004634, SECOND+4, 4)] and [row[0] for row in stages] == [second_stage] and
                bytes(cpu.mem_read(BASE, len(main))) == bytes(len(main))):
            raise ValueError(f"NOR reset fault: {faults}, {stages}") from error
        result = dict(result="missing header stopped before decompression", pc=hex(faults[0][0]),
                      unreadable_address=hex(faults[0][1]), application_ram_still_empty=True)
        if power_key_probe is not None:
            result.update(key_evidence(), source_slot=hex(SECOND))
        return result
    finally:
        for hook in hooks:
            cpu.hook_del(hook)
        for page in pages:
            cpu.mem_unmap(page, 4096)

    if power_key_probe is not None:
        require(cpu.reg_read(arm.UC_ARM_REG_PC) == LZSS and not faults and
                [row[0] for row in stages] == [second_stage, LZSS] and
                bytes(cpu.mem_read(BASE, len(main))) == bytes(len(main)), "power probe did not stop before decompression")
        return dict(key_evidence(), result="original choice observed at decompressor entry",
                    source_slot=hex(stages[-1][2]-8), advertised_application_bytes=stages[-1][3],
                    application_ram_still_empty=True)

    require(not (missing_main and source == SECOND) and cpu.reg_read(arm.UC_ARM_REG_PC) == BASE and not faults and
            [row[0] for row in stages] == [second_stage, LZSS, HANDOFF] and
            stages[1][1:] == (BASE, source+8, len(main)) and stages[2][1] == BASE and
            bytes(cpu.mem_read(0x20004000, 0x9BC)) == boot[0x4000:0x49BC] and cpu.mem_read(BASE, len(main)) == main,
            f"original NOR boot did not produce or enter the expected program: {stages}, {faults}")
    stored, = unpack_from("<I", cpu.mem_read(source, 4))
    return dict(reset_vector=hex(BOOT), copied_stage_entry=hex(second_stage), loader_entry=hex(LZSS),
                handoff_instruction=hex(HANDOFF), application_vector=hex(BASE), source_slot=hex(source),
                compressed_bytes=stored, application_bytes=len(main), application_sha256=sha256(main).hexdigest(),
                bootstrap_sha256=BOOT_HASH, application_ram_empty_before_reset=True, early_registers=registers,
                key_polls=key_polls, latches_after_loader=values[DSFR], power_latch_after_loader=values[POWER_LATCH],
                wake_handoff=cpu.mem_read(0x20004F20, 1)[0])
