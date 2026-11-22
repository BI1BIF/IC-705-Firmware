"""Adapt the offline HOME observer to E140. Only the emulator instrumentation is translated."""
from bisect import bisect_left
from functools import lru_cache
from hashlib import sha256
import re
from types import ModuleType
from pathlib import Path

from tools.decode_705_main import decode_main
from tools.emulate_705 import BASE
from tools.decode_705_main import J140_MAIN_SHA
from tools.replay_705_e140_ft import E_MAIN

def european_boot_replay():
    j,e = [bytes(decode_main(Path(f"firmware/705{r}140.dat").read_bytes())[1]) for r in "JE"]
    assert sha256(j).hexdigest() == J140_MAIN_SHA and sha256(e).hexdigest() == E_MAIN
    anchors = {}
    for i in range(0,len(j)-48,128):
        lo=max(0,i-2048)
        hi=min(len(e),i+2048)
        pattern=j[i:i+48]
        k=e.find(pattern,lo,hi)
        if k>=0 and e.find(pattern,k+1,hi)<0:
            anchors[i]=k-i
    positions=sorted(anchors)
    @lru_cache(maxsize=None)
    def delta(i):
        index=bisect_left(positions,i)
        local=positions[max(0,index-4):index+4]
        nearest=min(local,key=lambda p:abs(p-i))
        shifts={anchors[p] for p in local}
        if len(shifts)==1:
            return anchors[nearest]
        return max(shifts,key=lambda d:(sum(j[p]==e[p+d] for p in range(max(0,i-48),min(i+64,len(j)))
                                               if 0<=p+d<len(e)), d==anchors[nearest]))
    def translated(m):
        n=int(m[0],16)
        if BASE<=n<BASE+len(j):
            return hex(n+delta(n-BASE))
        return m[0]
    def model(name):
        path=Path("tools")/(name+".py")
        text=re.sub(r"0[xX]20[0-9a-fA-F]{6}\b",translated,path.read_text(encoding="utf-8-sig"))
        text=text.replace("SX4075 V4.51-J00", "SX4075 V4.51-E00")
        mod=ModuleType(name)
        mod.__file__=str(path.resolve())
        exec(compile(text,str(path),"exec"),mod.__dict__)
        return mod
    board=model("replay_705_font_boot")
    display=model("replay_705_boot_surfaces")
    board.BootClears,board.boot_outline=display.BootClears,display.boot_outline
    return board.replay_resource_task
