/* ETSI TS 102 361-1 slot type, embedded signalling and full link control.
   Codewords are constructed from their systematic parity columns on demand. */
#include "dmr-radio.h"

static const uint32_t data_signs[4] = {0xbc64b2, 0x89d791, 0xde8ae0, 0x9073dc};
static const uint16_t golay_cols[] = {0x3da,0xd99,0x6cd,0x367,0xdc6,0xa97,0x93e,0x8eb};
static const uint16_t qr_cols[] = {0x04f,0x11e,0x1b7,0x1e2,0x1c9,0x0e5,0x073};
static const uint8_t row_cols[] = {9,13,15,14,7,10,5,11,12,6,3,8,4,2,1};
static const uint8_t col_cols[] = {15,14,7,10,5,11,12,6,3,8,4,2,1};

static unsigned distance(unsigned x) {
    x -= (x >> 1) & 0x55555555;
    x = (x & 0x33333333) + ((x >> 2) & 0x33333333);
    x = (x + (x >> 4)) & 0x0f0f0f0f;
    return (x * 0x01010101) >> 24;
}

static unsigned block_code(unsigned info, const uint16_t *cols, unsigned k, unsigned parity) {
    unsigned word = info << parity;
    for (unsigned i = k; i; --i, info >>= 1)
        if (info & 1) word ^= cols[i-1];
    return word;
}

static int magnitude(int x) { return x < 0 ? -x : x; }
static unsigned bit(const uint8_t *dibits, unsigned i) {
    return (dibits[i/2] >> (1-(i&1))) & 1;
}
static unsigned field(const uint8_t *dibits, unsigned i, unsigned n) {
    unsigned v = 0;
    while (n--) v = (v << 1) | bit(dibits, i++);
    return v;
}
static unsigned hamming(uint8_t *line, unsigned stride, unsigned n,
                        const uint8_t *cols, int repair) {
    unsigned syndrome = 0;
    for (unsigned i=0; i<n; ++i)
        if (line[i*stride]) syndrome ^= cols[i];
    if (repair && syndrome)
        for (unsigned i=0; i<n; ++i)
            if (cols[i] == syndrome) { line[i*stride] ^= 1; break; }
    return syndrome;
}

static int link_payload(const uint8_t *dibits, unsigned kind, uint8_t word[12]) {
    uint8_t m[196];
    for (unsigned i=0; i<196; ++i)
        m[(13*i)%196] = bit(dibits, i < 98 ? i : i+68);
    for (unsigned pass=0; pass<3; ++pass) {
        unsigned syndrome=0;
        for (unsigned r=0; r<9; ++r)
            syndrome |= hamming(m+1+15*r,1,15,row_cols,pass<2);
        for (unsigned c=0; c<15; ++c)
            syndrome |= hamming(m+1+c,15,13,col_cols,pass<2);
        if (!syndrome) break;
        if (pass==2) return 0;
    }
    unsigned corrected=0;
    for (unsigned i=0; i<196; ++i)
        corrected += m[(13*i)%196] != bit(dibits, i<98 ? i : i+68);
    if (corrected>4) return 0;
    for (unsigned i=0; i<96; ++i) {
        unsigned idx=i+3;
        if ((i&7)==0) word[i/8]=0;
        word[i/8]=(word[i/8]<<1) | m[1+15*(idx/11)+idx%11];
    }
    if ((word[0]!=0 && word[0]!=3) || word[1]!=0 || (word[2]&0x40)) return 0;
    for (unsigned i=9; i<12; ++i) word[i] ^= kind==1 ? 0x96 : 0x99;
    for (unsigned power=1; power<=3; ++power) {
        unsigned syndrome=0;
        for (unsigned i=0; i<12; ++i) {
            for (unsigned n=0; n<power; ++n)
                syndrome=(syndrome<<1) ^ ((syndrome & 128) ? 0x11d : 0);
            syndrome ^= word[i];
        }
        if (syndrome) return 0;
    }
    return 1;
}

static unsigned id24(const uint8_t *p) { return ((unsigned)p[0]<<16)|(p[1]<<8)|p[2]; }

