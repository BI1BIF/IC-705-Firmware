/* IC-705 FT8/FT4 slot decoder. The native PCM and desktop WAV rates differ. */
#include "common/monitor.h"
#include "ft8/encode.h"
#include "device_memory.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef FTX_RX_RATE
#define FTX_RX_RATE 12000
#endif
#if FTX_RX_RATE != 8000 && FTX_RX_RATE != 12000
#error Unsupported receiver sample rate
#endif
enum { RATE = 12000, MAX_ROWS = 48 };
#ifdef FTX_DEVICE
#define monitor (ftx_memory->plan)
#define rows (ftx_memory->rows)
#define block (ftx_memory->block)
static int capture_bank, next_offset, heap_count;
static ftx_waterfall_t decoding;
unsigned rx_late_slots, rx_short_searches, rx_first_delay, ftx_cq_retry;
static unsigned retry_count;

/* A plain type-1 FT8 CQ carries a known first call (28-bit token 2),
   no suffix on that call, and i3=1. The remaining 142 bits must
   independently support the resulting codeword before the CRC check. */
void ftx_apply_cq_prior(float *llr)
{
    for(int j=0;j<32;++j) {
        int pos=j<29?j:j+45;
        llr[pos]=(pos==26 || pos==76)?12.0f:-12.0f;
    }
}

int ftx_cq_consistent(const float *llr, const uint8_t *plain)
{
    unsigned errors=0;
    for(int i=29;i<FTX_LDPC_N;++i)
        if(i<74 || i>76) errors+=((llr[i]>0)!=plain[i]);
    return errors<=45;
}
static uint32_t decode_boundary;
static unsigned decode_slot, candidate_index, candidate_count, decoded_count;
extern void view_publish(unsigned, unsigned);

unsigned live_pending(void);

static unsigned backlog_limit(void)
{
    return monitor.wf.protocol==FTX_PROTOCOL_FT4 ? 1536 : 1024;
}

int rx_hold_input(void)
{
    if (!candidate_count || monitor.wf.mag == ftx_memory->spectrum ||
        monitor.wf.num_blocks < ftx_memory->prefix_blocks) return 0;
    /* The worker runs a bounded LDPC slice on each wake. Keep new PCM queued
       when the prefix is full, but leave more headroom on FT8 after field audio overruns. */
    if (live_pending() < backlog_limit()) return 1;
    ++rx_short_searches;
    candidate_count = 0;
    if (!decoded_count) view_publish(decode_slot, 0);
    return 0;
}

static void prepare_spectrum(void)
{
    if (candidate_count || monitor.wf.mag == ftx_memory->spectrum) return;
    size_t bytes = monitor.wf.num_blocks * monitor.wf.block_stride;
    if (bytes) memcpy(ftx_memory->spectrum, monitor.wf.mag, bytes);
    monitor.wf.mag = ftx_memory->spectrum;
}

static void search_ready(int finish)
{
    int ft4 = monitor.wf.protocol == FTX_PROTOCOL_FT4;
    int end = ft4 ? 28 : 20;
    if (!finish) {
        int ready = monitor.wf.num_blocks - (ft4 ? 103 : 78);
        if (ready < end) end = ready;
        if (end <= next_offset) return;
    }
    heap_count = ftx_sync_range(&monitor.wf, ftx_memory->candidates[capture_bank],
                                heap_count, next_offset, end, finish);
    next_offset = end;
}

#else
static monitor_t monitor;
static struct DecodedRow rows[MAX_ROWS];
static float block[FTX_RX_RATE * 160 / 1000];
#endif
static unsigned filled;
static int receiving;

void rx_close(void)
{
#ifndef FTX_DEVICE
    if (receiving) monitor_free(&monitor);
#endif
    receiving = 0;
}

void rx_begin(int ft4)
{
    rx_close();
#ifdef FTX_DEVICE
    if (!ftx_memory || monitor.wf.protocol != (ft4 ? FTX_PROTOCOL_FT4 : FTX_PROTOCOL_FT8)) return;
    next_offset = -10;
    heap_count = 0;
    monitor_reset(&monitor);
    memset(monitor.last_frame, 0, monitor.nfft * sizeof(float));
#else
    monitor_config_t config = {
        .f_min = 200, .f_max = 3000, .sample_rate = FTX_RX_RATE,
        .time_osr = 2, .freq_osr = 2,
        .protocol = ft4 ? FTX_PROTOCOL_FT4 : FTX_PROTOCOL_FT8
    };
    monitor_init(&monitor, &config);
#endif
    filled = 0;
    receiving = 1;
}

void rx_push(const int16_t *samples, int length)
{
    if (!receiving) return;
    for (int i = 0; i < length; ++i) {
        block[filled++] = samples[i] / 32768.0f;
        if (filled == (unsigned)monitor.block_size) {
#ifdef FTX_DEVICE
            prepare_spectrum();
#endif
            monitor_process(&monitor, block);
#ifdef FTX_DEVICE
            search_ready(0);
#endif
            filled = 0;
        }
    }
}

