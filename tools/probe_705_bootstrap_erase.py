"""Check J140 boot-sector interruption in RAM; emit evidence only (no NOR image)."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from tools.emulate_705 import BASE, BOOT, arm, machine, uc
from tools.replay_705_stock_install import (A_PREFIX, BOOT_SIZE, J132_DAT_SHA, J140_DAT_SHA,
                                           J140_MAIN_SHA, NOR_BYTES, SELECTOR, SHARED,
                                           boot_from_nor, load_a, require, update_a)


def reset_with_erased_boot(snapshot, main):
    require(snapshot[:BOOT_SIZE] == b"\xff"*BOOT_SIZE, "expected a completed erase")
    cpu = machine(bootstrap=snapshot)
    reads = []
    cpu.hook_add(uc.UC_HOOK_MEM_READ, lambda _c, _k, at, n, *_: reads.append([hex(at), n]),
                 begin=BOOT+BOOT_SIZE, end=BOOT+NOR_BYTES-1)
    cpu.reg_write(arm.UC_ARM_REG_CPSR, 0xD3)
    try:
        cpu.emu_start(BOOT, BASE, count=16)
    except uc.UcError as error:
        require(error.errno == uc.UC_ERR_INSN_INVALID and cpu.reg_read(arm.UC_ARM_REG_PC) == BOOT and
                not reads and bytes(cpu.mem_read(BASE, len(main))) == bytes(len(main)),
                f"unexpected erased reset trace: {error}, {reads}")
    else:
        raise ValueError("erased NOR reset did not stop at an invalid instruction")
    return dict(result="invalid instruction at virtual NOR reset", pc=hex(BOOT),
                nor_reads_outside_boot_sector=reads, application_ram_still_empty=True)


def probe(j140, j132):
    require((sha256(j140).hexdigest(), sha256(j132).hexdigest()) == (J140_DAT_SHA, J132_DAT_SHA),
            "only the unchanged Japanese 1.40 and 1.32 official files may be used")
    main, group = load_a(j140, J140_MAIN_SHA)
    _, older = load_a(j132, "e2367bf67ec7969ef42cf74a4d0da22d3b75b825377c223ccc131f1ba217617f")
    require(group[:BOOT_SIZE] == older[:BOOT_SIZE] and group[BOOT_SIZE-1] == 255 and
            group[A_PREFIX:] == older[A_PREFIX:], "expected common bootstrap and resources")
    cases = {}
    for active_second in (False, True):
        initial = bytearray(b"\xff"*NOR_BYTES)
        first, second = (older, group) if active_second else (group, older)
        initial[:A_PREFIX] = first[:A_PREFIX]
        initial[A_PREFIX:SELECTOR] = second[BOOT_SIZE:A_PREFIX]
        initial[SHARED:SHARED+len(group)-A_PREFIX] = group[A_PREFIX:]
        if active_second:
            initial[SELECTOR:SELECTOR+16] = group[0x47e8:0x47f8]
        snapshot = bytes(initial)
        # A single synthetic mismatch in trailing fill prompts a real original erase command.
        initial[BOOT_SIZE-1] = 254
        cuts = {}
        _, writer = update_a(main, j140, bytes(initial), cuts=cuts, active_second=active_second)
        cut = cuts["first_sector_erased"]
        require(writer["erased_sectors"][0] == "0x0" and cut[BOOT_SIZE:] == snapshot[BOOT_SIZE:],
                "expected a guest erase of only the boot sector, with both slots and selector unchanged")
        stopped = reset_with_erased_boot(cut, main)
        # Approximate independently supplying only the saved original bytes, entirely in RAM.
        recovered = snapshot[:BOOT_SIZE] + cut[BOOT_SIZE:]
        require(recovered == snapshot, "only the bootstrap may differ across the control")
        boot = boot_from_nor(machine(), b"", main, snapshot=recovered)
        require(boot["source_slot"] == hex(BOOT+(A_PREFIX if active_second else BOOT_SIZE)),
                "original boot did not use the unchanged active slot")
        cases["B" if active_second else "A"] = dict(
            first_original_erase_offset=writer["erased_sectors"][0],
            both_app_slots_selector_and_shared_unchanged=True, cut_nor_sha256=sha256(cut).hexdigest(), stopped=stopped,
            ram_only_original_boot_sector_control=dict(source_slot=boot["source_slot"],
                                                       application_sha256=boot["application_sha256"],
                                                       reached_application_vector=True))
    return dict(stock_dat_sha256=J140_DAT_SHA, prior_dat_sha256=J132_DAT_SHA, cases=cases,
                scope="Stock J140 writer, Cortex-A9 reset at virtual NOR, RAM-only controls; no on-chip ROM or physical recovery")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("j140", type=Path)
    parser.add_argument("j132", type=Path)
    parser.add_argument("report", type=Path, help="new JSON evidence file")
    args = parser.parse_args()
    require(not args.report.exists(), "report already exists")
    j140, j132 = args.j140.read_bytes(), args.j132.read_bytes()
    evidence = probe(j140, j132)
    require((args.j140.read_bytes(), args.j132.read_bytes()) == (j140, j132), "original DAT changed")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as file:
        file.write(json.dumps(evidence, indent=2)+"\n")
    print(f"Original bootstrap sector cut checked with A and B active: {args.report}")


if __name__ == "__main__":
    main()
