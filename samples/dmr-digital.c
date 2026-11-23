/* Conventional P25 Phase 1 and System Fusion, one tuned carrier and one worker. */
#include "dmr-digital.h"
#include <string.h>
struct digital_call digital_call;
enum { AUDIO_BRANCHES=4 };
static struct {
    int16_t history[AUDIO_BRANCHES][256];
    int32_t integral, previous;
    uint32_t signs[AUDIO_BRANCHES][10], clock, best_tick, deadline, next, last_frame;
    unsigned count, duid, nac, phase, pending, protected_call, branch;
    float best, center, gain;
    uint8_t dibits[864];
} rx;

static unsigned value(const uint8_t *bits,unsigned n) {
    unsigned v=0;
    while(n--) v=2*v+*bits++;
    return v;
}

static unsigned airbit(unsigned pos) {
    return (rx.dibits[pos/2]>>(1-pos%2))&1;
}

static unsigned p25_get(unsigned *p, unsigned n) {
    unsigned v=0;
    while(n--) {
        if (*p%72==70) *p+=2;
        v=2*v+airbit((*p)++);
    }
    return v;
}

static int p25_nid(void) {
    static const uint64_t rows[]={
        0xcd930bdd3b2aULL,0xab5a8e33a6beULL,0x983e4cc4e874ULL,0x4c1f2662743aULL,
        0xeb9c98ec0136ULL,0xb85d47ab3bb0ULL,0x5c2ea3d59dd8ULL,0x2e1751eaceecULL,
        0x170ba8f56776ULL,0xc616dfa78890ULL,0x630b6fd3c448ULL,0x3185b7e9e224ULL,
        0x18c2dbf4f112ULL,0xc1f2662743a2ULL,0xad6a38ce9afbULL,0x9b2617ba7657ULL};
    unsigned p=48, info=p25_get(&p,16);
    uint64_t parity=(uint64_t)p25_get(&p,24)<<24;
    parity|=p25_get(&p,24);
    for(unsigned i=0;i<16;++i)
        if(info&(0x8000u>>i)) parity^=rows[i];
    if(__builtin_popcountll(parity>>1)>2) return 0;
    rx.duid=info&15;
    unsigned nac=info>>4;
    if(rx.nac!=nac || rx.duid==0 || rx.duid==3 || rx.duid==15) {
        digital_call.active=0;
        rx.protected_call=0;
    }
    rx.nac=nac;
    return rx.duid==5 || rx.duid==10;
}

static unsigned gf_mul(unsigned a,unsigned b) {
    unsigned r=0;
    while(b) {
        if(b&1) r^=a;
        b>>=1; a<<=1;
        if(a&64) a^=0x43;
    }
    return r;
}

static int p25_control(uint8_t bytes[12]) {
    static const unsigned starts[]={410,600,788,978,1168,1356};
    static const unsigned columns[]={14,13,11,7,3,12};
    unsigned symbols[24];
    for(unsigned j=0;j<6;++j) {
        unsigned p=starts[j];
        for(unsigned k=0;k<4;++k) {
            unsigned d=p25_get(&p,6), syndrome=p25_get(&p,4);
            for(unsigned i=0;i<6;++i) if(d&(32>>i)) syndrome^=columns[i];
            for(unsigned i=0;i<6;++i) if(syndrome==columns[i]) d^=32>>i;
            symbols[4*j+k]=d;
        }
    }
    unsigned parity=rx.duid==5 ? 12 : 8, root=1;
    for(unsigned i=0;i<parity;++i) {
        root=gf_mul(root,2);
        unsigned check=0;
        for(unsigned j=0;j<24;++j) check=gf_mul(check,root)^symbols[j];
        if(check) return 0;
    }
    for(unsigned i=0;i<16;++i)
        for(unsigned j=0;j<6;++j) {
            unsigned pos=i*6+j;
            bytes[pos/8]=(bytes[pos/8]<<1)|((symbols[i]>>(5-j))&1);
        }
    return 1;
}

static void start_call(unsigned kind,unsigned code,unsigned src,unsigned dst) {
    if(!digital_call.active || kind!=digital_call.kind || code!=digital_call.code ||
       src!=digital_call.source || dst!=digital_call.target) {
        dmr_audio_reset();
        digital_alert(kind);
    }
    digital_call.active=1; digital_call.kind=kind; digital_call.code=code;
    digital_call.source=src; digital_call.target=dst;
}