/* Estimate signal power along the decoded tones. The median nearby noise
   power is ln(2) times its mean for white Gaussian noise. */
static int estimate_snr(const ftx_waterfall_t *wf, const ftx_candidate_t *c, const ftx_message_t *msg)
{
    const int ft4 = wf->protocol == FTX_PROTOCOL_FT4;
    const int count = ft4 ? FT4_NN : FT8_NN;
    uint8_t tones[FT4_NN];
    unsigned short noise_hist[256] = {0};
    if (ft4) ft4_encode(msg->payload, tones);
    else ft8_encode(msg->payload, tones);
#ifdef FTX_DEVICE
    int shift = wf->freq_osr==1 ? 4*c->freq_sub : -1;
#endif
    float power = 0;
    int signal_count = 0, noise_count = 0;
    for (int s = 1; s < count - 1; ++s) {
        int t = c->time_offset + s, bin = c->freq_offset + tones[s];
        if (t < 0 || t >= wf->num_blocks || bin < 0 || bin >= wf->num_bins) continue;
        int start = ((t * wf->time_osr + c->time_sub) * wf->freq_osr + (wf->freq_osr==1 ? 0 : c->freq_sub)) * wf->num_bins;
        const uint8_t *bins = wf->mag + start;
#ifdef FTX_DEVICE
        power += ftx_memory->power[ftx_level(bins[bin],shift)];
#else
        power += powf(10.0f, WF_ELEM_MAG(bins[bin]) / 10.0f);
#endif
        ++signal_count;
        for (int flank = 0; flank < 2; ++flank) {
            int edge = c->freq_offset + (flank ? (ft4 ? 4 : 8) + 2 : -3);
            for (int k = 0; k < 8; ++k) {
                int nearby = edge + (flank ? k : -k);
                if (nearby < 0 || nearby >= wf->num_bins) continue;
#ifdef FTX_DEVICE
                ++noise_hist[ftx_level(bins[nearby],shift)];
#else
                ++noise_hist[bins[nearby]];
#endif
                ++noise_count;
            }
        }
    }
    int median = 0, cumulative = 0;
    while (median < 255 && (cumulative += noise_hist[median]) * 2 < noise_count) ++median;
    if (!signal_count || !noise_count || median == 0) return -128;
#ifdef FTX_DEVICE
    float noise = ftx_memory->power[median] / 0.69314718f;
#else
    float noise = powf(10.0f, WF_ELEM_MAG(median) / 10.0f) / 0.69314718f;
#endif
    float excess = power / signal_count / noise - 1.0f;
    if (excess <= 0) return -128;
    /* Hann equivalent noise bandwidth. Reference FT reports to 2500 Hz. */
    return lroundf(10.0f * log10f(excess * (1.5f * FTX_RX_RATE / monitor.nfft) / 2500.0f));
}

static int decode_one(const ftx_waterfall_t *wf, const ftx_candidate_t *c, int used)
{
    ftx_message_t msg;
    ftx_decode_status_t status;
    if (!ftx_decode_candidate(wf, c, 25, &msg, &status)) return 0;
    ftx_message_offsets_t fields;
    char *text = rows[used].text;
    if (ftx_message_decode(&msg, NULL, text, &fields) != FTX_MESSAGE_RC_OK || !text[0]) return 0;
#ifdef FTX_DEVICE
    if (ftx_cq_retry && (strncmp(text, "CQ ", 3) || fields.types[1] != FTX_FIELD_CALL)) return 0;
    rows[used].assisted = ftx_cq_retry;
    rows[used].grid_pos = 0;
    if (fields.types[2] == FTX_FIELD_GRID) {
        const char *grid = text + fields.offsets[2];
        if (!strncmp(grid,"R ",2)) grid+=2;
        if (strlen(grid)==4 && strcmp(grid,"RR73")) rows[used].grid_pos = (grid-text)+1;
    }
#endif
    int hz = lroundf((monitor.min_bin + c->freq_offset + c->freq_sub * 0.5f) / monitor.symbol_period);
    int j = 0;
    while (j < used && (strcmp(rows[j].text, text) || abs(hz - rows[j].hz) > 15)) ++j;
    if (j != used) return 0;
    rows[used].hz = hz;
    rows[used].score = c->score;
    rows[used].snr = estimate_snr(wf, c, &msg);
    rows[used].sender = fields.types[1] == FTX_FIELD_CALL ? fields.offsets[1] : -1;
    return 1;
}

#ifdef FTX_DEVICE
void rx_cancel_decode(void)
{
    candidate_count = rx_late_slots = rx_short_searches = 0;
    if (ftx_memory) monitor.wf.mag = ftx_memory->spectrum;
}

