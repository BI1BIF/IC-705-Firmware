"""Build FT QTH field candidates on the accepted regional AF-window bundles."""
import argparse
import json
from hashlib import md5
from pathlib import Path
from struct import pack, unpack_from
from subprocess import run

from elftools.elf.elffile import ELFFile
from tools.build_705_e140_log_test import BASE, ROOT, decode_main, digest, load_a, offline_test_page, repack_main
from tools.build_705_ft_panel_assets import build_panel_assets
from tools.build_705_ftx_rx import CC, FLAGS, FT_DATA_OFFSET, GLYPH_OFFSET, OUT, PIXEL_OFFSET
from tools.decode_705_main import checked_group_a

BASELINES = {
    "7fc38229a5dc88e5e0ab3ba657a8d5dacbb2fd64e7e54ac9cedc8e4b7987bab0":"J",
    "345658c0448045e013f8ba8096ce9e659c65ba874732928e18434d641beba900":"E",
}


def build(source, out):
    dat=bytearray(source.read_bytes())
    region=BASELINES[digest(dat)]
    main=bytearray(decode_main(bytes(dat))[1])
    _, flash=load_a(bytes(dat),digest(main))
    out.mkdir(parents=True,exist_ok=True)
    out=out.resolve()
    codes=json.loads((OUT/"countries.json").read_text())["codes"]
    panel=build_panel_assets(codes,out)
    glyph=(out/"glyphs.bin").read_bytes()
    assert flash[GLYPH_OFFSET:GLYPH_OFFSET+len(glyph)]==glyph
    panel_at=PIXEL_OFFSET+128*len(codes)
    from tools.build_705_ft_panel_assets import RX_SPLIT,message_tiles
    second=message_tiles()[448*RX_SPLIT:]
    old_tiles=0x5faa80-len(second)
    assert flash[old_tiles:0x5faa80]==second
    new_tiles=(panel_at+len(panel)+31)&~31
    artwork=panel+bytes(new_tiles-panel_at-len(panel))+second
    assert panel_at+len(artwork)<0x600000
    assert not flash[0x5faa80:panel_at+len(artwork)+1].strip(b"\xff")
    src=ROOT/"samples/ftx"
    run([CC,"-I",str(out),*FLAGS,"-mthumb","-c",src/"v132_qth.c","-o","qth.o"],cwd=out,check=True)
    run(["arm-none-eabi-as",src/"v132_qth.S","-o","site.o"],cwd=out,check=True)
    # Fixed-width Thumb instructions are assembled at their final address.
    edits={
        0x20369bda:"b.w qth_detail",
        0x2037cc08:"bl qth_copy",
        0x2037d502:"movs r1,#199",
        0x2037d474:"bl qth_rx_bar",0x2037d4b2:"bl qth_rx_bar",
        0x2037d684:"cmp r6,#20",0x2037d72c:"cmp r3,#20",
        0x2037d732:"cmp r4,#19",0x2037d738:"rsb.w r0,r4,#20",
    }
    (out/"edits.s").write_text(".syntax unified\n.thumb\n.cpu cortex-a9\n"+
        "".join(f'.section .edit_{at:x},"ax"\n{op}\n' for at,op in edits.items()))
    run(["arm-none-eabi-as","edits.s","-o","edits.o"],cwd=out,check=True)
    ram=0x20826868
    (out/"qth.ld").write_text("SECTIONS {\n"+
        "".join(f".edit_{at:x} {at:#x} : {{ *(.edit_{at:x}) }}\n" for at in edits)+
        f".row_site 0x2037d688 : {{ *(.row_site) }}\n.qth {ram:#x} : {{ qth.o(.text* .rodata*) }}\n"+
        "".join(f".{s} {at:#x} : {{ *(.import_{s}) }}\n" for s,at in
                (("memcpy",0x20373d54),("panel_word",0x20369ac0),("sender_flag",0x2037c87c),
                 ("text",0x2037c998),("rectangle",0x2037c624),("__aeabi_uidiv",0x2037f8f0)))+
        "}\nftx_ft4 = 0x2037fed4;\n")
    run(["arm-none-eabi-ld","-T","qth.ld","qth.o","site.o","edits.o","-o","qth.elf"],cwd=out,check=True)
    with (out/"qth.elf").open("rb") as f:
        elf=ELFFile(f)
        for at in [*edits,0x2037d688]:
            s=elf.get_section_by_name(".row_site" if at==0x2037d688 else f".edit_{at:x}")
            data=s.data()
            assert len(data)<=(0x46 if at==0x2037d688 else 4)
            main[at-BASE:at-BASE+len(data)]=data
        program=elf.get_section_by_name(".qth").data()
    assert ram+len(program)<=0x20826e60
    def replace_word(at,before,after):
        assert unpack_from("<I",main,at-BASE)[0]==before
        main[at-BASE:at-BASE+4]=pack("<I",after)
    replace_word(0x2037cc28,ram,ram+len(program))
    replace_word(0x2037d7ac,0x3b4d80,0x3b4d80+new_tiles-old_tiles)
    # Repack over the public envelope. An earlier shorter compressed stream
    # can leave inert bytes from its predecessor outside its declared length.
    from tools.build_705_ft_af_popup import BASELINES as PUBLIC
    dat=bytearray((ROOT/".analysis/sstv-refresh-tx2j1"/source.name).read_bytes())
    assert PUBLIC[digest(dat)]==region
    _,public=load_a(bytes(dat),digest(decode_main(bytes(dat))[1]))
    repack_main(dat,public,main,32 if region=="E" else 4)
    _,packed=load_a(bytes(dat),digest(main))
    expected=bytearray(packed)
    _, group=checked_group_a(bytes(dat))
    start,end=group["offset"],group["end_exclusive"]
    code_at=FT_DATA_OFFSET+ram-0x20825160
    assert packed[code_at:code_at+len(program)]==b"\xff"*len(program)
    for at,data in ((code_at,program),(panel_at,artwork)):
        expected[at:at+len(data)]=data
        for i in range(at,at+len(data)+1):
            dat[start+i]=expected[i]^((expected[i-1]+start+i-0x19)&255)
    dat[end:end+16]=md5(dat[start:end],usedforsecurity=False).digest()
    assert load_a(bytes(dat),digest(main))==(main,expected)
    name=f"705{region}140.dat"
    (out/name).write_bytes(dat)
    offline_test_page(out/"FT-QTH.html",(ROOT/"firmware"/name).read_bytes(),dat,region,
                      f"IC-705 {region}140 · FT 地名与时隙栏测试")
    print(name,digest(dat))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",type=Path)
    p.add_argument("out",type=Path)
    args=p.parse_args()
    build(args.source,args.out)
