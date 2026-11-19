#ifndef CW_AUDIO_SPECTRUM_H
#define CW_AUDIO_SPECTRUM_H

#include <stdint.h>

enum { CW_SPECTRUM_BINS = 20, CW_SPECTRUM_FEED_SAMPLES = 80 };

typedef struct {
    int32_t prev[CW_SPECTRUM_BINS], older[CW_SPECTRUM_BINS];
    unsigned used;
} CwAudioSpectrum;

static inline void cw_spectrum_reset(CwAudioSpectrum *s) {
    s->used = 0;
    for (unsigned i = 0; i < CW_SPECTRUM_BINS; ++i)
        s->prev[i] = s->older[i] = 0;
}

// One level row per 40 ms (320 samples at 8 kHz), from 300 + i*50 Hz.
// The triangular window tapers abrupt edges; work is shared across all four calls.
static inline int cw_spectrum_feed(CwAudioSpectrum *s, const int16_t samples[CW_SPECTRUM_FEED_SAMPLES],
                                   uint8_t levels[CW_SPECTRUM_BINS]) {
    // Round (2 * cos(2*pi*f/8000) * 2^14) for each bin.
    static const int16_t coeff[] = {31863, 31538, 31164, 30743, 30274, 29758, 29197, 28590, 27939, 27246,
                                    26510, 25733, 24917, 24062, 23170, 22243, 21281, 20286, 19261, 18205};
    enum { WINDOW = 4 * CW_SPECTRUM_FEED_SAMPLES };
    for (unsigned n = 0; n < CW_SPECTRUM_FEED_SAMPLES; ++n) {
        unsigned i = s->used + n;
        int32_t weight = i < WINDOW/2 ? i : WINDOW-1-i;
        int32_t sample = ((int32_t)samples[n] * weight + 16384) >> 15;
        for (unsigned bin = 0; bin < CW_SPECTRUM_BINS; ++bin) {
            int32_t prev = s->prev[bin];
            int32_t next = sample + (int32_t)(((int64_t)coeff[bin] * prev) >> 14) - s->older[bin];
            s->older[bin] = prev;
            s->prev[bin] = next;
        }
    }
    s->used += CW_SPECTRUM_FEED_SAMPLES;
    if (s->used != WINDOW)
        return 0;

    for (unsigned bin = 0; bin < CW_SPECTRUM_BINS; ++bin) {
        int32_t a = s->prev[bin], b = s->older[bin];
        int32_t cross = (int32_t)(((int64_t)coeff[bin] * a) >> 14);
        // Windowed input limits bin power to less than 2^31. Clamp roundoff at zero.
        int64_t power = (int64_t)a*a + (int64_t)b*b - (int64_t)cross*b;
        uint32_t v = power > 0 ? (uint32_t)power : 0;
        unsigned level = 0;
        if (v >= 128) {
            unsigned log = 31 - __builtin_clz(v);
            unsigned frac = (v >> (log-3)) & 7;
            level = (log-7)*12 + frac + (frac >> 1);
        }
        levels[bin] = level > 255 ? 255 : level;
    }
    cw_spectrum_reset(s);
    return 1;
}

#endif
