/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <mbelib-neo/mbelib.h>
#include <stdint.h>
#include <string.h>

/* DSD's DMR dibit schedule via pinned mbelib-neo/tools/quality.
 * Keeping the imported implementation also retains its license notice. */
#include "mbe_quality_dvsi.c"

enum { PCM_CAPACITY = 2048 };
static mbe_parms current, previous, enhanced;
static int16_t queue[PCM_CAPACITY];
static uint32_t produced, consumed;
static unsigned tone_left, tone_length, dmr_chime;
volatile uint32_t dmr_audio_active;

/* One worker begins each call. Publishing the write position as the new read
 * position discards old speech atomically, even if the DMA IRQ preempts us. */
void dmr_audio_reset(void) {
    __atomic_store_n(&consumed, __atomic_load_n(&produced, __ATOMIC_RELAXED), __ATOMIC_RELEASE);
    mbe_initMbeParms(&current, &previous, &enhanced);
    mbe_setThreadRngSeed(0x12345678);
    tone_left=dmr_chime=0;
}

/* One, two or three 35 ms pulses, mixed under speech on the worker. */
void digital_alert(unsigned kind) {
    dmr_chime=0;
    tone_length=tone_left=kind && kind<=3 ? (kind-1)*480+280 : 0;
}

void dmr_start_alert(unsigned kind) {
    dmr_chime=1;
    tone_length=tone_left=kind*304;
}

/* Short notes ramp to zero at both edges, even for fractional periods. */
static int note(unsigned sample,unsigned length,unsigned hz) {
    static const int16_t sine[]={0,293,574,833,1061,1247,1386,1471,1500,1471,1386,1247,1061,833,574,293,
                                0,-293,-574,-833,-1061,-1247,-1386,-1471,-1500,-1471,-1386,-1247,-1061,-833,-574,-293};
    if(sample>=length) return 0;
    unsigned edge=length-1-sample;
    unsigned ramp=sample<edge ? sample : edge;
    if(ramp>24) ramp=24;
    return sine[(sample*hz*32/8000)&31]*(int)ramp/24;
}

int dmr_end_alert(void) {
    enum { SAMPLES=480 };
    unsigned start=__atomic_load_n(&produced,__ATOMIC_RELAXED);
    if(start-__atomic_load_n(&consumed,__ATOMIC_ACQUIRE)>PCM_CAPACITY-SAMPLES) return 0;
    for(unsigned i=0;i<SAMPLES;++i) {
        int v=i<240 ? note(i,192,960) : note(i-240,240,720);
        queue[(start+i)&(PCM_CAPACITY-1)]=v;
    }
    __atomic_store_n(&produced,start+SAMPLES,__ATOMIC_RELEASE);
    return 1;
}

/* Speech gain in half units. Keep strong peaks below full scale and mix the
   existing call alert afterwards so its volume is independent of speech. */
static int publish(const int16_t pcm[160], int status, unsigned gain2) {
    unsigned start=__atomic_load_n(&produced,__ATOMIC_RELAXED);
    if (status<0 || start-__atomic_load_n(&consumed,__ATOMIC_ACQUIRE)>PCM_CAPACITY-160)
        return -1;
    for (unsigned i=0;i<160;++i) {
        int magnitude=pcm[i]<0 ? -(int)pcm[i] : pcm[i];
        int boosted=magnitude*(int)gain2/2;
        int ceiling=12288+magnitude/2;
        if(boosted>ceiling) boosted=ceiling;
        int v=pcm[i]<0 ? -boosted : boosted;
        if (tone_left) {
            unsigned t=tone_length-tone_left--;
            if(dmr_chime) {
                static const unsigned notes[]={800,1000,1250};
                v+=note(t%304,224,notes[t/304]);
            } else if ((t%=480)<280) {
                static const int16_t sine[]={0,1061,1500,1061,0,-1061,-1500,-1061};
                unsigned envelope=t<16 ? t : t>=264 ? 279-t : 16;
                v+=sine[t&7]*(int)envelope/16;
            }
        }
        queue[(start+i)&(PCM_CAPACITY-1)]=v>32767 ? 32767 : v< -32768 ? -32768 : v;
    }
    __atomic_store_n(&produced,start+160,__ATOMIC_RELEASE);
    return status;
}

