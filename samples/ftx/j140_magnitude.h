#ifndef J140_MAGNITUDE_H
#define J140_MAGNITUDE_H
#include "device_memory.h"
#include <string.h>

/* The binary exponent estimates the half-dB bin. Correct that estimate
   against the exact power boundaries, also used to invert bins for SNR. */
static inline uint8_t ftx_quantize(float power)
{
    uint32_t bits;
    memcpy(&bits, &power, sizeof(bits));
    int exponent = (int)(bits >> 23) - 127;
    int bin = 240 + 6 * exponent + (int)((bits >> 20) & 7);
    if (bin < 0) bin = 0;
    if (bin > 255) bin = 255;
    const float *limits = ftx_memory->power;
    while (bin && power < limits[bin]) --bin;
    while (bin < 255 && power >= limits[bin+1]) ++bin;
    return (uint8_t)bin;
}

static int level(kiss_fft_cpx s)
{
    return ftx_quantize(s.r*s.r+s.i*s.i+1E-12f);
}

/* Adjacent half-bin levels are correlated. Keep their mean on five bits and
   their signed difference on three, with a common noise reference per FFT. */
static int compact_spectrum(monitor_t *m, const kiss_fft_cpx *fft, int offset)
{
    unsigned sum=0, count=0;
    for(int k=m->min_bin;k<m->max_bin;k+=8) {
        kiss_fft_cpx s=fft[2*k];
        sum+=ftx_quantize(s.r*s.r + s.i*s.i + 1E-12f);
        ++count;
    }
    int floor=(int)(sum/count)-18;
    for(int k=m->min_bin;k<m->max_bin;++k) {
        int lo=level(fft[2*k]),hi=level(fft[2*k+1]);
        int mean=((lo+hi)/2-floor+2)/4;
        int delta=(hi-lo+14)/4;
        if(mean<0) mean=0;
        if(mean>31) mean=31;
        if(delta<0) delta=0;
        if(delta>7) delta=7;
        m->wf.mag[offset++]=(mean<<3) | delta;
    }
    return offset;
}
#endif
