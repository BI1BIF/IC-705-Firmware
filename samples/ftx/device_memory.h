#ifndef FTX_DEVICE_MEMORY_H
#define FTX_DEVICE_MEMORY_H
#include <stdint.h>
#include "common/monitor.h"
#include "ft8/message.h"

struct DecodedRow {
    char text[FTX_MAX_MESSAGE_LENGTH];
    int hz, score, sender, snr;
    uint8_t assisted, grid_pos;
};
struct DisplayRow {
    char text[FTX_MAX_MESSAGE_LENGTH];
    uint8_t assisted; /* Bit 0 marks a CQ retry. Upper bits hold grid offset + 1. */
    uint32_t slot;
    int16_t hz;
    int8_t db;
    uint8_t flag; /* Sender offset + 1, or zero if the message has no sender field. */
};
struct DisplayBatch { unsigned count, slot; struct DisplayRow rows[48]; };
struct AudioBlock { uint32_t first; int16_t pcm[6]; };

enum { FTX_MAX_CANDIDATES = 140 };
#ifdef FTX_DEVICE
/* Spectrum calculation and final slot decoding use the scratch area in turn. */
struct DecodeScratch {
    float tov[FTX_LDPC_N][3];
    float toc[FTX_LDPC_M][7];
};
struct DeviceMemory {
    struct AudioBlock queue[2048];
    struct DisplayBatch batches[3];
    struct DecodedRow rows[48];
    float *block;
    monitor_t plan;
    void *scratch;
    uint8_t *spectrum, *prefix;
    int prefix_blocks;
    ftx_candidate_t candidates[2][FTX_MAX_CANDIDATES];
    float power[256];
    uint8_t work[];
};
extern struct DeviceMemory *ftx_memory;
/* A negative shift selects a full-resolution half-dB sample. The compact
   spectrum stores a mean and a difference relative to the FFT noise level. */
static inline unsigned ftx_level(uint8_t byte, int shift)
{
    if(shift<0) return byte;
    int delta=2*((byte&7)-3);
    return 96+4*(byte>>3)+(shift?delta:-delta);
}
const char *ftx_allocate(unsigned ft4);
void rx_queue_decode(unsigned slot, uint32_t end_sample);
unsigned ftx_sample_count(void);
void ftx_apply_cq_prior(float *likelihood);
int ftx_cq_consistent(const float *likelihood, const uint8_t *plain);
extern unsigned ftx_cq_retry;
extern unsigned rx_late_slots, rx_short_searches, rx_first_delay;
int rx_hold_input(void);
void rx_decode_work(unsigned budget);
void rx_cancel_decode(void);
int ftx_sync_range(const ftx_waterfall_t *, ftx_candidate_t *, int, int, int, int);
void ftx_release(void);
#endif
#endif
