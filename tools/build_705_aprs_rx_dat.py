"""Build and verify an APRS test DAT from either stock IC-705 1.40 DAT."""

import argparse
from hashlib import md5, sha256
import json
from pathlib import Path
from struct import unpack_from

from tools.build_705_cw_sim import END
from tools.decode_705_main import BOOT_SIZE, J140_DAT_SHA, checked_group_a, decode_main
from tools.emulate_705 import BASE, arm, machine, uc
from tools.probe_705_boot_selection import FIRST, LZSS, NOR_BYTES, SECOND
from tools.probe_705_stock_update import STOCK_PATH
from tools.replay_705_aprs_beacon import ATEST, replay as replay_beacon
from tools.replay_705_aprs_fm import load_aprs_panel, read_wav, require
from tools.replay_705_aprs_history import replay as replay_history
from tools.replay_705_aprs_menu import replay as replay_menu
from tools.replay_705_aprs_panel import replay as replay_corpus
from tools.replay_705_aprs_popup import replay as replay_popups, replay_compact_positions, replay_symbol_atlas
from tools.replay_705_aprs_task import APRS_PICKER_BYTES, build_task, install_task, replay as replay_rtx
from tools.replay_705_nor_boot import boot_from_nor, with_pc_main
from tools.replay_705_stock_install import A_PREFIX, SELECTOR, SHARED, european_update_rom, load_a, update_a


def align(value, boundary):
    return (value + boundary - 1) & -boundary


def digest(data):
    return sha256(data).hexdigest()


def build_image(stock, output, european):
    base = align(BASE + len(stock), 32)
    code, symbols = build_task(output, european=european, base=base)
    bss_start, bss_end = (symbols[name] for name in ("__bss_start__", "__bss_end__"))
    menu_table = align(bss_end, 4)
    action_table = align(menu_table + APRS_PICKER_BYTES, 4)
    require(base + len(code) <= bss_start <= bss_end <= menu_table < action_table < END,
            "APRS sections overlap")
    cpu = machine(stock)
    end = install_task(cpu, code, symbols, european=european, layout=(base, menu_table, action_table))
    require(end <= END, "APRS would overlap the first stock RAM initialization target")
    image = bytes(cpu.mem_read(BASE, align(end, 4) - BASE))
    require(image[bss_start-BASE:bss_end-BASE] == bytes(bss_end-bss_start), "APRS BSS is not in the load image")
    return image, code, symbols, dict(code=hex(base), bss=hex(bss_start), bss_bytes=bss_end-bss_start,
                                     selector_table=hex(menu_table), gps_action_table=hex(action_table),
                                     end=hex(BASE+len(image)), free_before_stock_ram=END-BASE-len(image))


def repack(stock_dat, stock_flash, image, *, european):
    flash = with_pc_main(stock_flash, image, match_depth=20 if european else 2)
    stored = unpack_from("<I", flash, BOOT_SIZE)[0]
    join = BOOT_SIZE + 8 + stored + 1
    require(join <= A_PREFIX and flash[join-1:] == stock_flash[join-1:] and flash[join-1] == 255,
            "no unchanged NOR padding to rejoin")
    _, group = checked_group_a(stock_dat)
    start, end = group["offset"], group["end_exclusive"]
    dat = bytearray(stock_dat)
    for i in range(BOOT_SIZE, join):
        dat[start+i] = flash[i] ^ ((flash[i-1]+start+i-0x19) & 255)
    dat[end:end+16] = md5(dat[start:end], usedforsecurity=False).digest()
    dat = bytes(dat)
    unpacked, recovered = load_a(dat, digest(image))
    require(unpacked == image and recovered == flash and dat[:start+BOOT_SIZE] == stock_dat[:start+BOOT_SIZE]
            and dat[end+16:] == stock_dat[end+16:], "DAT did not preserve stock boot and peripheral groups")
    return dat, flash, stored


def verify_corpus(source, dat, symbols, fixtures, reference, output):
    image = bytes(decode_main(dat)[1])
    replay_corpus(source, fixtures, reference, output, installed=(image, symbols))


