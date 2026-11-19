"""Read-only replay of the shared IC-705 bootstrap selector, not a recovery procedure."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_a_range, decode_boot, decode_main
from tools.emulate_705 import BASE, BOOT_HASH, arm, call, machine, uc


ROUTINE, LZSS = 0x200045F4, 0x200044DC
FIRST, SECOND, MARKER = 0x18010000, 0x18600000, 0x18BF0000
POST_DECODE, HANDOFF = 0x20004948, 0x200049B8
NOR_BYTES = 0x1000000
ERASED = b"\xff"


def part(path):
    dat = path.read_bytes()
    boot, main, info = decode_main(dat)
    _, group = checked_group_a(dat)
    header = group["offset"] + BOOT_SIZE
    payload = decode_a_range(dat, header, 8 + info["main"]["stored_bytes"], boot[-1])
    return bytes(boot), bytes(payload), bytes(main), info["input"]["sha256"]


def catalog(directory, manifest):
    records = []
    for release in json.loads(manifest.read_text(encoding="utf-8")):
        dat = (directory / (release["name"] + ".dat")).read_bytes()
        info, group = checked_group_a(dat)
        if info["sha256"] != release["dat_sha256"]:
            raise ValueError(f"firmware hash differs from official manifest: {release['name']}")
        boot, padding = decode_boot(dat, group)
        records.append(dict(name=release["name"], dat_sha256=info["sha256"],
                            bootstrap_sha256=sha256(boot).hexdigest(), bootstrap_bytes=len(boot),
                            padding_bytes=padding, groups={g["name"]: g["sha256"] if g["bytes"] else None
                                                          for g in info["groups"]}))
    return records


def probe(boot, primary, alternate):
    cases = []
    marker_text = boot[0x47E8:0x47F8]
    for name, tag, first, second, expected in (
        ("unmarked", b"\xff"*16, primary, alternate, FIRST),
        ("exact-marker", marker_text, primary, alternate, SECOND),
        ("unreadable-first-slot", b"\xff"*16, None, alternate, FIRST),
        ("damaged-selected-slot", marker_text, primary, None, SECOND),
    ):
        cpu = machine()
        cpu.mem_write(0x20004000, boot[0x4000:0x49BC])
        cpu.mem_map(MARKER, 4096, uc.UC_PROT_READ)
        cpu.mem_write(MARKER, tag)
        for address, slot in ((FIRST, first), (SECOND, second)):
            if slot is not None:
                payload, _ = slot
                # Extra page models bytes read beyond the final output token.
                cpu.mem_map(address, ((len(payload) + 4095) // 4096 + 1) * 4096, uc.UC_PROT_READ)
                cpu.mem_write(address, payload)

        inputs, faults = [], []

        def enter(c, _address, _size, _data):
            inputs.append(c.reg_read(arm.UC_ARM_REG_R1) - 8)

        def missing(_cpu, _access, address, _size, _value, _data):
            faults.append(address)
            return False

        cpu.hook_add(uc.UC_HOOK_CODE, enter, begin=LZSS, end=LZSS)
        cpu.hook_add(uc.UC_HOOK_MEM_READ_UNMAPPED, missing)
        if first is None or second is None:
            try:
                call(cpu, ROUTINE)
            except uc.UcError as error:
                if error.errno != uc.UC_ERR_READ_UNMAPPED or faults != [expected+4] or inputs:
                    raise
            else:
                raise ValueError("expected the selected source header to fail")
            digest, outcome = None, "unreadable selected header; no alternate branch observed"
        else:
            _, image = first if expected == FIRST else second
            # The untouched J140 startup copies its initialized data to this address.
            # Bound the observation here without treating unwritten bytes as free memory.
            output_end, guard_end = BASE + len(image), 0x20380000
            if output_end >= guard_end:
                raise ValueError("stock image ends outside this startup observation window")
            ramp = bytes(range(1, 256))
            after = (ramp * ((guard_end-output_end+254)//255))[:guard_end-output_end]
            before = ramp[-64:]
            cpu.mem_write(BASE-len(before), before)
            cpu.mem_write(output_end, after)
            outside = []

            def outside_write(c, _kind, address, size, _value, _data):
                outside.append((address, size))
                c.emu_stop()

            for start, end in ((BASE-len(before), BASE), (output_end, guard_end)):
                cpu.hook_add(uc.UC_HOOK_MEM_WRITE, outside_write, begin=start, end=end-1)
            written = call(cpu, ROUTINE, instruction_limit=100_000_000, timeout_us=0)
            if inputs != [expected] or written != len(image) or bytes(cpu.mem_read(BASE, written)) != image:
                raise ValueError(f"stock bootstrap output mismatch: {name}, {inputs}, {written}")
            if (outside or bytes(cpu.mem_read(BASE-len(before), len(before))) != before or
                    bytes(cpu.mem_read(output_end, len(after))) != after):
                raise ValueError(f"stock bootstrap wrote outside the image: {name}, {outside}")
            digest, outcome = sha256(image).hexdigest(), "matches independently extracted stock image"
        case = dict(case=name, selected_header=hex(expected), source_headers_observed=list(map(hex, inputs)),
                    read_faults=list(map(hex, faults)), output_sha256=digest, result=outcome)
        if first is not None and second is not None:
            case.update(output_start=hex(BASE), output_end_exclusive=hex(output_end), output_bytes=written,
                        before_guard_bytes=len(before), after_guard_end_exclusive=hex(guard_end),
                        after_guard_bytes=len(after), guard_writes=outside)
        cases.append(case)
    # Enter at the stock BL to the selector, then continue through the original
    # post-decode path. Never execute SRAM bytes from an incomplete fixture.
    first_payload, primary_main = primary
    payload, alternate_main = alternate
    prefix = 0x10000
    for name, tag, first, second, expected, result in (
        ("partial-marker", marker_text[:-1] + ERASED, first_payload, payload, FIRST, "primary"),
        ("readable-partial-primary", ERASED*16, first_payload[:prefix], payload, FIRST, "corrupt-output"),
        ("readable-partial-alternate", marker_text, first_payload, payload[:prefix], SECOND, "corrupt-output"),
        ("erased-first-header", ERASED*16, b"", payload, FIRST, "erased-header"),
        ("erased-second-header", marker_text, first_payload, b"", SECOND, "erased-header"),
    ):
        cpu = machine()
        cpu.mem_write(0x20004000, boot[0x4000:0x49BC])
        cpu.mem_map(0x18000000, NOR_BYTES, uc.UC_PROT_READ)
        cpu.mem_write(0x18000000, ERASED * NOR_BYTES)
        for address, data in ((FIRST, first), (SECOND, second)):
            if data:
                cpu.mem_write(address, data)
        cpu.mem_write(MARKER, tag)
        cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)
        # At this point the stock stack includes the saved r2-r4 and lr.
        sp = 0x20004000 - 16
        cpu.reg_write(arm.UC_ARM_REG_SP, sp)
        inputs, faults, handoff, crossed_output = [], [], [], []
        reference = primary_main if expected == FIRST else alternate_main
        size = len(reference)
        headers = []

        def header(_c, _kind, address, size, *_):
            headers.append((address, size))

        def enter(c, *_):
            inputs.append((c.reg_read(arm.UC_ARM_REG_R1)-8, c.reg_read(arm.UC_ARM_REG_R2)))
            if result == "erased-header":
                c.emu_stop()  # Do not feed an erased header's invalid length to the decoder.

        def watch(c, pc, *_):
            handoff.append(hex(pc))
            c.emu_stop()

        def overrun(c, _kind, addr, *_):
            crossed_output.append(addr)
            c.emu_stop()  # Also avoid pretending the fixture models invalid SRAM accesses.

        cpu.hook_add(uc.UC_HOOK_CODE, enter, begin=LZSS, end=LZSS)
        cpu.hook_add(uc.UC_HOOK_CODE, watch, begin=HANDOFF, end=HANDOFF)
        cpu.hook_add(uc.UC_HOOK_MEM_WRITE, overrun, begin=BASE+size, end=BASE+size)
        cpu.hook_add(uc.UC_HOOK_MEM_INVALID, lambda _c, _k, addr, *_: faults.append(addr) or False)
        for slot in (FIRST, SECOND):
            cpu.hook_add(uc.UC_HOOK_MEM_READ, header, begin=slot, end=slot+7)
        cpu.emu_start(POST_DECODE-4, 0, count=100_000_000)
        pc = cpu.reg_read(arm.UC_ARM_REG_PC)
        advertised = 0xFFFFFFFF if result == "erased-header" else size
        if inputs != [(expected, advertised)] or headers != [(expected+4, 4)] or faults:
            raise ValueError(f"unexpected selection or fault: {name}, {inputs}, {headers}, {faults}")
        common = dict(case=name, selected_header=hex(expected), advertised_output_size=advertised,
                      header_reads=[hex(address) for address, _ in headers],
                      source_headers_observed=[hex(expected)], result=result)
        if result == "erased-header":
            if pc != LZSS or handoff or crossed_output:
                raise ValueError(f"erased header was not stopped before decoding: {name}, {pc:#x}")
            cases.append(dict(common, stopped_before_decompression=True))
            continue
        image = bytes(cpu.mem_read(BASE, size))
        decoded_sha = sha256(image).hexdigest()
        target = cpu.reg_read(arm.UC_ARM_REG_R0)
        if handoff != [hex(HANDOFF)] or target != BASE or crossed_output:
            raise ValueError(f"unexpected handoff: {name}, {pc:#x}")
        if (image == reference) != (result == "primary"):
            raise ValueError(f"unexpected decoded bytes: {name}")
        cases.append(dict(common, observed_output_sha256=decoded_sha, expected_output_sha256=sha256(reference).hexdigest(),
                          verified_prefix_bytes=next((i for i, (a, b) in enumerate(zip(image, reference)) if a != b),
                                                     size),
                          handoff_pc=handoff[0], handoff_target=hex(target), result=result))
    return {"bootstrap_sha256": sha256(boot).hexdigest(), "selector_marker_ascii": marker_text.decode("ascii"),
            "cases": cases, "synthetic_flash_layout": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary", type=Path)
    parser.add_argument("other_stock", type=Path, help="Different stock image used to distinguish the simulated locations")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--catalog", type=Path, help="Also compare local official DAT files against this provenance JSON")
    args = parser.parse_args()
    boot, payload, main, first_hash = part(args.primary)
    other_boot, other_payload, other_main, second_hash = part(args.other_stock)
    if sha256(boot).hexdigest() != BOOT_HASH or boot != other_boot or main == other_main:
        parser.error("need two distinct stock main images with a shared bootstrap")
    result = probe(boot, (payload, main), (other_payload, other_main))
    result.update(input_sha256=[first_hash, second_hash])
    if args.catalog:
        result["official_catalog"] = catalog(args.primary.parent, args.catalog)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(result['cases'])} offline boot cases; {len(result.get('official_catalog', []))} catalog entries; "
          f"{args.evidence}")