/* B through E each carry four columns of the embedded LC matrix. Confirm
   every row, the column parity and the five checksum bits before unmuting. */
static int embedded_call(dmr_radio *s) {
    static const uint8_t cols[16]={19,26,31,28,14,21,11,22,25,13,7,16,8,4,2,1};
    uint8_t *m=s->embedded, word[9]={0};
    unsigned repairs=0, checksum=0, pos=0;
    for (unsigned r=0;r<7;++r) {
        if (hamming(m+r,8,16,cols,1)) {
            if (++repairs>3 || hamming(m+r,8,16,cols,0)) return 0;
        }
        for (unsigned c=0;c<(r<2 ? 11u : 10u);++c,++pos)
            word[pos/8]=(word[pos/8]<<1)|m[8*c+r];
        if (r>=2) checksum=(checksum<<1)|m[80+r];
    }
    unsigned bad_columns=0;
    for (unsigned c=0;c<16;++c) {
        unsigned parity=0;
        for (unsigned r=0;r<8;++r) parity^=m[8*c+r];
        bad_columns+=parity;
    }
    unsigned sum=0;
    for (unsigned i=0;i<9;++i) sum+=word[i];
    if (repairs+bad_columns>3 || sum%31!=checksum ||
        (word[0]!=0 && word[0]!=3) || word[1] || (word[2]&0x40)) return 0;
    s->source=id24(word+6);
    s->target=id24(word+3);
    s->private_call=word[0]==3;
    ++s->headers;
    ++s->epoch;
    s->ended=0;
    s->active=1;
    return 1;
}

static unsigned control(dmr_radio *s, const uint8_t *dibits) {
    unsigned slot=(field(dibits,98,10)<<10) | field(dibits,156,10);
    uint8_t word[12];
    for (unsigned cc=0; cc<16; ++cc) {
        for (unsigned kind=1; kind<=2; ++kind) {
            unsigned code=block_code(16*cc+kind,golay_cols,8,12);
            if (distance(slot ^ code)>3) continue;
            if (!link_payload(dibits,kind,word)) return 0;
            unsigned src=id24(word+6), dst=id24(word+3);
            if (kind==2) {
                if (!s->active || s->source!=src || s->target!=dst || s->color_code!=cc) return 0;
                ++s->ends;
                s->active=0;
                s->ended=1;
            } else {
                if(!s->active || s->source!=src || s->target!=dst ||
                   s->color_code!=cc || s->private_call!=(word[0]==3)) ++s->epoch;
                ++s->headers;
                s->active=1;
                s->ended=0;
                s->source=src;
                s->target=dst;
                s->private_call=word[0]==3;
                s->color_code=cc;
            }
            s->voice_index=6;
            return kind;
        }
    }
    return 0;
}

static int sample(const dmr_radio *s, uint32_t i) { return s->history[i&2047]; }

/* Fit the two outer deviation levels to the known signs of the sync word.
   This also estimates discriminator DC offset and the radio's gain. */
static void calibrate(const dmr_radio *s, uint32_t center, unsigned signs, int *mid, int *step) {
    int sum_lo=0,sum_hi=0,lo_count=0;
    for (unsigned i=0; i<24; ++i) {
        int v=sample(s,center+i*10);
        if (signs & (1u<<(23-i))) { sum_lo+=v; ++lo_count; }
        else sum_hi+=v;
    }
    int lo=sum_lo/lo_count, hi=sum_hi/(24-lo_count);
    *mid=(hi+lo)/2;
    *step=(hi-lo)/6;
}

/* Find the sampling phase with least error to the nearest four levels.
   Search a whole symbol during acquisition and track each 60 ms thereafter. */
