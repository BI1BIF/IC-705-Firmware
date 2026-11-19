"""Trace J140 display-menu resources and replay startup initialization in RAM."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack
from zipfile import ZipFile

from tools.emulate_705 import BASE, PROFILES, SCRATCH, SP, arm, call, machine, uc
from tools.probe_705_resource_paths import FILE_STATE, LAYOUTS, opening_queue
from tools.probe_705_setting_map import parse_icf
from tools.render_705_display import load
from tools.render_705_stock_row import require
from tools.replay_705_language_storage import DISPLAY, EN, JA, ROWS, SYSTEM, LogicalStorage
from tools.replay_705_menu_word import page_six
from tools.replay_705_settings import SettingsGuest


A7, A8, CHOICES = 0x202F0DFC, 0x202F0E38, 0x202ED520
WATCH = ((A7, 0x78), (CHOICES, 16))
START, STOP, DISPATCH = 0x200052C8, 0x200052E0, 0x20071C8C
INIT = ((0x20367B78, 0x20380000, 0x1F44, 0x200052EC),
        (0x20369ABC, 0x20381F44, 0x4AEEFC, 0x200052FC),
        (0x2084C000, 0x2084C000, 0x1A7380, 0x200052FC))


def word(cpu, address):
    return unpack("<I", cpu.mem_read(address, 4))[0]


def snapshot(cpu):
    return [bytes(cpu.mem_read(address, size)) for address, size in WATCH]


def boot_init(main):
    cpu = machine(main)
    before = snapshot(cpu)
    marker = b"TEST"
    for _, dest, size, _ in INIT:
        cpu.mem_write(dest, marker)
        cpu.mem_write(dest+size-4, marker)
    calls = []

    def capture(_cpu, _pc, _size, _data):
        calls.append(tuple(cpu.reg_read(reg) for reg in (
            arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)))

    cpu.hook_add(uc.UC_HOOK_CODE, capture, begin=0x200052D8, end=0x200052D8)
    cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)
    cpu.reg_write(arm.UC_ARM_REG_SP, SP)
    cpu.emu_start(START | 1, STOP, timeout=5_000_000, count=12_000_000)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == STOP, "initialization loop did not finish")
    require(tuple((src, dst, size, fn & ~1) for src, dst, size, fn in calls) == INIT, f"unexpected descriptors: {calls!r}")
    for source, dest, size, function in INIT:
        expected = main[source-BASE:source-BASE+size] if function == 0x200052EC else bytes(size)
        require(len(expected) == size and bytes(cpu.mem_read(dest, size)) == expected, "init result mismatch")
        require(all(dest+size <= address or dest >= address+length for address, length in WATCH),
                "init destination overlaps menu resources")
    require(snapshot(cpu) == before, "initialization changed menu resources")
    return {"start": hex(START), "stop": hex(STOP), "menu_bytes_unchanged": True,
            "records": [dict(source=hex(src), destination=hex(dst), length=hex(size), callback=hex(fn))
                        for src, dst, size, fn in calls]}


def file_dispatch(main):
    cpu = machine(main)
    cases = {}
    for command in (*range(0x40), 0xFFFFFFFF):
        slot = DISPATCH+0x10+command*4 if command < 0x3F else DISPATCH+0xC
        opcode = word(cpu, slot)
        require(opcode >> 24 == 0xEA, f"unexpected file branch at {slot:#x}")
        delta = ((opcode & 0xFFFFFF) ^ 0x800000) - 0x800000
        target = slot+8+4*delta
        cpu.mem_write(FILE_STATE+0x60, pack("<I", command))
        cpu.reg_write(arm.UC_ARM_REG_R4, FILE_STATE)
        cpu.emu_start(DISPATCH, target, count=8)
        require(cpu.reg_read(arm.UC_ARM_REG_PC) == target, "dispatch target not reached")
        cases[hex(command)] = hex(target)
    require(cases["0x3f"] == cases["0xffffffff"] == "0x20071f70", "unexpected default")
    return {"dispatch": hex(DISPATCH), "cases": cases, "opening_bmp": opening_queue(main, LAYOUTS["705J140"])}


def icf_parser(main, path):
    member = "705_JPN_260627.icf"
    with ZipFile(path) as archive:
        source = archive.read(member)
    digest = sha256(source).hexdigest()
    require(digest == "2b50968e0a29c1c254fd3f2c1ffcf2a189ad6c2bc5ddcf2e985cf69b9f0cbf46",
            "expected the unmodified Icom Japan ICF sample")
    revision, records, decoded = parse_icf(source)
    cpu = machine(main)
    before = snapshot(cpu)
    position, reads, seeks = 0, 0, 0
    opening, reading, seeking, closing = 0x201F2864, 0x201F2914, 0x201F29C4, 0x201F28BC
    reached, writes, mapper = set(), [], []

    def storage(_cpu, pc, _size, _data):
        nonlocal position, reads, seeks
        r0, r1, r2, r3, lr = (cpu.reg_read(reg) for reg in (
            arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3, arm.UC_ARM_REG_LR))
        if pc == opening:
            position = 0
            cpu.mem_write(r2, pack("<I", 1))
        elif pc != 0x201EF558:  # Report the in-memory file request complete to the stock waiter.
            require(r0 == 1, "unexpected ICF stream handle")
            if pc == reading:
                require(0 < r2 <= 81, "unexpected ICF read size")
                data = source[position:position+r2]
                cpu.mem_write(r1, data)
                cpu.mem_write(r3, pack("<I", len(data)))
                position += len(data)
                reads += 1
            elif pc == seeking:
                require(r2 == 1, "unexpected ICF seek origin")
                position += (r1 ^ 0x80000000) - 0x80000000
                require(0 <= position <= len(source), "unexpected ICF position")
                seeks += 1
        cpu.reg_write(arm.UC_ARM_REG_R0, 1 if pc in (opening, reading, seeking, closing) else 0)
        cpu.reg_write(arm.UC_ARM_REG_PC, lr)

    def trace(_cpu, pc, _size, _data):
        reached.add(pc)
        if pc == 0x2006887C:
            mapper.append(tuple(cpu.reg_read(reg) for reg in (
                arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1)))

    def write(_cpu, _access, address, _size, _value, _data):
        writes.append(address)

    for pc in (opening, reading, seeking, closing, 0x201EF558):
        cpu.hook_add(uc.UC_HOOK_CODE, storage, begin=pc, end=pc)
    # Header accepted, integrity comparison, and original map callback.
    for pc in (0x2006857C, 0x200685C4, 0x2006887C):
        cpu.hook_add(uc.UC_HOOK_CODE, trace, begin=pc, end=pc)
    for address, size in WATCH:
        cpu.hook_add(uc.UC_HOOK_MEM_WRITE, write, begin=address, end=address+size-1)
    cpu.mem_write(FILE_STATE+0x60, pack("<I", 9))
    cpu.reg_write(arm.UC_ARM_REG_R4, FILE_STATE)
    cpu.emu_start(DISPATCH, 0x20068454, count=8)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == 0x20068454, "ICF parser not reached")
    status = call(cpu, 0x20068454, instruction_limit=80_000_000, timeout_us=30_000_000)
    require(len(decoded) == 0x3C9C0 and bytes(cpu.mem_read(0x20403740, len(decoded))) == decoded,
            "original parser staged different settings bytes")
    require(status == 0 and reached == {0x2006857C, 0x200685C4, 0x2006887C}
            and mapper == [(0x20067F20, 0x20403740, 0x20440100)] and not writes and snapshot(cpu) == before,
            f"unexpected ICF result: {status:#x}, reads={reads}, sites={reached!r}")
    return {"command": 9, "worker": "0x20068454", "member": member, "sha256": digest, "map_rev": revision,
            "records": records, "decoded_bytes": len(decoded), "stream_reads": reads, "stream_seeks": seeks,
            "file_language_bytes": list(decoded[DISPLAY:SYSTEM+1]),
            "staged_settings_sha256": sha256(decoded).hexdigest(),
            "reached": [hex(pc) for pc in sorted(reached)], "worker_status": hex(status),
            "mapper": [[hex(v) for v in record] for record in mapper], "menu_writes": writes,
            "menu_bytes_unchanged": True}


def frames(images, output, name, display, *, fixture=False):
    guest = SettingsGuest(images, front_panel=True)
    cpu = guest.cpu
    saved = LogicalStorage()
    saved.data[DISPLAY] = display
    before = snapshot(cpu)
    saved.restore(guest)
    require(len(saved.requests) == 714 and guest.language() == [display, 1] and snapshot(cpu) == before,
            "logical settings reload changed resources or missed language")
    page_six(guest)

    jp, option_table = A7+0x30, A7+0x38
    if fixture:
        # The PC sets two RAM pointers before stock drawing; no draw hook or code patch.
        cpu.mem_write(SCRATCH+0x400, b"LAB LABEL\0")
        cpu.mem_write(SCRATCH+0x420, b"LAB VALUE\0")
        cpu.mem_write(SCRATCH+0x440, bytes(cpu.mem_read(CHOICES, 12)) + pack("<I", SCRATCH+0x420))
        cpu.mem_write(jp, pack("<I", SCRATCH+0x400))
        cpu.mem_write(option_table, pack("<I", SCRATCH+0x440))

    reads, result = set(), {}
    ranges = WATCH + (((SCRATCH+0x440, 16),) if fixture else ())

    def read(_cpu, _access, address, size, _value, _data):
        if size == 4:
            reads.add((guest.surface.reg("PC"), address, word(cpu, address)))

    for address, size in ranges:
        cpu.hook_add(uc.UC_HOOK_MEM_READ, read, begin=address, end=address+size-1)

    def frame(stage, expected, required):
        reads.clear()
        labels, image = guest.render()
        require(labels == expected, f"{name}/{stage}: {labels!r}")
        require(set(required) <= {(pc, addr) for pc, addr, _ in reads},
                f"{name}/{stage} missing reads: {sorted(reads)!r}")
        (output / f"{name}-{stage}.png").write_bytes(image)
        result[stage] = {"text": labels, "png_sha256": sha256(image).hexdigest(),
                         "reads": [[hex(v) for v in record] for record in sorted(reads)]}

    page = [*JA[:2], "LAB LABEL", "LAB VALUE", *JA[4:]] if fixture else (JA if display else EN)
    label_slot = jp if display else A7+0x24
    value_slot = (SCRATCH+0x440 if fixture else CHOICES)+(12 if display else 0)
    frame("list", page, ((0x2014B41C, label_slot), (0x2014BB0C, option_table), (0x2014BB38, value_slot)))
    require(guest.click(*ROWS[0]) == 0x1E, "display picker did not open")
    choices = ["英語", "日本語"] if display else ["English", "Japanese"]
    frame("display-picker", [page[2], "1/1", choices[0], "LAB VALUE" if fixture else choices[1]],
          ((0x20154ABC, label_slot), (0x20153BD0, value_slot)))
    require(guest.click(449, 244) == 0x44, "picker back did not register")
    guest.render()
    require(guest.click(*ROWS[1]) == 0x1F, "system picker did not open")
    frame("system-picker", [page[4], "1/1", *choices],
          ((0x20154ABC, A8+(0x30 if display else 0x24)), (0x20153BD0, CHOICES+(12 if display else 0))))
    require(guest.language() == [display, 1], "viewing options changed preferences")
    return {"logical_reads": len(saved.requests), "language": guest.language(), "frames": result}


def replay(dat, output, icf_archive):
    images = load(dat)
    main, _, _, digest, _ = images
    require(PROFILES[digest].name == "705J140", "this experiment requires J140")
    output.mkdir(parents=True, exist_ok=True)
    report = {"dat_sha256": sha256(dat).hexdigest(), "main_sha256": digest,
              "boot": boot_init(main), "file_task": file_dispatch(main)}
    report["file_task"]["icf"] = icf_parser(main, icf_archive)
    report["ui"] = {name: frames(images, output, name, display, fixture=fixture) for name, display, fixture in
                    (("ja", 1, False), ("en", 0, False), ("ja-ram", 1, True))}
    for stage in ("list", "display-picker", "system-picker"):
        old, modified = (report["ui"][name]["frames"][stage]["png_sha256"] for name in ("ja", "ja-ram"))
        require((old == modified) == (stage == "system-picker"), f"unexpected pixel change: {stage}")
    (output / "menu-origin.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"J140 resource origin replay passed: {output / 'menu-origin.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--icf-archive", type=Path, default=Path("firmware/comparators/icom-705-settings-jpn.zip"))
    args = parser.parse_args()
    replay(args.dat.read_bytes(), args.output, args.icf_archive)