static void p25_frame(void) {
    static const unsigned voice[]={114,262,452,640,830,1020,1208,1398,1578};
    uint8_t lc[12]={0};
    if(!p25_control(lc)) { digital_call.active=0; return; }
    rx.last_frame=rx.clock;
    if(rx.duid==10) {
        rx.protected_call=lc[9]!=0x80;
        if(rx.protected_call) digital_call.active=0;
    } else {
        if(lc[1] || (lc[0]!=0 && lc[0]!=3) || (lc[2]&0x40) || rx.protected_call) {
            digital_call.active=0; return;
        }
        unsigned dst=(lc[4]<<8)|lc[5], src=(lc[6]<<16)|(lc[7]<<8)|lc[8];
        if(lc[0]==3) dst|=lc[3]<<16;
        unsigned kind=lc[0]==3 ? CALL_PRIVATE : dst==65535 ? CALL_ALL : CALL_GROUP;
        start_call(kind,rx.nac,src,dst);
    }
    if(!digital_call.active) return;
    for(unsigned i=0;i<9;++i) {
        uint8_t data[18];
        unsigned p=voice[i];
        for(unsigned j=0;j<18;++j) data[j]=p25_get(&p,8);
        digital_imbe(data,0);
    }
}

/* Trace one predecessor bit per state at each K=5 trellis step. */
static void viterbi(const uint8_t *air,unsigned steps,uint8_t *bits) {
    uint16_t trace[180], costs[16]={0}, next[16];
    for(unsigned s=1;s<16;++s) costs[s]=1000;
    unsigned depth=steps/20;
    for(unsigned i=0;i<steps;++i) {
        unsigned dibit=air[(i%depth)*20+i/depth], decisions=0;
        for(unsigned s=0;s<16;++s) {
            unsigned reg=s, prev=s>>1;
            unsigned pair=2*__builtin_parity(reg&25)+__builtin_parity(reg&23);
            unsigned weight=__builtin_popcount(pair^dibit);
            unsigned a=costs[prev]+weight, b=costs[prev+8]+2-weight;
            if(b<a) decisions|=1u<<s;
            next[s]=a<b ? a : b;
        }
        trace[i]=decisions; memcpy(costs,next,sizeof(costs));
    }
    unsigned s=0;
    while(steps) {
        --steps; bits[steps]=s&1;
        s=(s>>1)|(((trace[steps]>>s)&1)<<3);
    }
}

static unsigned crc16(const uint8_t *bits,unsigned n) {
    unsigned crc=0;
    while(n--) {
        unsigned top=(crc>>15)^*bits++;
        crc=((crc<<1)&65535)^(top ? 0x1021 : 0);
    }
    return crc^65535;
}
static unsigned golay(unsigned data) {
    unsigned r=data<<11;
    for(int i=22;i>=11;--i) if(r&(1u<<i)) r^=0xc75u<<(i-11);
    unsigned word=(data<<11)|r;
    return (word<<1)|__builtin_parity(word);
}
static int fich(uint8_t *info) {
    uint8_t bits[100];
    viterbi(rx.dibits+20,100,bits);
    for(unsigned k=0;k<4;++k) {
        unsigned w=value(bits+24*k,24), data=w>>12;
        /* Try the systematic word and one corrected information bit. */
        unsigned i=0, d=data;
        while(__builtin_popcount(golay(d)^w)>3) {
            if(i==12) return 0;
            d=data^(1u<<i++);
        }
        for(i=0;i<12;++i) info[k*12+i]=(d>>(11-i))&1;
    }
    return crc16(info,32)==value(info+32,16);
}
static void unwhiten(uint8_t *bits,unsigned n) {
    unsigned reg=0x1c9;
    for(unsigned i=0;i<n;++i) {
        bits[i]^=reg&1;
        reg=(reg>>1)|(((reg^(reg>>4))&1)<<8);
    }
}
static void callsign(unsigned width,unsigned offset) {
    uint8_t coded[180],bits[180]; unsigned steps=5*width;
    for(unsigned i=0;i<5;++i) memcpy(coded+i*width,rx.dibits+120+72*i,width);
    viterbi(coded,steps,bits);
    if(crc16(bits,steps-20)!=value(bits+steps-20,16)) return;
    unwhiten(bits,steps-20);
    char text[11]={0};
    for(unsigned i=0;i<10;++i) {
        unsigned ch=value(bits+offset+8*i,8);
        if(ch<32 || ch>126) return;
        text[i]=ch;
    }
    for(int i=9;i>=0 && text[i]==' ';--i) text[i]=0;
    memcpy(digital_call.callsign,text,sizeof(text));
}
static void fusion_frame(void) {
    uint8_t info[48];
    if(!fich(info)) return;
    unsigned fi=value(info,2), cm=value(info+4,2), fn=value(info+10,3);
    unsigned ft=value(info+13,3), dt=value(info+22,2), dg=value(info+25,7);
    rx.last_frame=rx.clock;
    if(fi==0 || fi==2) {
        digital_call.active=0; digital_call.callsign[0]=0;
        if(!fi) callsign(36,80);
        return;
    }
    if(fi!=1 || dt==1) { digital_call.active=0; return; }
    start_call(cm==0 ? CALL_GROUP : cm==3 ? CALL_PRIVATE : CALL_UNKNOWN,dg,0,0);
    digital_call.format=dt;
    if(dt==2 && fn==1) callsign(20,0);
    if(dt==0 && fn==0) callsign(36,80);
    for(unsigned i=0;i<5;++i) {
        unsigned pos=240+144*i;
        if(dt==2) {
            uint8_t ordered[104]; char bits[49];
            for(unsigned j=0;j<104;++j) ordered[(j%4)*26+j/4]=airbit(pos+40+j);
            unwhiten(ordered,104);
            for(unsigned j=0;j<27;++j) bits[j]=ordered[3*j]+ordered[3*j+1]+ordered[3*j+2]>=2;
            memcpy(bits+27,ordered+81,22);
            digital_ambe(bits);
        } else {
            uint8_t data[18]={0};
            if(dt==3 && ft==1 && !fn && i<3) continue;
            unsigned count=dt==0 ? 72 : 144;
            pos+=144-count;
            for(unsigned j=0;j<count;++j) data[j/8]=(data[j/8]<<1)|airbit(pos+j);
            if(dt==0) dmr_audio_frame(data); else digital_imbe(data,1);
        }
    }
}