def install_and_boot(stock_dat, dat, stock, stock_flash, candidate_flash, image, symbols, *, japan=None):
    snapshot = bytearray(b"\xff"*NOR_BYTES)
    snapshot[:A_PREFIX] = stock_flash[:A_PREFIX]
    snapshot[A_PREFIX:SELECTOR] = stock_flash[BOOT_SIZE:A_PREFIX]
    snapshot[SHARED:SHARED+len(stock_flash)-A_PREFIX] = stock_flash[A_PREFIX:]
    addr, size = symbols["__bss_start__"], symbols["__bss_end__"] - symbols["__bss_start__"]
    rom = european_update_rom(japan, stock) if japan is not None else lambda pc: pc
    path = b"C:\\IC-705\\705E140.dat\0" if japan is not None else STOCK_PATH
    reports = {}
    for active_second, slot in ((False, SECOND), (True, FIRST)):
        initial = snapshot.copy()
        if active_second:
            initial[SELECTOR:SELECTOR+16] = stock_flash[0x47e8:0x47f8]
        written, writer = update_a(stock, dat, bytes(initial), prior=stock_dat, active_second=active_second,
                                   rom=rom, path=path)
        candidate = snapshot.copy()
        begin, end = (BOOT_SIZE, A_PREFIX) if active_second else (A_PREFIX, SELECTOR)
        candidate[begin:end] = candidate_flash[BOOT_SIZE:A_PREFIX]
        if slot == SECOND:
            candidate[SELECTOR:SELECTOR+16] = stock_flash[0x4f00:0x4f10]
        require(written == candidate and writer["completion"]["restart_tail"]["watchdog_request_pc"],
                "original updater did not write the verified slot and request restart")
        cpu = machine()
        # Dirty APRS state at the loader boundary to prove the slot actually initializes it.
        hook = cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: c.mem_write(addr, b"\xa5"*size), begin=LZSS, end=LZSS)
        report = boot_from_nor(cpu, None, image, snapshot=written)
        cpu.hook_del(hook)
        require(int(report["source_slot"], 16) == slot and cpu.mem_read(addr, size) == bytes(size),
                "wrong cold slot or APRS state not initialized by the loader")
        cpu.emu_start(0x200052C9, 0x200052A8, count=12_000_000)
        require(cpu.reg_read(arm.UC_ARM_REG_PC) == 0x200052A8 and cpu.mem_read(addr, size) == bytes(size),
                "native data initialization changed APRS state")
        reports[hex(slot)] = dict(boot=report, writer=writer, full_nor_equal=True,
                                  aprs_ram_before_decompress="a5", aprs_ram_after_app_init="00", default_mode="OFF")
        print(f"Stock update and cold boot passed for {slot:#x}", flush=True)
    return reports


def build(source, output, fixtures, reference, japan_source, *, atest=ATEST):
    output.mkdir(parents=True, exist_ok=True)
    stock_dat = source.read_bytes()
    images, european = load_aprs_panel(stock_dat)
    stock, font, _, stock_main_hash, small_font = images
    _, stock_flash = load_a(stock_dat, stock_main_hash)
    image, code, symbols, layout = build_image(stock, output, european)
    dat, candidate_flash, stored = repack(stock_dat, stock_flash, image, european=european)
    print(f"Repacked {source.name}: {len(image)} bytes in RAM, {stored} bytes in NOR", flush=True)
    japan = None
    if european:
        package = japan_source.read_bytes()
        require(digest(package) == J140_DAT_SHA, "E140 updater replay requires the stock J140 reference")
        japan = bytes(decode_main(package)[1])
    slots = install_and_boot(stock_dat, dat, stock, stock_flash, candidate_flash, image, symbols, japan=japan)
    print("Both cold slots loaded and initialized the same application", flush=True)
    installed = (image, font, candidate_flash[:A_PREFIX], digest(image), small_font)
    replay_menu(installed, output/"menu", european, installed_symbols=symbols)
    replay_popups(installed, output/"popups", european, installed_symbols=symbols)
    replay_symbol_atlas(installed, output/"atlas", european, symbols)
    replay_compact_positions(installed, output/"positions", european, symbols, atest.with_name("decode_aprs.exe"))
    replay_history(installed, output/"history", european, installed_symbols=symbols)
    replay_beacon(installed, output/"beacon", european, installed_symbols=symbols, atest=atest)
    previous = json.loads((reference/"replay.json").read_text(encoding="utf-8"))
    expected = previous["cases"]["continuous"]["frames"][:3]
    clean = read_wav(fixtures/"continuous-source48.wav")[:expected[-1]["end_sample"]+144]
    bad = read_wav(fixtures/"bad-fcs-source48.wav")
    rtx = replay_rtx(images, code, symbols, clean, expected, bad, european=european, application=image)
    name = "705E140.dat" if european else "705J140.dat"
    verify_corpus(source, dat, symbols, fixtures, reference, output/"corpus")
    report = dict(region=name[3:7], source_sha256=digest(stock_dat), dat_sha256=digest(dat),
                  app_sha256=digest(image), layout=layout, compressed_main_bytes=stored, boot_slots=slots,
                  rtx=rtx, menu="menu/menu.json", popups="popups/popup.json", history="history/history.json",
                  beacon="beacon/beacon.json", atlas="atlas/atlas.json", positions="positions/positions.json",
                  corpus="corpus/replay.json")
    (output/name).write_bytes(dat)
    (output/"verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(f"{name} {report['dat_sha256']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dat", "output", "fixtures", "reference"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--japan-reference", type=Path, default=Path("firmware/705J140.dat"))
    parser.add_argument("--atest", type=Path, default=ATEST)
    args = parser.parse_args()
    build(args.dat, args.output, args.fixtures, args.reference, args.japan_reference, atest=args.atest)
