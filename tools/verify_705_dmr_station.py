"""Run the existing factory upgrade and sibling-mode checks against the private DMR DAT."""
import json
from hashlib import sha256
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/".analysis/ic705-emulator/deps"),str(ROOT/".analysis/ftx-tools")]
from tools.build_705_dmr_station import OUT, RELEASE, decode_main, load_a, symbols
from tools.build_705_aprs_rx_dat import install_and_boot
from tools.replay_705_e140_ft import check_other_receivers
from tools.verify_705_aprs_slot import check_panel
from tools.verify_705_dmr_tx_guard import verify
from tools.verify_705_ft_log_timezone import check

def test(region,kind):
    folder=OUT/region
    path=folder/f"705{region}140.dat"
    dat=path.read_bytes()
    meta=json.loads((folder/"package.json").read_text())
    assert sha256(dat).hexdigest()==meta["sha256"]
    main,flash=load_a(dat,meta["main_sha256"])
    if kind in ("upgrade","upgrade-rx5","upgrade-rx6","upgrade-rx7","upgrade-rx8","upgrade-rx9","upgrade-rx10","upgrade-rx11","restore"):
        previous={"upgrade-rx11":ROOT/".analysis/digital-rx11/final"/region,
                  "upgrade-rx10":ROOT/".analysis/digital-rx10/final"/region,
                  "upgrade-rx9":ROOT/".analysis/digital-rx9/final"/region,
                  "upgrade-rx8":ROOT/".analysis/digital-rx8/final"/region,
                  "upgrade-rx7":ROOT/".analysis/dmr-rx7-volume/final"/region,
                  "upgrade-rx5":ROOT/".analysis/dmr-rx5-start/final"/region,
                  "upgrade-rx6":ROOT/".analysis/dmr-rx6-worker/final"/region}.get(kind,RELEASE/"verified")
        baseline=(previous/path.name).read_bytes()
        old,old_flash=load_a(baseline,sha256(decode_main(baseline)[1]).hexdigest())
        sy=symbols(folder/"station.elf")
        bss={"__bss_start__":sy["__work_start"],"__bss_end__":sy["__work_end"]}
        japan=decode_main((RELEASE/"verified/705J140.dat").read_bytes())[1] if region=="E" else None
        if kind=="restore":
            bss=symbols(RELEASE/"rebuild"/region/"manager.elf")
            result=install_and_boot(dat,baseline,main,flash,old_flash,old,bss,japan=japan)
        else:
            result=install_and_boot(baseline,dat,old,old_flash,flash,main,bss,japan=japan)
    elif kind=="ptt":
        guard=meta["guard"]
        result=verify(dat,region,installed_origin=guard["origin"],active_address=guard["active"])
    elif kind=="siblings":
        result=check_other_receivers(main)
        result["ft"]=check(path,True)[0]
        previous=RELEASE/"rebuild"/region
        shutil.copyfile(previous/"aprs-task.elf",folder/"aprs-task.elf")
        result["aprs"]=check_panel(region,folder,main,flash,symbols(previous/"manager.elf"))
    else: raise ValueError(kind)
    (folder/f"{kind}.json").write_text(json.dumps(dict(dat_sha256=meta["sha256"],result=result),indent=2)+"\n",encoding="utf-8")
    print(region,kind,"passed",flush=True)

if __name__=="__main__": test(*sys.argv[1:])
