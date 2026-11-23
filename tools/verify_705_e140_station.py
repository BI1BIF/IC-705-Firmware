"""Build E140 from the official inputs and replay installation, FT and SSTV."""
import argparse
from hashlib import md5, sha256
import json
from struct import unpack_from

from tools.decode_705_main import BOOT_SIZE, checked_group_a
from tools.replay_705_e140_ft import BASE, E_MAIN, OUT, REPORTS, ROOT, load_a, prepare, symbols
from tools.replay_705_e140_panel import panel_graphics
from tools.replay_705_settings import SettingsGuest
from tools.verify_705_ftx_rx import call
from tools.verify_705_ftx_tx import replay


def build_candidate():
    stock_dat = (ROOT/"firmware/705E140.dat").read_bytes()
    stock, flash, image, resources, _ = prepare(symbols(OUT/"rx.elf"))
    _, group = checked_group_a(stock_dat)
    start, end = group["offset"], group["end_exclusive"]
    assert resources[:BOOT_SIZE] == flash[:BOOT_SIZE]
    data = bytearray(stock_dat)
    previous = resources[BOOT_SIZE-1]
    for pos in range(BOOT_SIZE, len(resources)):
        octet = resources[pos]
        data[start+pos] = octet ^ ((previous+start+pos-0x19) & 255)
        previous = octet
    assert previous == flash[len(resources)-1]
    data[end:end+16] = md5(data[start:end], usedforsecurity=False).digest()
    check_main, check_flash = load_a(bytes(data), sha256(image).hexdigest())
    assert check_main == image and check_flash == resources+flash[len(resources):]
    assert data[:start+BOOT_SIZE] == stock_dat[:start+BOOT_SIZE] and data[end+16:] == stock_dat[end+16:]
    return bytes(data), stock, flash, sha256(image).hexdigest()


class EuropeanReplay:
    folder = REPORTS/"station"

    def __init__(self, stock, flash, main_hash):
        from tools.decode_705_main import J140_MAIN_SHA
        from tools.replay_705_stock_install import european_update_rom
        self.stock, self.flash, self.main_hash = stock, flash, main_hash
        japan, _ = load_a((ROOT/"firmware/705J140.dat").read_bytes(), J140_MAIN_SHA)
        self.rom = european_update_rom(japan, stock)
        self.defaults = unpack_from("<I", stock, 0x30c)[0]

    def station_guest(self, dat, *, loaded_bytes=None):
        image, flash = load_a(dat, self.main_hash)
        from tools.replay_705_stock_install import A_PREFIX
        guest = SettingsGuest(panel_graphics(self.stock, self.flash, flash[:A_PREFIX]),
                              front_panel=True, rom=self.rom, language_address=0x203eae44)
        cpu = guest.cpu
        application = image[:loaded_bytes]
        cpu.mem_write(BASE, application)
        cpu.ctl_remove_cache(BASE, BASE+len(application))
        desc, end = unpack_from("<II", image, 0x2e4)
        # The first five records initialize stock RAM. This component fixture
        # preserves its modeled display device and initializes the two menu records.
        assert end-desc == 7*16
        for pos in range(desc+5*16, end, 16):
            source, target, size, copy = unpack_from("<4I", image, pos-BASE)
            call(cpu, copy | 1, source, target, size)
        return guest, image


