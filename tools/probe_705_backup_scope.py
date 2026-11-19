"""Test which EEPROM bytes stock J140 restores from an official ICF, offline."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
from zipfile import ZipFile

from tools.decode_705_main import J140_DAT_SHA, J140_MAIN_SHA, decode_main
from tools.emulate_705 import arm, call, machine, uc
from tools.probe_705_menu_origin import icf_parser
from tools.probe_705_setting_map import parse_icf
from tools.render_705_stock_row import require


STAGED, CURRENT, BULK_END = 0x20403740, 0x20625D84, 0x355C0
APPLY, LOGICAL_WRITE, PHYSICAL_REQUEST = 0x20068ED8, 0x2005E554, 0x2005BC08
READ, READY, INIT = 0x2005E4C8, 0x2005E8D4, 0x2004E73C
JOURNAL_SLOT, JOURNAL_SHADOW = 0x2038025C, 0x2039A01E
STARTUP_RECORDS = ((0x1FFC0, 16), (0x3FFC0, 16), (0x3FE40, 16),
                   (0x3FF90, 30), (0x3FFB0, 16))
REGS = (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)


def replay(program, decoded, current, slot):
    cpu = machine(program)
    logical, physical, open_request = [], [], []

    def args(c):
        return tuple(c.reg_read(r) for r in REGS)

    def respond(c, result):
        c.reg_write(REGS[0], result)
        c.reg_write(arm.UC_ARM_REG_PC, c.reg_read(arm.UC_ARM_REG_LR))

    def io(c, pc, _size, _data):
        if pc == READY:
            respond(c, 1)  # An idle simulated EEPROM finishes immediately.
            return
        address, pointer, length = args(c)
        if pc == READ:
            require(address + length <= len(current), "unexpected EEPROM initialization read")
            c.mem_write(pointer, current[address:address+length])
            respond(c, 0)
        elif pc == LOGICAL_WRITE:
            require(not open_request or open_request[2] == 0, "previous request was not fully split")
            logical.append((address, length))
            open_request[:] = [address, pointer, length]
        else:
            linear, source, remaining = open_request
            expected = ((linear >> 7) << 6) + ((linear & 64) << 11) + (linear & 63)
            require(address == expected and pointer == source
                    and length == min(remaining, 64 - (linear & 63)), "unexpected physical page mapping")
            physical.append((address, length))
            open_request[:] = [linear + length, source + length, remaining - length]
            respond(c, 0)  # Stop before enqueueing a physical write; no bus is connected or mapped.

    for pc in (READ, READY, LOGICAL_WRITE, PHYSICAL_REQUEST):
        cpu.hook_add(uc.UC_HOOK_CODE, io, begin=pc, end=pc)
    cpu.mem_write(STAGED, decoded)
    cpu.mem_write(CURRENT, current)
    cpu.mem_write(CURRENT + 0x40000, pack("<I", len(current)))
    cpu.mem_write(JOURNAL_SLOT, bytes((slot, slot)))
    cpu.mem_write(JOURNAL_SHADOW, current[0x3C800:0x3C969])
    call(cpu, INIT, instruction_limit=1_000_000)
    call(cpu, APPLY, instruction_limit=10_000_000)
    require(open_request[2] == 0, "lost a physical page")
    require(all(p + n <= start or p >= start + size
                for p, n in physical for start, size in STARTUP_RECORDS), "restore reached a startup record")
    bulk = [(address, count) for address, count in logical if address < BULK_END]
    other = [(address, count) for address, count in logical if address >= BULK_END]
    return {
        "bulk_requests": len(bulk),
        "bulk_total_bytes": sum(n for _, n in bulk),
        "bulk_last": [hex(bulk[-1][0]), bulk[-1][1]],
        "other_requests": len(other),
        "other_ranges": merge(other),
        "physical_page_requests": len(physical),
        "physical_ranges": merge(physical),
        "startup_record_overlap": False,
    }


def merge(ranges):
    out = []
    for start, count in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], start + count)
        else:
            out.append([start, start + count])
    return [[hex(start), hex(end)] for start, end in out]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--icf-archive", type=Path, default=Path("firmware/comparators/icom-705-settings-jpn.zip"))
    args = parser.parse_args()
    dat = args.dat.read_bytes()
    require(sha256(dat).hexdigest() == J140_DAT_SHA, "expected stock J140 DAT")
    _, program, manifest = decode_main(dat)
    require(manifest["main"]["sha256"] == J140_MAIN_SHA, "expected stock J140 main")
    program = bytes(program)
    stock_parse = icf_parser(program, args.icf_archive)
    with ZipFile(args.icf_archive) as archive:
        _, _, decoded = parse_icf(archive.read(stock_parse["member"]))
    require(sha256(decoded).hexdigest() == stock_parse["staged_settings_sha256"], "staged ICF bytes differ")

    inverse = bytes(value ^ 255 for value in decoded)
    cases = {f"different_slot_{slot}": replay(program, decoded, inverse, slot) for slot in range(8)}
    cases["identical"] = replay(program, decoded, decoded, 0)
    require(all(case["bulk_requests"] == 214 and case["bulk_total_bytes"] == BULK_END
                and case["bulk_last"] == ["0x35400", 0x1C0] and case["other_requests"] > 0
                for name, case in cases.items() if name != "identical"), "different preimage did not cover restore paths")
    require(cases["identical"]["bulk_requests"] == 1 and cases["identical"]["bulk_total_bytes"] == 0x1C0
            and cases["identical"]["other_requests"] == 0, "identical preimage triggered unexpected writes")
    report = {"dat_sha256": J140_DAT_SHA, "main_sha256": J140_MAIN_SHA, "icf_sha256": stock_parse["sha256"],
              "staged_sha256": stock_parse["staged_settings_sha256"], "staged_bytes": len(decoded),
              "startup_records_physical": [[hex(p), n] for p, n in STARTUP_RECORDS], "cases": cases,
              "physical_writes_performed": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"J140 ICF restore: {len(cases)} cases; no startup record overwritten; {args.output}")


if __name__ == "__main__":
    main()
