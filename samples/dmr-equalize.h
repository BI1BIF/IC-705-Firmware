#ifndef IC705_DMR_EQUALIZE_H
#define IC705_DMR_EQUALIZE_H
#include "dmr-radio.h"
#include <string.h>

typedef struct {
    dmr_radio flat, equalized, transition;
    int32_t integral, previous;
    unsigned selected, last, call_id;
} dmr_frontend;

static inline dmr_radio *dmr_frontend_status(dmr_frontend *s) {
    if (s->last==3) return &s->transition;
    return s->last==2 ? &s->equalized : &s->flat;
}

/* One factory 36-sample block. A verified group header chooses the branch
   for its entire call. The idle branch starts clean at the next acquisition. */
static inline void dmr_frontend_block(dmr_frontend *s, const int16_t pcm[36],
                                      dmr_radio_voice_fn sink, void *context) {
    unsigned was=s->selected;
    if (!was || was==1) {
        unsigned headers=s->flat.epoch;
        dmr_radio_feed(&s->flat,pcm,36,sink,context);
        if (s->flat.epoch!=headers) ++s->call_id;
        if (s->flat.active) s->selected=1;
    }
    if (!s->selected || was==2) {
        int16_t filtered[36];
        /* A long rail-valued muted input can wind up the integrator. Recenter
           between acquisition attempts, before a subsequent call arrives. */
        if (!s->equalized.active && !s->equalized.pending && !s->equalized.acquiring_voice &&
            (s->integral>1048576 || s->integral< -1048576)) s->integral=0;
        for (unsigned i=0;i<36;++i) {
            int v=pcm[i];
            s->integral+=v-(s->integral>>16);
            /* Leaky integral restores low frequencies, lead lifts the
               upper voice band; halve the gain for transient headroom. */
            int sample=(v+2*(v-s->previous)+7*(s->integral>>8))/2;
            s->previous=v;
            filtered[i]=sample>32767 ? 32767 : sample < -32768 ? -32768 : sample;
        }
        s->equalized.adaptive=1;
        unsigned headers=s->equalized.epoch;
        dmr_radio_feed(&s->equalized,filtered,36,sink,context);
        if (s->equalized.epoch!=headers) ++s->call_id;
        if (s->equalized.active) s->selected=2;
    }
    if (!s->selected || was==3) {
        unsigned headers=s->transition.epoch;
        s->transition.transition=1;
        dmr_radio_feed(&s->transition,pcm,36,sink,context);
        if (s->transition.epoch!=headers) ++s->call_id;
        if (s->transition.active) s->selected=3;
    }
    if (!was && s->selected) {
        s->last=s->selected;
        if (s->selected!=1) memset(&s->flat,0,sizeof(s->flat));
        if (s->selected!=2) {
            memset(&s->equalized,0,sizeof(s->equalized));
            s->integral=s->previous=0;
        }
        if (s->selected!=3) memset(&s->transition,0,sizeof(s->transition));
    }
    if (was && !dmr_frontend_status(s)->active) s->selected=0;
}
#endif
