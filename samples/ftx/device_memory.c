#include "device_memory.h"
#include <math.h>
#include <string.h>

struct DeviceMemory *ftx_memory;

static void *allocate(unsigned bytes)
{
    return ((void *(*)(unsigned))0x20127a28)(bytes);
}

static void release(void *ptr)
{
    if (ptr) ((void (*)(void *))0x20127a78)(ptr);
}

__attribute__((section(".ftx_controls"),noinline)) const char *ftx_allocate(unsigned ft4)
{
    if (ftx_memory || ft4 > 1) return "RX session unavailable";
    const float period = ft4 ? FT4_SYMBOL_PERIOD : FT8_SYMBOL_PERIOD;
    const int block = (int)(8000 * period), nfft = block * 2;
    const int min = (int)(200 * period), max = (int)(3000 * period) + 1;
    const int symbols = (int)((ft4 ? FT4_SLOT_TIME : FT8_SLOT_TIME) / period);
    const size_t bins = symbols * 4 * (max - min);
    size_t fft_bytes = 0;
    kiss_fftr_alloc(nfft, 0, NULL, &fft_bytes);
    /* kiss_fftr consumes its input into its private tmpbuf before writing output. */
    size_t scratch = (nfft/2+1) * sizeof(kiss_fft_cpx);
    if (scratch < sizeof(struct DecodeScratch)) scratch = sizeof(struct DecodeScratch);
    size_t bytes = sizeof(struct DeviceMemory) + scratch + (block + 2 * nfft) * sizeof(float) + fft_bytes;
    int time_osr = 2, freq_osr = 2;
    uint8_t *spectrum = allocate(bins);
    struct DeviceMemory *m = spectrum ? allocate(bytes) : NULL;
    if (!m) {
        release(spectrum);
        if (ft4) time_osr = 1;
        else freq_osr = 1;
        spectrum = allocate(bins/2);
        if (!spectrum) return "RX spectrum RAM unavailable";
        m = allocate(bytes);
        if (!m) { release(spectrum); return "RX work RAM unavailable"; }
    }
    memset(m, 0, sizeof(*m));
    monitor_t *p = &m->plan;
    p->block_size = block;
    p->subblock_size = block / time_osr;
    p->nfft = nfft;
    p->fft_norm = 2.0f / nfft;
    p->symbol_period = period;
    p->min_bin = min;
    p->max_bin = max;
    m->spectrum = spectrum;
    m->scratch = m->work;
    m->block = (float *)(m->work + scratch);
    p->window = m->block + block;
    p->last_frame = p->window + nfft;
    p->fft_work = p->last_frame + nfft;
    p->fft_cfg = kiss_fftr_alloc(nfft, 0, p->fft_work, &fft_bytes);
    if (!p->fft_cfg) {
        release(spectrum);
        release(m);
        return "RX FFT unavailable";
    }
    for (int i = 0; i < nfft; ++i) {
        float s = sinf(3.14159265358979323846f * i / nfft);
        p->window[i] = p->fft_norm * (s * s);
    }
    p->wf = (ftx_waterfall_t){.max_blocks=symbols, .num_bins=max-min,
        .time_osr=time_osr, .freq_osr=freq_osr, .block_stride=freq_osr*time_osr*(max-min),
        .mag=spectrum, .protocol=ft4 ? FTX_PROTOCOL_FT4 : FTX_PROTOCOL_FT8};
    /* Keep at most 3.84 seconds of the next slot while LDPC reads the previous
       slot. A smaller heap shortens this overlap without changing the FFT. */
    for (int n = ft4 ? 80 : 24; n; n /= 2) {
        m->prefix = allocate(n * p->wf.block_stride);
        if (m->prefix) { m->prefix_blocks = n; break; }
    }
    /* 20 half-dB bins per power decade. Re-anchor every decade rather
       than accumulating error over the entire dynamic range. */
    static const float fraction[20]={
        1.0f, 1.12201845f, 1.25892541f, 1.41253754f, 1.58489319f,
        1.77827941f, 1.99526231f, 2.23872114f, 2.51188643f, 2.81838293f,
        3.16227766f, 3.54813389f, 3.98107171f, 4.46683592f, 5.01187234f,
        5.62341325f, 6.30957344f, 7.07945784f, 7.94328235f, 8.91250938f,
    };
    float decade=1e-12f;
    for(unsigned i=0;i<256;++i) {
        m->power[i]=decade*fraction[i%20];
        if(i%20==19) decade*=10.f;
    }
    ftx_memory = m;
    return NULL;
}

void ftx_release(void)
{
    struct DeviceMemory *m = ftx_memory;
    ftx_memory = NULL;
    if (m) {
        release(m->prefix);
        release(m->spectrum);
        release(m);
    }
}


#ifdef FTX_DEVICE
/* The two halves are exactly representable in VFP double precision. Only
   their sum rounds, just as for a signed 64-bit to double conversion. */
double __wrap___aeabi_l2d(int64_t value)
{
    return (double)(int32_t)(value >> 32) * 4294967296.0 + (double)(uint32_t)value;
}
#endif
