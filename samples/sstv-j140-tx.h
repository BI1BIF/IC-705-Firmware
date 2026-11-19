/* J140 PICTURE TX. The canvas stays immutable while the SSI0 reader owns it. */
const char sstv_tx_title[]="SSTV TX MODE";
const char sstv_tx_robot[]="Robot 36", sstv_tx_martin[]="Martin M1";
volatile unsigned sstv_tx_choice;
static unsigned tx_mode;
enum { TX_MODE_COUNT = 2 + sizeof(basic_modes)/sizeof(basic_modes[0]) };
/* Read by the packer to populate the stock scrollable selector. */
const unsigned sstv_tx_table_layout[]={TX_MODE_COUNT,sizeof(struct Mode),__builtin_offsetof(struct Mode,name)};
static const char *tx_mode_name(void) {
    return tx_mode>=2 ? basic_modes[tx_mode-2].name : tx_mode ? sstv_tx_martin : sstv_tx_robot;
}

static void tx_commit_mode(void) {
    ((void (*)(void))0x200cd828)();
    if (sstv_tx_choice<TX_MODE_COUNT) tx_mode=sstv_tx_choice;
    *(volatile uint8_t *)0x20380c98 |= 1;
}

unsigned sstv_tx_select(void) {
    ((void (*)(void (*)(void)))0x200cd7dc)(tx_commit_mode);
    return 2;
}

unsigned sstv_tx_detail_active(void) { return viewing() && current_menu()==276; }

unsigned sstv_tx_mode_open(void) {
    if (!sstv_tx_detail_active()) return 0;
    sstv_tx_choice=tx_mode;
    ((void (*)(unsigned,unsigned))0x200cd628)(293,0xffff);
    return 1;
}

enum TxChannel { FIXED, LUMA, CR, CB, GREEN, BLUE, RED };
struct TxSegment { unsigned us; unsigned value; enum TxChannel channel; };
/* Build one scan schedule at selection time and reuse it for every line.
   A scan spans the source canvas even when the on-air raster is wider. */
static struct TxSegment tx_line[10];
static unsigned tx_segments, tx_height, tx_vis, tx_pair, tx_width;
static void tx_segment(unsigned us,unsigned hz,enum TxChannel ch) {
    if (us) tx_line[tx_segments++]=(struct TxSegment){us,hz,ch};
}
static void tx_gap(unsigned us,unsigned hz) { tx_segment(us,hz,FIXED); }
static void tx_scan(unsigned us,enum TxChannel ch) { tx_segment(us,0,ch); }

static void tx_schedule(unsigned mode) {
    const struct Mode *m=mode>=2 ? &basic_modes[mode-2] : 0;
    enum Layout layout=m ? m->layout : mode ? GBR : YCRCB;
    tx_vis=m ? m->vis : mode ? MARTIN_M1 : ROBOT36;
    tx_height=m ? m->height : mode ? 256 : 240;
    tx_pair=layout==PD;
    tx_width=(tx_vis==40 || tx_vis==32 || tx_vis==2 || tx_vis==6) ? 160 : WIDTH;
    unsigned scan=m ? m->length[0] : 146432;
    tx_segments=0;
    if (layout!=SCOTTIE) tx_gap(m ? m->sync : mode ? 4862 : 9000,1200);
    if (layout==YCRCB) {
        tx_gap(3000,1500); tx_scan(mode ? 138000 : 88000,LUMA);
        tx_gap(4500,1500); tx_gap(1500,1900); tx_scan(mode ? 69000 : 44000,CR);
        if (mode) { tx_gap(4500,2300); tx_gap(1500,1900); tx_scan(69000,CB); }
    } else if (layout==PD) {
        tx_gap(2080,1500); tx_scan(scan,LUMA); tx_scan(scan,CR);
        tx_scan(scan,CB); tx_scan(scan,LUMA);
    } else if (layout==MONO) {
        tx_scan(scan,LUMA);
    } else if (layout==SCOTTIE) {
        tx_gap(1500,1500); tx_scan(scan,GREEN); tx_gap(1500,1500); tx_scan(scan,BLUE);
        tx_gap(9000,1200); tx_gap(1500,1500); tx_scan(scan,RED);
    } else {
        unsigned porch=m ? m->start[0] : 572;
        unsigned gap=tx_vis==55 ? 0 : porch;
        tx_gap(porch,1500); tx_scan(scan,layout==GBR ? GREEN : RED);
        tx_gap(gap,1500); tx_scan(scan,layout==GBR ? BLUE : GREEN);
        tx_gap(gap,1500); tx_scan(scan,layout==GBR ? RED : BLUE); tx_gap(gap,1500);
    }
}
static const int16_t quarter_sine[]={
    0, 319, 638, 956, 1274, 1591, 1907, 2223, 2536, 2848, 3159, 3467, 3774, 4078, 4380, 4679, 4975, 5268, 5558, 5845, 6128, 6408, 6683, 6955, 7222, 7486, 7744, 7998, 8247, 8491, 8730, 8964, 9192, 9415, 9632, 9844, 10049, 10249, 10442, 10629, 10809, 10983, 11150, 11311, 11465, 11612, 11752, 11885, 12010, 12129, 12240, 12344, 12440, 12529, 12610, 12684, 12750, 12809, 12859, 12902, 12937, 12965, 12984, 12996, 13000
};
static struct {
    const uint16_t *canvas;
    unsigned source_y, y_error;
    unsigned mode, header, row, segment, x, remainder, samples, phase, increment;
} tx;

