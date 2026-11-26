/* One producer (the factory PCM consumer), one decoder task, one DMA reader. */
#include "dmr-equalize.h"
#include "dmr-ui.h"
#include "dmr-digital.h"
#include <string.h>

extern void dmr_audio_reset(void);
extern int dmr_audio_frame(const uint8_t voice[9]);
extern void dmr_start_alert(unsigned kind);
extern int dmr_end_alert(void);

enum { BLOCKS=128, SAMPLES=36 };
static struct block { unsigned hz, seq; int16_t pcm[SAMPLES]; } fifo[BLOCKS];
static unsigned written, read_count, expected, speech_header, last_voice;
static unsigned speech_open, closing;
/* Published after flushing the old speaker queue. Read in the DMA interrupt. */
static volatile unsigned frequency;
static dmr_frontend radio;
unsigned digital_mode;

void dmr_core_switch(unsigned mode) {
    __atomic_store_n(&read_count,__atomic_load_n(&written,__ATOMIC_ACQUIRE),__ATOMIC_RELEASE);
    memset(&radio,0,sizeof(radio));
    digital_reset();
    dmr_audio_reset();
    expected=frequency=speech_header=speech_open=closing=0;
    digital_mode=mode;
}

static unsigned dmr_kind(const dmr_radio *r) {
    /* ETSI TS 102 361-1 annex A reserves the last 16 IDs for all-call addressing. */
    if(r->target>=0xfffff0) return CALL_ALL;
    return r->private_call ? CALL_PRIVATE : CALL_GROUP;
}

void dmr_core_input(const int16_t *pcm, unsigned hz, unsigned seq)
{
    unsigned w=__atomic_load_n(&written,__ATOMIC_RELAXED);
    if (w-__atomic_load_n(&read_count,__ATOMIC_ACQUIRE)>=BLOCKS) return;
    struct block *b=&fifo[w&(BLOCKS-1)];
    memcpy(b->pcm,pcm,sizeof(b->pcm));
    b->hz=hz; b->seq=seq;
    __atomic_store_n(&written,w+1,__ATOMIC_RELEASE);
}

static void voice(void *unused,const uint8_t frames[27])
{
    (void)unused;
    if (speech_header!=radio.call_id) {
        dmr_audio_reset();
        dmr_start_alert(dmr_kind(dmr_frontend_status(&radio)));
        speech_header=radio.call_id;
        speech_open=closing=0;
    }
    for (unsigned pos=0;pos<27;pos+=9) {
        if(dmr_audio_frame(frames+pos)>=0) {
            speech_open=1;
            last_voice=expected;
        }
    }
}

void dmr_core_work(void)
{
    unsigned r=__atomic_load_n(&read_count,__ATOMIC_RELAXED);
    unsigned limit=__atomic_load_n(&written,__ATOMIC_ACQUIRE);
    while (r!=limit) {
        const struct block *b=&fifo[r&(BLOCKS-1)];
        if (b->hz!=frequency || b->seq!=expected) {
            memset(&radio,0,sizeof(radio));
            digital_reset();
            dmr_audio_reset();
            speech_header=speech_open=closing=0;
            frequency=b->hz;
        }
        expected=b->seq+1;
        if(digital_mode>=RX_YSF) digital_block(digital_mode,b->pcm);
        else {
            dmr_frontend_block(&radio,b->pcm,voice,0);
            dmr_radio *status=dmr_frontend_status(&radio);
            /* Debounce lost bursts. A checked terminator can close immediately.
               The queue keeps the chime behind the final decoded speech. */
            if(speech_open && !status->active && (status->ended || expected-last_voice>=320)) {
                speech_open=0;
                closing=1;
            }
            if(closing && dmr_end_alert()) closing=0;
        }
        __atomic_store_n(&read_count,++r,__ATOMIC_RELEASE);
    }
}

static char *append(char *out,const char *text) {
    while(*text) *out++=*text++;
    return out;
}
static char *number(char *out,unsigned v,unsigned radix,unsigned width) {
    char reverse[10]; unsigned n=0;
    do { reverse[n++]="0123456789ABCDEF"[v%radix]; v/=radix; } while(v || n<width);
    while(n) *out++=reverse[--n];
    return out;
}
void dmr_core_status(volatile struct dmr_ui_status *s)
{
    const dmr_radio *r=dmr_frontend_status(&radio);
    s->phase=r->active ? DMR_GROUP : radio.flat.pending || radio.equalized.pending || radio.transition.pending ? DMR_SYNC :
        r->ended ? DMR_END : DMR_SEARCH;
    s->color_code=r->headers ? r->color_code : UINT32_MAX;
    s->source_id=r->headers ? r->source : UINT32_MAX;
    s->talkgroup=r->headers ? r->target : UINT32_MAX;
    unsigned kind=dmr_kind(r);
    if(digital_mode>=RX_YSF) {
        s->phase=digital_call.active ? DMR_GROUP : DMR_SEARCH;
        s->color_code=digital_call.code; s->source_id=digital_call.source;
        s->talkgroup=digital_call.target; kind=digital_call.kind;
    }
    char row[48], *p=row;
    if(s->phase==DMR_GROUP) {
        p=append(p,kind==CALL_PRIVATE ? "PVT " : kind==CALL_ALL ? "ALL " : kind==CALL_GROUP ? "GRP " : "");
        if(digital_mode==RX_YSF) {
            p=append(p,digital_call.format==3 ? "VW DG-ID " : "DN DG-ID ");
            p=number(p,s->color_code,10,2);
            if(digital_call.callsign[0]) { p=append(p," RX "); p=append(p,digital_call.callsign); }
        } else {
            if(digital_mode==RX_P25) { p=append(p,"NAC "); p=number(p,s->color_code,16,3); }
            else {
                p=append(p,"CC "); p=number(p,s->color_code,10,1);
                if(r->family==3 || r->family==4) { p=append(p," TS "); p=number(p,r->family-2,10,1); }
            }
            if(s->source_id!=UINT32_MAX) { p=append(p," ID "); p=number(p,s->source_id,10,1); }
            if(s->talkgroup!=UINT32_MAX) {
                p=append(p,kind==CALL_PRIVATE ? " TO " : " TG "); p=number(p,s->talkgroup,10,1);
            }
        }
    }
    *p=0;
    for(unsigned i=0;i<=(unsigned)(p-row);++i) s->row[i]=row[i];
}
