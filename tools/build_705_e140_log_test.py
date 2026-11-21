"""Rebuild the FT SD fixes from the immutable regional TX2j baselines."""
import argparse
import base64
import gzip
from hashlib import md5, sha256
from pathlib import Path
from struct import unpack_from
from subprocess import run

from elftools.elf.elffile import ELFFile
from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_main
from tools.emulate_705 import BASE
from tools.replay_705_nor_boot import with_pc_main
from tools.replay_705_stock_install import load_a

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".analysis/e140-log-retry"
PAGES = ROOT / "docs/converter"
BASELINES = {
    "E": ("15f3c89e5a6b2fa81eb53292e8c4d2c7b02b4034c1667a69ba7c1cc7ca3bfdd0",
          "eae5fe51c75e93ba8531c1d2045f459d207daacb0ac9bee03558192f31a85d94"),
    "J": ("8dadf23053636f5118c3198cd4fef2eb338d473cc68edda4228cc8f1c9cbba94",
          "8dcb44ae45c02d963d4eba6c9feca23d97f1e90b1f0409f75366de7d467c3c68"),
}


def digest(data):
    return sha256(data).hexdigest()


def offline_test_page(path, stock, dat, region, title, note=""):
    delta = gzip.compress(bytes(x ^ y for x,y in zip(stock,dat,strict=True)),mtime=0)
    html = (ROOT/"tools/fixtures/e140-log-test.html").read_text(encoding="utf8")
    fields = {"TITLE":title,"REGION":"日版" if region=="J" else "欧／美版",
              "FILENAME":f"705{region}140.dat","NOTE":note,
              "STOCK_SHA":digest(stock),"OUTPUT_SHA":digest(dat),
              "PATCH_BASE64":base64.b64encode(delta).decode("ascii")}
    for key,value in fields.items():
        html = html.replace("{{"+key+"}}",value)
    path.write_text(html, encoding="utf8")


def repack_main(dat, flash, main, match_depth):
    updated = with_pc_main(flash, bytes(main), match_depth=match_depth)
    _, group = checked_group_a(bytes(dat))
    start, stop = group["offset"], group["end_exclusive"]
    end = BOOT_SIZE + 9 + unpack_from("<I",updated,BOOT_SIZE)[0]
    assert updated[end:] == flash[end:]
    for i in range(BOOT_SIZE,end):
        dat[start+i] = updated[i] ^ ((updated[i-1]+start+i-0x19) & 255)
    dat[stop:stop+16] = md5(dat[start:stop], usedforsecurity=False).digest()
    reread, resources = load_a(bytes(dat), digest(main))
    assert reread == main and resources == updated


def build(region):
    out = OUT if region == "E" else ROOT / ".analysis/j140-ft-sd"
    out.mkdir(parents=True, exist_ok=True)
    filename = f"705{region}140.dat"
    stock = (ROOT / "firmware" / filename).read_bytes()
    patch_hash, baseline_hash = BASELINES[region]
    packed = (PAGES / f"{patch_hash}.xor.gz").read_bytes()
    assert digest(packed) == patch_hash
    delta = gzip.decompress(packed)
    dat = bytearray(x ^ y for x, y in zip(stock, delta, strict=True))
    assert digest(dat) == baseline_hash
    main = bytearray(decode_main(bytes(dat))[1])
    _, flash = load_a(bytes(dat), digest(main))
    sd_check = "0x200c28cc" if region == "E" else "0x200c27e8"
    run(["arm-none-eabi-as", "-o", "card.o", ROOT/"samples/ftx/e140_log_card.S"], cwd=out, check=True)
    run(["arm-none-eabi-ld", "-Ttext=0x203744ec", f"--defsym=stock_sd_check={sd_check}",
         "-e", "edit_feedback", "-o", "card.elf", "card.o"], cwd=out, check=True)
    desc_end = unpack_from("<I",main,0x2e8)[0]
    menu_stream = unpack_from("<I",main,desc_end-16-BASE)[0]
    applied = set()
    with (out/"card.elf").open("rb") as f:
        elf = ELFFile(f)
        section = elf.get_section_by_name(".text")
        code = section.data()
        for symbol in elf.get_section_by_name(".symtab").iter_symbols():
            if not symbol.name.startswith("edit_"):
                continue
            if region == "J" and symbol.name != "edit_prefs":
                continue
            at, size = symbol["st_value"], symbol["st_size"]
            if symbol.name == "edit_feedback":
                assert at == 0x203744ec and at+size <= menu_stream
            offset = at-section["sh_addr"]
            main[at-BASE:at-BASE+size] = code[offset:offset+size]
            applied.add(symbol.name)
    assert "edit_prefs" in applied
    repack_main(dat, flash, main, 20 if region == "E" else 2)
    (out/filename).write_bytes(dat)
    print(digest(dat), digest(main))
    if region == "J":
        return
    offline_test_page(OUT/"E140-log-test.html", stock, dat, region, "欧版 FT 通联日志测试",
                      "当前仍在「待存卡」的通联请先手工记下，重启会清除待存记录。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("region", choices=["E", "J"], nargs="?", default="E")
    build(parser.parse_args().region)
