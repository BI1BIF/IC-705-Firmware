#ifndef IC705_DMR_RADIO_H
#define IC705_DMR_RADIO_H

#include <stdint.h>

typedef struct {
    uint32_t source, target, headers, bursts, ends, losses;
    uint8_t active, family, color_code;
    uint8_t pending, phase, inverted, voice_index, misses, adaptive, transition, ended;
    uint32_t clock, center_time, signs[10];
    int32_t midpoint, step, dc_accumulator, slope_q8;
    int16_t history[2048];
    uint8_t private_call;
    unsigned epoch;
    uint8_t acquiring_voice, embedded[128];
} dmr_radio;

/* Queue or copy three packed 72-bit AMBE codewords before returning. */
typedef void (*dmr_radio_voice_fn)(void *context, const uint8_t frames[27]);

/* Start with zeroed state. Supply continuous mono FM discriminator PCM at
   48 kHz, in any chunk size. One clear group voice call is followed at once. */
void dmr_radio_feed(dmr_radio *s, const int16_t *pcm, unsigned count,
                    dmr_radio_voice_fn sink, void *context);

#endif
