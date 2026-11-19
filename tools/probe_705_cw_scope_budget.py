"""Check J140 scope raster cadence under external RF draws; no GPU or boot.

Run with the existing Unicorn dependency path:
python -m tools.probe_705_cw_scope_budget candidate.ic705sim new-report.json
Add --baseline previous.ic705sim for a same-audio instruction comparison.
Use --interval-ms for a candidate with a different ordinary raster cadence.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from struct import iter_unpack, pack, unpack

from tools.build_705_cw_sim import load_image
from tools.emulate_705 import BASE, SP, STOP, arm, call, machine, uc
from tools.probe_705_cw_break_in import audio
from tools.probe_705_cw_field_audio import STATE, bl_target

CANVAS,SIZE,CLOCK=0x20800010,184*60*2,0x20381e08

def entry(main,meta):
    renderer=bl_target(main,int(meta['branch_sites']['0x2013d4a8'],16)+48)
    for address in range(renderer,renderer+0x180,4):
        instruction=unpack('<I',main[address-BASE:address-BASE+4])[0]
        if instruction>>24==0xeb:
            target=bl_target(main,address)
            if meta['code_base']<=target<meta['code_end']:
                return target
    raise AssertionError('scope call not found')

class Fixture:
    def __init__(self,bundle):
        self.image,self.meta=load_image(bundle)
        self.cpu=machine(self.image[0])
        self.cpu.reg_write(arm.UC_ARM_REG_C1_C0_2,0xf00000)
        self.cpu.reg_write(arm.UC_ARM_REG_FPEXC,0x40000000)
        self.cpu.mem_write(self.meta['symbols']['cw_state_anchor'],pack('<I',STATE))
        self.put(0,1)
        self.put(0x714,CANVAS)
        self.cpu.mem_write(0x203e2128,b'\x20')
        self.worker=bl_target(self.image[0],self.meta['symbols']['cw_rtx_worker']+28)
        self.scope=entry(self.image[0],self.meta)
        self.writes=0
        self.instructions=0
        self.drawing=False
        def boundary(c,*_):
            c.reg_write(arm.UC_ARM_REG_PC,STOP)
            c.emu_stop()
        def write(c,kind,address,width,value,_):
            if self.drawing: self.writes+=width
        def instruction(c,address,*_):
            if self.drawing: self.instructions+=1
        self.cpu.hook_add(uc.UC_HOOK_CODE,boundary,begin=0x2010feb0,end=0x2010feb0)
        self.cpu.hook_add(uc.UC_HOOK_MEM_WRITE,write,begin=CANVAS,end=CANVAS+SIZE-1)
        # Scope helpers can precede its entry; drawing limits this full-code counter.
        self.cpu.hook_add(uc.UC_HOOK_CODE,instruction,begin=self.meta['code_base'],end=self.meta['code_end']-1)
    def put(self,offset,value):
        self.cpu.mem_write(STATE+offset,pack('<I',value))
    def get(self,offset):
        return unpack('<I',self.cpu.mem_read(STATE+offset,4))[0]
    def draw(self,milliseconds):
        self.cpu.mem_write(CLOCK,pack('<I',milliseconds&0xffffffff))
        before=bytes(self.cpu.mem_read(CANVAS,SIZE))
        self.writes=self.instructions=0
        self.drawing=True
        call(self.cpu,self.scope,instruction_limit=1000000,timeout_us=0)
        self.drawing=False
        after=bytes(self.cpu.mem_read(CANVAS,SIZE))
        if not self.writes: assert after==before,'canvas changed on a reused draw'
        return dict(write_bytes=self.writes,arm_instructions=self.instructions,
                    bitmap_sha256=sha256(after).hexdigest())
    def feed(self,six):
        self.cpu.mem_write(SP+8,pack('<6h',*six))
        call(self.cpu,self.meta['symbols']['cw_pcm_bridge'],timeout_us=0)
        assert call(self.cpu,self.worker,1,timeout_us=0)==1

def replay(bundle,hz,start_ms,*,limited,interval_ms=120):
    f=Fixture(bundle)
    raw=audio('CQ',trim_leading=True)+bytes(3204)
    groups=list(iter_unpack('<6h',raw[:len(raw)//12*12]))
    frames=[]
    frame=1
    for index,six in enumerate(groups,1):
        now=start_ms+index*3//4
        f.cpu.mem_write(CLOCK,pack('<I',now&0xffffffff))
        f.feed(six)
        while index*6*hz>=frame*8000:
            row=f.draw(now)
            row.update(frame=frame,elapsed_ms=now-start_ms,fed=f.get(8))
            frames.append(row)
            frame+=1
    text=bytes(f.cpu.mem_read(STATE+344,f.get(20))).decode('ascii')
    counters=unpack('<4I',f.cpu.mem_read(STATE+0x71c,16))
    rebuilt=[row for row in frames if row['write_bytes']]
    counts=Counter(row['elapsed_ms']//1000 for row in rebuilt)
    if limited:
        assert max(counts.values())<=(1000+interval_ms-1)//interval_ms+1,counts
        gaps=[b['elapsed_ms']-a['elapsed_ms'] for a,b in zip(rebuilt,rebuilt[1:])]
        assert all(interval_ms<=gap<=interval_ms+(1000+hz-1)//hz+1 for gap in gaps),gaps
        assert len(rebuilt)>=int(len(groups)*.75/(interval_ms+1000/hz)),'render starved'
    assert text.strip()=='CQ',text
    assert counters[1:]==(len(groups),)*3,counters
    assert f.get(740)==0,'dropped PCM'
    return dict(application_sha256=f.image[3],scope_entry=hex(f.scope),rf_draw_hz=hz,
                start_ms=start_ms,pcm_groups=len(groups),fed=f.get(8),text=text,
                diagnostic_raw_tap_in_out=list(counters),drops=f.get(740),
                frames=frames,full_raster_calls=len(rebuilt),
                full_raster_calls_per_elapsed_second=dict(sorted(counts.items())),
                cpu_scope_arm_instructions=sum(row['arm_instructions'] for row in frames))

def state_changes(bundle,interval_ms=120):
    f=Fixture(bundle)
    f.put(8,1)
    assert f.draw(1000)['write_bytes']
    f.put(8,2)
    assert not f.draw(1001)['write_bytes'],'audio alone rebuilt inside the cadence limit'
    rows=[]
    def check(name,change):
        change()
        result=f.draw(1002)
        assert result['write_bytes'],name
        rows.append(dict(case=name,**result))
    check('generation',lambda:f.put(724,f.get(724)+1))
    check('wave-color',lambda:f.put(1732,0xff0000ff))
    check('fft-color',lambda:f.put(1728,0xffff00ff))
    check('pitch-marker',lambda:f.put(1688,600))
    check('receive-blocked',lambda:f.cpu.mem_write(0x203e2128,b'\x00'))
    check('receive-resumed',lambda:f.cpu.mem_write(0x203e2128,b'\x20'))
    assert not f.draw(1003)['write_bytes'],'unchanged key was not reused'
    f.put(8,f.get(8)+1)
    assert f.draw(1002+interval_ms)['write_bytes'],'audio refresh did not resume at the cadence limit'
    return dict(application_sha256=f.image[3],cases=rows,
                only_audio_change_at_1ms_reused=True,unchanged_key_reused=True,
                next_audio_refresh_at_interval_ms=interval_ms)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('bundle',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--baseline',type=Path)
    p.add_argument('--interval-ms',type=int,default=120)
    args=p.parse_args()
    if args.interval_ms<2: p.error('--interval-ms must be at least 2')
    assert not args.output.exists(),'output already exists'
    report=dict(scope='Exact ARM PCM bridge, audio worker and CPU scope only; no native GPU/cache/panel timing',
                candidate_interval_ms=args.interval_ms,
                candidate=[replay(args.bundle,hz,start,limited=True,interval_ms=args.interval_ms)
                           for hz in (30,60) for start in (0,0xffffff00)],
                immediate_state_changes=state_changes(args.bundle,args.interval_ms))
    if args.baseline:
        report['baseline']=[replay(args.baseline,hz,0,limited=False) for hz in (30,60)]
        reference=report['baseline'][0]
        for row in report['candidate']:
            for key in ('pcm_groups','fed','text','diagnostic_raw_tap_in_out','drops'):
                assert row[key]==reference[key],key
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(candidate=[{k:r[k] for k in ('rf_draw_hz','start_ms','full_raster_calls','cpu_scope_arm_instructions','text')} for r in report['candidate']],
                          baseline=[{k:r[k] for k in ('rf_draw_hz','full_raster_calls','cpu_scope_arm_instructions')} for r in report.get('baseline',[])]),indent=2),flush=True)

if __name__=='__main__': main()
