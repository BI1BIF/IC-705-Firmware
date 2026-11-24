/* Conventional P25 Phase 1 and System Fusion, one tuned carrier and one worker. */
#include "dmr-digital.h"
#include <string.h>
struct digital_call digital_call;
enum { AUDIO_BRANCHES=4 };
static struct {
    int16_t history[AUDIO_BRANCHES][256];
    int32_t integral, previous;
    uint32_t signs[AUDIO_BRANCHES][10], clock, best_tick, deadline, next, last_frame;
    unsigned count, nid, equalized_nid, nac, phase, pending, protected_call, branch;
    float best, center, gain;
    uint16_t audio_signs[10];
    unsigned audio_pending, audio_tick, audio_count, audio_next, frame_seen, audio_profile;
    float audio_score, audio_scale, symbol_scale, response_margin, response_history;
    int8_t fich_levels[100];
    uint8_t dibits[864], equalized_dibits[864];
} rx;

static unsigned value(const uint8_t *bits,unsigned n) {
    unsigned v=0;
    while(n--) v=2*v+*bits++;
    return v;
}

static unsigned airbit(const uint8_t *frame,unsigned pos) {
    return (frame[pos/2]>>(1-pos%2))&1;
}

static unsigned p25_get(const uint8_t *frame,unsigned *p, unsigned n) {
    unsigned v=0;
    while(n--) {
        if (*p%72==70) *p+=2;
        v=2*v+airbit(frame,(*p)++);
    }
    return v;
}