def install(download, board):
    from tools.emulate_705 import machine
    from tools.probe_705_boot_selection import FIRST, SECOND, NOR_BYTES
    from tools.replay_705_nor_boot import boot_from_nor
    from tools.replay_705_stock_install import A_PREFIX, SELECTOR, SHARED, update_a
    base = (ROOT/"firmware/705E140.dat").read_bytes()
    program, target = load_a(download, board.main_hash)
    initial = bytearray(b"\xff"*NOR_BYTES)
    initial[:A_PREFIX] = board.flash[:A_PREFIX]
    initial[A_PREFIX:SELECTOR] = board.flash[BOOT_SIZE:A_PREFIX]
    initial[SHARED:SHARED+len(board.flash)-A_PREFIX] = board.flash[A_PREFIX:]
    reports = []
    for second in (False, True):
        if second:
            initial[SELECTOR:SELECTOR+16] = board.flash[0x47e8:0x47f8]
        expected = initial.copy()
        begin, end = (BOOT_SIZE, A_PREFIX) if second else (A_PREFIX, SELECTOR)
        expected[begin:end] = target[BOOT_SIZE:A_PREFIX]
        expected[SELECTOR:SELECTOR+16] = bytes([255])*16 if second else board.flash[0x4f00:0x4f10]
        written, writer = update_a(board.stock,download,bytes(initial),prior=base,active_second=second,
                                   rom=board.rom,path=b"C:\\IC-705\\705E140.dat\0")
        assert written == expected
        boot = boot_from_nor(machine(),None,program,snapshot=written)
        assert int(boot["source_slot"],16) == (FIRST if second else SECOND)
        assert boot["application_sha256"] == board.main_hash
        reports.append(dict(prior_second=second,writer=writer,boot=boot,full_nor_equal=True))
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("FT8", "FT4", "sstv", "archive", "sstv-rx-modes", "sstv-tx-modes", "build", "install"))
    args = parser.parse_args()
    output = REPORTS/"station"
    output.mkdir(parents=True, exist_ok=True)
    if args.mode == "build":
        dat, stock, flash, digest = build_candidate()
        (output/"705E140.dat").write_bytes(dat)
        print(sha256(dat).hexdigest(), digest)
        return
    from tools.decode_705_main import decode_main
    dat = (output/"705E140.dat").read_bytes()
    if args.mode == "install":
        download = (output/"browser"/"705E140.dat").read_bytes()
        assert download == dat
        dat = download
    digest = sha256(decode_main(dat)[1]).hexdigest()
    stock, flash = load_a((ROOT/"firmware/705E140.dat").read_bytes(), E_MAIN)
    board = EuropeanReplay(stock, flash, digest)
    if args.mode in ("sstv-rx-modes","sstv-tx-modes"):
        from os import environ
        from pathlib import Path
        import sys
        from tools.probe_705_sstv_multimode import check_mode, encoders, pcm_runner
        from tools.probe_705_sstv_tx_modes import run as compare_transmit
        sys.path.insert(0,str(ROOT/".analysis/sstv-independent-tx"))
        clang = Path(environ.get("IC705_CLANG", Path.home()/".codex/ndi-android-toolchain/sdk/ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"))
        main = bytes(decode_main(dat)[1])
        sym = symbols(OUT/"sstv/rx.elf")
        folder = output/args.mode
        (folder/"build").mkdir(parents=True,exist_ok=True)
        if args.mode == "sstv-tx-modes":
            results = compare_transmit(main,sym,folder,clang)
        else:
            runner = pcm_runner(folder,clang)
            results = {cls.__name__:check_mode(main,sym,runner,cls) for cls in encoders()}
            assert all(r["phase"]==2 and r["vis"]==r["detected"] and r["locks"]==1 and
                       r["rows"]==r["height"] and not r["drops"] and r["mae"]<18 and r["bottom_mae"]<20
                       for r in results.values())
        assert len(results)==23
        report = dict(modes=results)
    elif args.mode in ("sstv","archive"):
        from tools import render_705_stock_row as renderer
        from tools.probe_705_sstv_archive import check_archive
        from tools.probe_705_sstv_tx import exercise
        from struct import pack
        from unittest.mock import patch
        main = bytes(decode_main(dat)[1])
        sym = symbols(OUT/"sstv/rx.elf")
        folder = output/args.mode
        folder.mkdir(exist_ok=True)
        if args.mode == "sstv":
            report = exercise(folder,None,(main,sym),board=board,dat=dat)
        else:
            with patch.object(renderer,"HEAP_START",0x20700000):
                guest, _ = board.station_guest(dat)
            report = check_archive(None,main,sym,lambda g:g.cpu.mem_write(sym["sstv_thread"],pack("<I",1)),folder,guest=guest)
    elif args.mode == "install":
        report = dict(installs=install(dat,board))
    else:
        report = replay(dat, args.mode=="FT4", e140=board)
    report.update(dat_sha256=sha256(dat).hexdigest(), main_sha256=digest)
    (output/(args.mode+".json")).write_text(json.dumps(report, indent=2)+"\n", encoding="utf8")


if __name__ == "__main__":
    main()