static void tx_pcm_end(void) { tx.canvas=0; tx.samples=0; }

static void tx_pcm_begin(const uint16_t *canvas) {
    zero(&tx,sizeof(tx));
    tx.mode=tx_mode;
    tx_schedule(tx.mode);
    tx.y_error=HEIGHT/2;
    tx.source_y=tx.y_error>=tx_height;
    if (tx.source_y) tx.y_error-=tx_height;
    tx.canvas=canvas;
}

static void tx_tone(unsigned hz,unsigned ticks) {
    /* Durations are in 1/320 us. Carry fractional 48 kHz samples across
       pixels, lines and consumer blocks to keep the clock continuous. */
    unsigned total=ticks*3+tx.remainder;
    tx.samples=total/20000;
    tx.remainder=total%20000;
    tx.increment=hz*89478u; /* 2^32 / 48000, rounded */
}

static unsigned tx_component(uint16_t pixel,enum TxChannel channel) {
    int r=(pixel>>11)*255/31, g=((pixel>>5)&63)*255/63, b=(pixel&31)*255/31;
    switch (channel) {
        case RED: return r;
        case GREEN: return g;
        case BLUE: return b;
        case CR: return (32768+128*r-107*g-21*b)>>8;
        case CB: return (32768-43*r-85*g+128*b)>>8;
        default: return (77*r+150*g+29*b+128)>>8;
    }
}

static void tx_next_tone(void) {
    if (tx.header<13) {
        unsigned i=tx.header++, vis=tx_vis;
        unsigned hz=1200, us=30000;
        if (i==0 || i==2) { hz=1900; us=300000; }
        else if (i==1) us=10000;
        else if (i>=4 && i<=11) {
            unsigned bit=i==11 ? __builtin_parity(vis) : (vis>>(i-4))&1;
            hz=bit ? 1100 : 1300;
        }
        tx_tone(hz,us*WIDTH);
        return;
    }
    if (tx.row==tx_height) { tx_pcm_end(); return; }
    const struct TxSegment *segment=tx_line+tx.segment;
    unsigned hz=segment->value, ticks=segment->us;
    if (segment->channel==FIXED) {
        if (!tx.mode && tx.segment==3 && (tx.row&1)) hz=2300;
        ticks*=WIDTH;
    } else {
        unsigned row=tx.row+(tx_pair && tx.segment==tx_segments-1);
        unsigned next_y=tx.source_y;
        unsigned error=tx.y_error+HEIGHT;
        while (error>=tx_height) { error-=tx_height; next_y++; }
        unsigned y=row==tx.row ? tx.source_y : next_y;
        unsigned x=tx_width==WIDTH ? tx.x : 2*tx.x+1;
        enum TxChannel ch=segment->channel;
        if (!tx.mode && ch==CR && (row&1)) ch=CB;
        unsigned level=tx_component(tx.canvas[y*WIDTH+x],ch);
        if ((tx_pair || !tx.mode) && (ch==CB || ch==CR)) {
            unsigned other=tx_pair ? next_y : (y^1);
            level=(level+tx_component(tx.canvas[other*WIDTH+x],ch)+1)/2;
        }
        if (tx_width!=WIDTH) ticks*=2;
        hz=1500+(800*level+127)/255;
        tx.x++;
    }
    tx_tone(hz,ticks);
    if (segment->channel==FIXED || tx.x==tx_width) {
        tx.x=0;
        if (++tx.segment==tx_segments) {
            tx.segment=0; tx.row+=1+tx_pair;
            tx.y_error+=HEIGHT*(1+tx_pair);
            while (tx.y_error>=tx_height) { tx.y_error-=tx_height; tx.source_y++; }
        }
    }
}