static int p25_nid(const uint8_t *frame,unsigned *nid) {
    static const uint64_t rows[]={
        0xcd930bdd3b2aULL,0xab5a8e33a6beULL,0x983e4cc4e874ULL,0x4c1f2662743aULL,
        0xeb9c98ec0136ULL,0xb85d47ab3bb0ULL,0x5c2ea3d59dd8ULL,0x2e1751eaceecULL,
        0x170ba8f56776ULL,0xc616dfa78890ULL,0x630b6fd3c448ULL,0x3185b7e9e224ULL,
        0x18c2dbf4f112ULL,0xc1f2662743a2ULL,0xad6a38ce9afbULL,0x9b2617ba7657ULL};
    unsigned p=48, info=p25_get(frame,&p,16);
    uint64_t parity=(uint64_t)p25_get(frame,&p,24)<<24;
    parity|=p25_get(frame,&p,24);
    for(unsigned i=0;i<16;++i)
        if(info&(0x8000u>>i)) parity^=rows[i];
    /* BCH(63,16,23): this radius of eight has a unique solution. Try up
       to two bad information bits; the remaining errors may be in parity. */
    if(__builtin_popcountll(parity>>1)>8) {
        unsigned correction=0;
        for(unsigned i=0;i<16 && !correction;++i) {
            uint64_t one=parity^rows[i];
            if(__builtin_popcountll(one>>1)<=7) correction=0x8000u>>i;
            for(unsigned j=i+1;j<16 && !correction;++j)
                if(__builtin_popcountll((one^rows[j])>>1)<=6)
                    correction=(0x8000u>>i)|(0x8000u>>j);
        }
        if(!correction) return 0;
        info^=correction;
    }
    unsigned duid=info&15;
    *nid=info;
    unsigned nac=info>>4;
    if(rx.nac!=nac || duid==0 || duid==3 || duid==15) {
        digital_call.active=0;
        rx.protected_call=0;
        rx.frame_seen=0;
    }
    rx.nac=nac;
    return duid==5 || duid==10;
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

static unsigned gf_inverse(unsigned v) {
    unsigned r=1;
    for(unsigned power=62;power;power>>=1) {
        if(power&1) r=gf_mul(r,v);
        v=gf_mul(v,v);
    }
    return r;
}

static unsigned gf_eval(const unsigned *coeff,unsigned count,unsigned x) {
    unsigned sum=0;
    while(count) sum=gf_mul(sum,x)^coeff[--count];
    return sum;
}

static unsigned syndromes(const unsigned word[24],unsigned *s,unsigned parity) {
    unsigned root=1, bad=0;
    for(unsigned k=0;k<parity;++k) {
        root=gf_mul(root,2);
        unsigned v=0;
        for(unsigned j=0;j<24;++j) v=gf_mul(v,root)^word[j];
        bad|=s[k]=v;
    }
    return bad;
}

/* Shortened GF(64) RS: Berlekamp-Massey locator and Forney magnitudes.
   Accept corrected control bytes only after all syndromes are zero. */
static int p25_rs(unsigned word[24],unsigned parity) {
    unsigned s[12], loc[13]={1}, prev[13]={1}, degree=0, shift=1, scale=1;
    if(!syndromes(word,s,parity)) return 1;
    for(unsigned k=0;k<parity;++k) {
        unsigned discrepancy=s[k];
        for(unsigned j=1;j<=degree;++j) discrepancy^=gf_mul(loc[j],s[k-j]);
        if(!discrepancy) { ++shift; continue; }
        unsigned before[13], factor=gf_mul(discrepancy,gf_inverse(scale));
        memcpy(before,loc,sizeof(loc));
        for(unsigned j=shift;j<=parity;++j) loc[j]^=gf_mul(factor,prev[j-shift]);
        if(2*degree<=k) {
            degree=k+1-degree; memcpy(prev,before,sizeof(prev));
            scale=discrepancy; shift=1;
        } else ++shift;
    }
    if(!degree || degree>parity/2) return 0;
    unsigned omega[6]={0}, derivative[6]={0};
    for(unsigned i=0;i<degree;++i) {
        for(unsigned j=0;j<=i;++j) omega[i]^=gf_mul(loc[j],s[i-j]);
        if(!(i&1)) derivative[i]=loc[i+1];
    }
    unsigned roots=0, z=1, half=gf_inverse(2);
    for(unsigned j=24;j;--j,z=gf_mul(z,half)) {
        if(gf_eval(loc,degree+1,z)) continue;
        unsigned den=gf_eval(derivative,degree,z);
        if(!den) return 0;
        word[j-1]^=gf_mul(gf_eval(omega,degree,z),gf_inverse(den));
        ++roots;
    }
    return roots==degree && !syndromes(word,s,parity);
}

static int p25_control(const uint8_t *frame,unsigned duid,uint8_t bytes[12]) {
    static const unsigned starts[]={410,600,788,978,1168,1356};
    static const unsigned columns[]={14,13,11,7,3,12};
    unsigned symbols[24];
    for(unsigned j=0;j<6;++j) {
        unsigned p=starts[j];
        for(unsigned k=0;k<4;++k) {
            unsigned d=p25_get(frame,&p,6), syndrome=p25_get(frame,&p,4);
            for(unsigned i=0;i<6;++i) if(d&(32>>i)) syndrome^=columns[i];
            for(unsigned i=0;i<6;++i) if(syndrome==columns[i]) d^=32>>i;
            symbols[4*j+k]=d;
        }
    }
    if(!p25_rs(symbols,duid==5 ? 12 : 8)) return 0;
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

static void p25_frame(const uint8_t *frame,unsigned nid) {
    static const unsigned voice[]={114,262,452,640,830,1020,1208,1398,1578};
    uint8_t lc[12]={0};
    if(rx.nac!=(nid>>4) || (rx.frame_seen && rx.clock-rx.last_frame<4320)) return;
    unsigned duid=nid&15;
    if(!p25_control(frame,duid,lc)) return;
    rx.frame_seen=1;
    rx.last_frame=rx.clock;
    if(duid==10) {
        rx.protected_call=lc[9]!=0x80;
        if(rx.protected_call) digital_call.active=0;
        else if(!digital_call.active) start_call(CALL_UNKNOWN,rx.nac,UINT32_MAX,UINT32_MAX);
    } else {
        unsigned opcode=lc[0]&63;
        unsigned standard=(lc[0]&0x40) || lc[1]<=1;
        unsigned regroup=lc[1]==0x90 && opcode==0;
        if((lc[0]&0x80) || (!standard && !regroup) || (opcode!=0 && opcode!=3) ||
           (lc[2]&0x40) || rx.protected_call) {
            digital_call.active=0; return;
        }
        unsigned dst=(lc[4]<<8)|lc[5], src=(lc[6]<<16)|(lc[7]<<8)|lc[8];
        if(opcode==3) dst|=lc[3]<<16;
        unsigned kind=opcode==3 ? CALL_PRIVATE : dst==65535 ? CALL_ALL : CALL_GROUP;
        start_call(kind,rx.nac,src,dst);
    }
    if(!digital_call.active) return;
    for(unsigned i=0;i<9;++i) {
        uint8_t data[18];
        unsigned p=voice[i];
        for(unsigned j=0;j<18;++j) data[j]=p25_get(frame,&p,8);
        digital_imbe(data,0);
    }
}

/* Trace one predecessor bit per state at each K=5 trellis step. */
static void viterbi(const uint8_t *air,unsigned steps,uint8_t *bits,const int8_t *soft) {
    uint16_t trace[180], costs[16]={0}, next[16];
    for(unsigned s=1;s<16;++s) costs[s]=8192;
    unsigned depth=steps/20;
    for(unsigned i=0;i<steps;++i) {
        unsigned j=(i%depth)*20+i/depth, dibit=air[j], decisions=0, metric[4];
        for(unsigned k=0;k<4;++k) {
            static const int8_t level[]={4,12,-4,-12};
            int error=soft ? soft[j]-level[k] : 0;
            metric[k]=soft ? (unsigned)(error*error)/4 : __builtin_popcount(k^dibit);
        }
        for(unsigned s=0;s<16;++s) {
            unsigned reg=s, prev=s>>1;
            unsigned pair=2*__builtin_parity(reg&25)+__builtin_parity(reg&23);
            unsigned a=costs[prev]+metric[pair], b=costs[prev+8]+metric[pair^3];
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
/* Extended Golay has minimum distance eight. Search the systematic data
   half for up to three errors and charge the remaining radius to parity. */
static int golay_correct(unsigned word,unsigned *out) {
    unsigned data=word>>12, syndrome=(golay(data)^word)&4095;
    if(__builtin_popcount(syndrome)<=3) { *out=data; return 1; }
    static const uint16_t columns[]={0x8eb,0x93e,0xa97,0xdc6,0x367,0x6cd,0xd99,0x3da,0x7b4,0xf68,0x63b,0xc75};
    for(unsigned i=0;i<12;++i) {
        unsigned one=syndrome^columns[i], a=data^(1u<<i);
        if(__builtin_popcount(one)<=2) { *out=a; return 1; }
        for(unsigned j=i+1;j<12;++j) {
            unsigned two=one^columns[j], b=a^(1u<<j);
            if(!(two&(two-1))) { *out=b; return 1; }
            for(unsigned k=j+1;k<12;++k)
                if(two==columns[k]) { *out=b^(1u<<k); return 1; }
        }
    }
    return 0;
}
static int fich(const uint8_t *frame,uint8_t *info,const int8_t *soft) {
    uint8_t bits[100];
    int8_t sliced[100];
    if(!soft && frame==rx.equalized_dibits) {
        static const int8_t level[]={4,12,-4,-12};
        for(unsigned i=0;i<100;++i) sliced[i]=level[frame[20+i]];
        soft=sliced;
    }
    viterbi(frame+20,100,bits,soft);
    for(unsigned k=0;k<4;++k) {
        unsigned data;
        if(!golay_correct(value(bits+24*k,24),&data)) return 0;
        for(unsigned i=0;i<12;++i) info[k*12+i]=(data>>(11-i))&1;
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
static void callsign(const uint8_t *frame,unsigned width,unsigned offset) {
    uint8_t coded[180],bits[180]; unsigned steps=5*width;
    for(unsigned i=0;i<5;++i) memcpy(coded+i*width,frame+120+72*i,width);
    viterbi(coded,steps,bits,0);
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
static void fusion_frame(const uint8_t *frame) {
    uint8_t info[48];
    /* The two symbol detectors may deliver the same 100 ms frame. */
    if(rx.frame_seen && rx.clock-rx.last_frame<2400) return;
    if(!fich(frame,info,0) && (frame!=rx.equalized_dibits || !fich(frame,info,rx.fich_levels))) return;
    rx.frame_seen=1;
    unsigned fi=value(info,2), cm=value(info+4,2), fn=value(info+10,3);
    unsigned ft=value(info+13,3), dt=value(info+22,2), dg=value(info+25,7);
    rx.last_frame=rx.clock;
    if(fi==0 || fi==2) {
        digital_call.active=0; digital_call.callsign[0]=0;
        if(!fi) callsign(frame,36,80);
        return;
    }
    if(fi!=1 || dt==1) { digital_call.active=0; return; }
    start_call(cm==0 ? CALL_GROUP : cm==3 ? CALL_PRIVATE : CALL_UNKNOWN,dg,0,0);
    digital_call.format=dt;
    if(dt==2 && fn==1) callsign(frame,20,0);
    if(dt==0 && fn==0) callsign(frame,36,80);
    for(unsigned i=0;i<5;++i) {
        unsigned pos=240+144*i;
        if(dt==2) {
            uint8_t ordered[104]; char bits[49];
            for(unsigned j=0;j<104;++j) ordered[(j%4)*26+j/4]=airbit(frame,pos+40+j);
            unwhiten(ordered,104);
            for(unsigned j=0;j<27;++j) bits[j]=ordered[3*j]+ordered[3*j+1]+ordered[3*j+2]>=2;
            memcpy(bits+27,ordered+81,22);
            digital_ambe(bits);
        } else {
            uint8_t data[18]={0};
            if(dt==3 && ft==1 && !fn && i<3) continue;
            unsigned count=dt==0 ? 72 : 144;
            pos+=144-count;
            for(unsigned j=0;j<count;++j) data[j/8]=(data[j/8]<<1)|airbit(frame,pos+j);
            if(dt==0) fusion_ambe_frame(data); else digital_imbe(data,1);
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

/* The FM audio path spreads each symbol across its neighbours. Match the
   differential waveform of the selected protocol sync, then estimate timing,
   polarity and amplitude anew for each frame. Taps use the 48 kHz clock. */
static void audio_sync(unsigned mode,unsigned index,unsigned phase) {
    static const int16_t fusion_pulse[]={
        19,-19,-90,-163,-201,-181,-106,-3,92,143,136,78,-2,-64,-79,-45,14,
        59,65,35,-5,-19,10,67,124,148,126,66,-10,-74,-104,-98,-67,-41,-44,
        -80,-126,-143,-105,-16,87,157,164,109,20,-64,-111,-108,-58,17,86
    };
    static const int16_t p25_pulse[]={
        166,105,37,-29,-79,-110,-111,-77,-13,66,147,195,201,173,109,25,-60,-127,
        -162,-162,-142,-107,-75,-67,-76,-90,-83,-35,52,146,195,161,60,-37,-73,-33,
        48,110,101,20,-83,-152,-157,-112,-55,-23,-21,-22,-10,15,33
    };
    static const int16_t alternate[2][51]={
    {
        19,-1,-57,-123,-161,-145,-72,32,128,181,173,110,22,-51,
        -79,-54,3,54,68,40,-7,-34,-19,31,87,114,95,36,
        -39,-102,-132,-123,-85,-45,-31,-54,-96,-119,-90,-8,95,169,
        180,126,34,-56,-110,-112,-63,13,86
    },
    {
        114,62,5,-42,-74,-87,-82,-58,-17,33,81,114,121,99,
        54,-5,-61,-103,-120,-111,-81,-44,-16,-9,-24,-43,-43,-8,
        55,117,142,111,37,-38,-71,-45,17,70,74,24,-49,-104,
        -111,-78,-30,3,14,10,8,15,25
    }
    };
    unsigned protocol=mode==RX_P25;
    const int16_t *pulse=protocol ? p25_pulse : fusion_pulse;
    const int16_t *raw=rx.history[0];
    unsigned signs=(uint16_t)((rx.audio_signs[phase]<<1)|(raw[index]<raw[(index-6)&255]));
    rx.audio_signs[phase]=signs;
    if(rx.audio_count) return;
    if(rx.audio_pending && rx.clock-rx.audio_tick>6) return;
    /* The two FM responses have the same sync epoch. Gate on common signs,
       then use the higher normalized correlation to select the symbol filter. */
    unsigned mask=protocol ? 0xfffd : 0xddff;
    unsigned diff=(signs^(protocol ? 0x67ae : 0x6a72))&mask, inverse=diff^mask;
    diff&=diff-1; inverse&=inverse-1;
    if((diff&(diff-1)) && (inverse&(inverse-1))) return;
    int dot=0, other=0, energy=0;
    for(unsigned j=0;j<51;++j) {
        unsigned at=index-150+3*j;
        int y=(raw[at&255]-raw[(at-6)&255])>>4;
        dot+=y*pulse[j];
        other+=y*alternate[protocol][j];
        energy+=y*y;
    }
    if(energy<51) return;
    float norm=protocol ? 557748.0f : 455904.0f;
    float alternate_norm=protocol ? 248363.0f : 433350.0f;
    float score=(float)dot*dot/(norm*energy), other_score=(float)other*other/(alternate_norm*energy);
    float peak=score>other_score ? score : other_score;
    if(peak<0.77f || (rx.audio_pending && peak<=rx.audio_score)) return;
    float margin=other_score-score;
    float history=rx.frame_seen ? rx.response_history : 0;
    unsigned profile=0;
    if(other_score>=0.77f && (score<0.77f || margin+history>0)) {
        norm=alternate_norm; dot=other; profile=1+protocol;
    }
    rx.response_margin=margin;
    rx.audio_pending=1; rx.audio_tick=rx.clock; rx.audio_score=peak; rx.audio_profile=profile;
    rx.audio_scale=norm/(2048.0f*dot);
}

static unsigned audio_dibit(unsigned index) {
    /* Feed-forward taps six samples apart, feedback taps oldest first, Q10. */
    static const int16_t fir[3][29]={{192,-279,375,-178,1,175,-103,-19,98,-143,
        -95,100,-277,-282,237,-333,-646,580,152,-1229,875,2605,-891,-3088,1349},
    {
        130,-79,118,73,51,132,111,85,150,133,88,155,
        125,-22,67,151,-189,-209,212,-275,-647,442,192,-1167,
        692,2719,-239,-2868,859
    },
    {
        166,-209,1115,-376,638,3435,369,-4326,-2726,1132,1620,866,946,747,
        130,-285,-469,-455,-253,128,416,409,281,-414,-6
    }
    };
    static const int16_t feedback[3][10]={{-5,-32,-64,-87,-112,-49,-2,228,296,663},
    {
        -1,-24,-66,-96,-116,-64,-6,244,357,632
    },
    {
        -150,-54,332,393,73,-559,-639,-350,989,955
    }
    };
    static const int8_t levels[]={1,3,-1,-3};
    int signal=0, correction=0;
    unsigned taps=rx.audio_profile==1 ? 29 : 25;
    for(unsigned j=0;j<taps;++j) signal+=fir[rx.audio_profile][j]*rx.history[0][(index-6*j)&255];
    for(unsigned j=0;j<10;++j) correction+=feedback[rx.audio_profile][j]*levels[rx.equalized_dibits[rx.audio_count-10+j]];
    float v=signal*rx.symbol_scale+correction;
    if(rx.audio_count>=20 && rx.audio_count<120) {
        int soft=(int)(v/256.0f);
        rx.fich_levels[rx.audio_count-20]=soft< -24 ? -24 : soft>24 ? 24 : soft;
    }
    return (v<0 ? 2 : 0)+(v>2048 || v< -2048);
}

static void audio_sample(unsigned mode,unsigned index,unsigned phase,unsigned n) {
    audio_sync(mode,index,phase);
    static const unsigned delay[]={0,165u,55u};
    unsigned wait=rx.audio_profile ? delay[rx.audio_profile] : (mode==RX_P25 ? 150u : 140u);
    if(rx.audio_pending && rx.clock-rx.audio_tick==wait) {
        /* The last ten known sync dibits seed decision feedback. */
        static const uint8_t tail[]={2,1,1,2,0,3,1,0,3,1};
        static const uint8_t p25_tail[]={3,3,1,3,1,3,3,3,3,3};
        memcpy(rx.equalized_dibits+n-10,mode==RX_P25 ? p25_tail : tail,10);
        rx.audio_pending=0; rx.audio_count=n;
        rx.response_history=(rx.frame_seen ? 0.94f*rx.response_history : 0)+rx.response_margin;
        rx.symbol_scale=rx.audio_scale; rx.audio_next=rx.clock;
    }
    if(rx.audio_count && rx.clock==rx.audio_next) {
        rx.equalized_dibits[rx.audio_count]=audio_dibit(index);
        rx.audio_next+=10;
        ++rx.audio_count;
        if(mode==RX_P25 && rx.audio_count==57 &&
           !p25_nid(rx.equalized_dibits,&rx.equalized_nid)) rx.audio_count=0;
        if(mode==RX_P25 && rx.audio_count==864) {
            p25_frame(rx.equalized_dibits,rx.equalized_nid);
            rx.audio_count=0;
        }
        if(mode==RX_YSF && rx.audio_count==480) {
            fusion_frame(rx.equalized_dibits);
            rx.audio_count=0;
        }
    }
    if(rx.clock-rx.last_frame>21600) rx.frame_seen=0;
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
        audio_sample(mode,index,phase,n);
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
            if(mode==RX_P25 && rx.count==57 && !p25_nid(rx.dibits,&rx.nid)) rx.count=0;
            if(mode==RX_P25 && rx.count==864) { p25_frame(rx.dibits,rx.nid); rx.count=0; }
            if(mode==RX_YSF && rx.count==480) { fusion_frame(rx.dibits); rx.count=0; }
        }
    }
}