void rx_queue_decode(unsigned slot, uint32_t end_sample)
{
    if(candidate_count) ++rx_late_slots;
    decode_boundary=end_sample;
    search_ready(1);
    decode_slot = slot;
    ftx_cq_retry=0;
    retry_count=monitor.wf.protocol==FTX_PROTOCOL_FT8 ? (heap_count<8?heap_count:8) : 0;
    candidate_count = heap_count + retry_count;
    candidate_index = decoded_count = 0;
    decoding = monitor.wf;
    monitor.wf.mag = ftx_memory->prefix;
    monitor.wf.num_blocks = 0;
    capture_bank ^= 1;
    rx_close();
    if (!candidate_count) view_publish(slot, 0);
}

void rx_decode_work(unsigned budget)
{
    while (budget-- && candidate_count) {
        /* Give the strongest ordinary candidates first use of the old slot.
           Retry those CQs before queue pressure can retire the weak tail. */
        unsigned i=candidate_index++;
        ftx_cq_retry = i>=retry_count && i<2*retry_count;
        if (i>=retry_count) i-=retry_count;
        const ftx_candidate_t *c = &ftx_memory->candidates[capture_bank ^ 1][i];
        int added = decode_one(&decoding, c, decoded_count);
        if(added && !decoded_count) rx_first_delay=(ftx_sample_count()-decode_boundary)/800;
        decoded_count += added;
        if (candidate_index == candidate_count || decoded_count == MAX_ROWS)
            candidate_count=0;
        if (added || (!candidate_count && !decoded_count))
            view_publish(decode_slot, decoded_count);
        if (live_pending() >= backlog_limit()) break;
    }
}
#else
int rx_end(void)
{
    if (!receiving) return 0;
    ftx_candidate_t candidates[FTX_MAX_CANDIDATES];
    int count = ftx_find_candidates(&monitor.wf, FTX_MAX_CANDIDATES, candidates, 10);
    int used = 0;
    for (int i = 0; i < count && used < MAX_ROWS; ++i)
        used += decode_one(&monitor.wf, &candidates[i], used);
    rx_close();
    return used;
}
#endif

#ifdef FTX_DEVICE
unsigned row_assisted(int i) { return rows[i].assisted | (rows[i].grid_pos<<1); }
#endif
const char *row_text(int i) { return rows[i].text; }
int row_hz(int i) { return rows[i].hz; }
int row_score(int i) { return rows[i].score; }
int row_snr(int i) { return rows[i].snr; }
int row_sender(int i) { return rows[i].sender; }

/* The caller supplies one slot of PCM. Sum the three adjacent Gaussian
   pulses at each sample instead of allocating a per-sample phase array. */
int tx_slot(int ft4, const char *text, int base_hz, int16_t *pcm, int capacity)
{
    const int slot = ft4 ? 90000 : 180000;
    const int symbol = ft4 ? 576 : 1920;
    const int count = ft4 ? FT4_NN : FT8_NN;
    if (capacity < slot || base_hz < 200 || base_hz > 2900 || strlen(text) >= FTX_MAX_MESSAGE_LENGTH) return 0;
    ftx_message_t msg;
    char check[FTX_MAX_MESSAGE_LENGTH];
    ftx_message_offsets_t fields;
    if (ftx_message_encode(&msg, NULL, text) != FTX_MESSAGE_RC_OK ||
        ftx_message_decode(&msg, NULL, check, &fields) != FTX_MESSAGE_RC_OK ||
        strcmp(check, text)) return 0;
    uint8_t tones[FT4_NN];
    if (ft4) ft4_encode(msg.payload, tones);
    else ft8_encode(msg.payload, tones);
    memset(pcm, 0, slot * sizeof(*pcm));
    const float tau = 6.28318530718f;
    const float k = 5.336446f * (ft4 ? 1 : 2);
    const int ramp = ft4 ? symbol : symbol / 8;
    float phase = 0;
    for (int s = 0; s < count; ++s) {
        int prev = tones[s ? s-1 : s], next = tones[s+1 < count ? s+1 : s];
        for (int j = 0; j < symbol; ++j) {
            float t = (float)j / symbol;
            float a = 0.5f * (1 - erff(k * t));
            float b = 0.5f * (1 + erff(k * (t - 1)));
            float tone = prev*a + tones[s]*(1-a-b) + next*b;
            int p = s*symbol + j;
            int edge = p < count*symbol-1-p ? p : count*symbol-1-p;
            float gain = edge < ramp ? 0.5f * (1 - cosf(0.5f*tau*edge/ramp)) : 1.0f;
            pcm[RATE/2 + p] = (int16_t)lroundf(24000 * gain * sinf(phase));
            phase += tau * (base_hz / (float)RATE + tone / symbol);
            if (phase >= tau) phase -= tau;
        }
    }
    return slot;
}