static uint32_t clock_phase(dmr_radio *s, int acquiring, unsigned signs) {
    int best=0x7fffffff, best_delta=0, best_mid=s->midpoint, best_step=s->step;
    int radius=acquiring ? 8 : 4, best_slope=0;
    for (int d=-radius; d<=radius; ++d) {
        uint32_t center=s->center_time+d;
        int mid=s->midpoint, step=s->step;
        int slope=0;
        if (acquiring) calibrate(s,center,signs,&mid,&step);
        if (step<4) continue;
        if (!acquiring && !s->adaptive) {
            /* The two outer symbol clusters shift together as the VFO
               moves. Their midpoint is independent of voice bit balance. */
            int low=0,high=0,nlow=0,nhigh=0;
            for (unsigned j=6;j<126;j+=2) {
                int v=sample(s,center-540+j*10)-mid;
                if (v>2*step) { high+=v; ++nhigh; }
                if (v< -2*step) { low+=v; ++nlow; }
            }
            if (nlow>=4 && nhigh>=4) {
                int shift=(high/nhigh+low/nlow)/2;
                if (magnitude(shift)>step/8 && magnitude(shift)<step) mid+=shift;
            }
        }
        if (s->adaptive) {
            for (unsigned it=0;it<3;++it) {
                int half[2]={0,0};
                for (int j=6;j<126;j+=2) {
                    int v=sample(s,center-540+10*j)-mid-((slope*(j-65))>>8);
                    int ideal=magnitude(v)>2*step ? 3*step : step;
                    half[j>=66]+=v-(v<0 ? -ideal : ideal);
                }
                mid+=(half[0]+half[1])/60;
                slope+=(half[1]-half[0])*256/1800;
            }
        }
        int error=0;
        for (unsigned j=s->adaptive ? 6 : 0; j<(s->adaptive ? 126u : 132u); j+=2) {
            int level=magnitude(sample(s,center-540+j*10)-mid-((slope*((int)j-65))>>8));
            error+=magnitude(level-(level>step*2 ? step*3 : step));
        }
        /* Relative error prevents the near-zero eye opening from winning. */
        int score=error*32/step+magnitude(d);
        if (score<best) { best=score; best_delta=d; best_mid=mid; best_step=step; best_slope=slope; }
    }
    s->midpoint=best_mid;
    s->step=best_step;
    s->slope_q8=best_slope;
    return s->center_time+best_delta;
}

/* Base stations fill the other time slot with data-sync idle bursts. A
   recognized slot type must leave acquisition free for a header 30 ms later. */
static int has_slot_type(const uint8_t *dibits) {
    unsigned slot=(field(dibits,98,10)<<10)|field(dibits,156,10);
    unsigned info=slot>>12;
    for (unsigned mask=0;mask<256;mask=mask ? mask<<1 : 1)
        if (distance(slot^block_code(info^mask,golay_cols,8,12))<=1) return 1;
    return 0;
}

static int accept_burst(dmr_radio *s, const uint8_t dibits[132], unsigned family,
                        uint32_t center, dmr_radio_voice_fn sink, void *context) {
    uint8_t voice[27];
    unsigned signs=0, inner=0, ref=data_signs[family-1];
    for (unsigned i=54;i<78;++i) {
        signs=(signs<<1)|(dibits[i]>>1);
        inner+=(dibits[i]&1)==0;
    }
    unsigned diff=distance(signs^ref);
    if (diff<=2 && inner<=3) {
        if (!control(s,dibits)) {
            /* Voice A has the complementary sync. At acquisition the sync
               alone cannot distinguish an inverted data burst from voice. */
            if (!s->active && !s->acquiring_voice && !has_slot_type(dibits)) {
                s->family=family;
                s->voice_index=0;
                s->inverted^=1;
                s->acquiring_voice=1;
                s->center_time=center;
                return 1;
            }
            /* A different or damaged control burst ends this attribution.
               Voice on this slot might now belong to another call. */
            if (s->active) { s->active=0; ++s->losses; }
            return 0;
        }
        s->family=family;
    } else {
        static const uint8_t lcss[6]={0,1,3,3,2,0};
        if (s->acquiring_voice) {
            unsigned idx=++s->voice_index;
            if (idx>4 || (diff>=22 && inner<=3)) return 0;
            unsigned emb=field(dibits,108,8)*256+field(dibits,148,8);
            unsigned cc=idx==1 ? 0 : s->color_code;
            for (;cc<16;++cc) {
                if (distance(block_code(cc*8+lcss[idx],qr_cols,7,9)^emb)<=2) break;
                if (idx!=1) return 0;
            }
            if (cc==16) return 0;
            s->color_code=cc;
            for (unsigned i=0;i<32;++i) s->embedded[(idx-1)*32+i]=bit(dibits,116+i);
            s->center_time=center;
            if (idx==4) {
                if (!embedded_call(s)) return 0;
                s->acquiring_voice=0;
            }
            /* The frontend selects the confirmed branch after this block. */
            return 1;
        }
        if (!s->active) return 0;
        if (diff>=22 && inner<=3) s->voice_index=0;
        else {
            if (s->voice_index>=5) return 0;
            unsigned expected=s->color_code*8 + lcss[++s->voice_index];
            unsigned emb=field(dibits,108,8)*256+field(dibits,148,8);
            if (distance(block_code(expected,qr_cols,7,9)^emb)>2) return 0;
        }
        for (unsigned i=0; i<27; ++i) {
            unsigned pos=i*4;
            unsigned value=0;
            for (unsigned j=pos; j<pos+4; ++j)
                value=(value<<2) | dibits[j<54 ? j : j+24];
            voice[i]=value;
        }
        ++s->bursts;
        if (sink) sink(context,voice);
    }
    s->center_time=center;
    return 1;
}

