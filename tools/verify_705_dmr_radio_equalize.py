"""Exercise automatic RX path selection using synthetic audio passbands."""
import json
from hashlib import sha256
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, lfilter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import verify_705_dmr_radio as radio
from unicorn import UC_HOOK_BLOCK

PROBE = """
#include <dmr-equalize.h>
dmr_frontend front;
unsigned char output[8192];
unsigned used;
dmr_radio state;
const unsigned state_bytes=sizeof(front);
void *memset(void *p,int v,size_t n) {
    unsigned char *b=p;
    while(n--) *b++=v;
    return p;
}
static void save(void *arg,const uint8_t v[27]) {
    (void)arg;
    for(unsigned i=0;i<27;++i) output[used++]=v[i];
}
void run(const int16_t *p,unsigned n) {
    while(n>=36) {dmr_frontend_block(&front,p,save,0); p+=36; n-=36;}
    /* Export the active/last receiver counters and selected branch. */
    const dmr_radio *r=dmr_frontend_status(&front);
    unsigned char *out=(unsigned char *)&state;
    for(unsigned i=0;i<27;++i) out[i]=((const unsigned char *)r)[i];
    state.active=front.last;
}
"""

def channel(pcm, highpass, tau=0, noise=0):
    y=pcm.astype(float)
    if highpass:
        y=lfilter(*butter(1,highpass,btype="high",fs=48000),y)
        y=lfilter(*butter(2,3000,fs=48000),y)
    if tau:
        y=lfilter(*butter(1,1e6/(2*np.pi*tau),fs=48000),y)
    if noise:
        y+=np.random.default_rng(705).normal(0,noise,len(y))
    return np.rint(np.clip(y,-32768,32767)).astype("<i2")

def instructions(image,pcm,start,length):
    binary,symbols=image
    cpu=radio.machine(binary)
    base=0x20100000
    cpu.mem_write(base,pcm.tobytes())
    count=0
    def executed(_cpu,_pc,size,_data):
        nonlocal count
        count+=size//4  # Probe and linked libgcc both use 32-bit ARM state.
    hook=cpu.hook_add(UC_HOOK_BLOCK,executed)
    if start:
        radio.call(cpu,symbols["run"],base,start,timeout_us=0,instruction_limit=10_000_000)
        count=0
    radio.call(cpu,symbols["run"],base+2*start,length,timeout_us=0,instruction_limit=10_000_000)
    cpu.hook_del(hook)
    return dict(arm_instructions=count,samples=length,instructions_per_sample=round(count/length,2))

def main():
    radio.OUT=radio.OUT/"equalizer"
    radio.WRAPPER=PROBE
    image=radio.build()
    source=(radio.HERE/"dmr-reference/voice9.bin").read_bytes()
    sent=source+source[-9:]
    pcm=radio.discriminator(radio.render_if(radio.mobile_call(sent)))
    cases={}
    for hp,tau,noise in [(0,0,0),(200,0,0),(250,0,0),(300,0,0),(200,75,2),(300,75,0),(200,300,0)]:
        name=f"hp{hp}-tau{tau}-noise{noise}"
        result,frames,size=radio.replay(image,channel(pcm,hp,tau,noise))
        errors=sum((a^b).bit_count() for a,b in zip(sent,frames))
        result["branch"]=result.pop("active")
        cases[name]=dict(**result,frames=len(frames)//9,bit_errors=errors if len(frames)==len(sent) else None,
                         bytes_equal=frames==sent,bytes_sha256=sha256(frames).hexdigest(),state_bytes=size)
        print(name,cases[name],flush=True)
    (radio.OUT/"results.json").write_text(json.dumps(cases,indent=2)+"\n",encoding="utf-8")
    for name,row in list(cases.items())[:5]:
        assert (row["source"],row["target"],row["color_code"],row["headers"],row["ends"])==(1234567,3100,7,1,1), (name,row)
        assert row["bytes_equal"] and row["branch"]==(1 if name.startswith("hp0-") else 2), (name,row)
    short=radio.discriminator(radio.render_if(radio.mobile_call(sent[:81])))
    def padded(v):
        return np.pad(v,(0,(-len(v))%36+2880))
    filtered=padded(channel(short,300))
    flat=padded(short)
    switches={}
    for name,samples,branch in [("flat_to_eq",np.concatenate((flat,filtered)),2),
                                ("eq_to_flat",np.concatenate((filtered,flat)),1),
                                ("flat_to_flat",np.tile(flat,2),1),
                                ("eq_to_eq",channel(np.tile(flat,2),300),2)]:
        result,frames,_=radio.replay(image,samples)
        assert frames==sent[:81]*2 and result["active"]==branch, (name,result)
        switches[name]=dict(last_branch=branch,frames=len(frames)//9,bytes_equal=True)
    # Independently restarted filter states splice a discontinuity into the
    # simulated receive port. Record it separately from the continuous channel.
    result,frames,_=radio.replay(image,np.tile(filtered,2))
    assert len(frames)==162 and result["ends"]==2
    switches["restarted_filter_splice"]=dict(frames=len(frames)//9,
        bit_errors=sum((a^b).bit_count() for a,b in zip(frames,sent[:81]*2)))
    cost=dict(search=instructions(image,np.zeros(2880,dtype="<i2"),0,2880),
              locked_flat=instructions(image,pcm,5760,17280),
              locked_equalized=instructions(image,channel(pcm,300),5760,17280))
    profile=dict(switches=switches,instruction_profile=cost)
    print(profile)
    (radio.OUT/"profile.json").write_text(json.dumps(profile,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