static unsigned tx_render(int16_t *dst,unsigned count) {
    unsigned n=0;
    while (n<count && tx.canvas) {
        if (!tx.samples) { tx_next_tone(); continue; }
        unsigned pos=tx.phase>>24, index=pos&63;
        int sample=quarter_sine[(pos&64) ? 64-index : index];
        dst[n++]=(int16_t)((pos&128) ? -sample : sample);
        tx.phase+=tx.increment;
        tx.samples--;
    }
    return n;
}

enum { TX_IDLE, TX_ARMED, TX_SENDING, TX_RELEASE, TX_HOLD, TX_DRAIN };
static volatile unsigned tx_state, tx_reading;
static volatile unsigned tx_progress;
static unsigned last_progress, stalled_polls, drain_blocks;
static void *tx_snapshot;
static const char *tx_message;

static unsigned tx_feedback(void) { return *(volatile uint8_t *)0x203809a1 & 0x10; }
static const char *tx_busy(void) {
    unsigned flags=*(volatile uint8_t *)0x203806f4;
    if (tx_feedback() || (flags&0x80)) return "TX ACTIVE";
    if (flags&0x20) return "REMOTE TX";
    if (*(volatile unsigned *)0x203809b0) return "TX REQ";
    if (*(volatile uint8_t *)0x203809c4 & 0xc0) return "TX INHIB";
    return 0;
}
static int tx_half(void) { return viewing() && current_menu()==PICTURE; }
static int tx_analog_mode(void) {
    unsigned bank=(*(volatile uint8_t *)0x203e84c0>>1)&1;
    unsigned mode=((volatile uint8_t *)0x203e212f)[bank*7]>>4;
    return mode<=1 || mode==6 || mode==7;
}
unsigned sstv_tx_source(unsigned configured) {
    return tx_state!=TX_IDLE && tx_half() && tx_analog_mode() ? 3 : configured;
}
/* Contribute a transient request to the native request builder. The real
   CI-V request remains owned by its caller. The original filter runs next. */
unsigned sstv_tx_requested(unsigned flags) {
    unsigned state=tx_state;
    if (state!=TX_ARMED && state!=TX_SENDING && state!=TX_DRAIN) return flags;
    if (!tx_half() || !tx_analog_mode() || (state!=TX_ARMED && !tx_feedback()))
        tx_state=TX_RELEASE;
    else {
        if (last_progress!=tx_progress) { last_progress=tx_progress; stalled_polls=0; }
        if (++stalled_polls<512) return flags|32;
        tx_message="TX TIMEOUT";
        tx_state=TX_RELEASE;
    }
    return flags;
}
static int tx_photo_ready(void) {
    const volatile uint8_t *request=(const volatile uint8_t *)0x203e0f64;
    const volatile uint8_t *name=(const volatile uint8_t *)0x203e1038;
    if (!name[0] || (request[0]&1) || request[128]>2 ||
        !((unsigned (*)(void))0x200c2a68)() || ((unsigned (*)(void))0x200c27c0)()) return 0;
    for (unsigned i=0;i<28;i++) {
        if (request[4+i]!=name[i]) return 0;
        if (!name[i]) return 1;
    }
    return 0;
}
static const char *tx_button_text(void) {
    if (tx_state==TX_ARMED) return "STARTING";
    if (tx_state==TX_SENDING || tx_state==TX_DRAIN) return "SENDING";
    if (tx_state==TX_HOLD || tx_state==TX_RELEASE) return "RELEASE";
    return tx_message;
}
static void tx_frame(void) {
    unsigned old=lock();
    if (!tx_half() || !tx_analog_mode()) {
        if (tx_state!=TX_IDLE) tx_state=TX_RELEASE;
        if (!tx_half()) tx_message=0;
    } else if ((tx_state==TX_SENDING || tx_state==TX_HOLD) && !tx_feedback()) tx_state=TX_RELEASE;
    void *done=0;
    if (tx_state==TX_RELEASE && !tx_reading) {
        done=tx_snapshot;
        tx_snapshot=0;
        tx_pcm_end();
        tx_state=tx_half() && tx_analog_mode() && tx_feedback() ? TX_HOLD : TX_IDLE;
        *(volatile uint8_t *)0x20380c98 |= 1;
    }
    unlock(old);
    if (done) ((void (*)(void *))0x20127a78)(done);
}

