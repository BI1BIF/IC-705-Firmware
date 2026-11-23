/* Fractionally spaced equalizers for the bandwidth-limited FM audio path.
   Taps are six 48 kHz samples apart. The second filter estimates a difference
   between consecutive symbol levels, which survives receiver bass filtering. */
static const int16_t level_taps[25]={
    -8,12,-3,-19,25,-5,-18,7,17,-23,13,0,-87,129,-22,-124,202,-125,-100,244,-201,11,124,-121,51
};
static const int16_t delta_taps[25]={
    -5,9,-14,14,-16,14,-9,-12,18,-13,42,-31,-76,56,40,-34,-20,35,-6,-37,26,3,-32,25,-13
};
static int filter_symbol(const dmr_radio *s,uint32_t at,const int16_t *taps) {
    int sum=0;
    for (int k=0;k<25;++k) sum+=taps[k]*sample(s,at-72+k*6);
    return sum>>8;
}
static int sync_level(unsigned ref,unsigned j) { return (ref & (1u<<(23-j))) ? -3 : 3; }

/* Fit the gain and sample phase to the transitions of the sync word. Its
   complement is the voice sync. The verified header establishes polarity. */
static int transition_sync(dmr_radio *s,unsigned ref,uint32_t *center,int *gain) {
    int best=600,kind=0;
    for (int shift=-6;shift<=6;++shift) {
        uint32_t at=s->center_time+shift;
        int obs[23],xy=0,xx=0;
        for (unsigned j=1;j<24;++j) {
            int d=sync_level(ref,j)-sync_level(ref,j-1);
            obs[j-1]=filter_symbol(s,at+j*10,delta_taps);
            xy+=obs[j-1]*d;
            xx+=d*d;
        }
        int g=xy/xx;
        if (magnitude(g)<4) continue;
        int error=0;
        for (unsigned j=1;j<24;++j) {
            int d=sync_level(ref,j)-sync_level(ref,j-1);
            error+=magnitude(obs[j-1]-g*d);
        }
        int score=error*32/(23*magnitude(g))+magnitude(shift)/3;
        if (score>=best || score>30) continue;
        best=score; *center=at;
        kind=(s->active || s->acquiring_voice) && ((g<0)!=(s->step<0)) ? 2 : 1;
        *gain=kind==2 ? -g : g;
    }
    return kind;
}

static int normalized(int v,int gain) {
    int n=v*16/gain;
    return n>192 ? 192 : n< -192 ? -192 : n;
}
static const int levels[]={16,48,-16,-48};
static int emb_cost(unsigned byte,const int16_t *a,const int16_t *d) {
    int sum=0,last=0;
    for (unsigned i=0;i<4;++i) {
        int level=levels[(byte>>(6-2*i))&3], e=a[i]-level;
        sum+=(e*e)>>3;
        if (i) { e=d[i]-level+last; sum+=e*e; }
        last=level;
    }
    return sum;
}

static int transition_burst(dmr_radio *s,dmr_radio_voice_fn sink,void *context) {
    unsigned tracking=s->active || s->acquiring_voice;
    unsigned family=tracking ? s->family : s->pending;
    unsigned ref=data_signs[family-1];
    uint32_t center=s->center_time;
    int gain=s->step;
    int kind=transition_sync(s,ref,&center,&gain);
    if (!kind && !tracking) return 0;
    int16_t absolute[132],delta[132];
    for (int j=0;j<132;++j) {
        uint32_t at=center+(j-54)*10;
        absolute[j]=normalized(filter_symbol(s,at,level_taps),gain);
        delta[j]=normalized(filter_symbol(s,at,delta_taps),gain);
    }
    unsigned emb=0;
    if (!kind) {
        static const uint8_t lcss[]={1,3,3,2,0};
        if (s->voice_index>=5) return 0;
        unsigned expected=s->color_code*8+lcss[s->voice_index];
        int best=0x7fffffff;
        unsigned match=128;
        for (unsigned info=0;info<128;++info) {
            unsigned code=block_code(info,qr_cols,7,9);
            int cost=emb_cost(code>>8,absolute+54,delta+54)+emb_cost(code&255,absolute+74,delta+74);
            if (cost<best) { best=cost; match=info; emb=code; }
        }
        int first_emb=s->acquiring_voice && s->voice_index==0;
        if ((first_emb ? (match&7)!=1 : match!=expected) || best>11000) {
            ++s->voice_index;
            return 0;
        }
    }
    int costs[4]={0,0,0,0};
    uint8_t back[132][4],dibits[132];
    for (int j=0;j<132;++j) {
        int a=absolute[j], d=delta[j];
        int next[4];
        for (unsigned k=0;k<4;++k) {
            int cheapest=0x3fffffff;
            for (unsigned prev=0;prev<4;++prev) {
                int err=d-(levels[k]-levels[prev]);
                int cost=costs[prev]+err*err;
                if (cost<cheapest) { cheapest=cost; back[j][k]=prev; }
            }
            int err=a-levels[k];
            next[k]=cheapest+(err*err>>5);
            if (kind && j>=54 && j<78) {
                int sync=sync_level(ref,j-54)*(kind==2 ? -16 : 16);
                if (levels[k]!=sync) next[k]+=100000;
            } else if (!kind && ((j>=54 && j<=57) || (j>=74 && j<=77))) {
                unsigned shift=j<=57 ? 14-2*(j-54) : 6-2*(j-74);
                if (k!=((emb>>shift)&3)) next[k]+=100000;
            }
        }
        for (int k=0;k<4;++k) costs[k]=next[k];
    }
    unsigned k=0;
    for (unsigned i=1;i<4;++i) if (costs[i]<costs[k]) k=i;
    for (int j=131;j>=0;--j) { dibits[j]=k; k=back[j][k]; }
    if (!accept_burst(s,dibits,family,center,sink,context)) return 0;
    s->step=!tracking && s->acquiring_voice ? -gain : gain;
    return 1;
}
