"""Apply the FT AF level window fix to the two verified v1.3.2 DATs."""
from argparse import ArgumentParser
from pathlib import Path
from subprocess import run

from elftools.elf.elffile import ELFFile
from tools.build_705_e140_log_test import BASE, ROOT, decode_main, digest, load_a, offline_test_page, repack_main
from tools.build_705_ftx_rx import CC, FLAGS

BASELINES = {
    "eb7d2d1bb969241e17dbc7effb387cf4c9d73ab2e58c7267c4c461014febff65": "J",
    "be19795bc4f0fbf0daa058b838ccfc0bcb694def4415ee0213f2bd1e8eca0471": "E",
}


def build(source, out):
    dat = bytearray(source.read_bytes())
    region = BASELINES[digest(dat)]
    out.mkdir(parents=True, exist_ok=True)
    main = bytearray(decode_main(bytes(dat))[1])
    _, flash = load_a(bytes(dat), digest(main))
    run([CC, *FLAGS, "-mthumb", "-fno-if-conversion", "-x", "c", "-c", "-", "-o", "top.o"],
        cwd=out, input='#include "j140_tx.h"\nunsigned af_top(void) { return ft_af_top(); }\n',
        text=True, check=True)
    run(["arm-none-eabi-as", ROOT/"samples/ftx/v132_af_popup.S", "-o", "overlay.o"], cwd=out, check=True)
    (out/"af.ld").write_text("""
SECTIONS {
  .af_top 0x20369fc8 : { *(.text.af_top) }
  .af_touch 0x20374450 : { *(.af_touch) }
  .af_draw 0x2037c730 : { *(.af_draw) }
}
""", encoding="ascii")
    run(["arm-none-eabi-ld", "-T", "af.ld", "top.o", "overlay.o", "-o", "af.elf"], cwd=out, check=True)
    with (out/"af.elf").open("rb") as fp:
        elf = ELFFile(fp)
        for name, end in ((".af_top", 0x2036a000), (".af_draw", 0x2037c754), (".af_touch", 0x20374468)):
            section = elf.get_section_by_name(name)
            at = section["sh_addr"]
            code = section.data()
            assert code and at + len(code) <= end
            if name == ".af_top":
                assert not any(main[at-BASE:end-BASE])  # reserved padding after .panel
            if name == ".af_touch":
                assert at + len(code) == end
            main[at-BASE:at-BASE+len(code)] = code
    repack_main(dat, flash, main, 32 if region == "E" else 3)
    filename = out/f"705{region}140.dat"
    filename.write_bytes(dat)
    stock = (ROOT/"firmware"/filename.name).read_bytes()
    offline_test_page(out/"FT-AF.html", stock, dat, region, f"IC-705 {region}140 · FT 音量窗测试")
    print(filename, digest(dat))


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    build(args.source, args.out)
