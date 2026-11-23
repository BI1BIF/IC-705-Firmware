"""Measure the stock RTX stack pool and create a worker at v1.4.0's cold HOME."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from struct import pack
from unittest.mock import patch

from tools import verify_705_aprs_slot as boot
from tools.build_705_dmr_ui import ROOT
from tools.emulate_705 import RAM, RAM_BYTES, arm, call, machine, uc

POOL=0x2049a5c0
CURRENT=0x20381e90


def measure(region):
    folder=ROOT/".analysis/aprs-hop/smart-final"/region
    out=ROOT/".analysis/dmr-ui"/region
    out.mkdir(parents=True,exist_ok=True)
    class Done(Exception):
        pass

    def observe(c,frame,slot,r,*_,**kwargs):
        assert r==region and c.mem_read(0x204bab5d,1)==b"\x01"
        delta=224 if region=="E" else 0
        def largest():
            # Each candidate sees exactly the same HOME RAM, including fragmentation.
            state=bytes(c.mem_read(RAM,RAM_BYTES))
            tmp=machine()
            lo,hi=0,0x20000//8  # isolated RTX stack pool is 129264 bytes
            while lo+1<hi:
                n=(lo+hi)//2
                tmp.mem_write(RAM,state)
                if call(tmp,0x202d4b17+delta,POOL,n*8): lo=n
                else: hi=n
            return lo*8

        def word(addr,n=4):
            return int.from_bytes(c.mem_read(addr,n),"little")
        resume=c.reg_read(arm.UC_ARM_REG_PC)
        saved=c.context_save()
        sp=c.reg_read(arm.UC_ARM_REG_SP)
        descriptor=(sp-32)&~7
        main=word(CURRENT)
        old=bytes(c.mem_read(descriptor,16))
        before=largest()
        (out/"rtx-home-ram.bin").write_bytes(bytes(c.mem_read(RAM,RAM_BYTES)))
        print(f"{region} verified HOME: max stack allocation {before}; current={main:#x} pc={resume:#x} sp={sp:#x}",flush=True)
        def create(size):
            # Lower priority than the HOME task; never run the placeholder entry.
            worker=0x200052a8
            c.mem_write(descriptor,pack("<4I",worker,0xe8,1,size))
            c.reg_write(arm.UC_ARM_REG_SP,descriptor-8)
            c.reg_write(arm.UC_ARM_REG_R0,descriptor)
            c.reg_write(arm.UC_ARM_REG_R1,0)
            c.reg_write(arm.UC_ARM_REG_LR,resume|(c.reg_read(arm.UC_ARM_REG_CPSR)>>5 & 1))
            hooks=[c.hook_add(uc.UC_HOOK_CODE,lambda cpu,*_:cpu.emu_stop(),begin=a,end=a)
                   for a in (worker,resume)]
            try: c.emu_start(0x202d48c1+delta,resume,count=300000)
            finally:
                for h in hooks: c.hook_del(h)
            actual=c.reg_read(arm.UC_ARM_REG_R0)
            pc=c.reg_read(arm.UC_ARM_REG_PC)
            if pc==worker and word(CURRENT)!=main:
                actual=word(CURRENT)
            else:
                assert pc==resume and word(CURRENT)==main,(hex(pc),hex(resume),hex(word(CURRENT)),hex(main),hex(actual))
            c.context_restore(saved)
            if not actual: return None
            base,size_actual,initial_sp=word(actual+0x2c),word(actual+0x26,2),word(actual+0x28)
            assert size_actual==size and word(base)==0xe25a2ea5 and initial_sp==((base+size)&~7)-64
            return dict(thread=hex(actual),base=hex(base),bytes=size,initial_sp=hex(initial_sp))

        sixteen=create(16384)
        fallback=None
        if not sixteen and before: fallback=create(min(before,0xfff8))
        c.mem_write(descriptor,old)
        report=dict(region=region,baseline=sha256((folder/f"705{region}140.dat").read_bytes()).hexdigest(),
            home_page=c.mem_read(0x204bab5d,1)[0],current=hex(main),pool=hex(POOL),
            largest_free_8byte_multiple_before=before,create_16384=sixteen,
            largest_verified_fallback=fallback,largest_free_8byte_multiple_after=largest())
        (out/"rtx-stack.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        print(report,flush=True)
        raise Done()
    with patch.object(boot,"check_home",observe):
        try: boot.run(region,"first",folder)
        except Done: return
    raise AssertionError("cold HOME not reached")


if __name__=="__main__":
    p=ArgumentParser(description=__doc__)
    p.add_argument("region",choices=["E","J"])
    measure(p.parse_args().region)
