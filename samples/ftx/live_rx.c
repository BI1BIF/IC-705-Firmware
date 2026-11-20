/* Receive worker; the producer never allocates, decodes, or waits for it. */
#include "live_rx.h"
#include "device_memory.h"
#include <stdatomic.h>

void rx_begin(int ft4);
void rx_push(const int16_t *samples, int length);
int rx_end(void);
void rx_close(void);

enum { BLOCKS = 2048, BLOCK_SAMPLES = 6, POLL_BLOCKS = 24 };
#ifdef FTX_DEVICE
/* The worker checks the prefix limit before every poll. One poll can finish
   at most one FFT block at the shortest supported symbol period (FT4). */
_Static_assert(POLL_BLOCKS * BLOCK_SAMPLES <= 384, "RX poll crosses two FT4 blocks");
#define queue (ftx_memory->queue)
#else
static struct AudioBlock queue[BLOCKS];
#endif
static _Atomic unsigned head, tail, enabled, overruns;
static unsigned mode, slot_length, slot_id, phase, aligned, last_slot, gaps;
static uint32_t expected;
static unsigned frequency;

void live_close(void)
{
    atomic_store(&enabled, 0);
    rx_close();
#ifdef FTX_DEVICE
    rx_cancel_decode();
#endif
    aligned = 0;
}

void live_open(unsigned ft4, uint32_t first_sample, unsigned slot, unsigned initial_phase)
{
    live_close();
    mode = ft4;
    frequency = 0;
    slot_length = ft4 ? 60000 : 120000;
    if (ft4 > 1 || initial_phase >= slot_length) return;
    atomic_store(&head, 0);
    atomic_store(&tail, 0);
    atomic_store(&overruns, 0);
    slot_id = slot;
    expected = first_sample;
    phase = initial_phase;
    gaps = 0;
#ifndef FTX_DEVICE
    view_reset(ft4);
#endif
    atomic_store(&enabled, 1);
}

void live_vfo(unsigned hz, uint32_t first_sample, unsigned slot, unsigned initial_phase)
{
    if (!live_enabled()) return;
    if (frequency && hz != frequency) live_open(mode, first_sample, slot, initial_phase);
    frequency = hz;
}

void live_capture(const int16_t pcm[6], uint32_t first_sample)
{
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) return;
    unsigned w = atomic_load_explicit(&head, memory_order_relaxed);
    if (w - atomic_load_explicit(&tail, memory_order_acquire) == BLOCKS) {
        atomic_fetch_add_explicit(&overruns, 1, memory_order_relaxed);
        return;
    }
    unsigned index = w % BLOCKS;
    queue[index].first = first_sample;
    for (int j = 0; j < BLOCK_SAMPLES; ++j) queue[index].pcm[j] = pcm[j];
    atomic_store_explicit(&head, w + 1, memory_order_release);
}

int live_poll(void)
{
    if (!atomic_load(&enabled)) return -1;
    for (unsigned n = 0; n < POLL_BLOCKS; ++n) {
        unsigned r = atomic_load_explicit(&tail, memory_order_relaxed);
        if (r == atomic_load_explicit(&head, memory_order_acquire)) break;
        unsigned index = r % BLOCKS;
        uint32_t first = queue[index].first;
        int16_t pcm[BLOCK_SAMPLES];
        for (int j = 0; j < BLOCK_SAMPLES; ++j) pcm[j] = queue[index].pcm[j];
        atomic_store_explicit(&tail, r + 1, memory_order_release);
        if (first != expected) {
            rx_close();
            aligned = 0;
            ++gaps;
            uint32_t skipped = first - expected;
            if (skipped > 0x7fffffffu) { live_close(); return -1; }
            unsigned advance = phase + skipped;
            slot_id += advance / slot_length;
            phase = advance % slot_length;
        }
        expected = first + BLOCK_SAMPLES;
        int result = -1;
        for (unsigned j = 0; j < BLOCK_SAMPLES;) {
            if (!phase) { rx_begin(mode); aligned = 1; }
            unsigned count = slot_length - phase;
            if (count > BLOCK_SAMPLES - j) count = BLOCK_SAMPLES - j;
            if (aligned) rx_push(pcm + j, count);
            phase += count;
            j += count;
#ifdef FTX_DEVICE
            /* During an exchange freeze the opposite-slot spectrum 1.2 s early.
               Both nominal waveforms have already ended. Normal listening keeps the full slot. */
            
            if (aligned && phase >= slot_length-9600 && phase < slot_length && ft_need_early_decode(slot_id)) {
                rx_queue_decode(slot_id,first+j);
                aligned=0;
            }
#endif
            if (phase == slot_length) {
                if (aligned) {
#ifdef FTX_DEVICE
                    rx_queue_decode(slot_id,first+j);
#else
                    result = rx_end(); last_slot = slot_id;
                    view_publish(slot_id,(unsigned)result);
#endif
                }
                ++slot_id;
                phase = aligned = 0;
            }
        }
        if (result >= 0) return result;
    }
    return -1;
}

unsigned live_last_slot(void) { return last_slot; }
unsigned live_pending(void) { return atomic_load(&enabled) ? atomic_load(&head) - atomic_load(&tail) : 0; }
unsigned live_overruns(void) { return atomic_load(&overruns); }
unsigned live_gaps(void) { return gaps; }
unsigned live_enabled(void) { return atomic_load(&enabled); }

void live_panel_key(unsigned key)
{
    if (key == 9 && live_enabled()) live_close();  /* Physical EXIT. */
}