unsigned sstv_tx_toggle(void) {
    if (!tx_half()) return unavailable;
    *(volatile uint8_t *)0x20380c98 |= 1;
    if (tx_state!=TX_IDLE) { tx_state=TX_RELEASE; return 1; }
    tx_message=tx_busy();
    if (tx_message) return 1;
    if (!tx_photo_ready()) { tx_message="SET PHOTO"; return 1; }
    if (!tx_analog_mode()) { tx_message="SSB AM FM"; return 1; }
    unsigned revision=*(volatile uint8_t *)0x20624714;
    void *copy=((void *(*)(unsigned))0x20127a28)(sizeof(Canvas));
    if (!copy) { tx_message="NO MEMORY"; return 1; }
    ((void (*)(void *,const void *,unsigned))0x202c8f51)(copy,(const void *)0x2064b584,sizeof(Canvas));
    if (revision!=*(volatile uint8_t *)0x20624714 || !tx_photo_ready() || tx_busy()) {
        ((void (*)(void *))0x20127a78)(copy);
        tx_message="TRY AGAIN";
        return 1;
    }
    tx_snapshot=copy;
    tx_pcm_begin(copy);
    last_progress=tx_progress=stalled_polls=drain_blocks=0;
    tx_state=TX_ARMED;
    return 1;
}

static unsigned tx_pcm_read(int16_t *dst,unsigned count) {
    unsigned old=lock();
    if ((tx_state!=TX_ARMED && tx_state!=TX_SENDING) || tx_reading || !count) {
        unlock(old); return 0;
    }
    if (!tx_half() || !tx_feedback()) {
        if (!tx_half() || tx_state==TX_SENDING) tx_state=TX_RELEASE;
        unlock(old); return 0;
    }
    if (tx_state==TX_ARMED) *(volatile uint8_t *)0x20380c98 |= 1;
    tx_state=TX_SENDING;
    tx_reading=1;
    unlock(old);
    unsigned n=tx_render(dst,count);
    old=lock();
    if (tx_state!=TX_SENDING || !tx_half() || !tx_feedback()) { n=0; tx_state=TX_RELEASE; }
    else if (!tx.canvas) tx_state=TX_DRAIN;
    if (n) tx_progress++;
    tx_reading=0;
    unlock(old);
    return n;
}

/* SSI0 slot 1 carries 36 full-rate samples. Use the factory full-rate
   normalization entry, followed by the ordinary WLAN MOD Level. */
unsigned sstv_tx_mod_block(void) {
    if (tx_state==TX_IDLE || !tx_half() || !tx_analog_mode())
        return ((unsigned (*)(void))0x201f644c)();
    int16_t *pcm=(int16_t *)0x20401c14;
    /* Two bank completions retire the last queued samples before unkeying. */
    if (tx_state==TX_DRAIN && ++drain_blocks>=2) tx_state=TX_RELEASE;
    unsigned n=tx_pcm_read(pcm,36);
    while (n<36) pcm[n++]=0;
    return 4;
}