/* One worker publishes whole 20 ms frames. -1 means retry when space returns. */
static int ambe_fec_frame(const uint8_t voice[9], unsigned gain2) {
    uint32_t start = __atomic_load_n(&produced, __ATOMIC_RELAXED);
    if (start - __atomic_load_n(&consumed, __ATOMIC_ACQUIRE) > PCM_CAPACITY - 160)
        return -1;
    char plane[4][24] = {{0}}, bits[49];
    int16_t pcm[160];
    deinterleave(voice, 36, dmr_row_high, dmr_col_high, dmr_row_low, dmr_col_low, &plane[0][0], 24);
    int status = mbe_processAmbe3600x2450Frame(pcm, NULL, plane, bits, &current, &previous, &enhanced);
    return publish(pcm,status,gain2);
}

int dmr_audio_frame(const uint8_t voice[9]) { return ambe_fec_frame(voice,3); }
int fusion_ambe_frame(const uint8_t voice[9]) { return ambe_fec_frame(voice,8); }

int digital_ambe(const char bits[49]) {
    int16_t pcm[160];
    int status=mbe_processAmbe2450Data(pcm,NULL,bits,&current,&previous,&enhanced);
    return publish(pcm,status,8);
}

int digital_imbe(const uint8_t *packed, int fusion) {
    char plane[8][23]={{0}}, bits[88];
    int16_t pcm[160];
    if (fusion) {
        unsigned j=0;
        for (unsigned row=0;row<8;++row) {
            int width=row<4 ? 23 : row<7 ? 15 : 7;
            for (int col=width-1;col>=0;--col,++j) {
                unsigned c=j%24, r=j/24, pos=6*c+(r^(c&1));
                plane[row][col]=(packed[pos/8]>>(7-pos%8))&1;
            }
        }
    } else deinterleave(packed,72,p25_row_high,p25_col_high,p25_row_low,p25_col_low,&plane[0][0],23);
    int status=mbe_processImbe7200x4400Frame(pcm,NULL,plane,bits,&current,&previous,&enhanced);
    return publish(pcm,status,fusion ? 8 : 4);
}

/* The DMA callback must prefer native playback and check its mode is RX first.
 * On an empty queue it leaves the original six-sample block intact. */
unsigned dmr_audio_pull6(int16_t out[6]) {
    uint32_t start = __atomic_load_n(&consumed, __ATOMIC_RELAXED);
    uint32_t count = __atomic_load_n(&produced, __ATOMIC_ACQUIRE) - start;
    if (!count)
        return 0;
    if (count > 6)
        count = 6;
    for (unsigned i = 0; i < 6; ++i)
        out[i] = i < count ? queue[(start+i) & (PCM_CAPACITY-1)] : 0;
    __atomic_store_n(&consumed, start+count, __ATOMIC_RELEASE);
    return count;
}

/* Stock DMA callback replacement at J 0x200ffd9c, E 0x200ffe80. */
extern void native_playback_read(int16_t out[6]);
extern unsigned native_playback_queued(void);
void dmr_audio_dma_read(int16_t out[6]) {
    if (!dmr_audio_active) {
        native_playback_read(out);
        return;
    }
    unsigned native = native_playback_queued();
    native_playback_read(out);
    if (native || (*(volatile uint8_t *)0x203806f4 & 0xa0) ||
        (*(volatile uint8_t *)0x203809a1 & 0x10) ||
        *(volatile uint32_t *)0x203809ac || *(volatile uint32_t *)0x203809b0) {
        __atomic_store_n(&consumed, __atomic_load_n(&produced, __ATOMIC_ACQUIRE), __ATOMIC_RELEASE);
        return;
    }
    dmr_audio_pull6(out);
}