#include "dmr-transition.h"

static int burst(dmr_radio *s, dmr_radio_voice_fn sink, void *context) {
    unsigned tracking=s->active || s->acquiring_voice;
    unsigned family=tracking ? s->family : s->pending;
    unsigned ref=data_signs[family-1];
    unsigned physical=ref ^ (s->inverted ? 0xffffff : 0);
    uint32_t center=clock_phase(s,!tracking,physical);
    if (s->step<4) return 0;
    uint8_t dibits[132];
    int low=0x7fffffff, high=-0x7fffffff;
    for (unsigned i=0; i<132; ++i) {
        int v=sample(s,center-540+10*i)-s->midpoint-((s->slope_q8*((int)i-65))>>8);
        if (s->inverted) v=-v;
        if (v<low) low=v;
        if (v>high) high=v;
        dibits[i]=(v<0 ? 2 : 0) | (magnitude(v)>s->step*2);
    }
    if (high-low<3*s->step) return 0;
    return accept_burst(s,dibits,family,center,sink,context);
}

void dmr_radio_feed(dmr_radio *s, const int16_t *pcm, unsigned count,
                    dmr_radio_voice_fn sink, void *context) {
    for (unsigned i=0; i<count; ++i) {
        uint32_t now=s->clock++;
        int v=pcm[i];
        s->history[now&2047]=v;
        /* A keyed mobile can enter from muted or rail-valued discriminator
           samples. Forget that level within the first half-burst. */
        s->dc_accumulator+=v-sample(s,now-128);
        unsigned phase=s->phase++;
        if (s->phase==10) s->phase=0;
        int negative=s->transition ? v<sample(s,now-2) : v<(s->dc_accumulator>>7);
        unsigned signs=((s->signs[phase]<<1)|negative)&0xffffff;
        s->signs[phase]=signs;
        if (s->active || s->acquiring_voice || s->pending) {
            if (now!=s->center_time+(s->transition ? 864u : 780u)) continue;
            int ok=s->transition ? transition_burst(s,sink,context) : burst(s,sink,context);
            s->pending=0;
            if (!ok || s->active) s->acquiring_voice=0;
            if (ok) s->misses=0;
            else if (s->active && ++s->misses>=3) { s->active=0; ++s->losses; }
            if (s->active || s->acquiring_voice) s->center_time+=2880;
            continue;
        }
        for (unsigned k=0; k<4; ++k) {
            unsigned diff=signs ^ data_signs[k];
            unsigned inverted=diff>>23;
            if (inverted) diff ^= 0xffffff;
            if (diff && (diff & (diff-1))) continue;
            s->pending=k+1;
            s->inverted=inverted;
            s->center_time=now-230;
            s->step=0;
            break;
        }
    }
}
