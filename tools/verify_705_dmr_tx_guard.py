"""Exercise the wired MICPTT pin, CI-V mailbox and common TX grant on both public images."""
import json
from hashlib import sha256
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/".analysis/ic705-emulator/deps")]
from tools.decode_705_main import decode_main
from tools.dmr_tx_guard import BASE, FILTER, MAX_BYTES, install_guard
from tools.emulate_705 import call, machine
from tools.probe_705_cw_pcm import BUILD_REQUEST, FILTER_REQUEST, FILTERED, REQUEST, simulated_gpio
from tools.replay_705_ptt_tune import FLAGS, INIT_RANGES, STATUS_TASK
from tools.replay_705_vfo_split import CIV_BYTE, CIV_DISPATCH, SELECT_VFO, exchange_in_guest, seed_vfos

MIC_PORT=0xfcfe3214   # MAIN UNIT 6/8, MICPTT -> P5_5
DEBOUNCE=0x20401f95
SAMPLED_MIC=0x203e1e6b
TEST_FLAG=0x20810000

def verify(dat, region, *, installed_origin=None, active_address=TEST_FLAG):
    main=bytearray(decode_main(dat)[1])
    if installed_origin is None:
        # Keep the isolated test stub outside the initialized application and its BSS.
        origin=0x20600000
        main.extend(bytes(origin-BASE-len(main)+MAX_BYTES))
        patch=install_guard(main,region,origin,active_address)
    else:
        site=FILTER[region]
        insn=int.from_bytes(main[site-BASE:site-BASE+4],"little")
        offset=(insn&0xffffff) ^ 0x800000
        assert insn>>24==0xea and site+8+4*(offset-0x800000)==installed_origin
        patch=dict(site=site,origin=installed_origin,active=active_address,from_packaged_main=True)
    cpu=machine(bytes(main))
    def rom(pc):
        if region=="J": return pc
        if pc in (CIV_BYTE,CIV_DISPATCH,SELECT_VFO[0]): return pc-244
        if pc==INIT_RANGES: return pc+192
        return pc+228
    def invoke(pc,*args):
        return call(cpu,rom(pc),*args,instruction_limit=1500000)
    def get(addr,size=4):
        return int.from_bytes(cpu.mem_read(addr,size),"little")
    def put(addr,n,size=1):
        cpu.mem_write(addr,n.to_bytes(size,"little"))
    seed_vfos(cpu,(145500000,145500000))
    invoke(INIT_RANGES)
    invoke(SELECT_VFO[0])
    simulated_gpio(cpu,rom=rom)
    for a in (0x203e212f,0x203e2136): put(a,0x70)

    def grant():
        invoke(BUILD_REQUEST)
        invoke(FILTER_REQUEST)
        invoke(STATUS_TASK)
        return [get(REQUEST),get(FILTERED),bool(get(FLAGS,1)&128)]
    def civ(down):
        reply,_=exchange_in_guest(cpu,bytes((0x1c,0,int(down))),invoke=invoke)
        assert reply[2:-1]==b"\xfb"
        return grant()
    def sample_mic(down):
        put(MIC_PORT,32 if down else 0,2)
        # Run the native port sample block, including its own r5 pointer load.
        cpu.emu_start(rom(0x2011de5c),rom(0x2011de80))
        assert get(SAMPLED_MIC,1)==int(down)
    def mic(down):
        sample_mic(down)
        # The radio's periodic timer normally increments the builder's debounce byte.
        grant()
        put(DEBOUNCE,36)
        grant()
        return grant()
    results={}
    for name,request,mask in (("wired_mic",mic,0x400),("ci_v",civ,0x8000)):
        rows={}
        rows["stock_permission"]=request(True)
        rows["stock_release"]=request(False)
        put(active_address,1)
        rows["dmr_held"]=request(True)
        rows["dmr_still_held"]=grant()
        put(active_address,0)
        rows["exit_held"]=grant()
        rows["release_after_exit"]=request(False)
        rows["fresh_request"]=request(True)
        rows["final_release"]=request(False)
        for stage in ("stock_permission","fresh_request"):
            assert rows[stage]==[mask,mask,True],(name,stage,rows)
        for stage in ("dmr_held","dmr_still_held","exit_held"):
            assert rows[stage]==[mask,0,False],(name,stage,rows)
        for stage in ("stock_release","release_after_exit","final_release"):
            assert rows[stage]==[0,0,False],(name,stage,rows)
        results[name]=rows
    put(active_address,1)
    sample_mic(True)
    assert grant()==[0,0,False]
    put(active_address,0)
    assert grant()==[0,0,False]
    assert mic(True)==[0x400,0,False]
    assert mic(False)==[0,0,False]
    assert mic(True)==[0x400,0x400,True]
    assert mic(False)==[0,0,False]
    results["exit_before_mic_debounce"]="held until release; fresh press granted"
    return dict(dat_sha256=sha256(dat).hexdigest(),patch=patch,sequence=results)

if __name__=="__main__":
    report={r:verify((ROOT/f".analysis/release-v1.4.0/verified/705{r}140.dat").read_bytes(),r) for r in "JE"}
    dest=ROOT/".analysis/dmr-if-study/tx-guard.json"
    dest.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(dest)