void digital_reset(void) {
    memset(&rx,0,sizeof(rx));
    memset(&digital_call,0,sizeof(digital_call));
}

static void correlate(unsigned mode,unsigned n,unsigned branch) {
    static const int8_t p25[]={3,3,3,3,3,-3,3,3,-3,-3,3,3,-3,-3,-3,-3,3,-3,3,-3,-3,-3,-3,-3};
    static const int8_t ysf[]={-3,3,3,1,3,-3,1,3,-3,1,-1,3,3,-1,1,-3,3,1,-3,3};
    const int8_t *levels=mode==RX_P25 ? p25 : ysf;
    float sx=0,sy=0,xx=0,xy=0,yy=0;
    for(unsigned i=0;i<n;++i) {
        float x=levels[i], y=rx.history[branch][(rx.clock-10*(n-1-i))&255];
        sx+=x; sy+=y; xx+=x*x; xy+=x*y; yy+=y*y;
    }
    xx-=sx*sx/n; xy-=sx*sy/n; yy-=sy*sy/n;
    if(yy<64*n) return;
    float score=xy*xy/(xx*yy);
    if(score<0.72f || (rx.pending && score<=rx.best)) return;
    if(!rx.pending) { rx.deadline=rx.clock+9; rx.pending=1; }
    rx.best=score; rx.best_tick=rx.clock; rx.branch=branch;
    rx.gain=xy/xx; rx.center=(sy-rx.gain*sx)/n;
}

static int16_t clip_pcm(int value) {
    return value>32767 ? 32767 : value< -32768 ? -32768 : value;
}

void digital_block(unsigned mode,const int16_t pcm[36]) {
    unsigned n=mode==RX_P25 ? 24 : 20, mask=(1u<<n)-1;
    unsigned sync=mode==RX_P25 ? 0x4cf5f : 0x84a52;
    for(unsigned i=0;i<36;++i) {
        ++rx.clock;
        unsigned index=rx.clock&255, phase=rx.phase;
        int v=pcm[i];
        rx.integral+=v-(rx.integral>>12);
        int delta=v-rx.previous;
        rx.previous=v;
        rx.history[0][index]=v;
        rx.history[1][index]=clip_pcm((v+2*delta+8*(rx.integral>>8))/2);
        /* Let the sync word select the compensation for FM receive de-emphasis. */
        int level=v+(rx.integral>>5);
        rx.history[2][index]=clip_pcm((level+8*delta)/2);
        rx.history[3][index]=clip_pcm((level+12*delta)/2);
        rx.phase=rx.phase==9 ? 0 : rx.phase+1;
        if(rx.clock-rx.last_frame>21600 && (digital_call.active || rx.protected_call || digital_call.callsign[0])) {
            digital_call.active=0; rx.protected_call=0; digital_call.callsign[0]=0;
        }
        if(!rx.count) {
            for(unsigned b=0;b<AUDIO_BRANCHES;++b) {
                uint32_t *s=&rx.signs[b][phase];
                *s=(*s<<1)|(rx.history[b][index]<0);
                unsigned diff=(*s^sync)&mask, inv=diff^mask;
                if(!(diff&(diff-1)) || !(inv&(inv-1))) correlate(mode,n,b);
            }
            if(rx.pending && rx.clock==rx.deadline) {
                rx.next=rx.best_tick+10; rx.count=n; rx.pending=0;
            }
        } else if(rx.clock==rx.next) {
            float v=rx.history[rx.branch][index]-rx.center, gain=rx.gain;
            if(gain<0) { gain=-gain; v=-v; }
            rx.dibits[rx.count++]=(v<0 ? 2 : 0)+(v>2*gain || v< -2*gain);
            rx.next+=10;
            if(mode==RX_P25 && rx.count==57 && !p25_nid()) rx.count=0;
            if(mode==RX_P25 && rx.count==864) { p25_frame(); rx.count=0; }
            if(mode==RX_YSF && rx.count==480) { fusion_frame(); rx.count=0; }
        }
    }
}
