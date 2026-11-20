/* Test driver running inside the offline ARM guest. The original J140 DMA
   service and consumer execute for every bank. Unicorn copies the six words
   observed at their existing PCM boundary into observed_pcm. */
#include <stdint.h>
#include "live_rx.h"

volatile int16_t observed_pcm[6];
static unsigned bank;
static uint32_t adc;
static unsigned captures;

void fixture_clock(uint32_t first) { adc = first; }
unsigned fixture_captures(void) { return captures; }

int fixture_input(const int16_t *six, unsigned blocks, int poll)
{
    int result = -1;
    for (unsigned i = 0; i < blocks; ++i, six += 6) {
        volatile uint32_t *target = (volatile uint32_t *)(0x20400800u + bank * 288);
        for (unsigned j = 0; j < 36; ++j) {
            target[2*j] = (uint32_t)(uint16_t)six[j/6] << 16;
            target[2*j+1] = 0;
        }
        *(volatile uint32_t *)0xe82000e4 = bank ? 0x41 : 0xc1;
        bank ^= 1;
        ((void (*)(void))0x200ffc70)();
        ((void (*)(void))0x2010fe04)();
        for (unsigned j=0; j<6; ++j) if (observed_pcm[j]!=six[j]) return -2;
        live_capture((const int16_t *)observed_pcm, adc);
        adc += 6;
        ++captures;
        if (poll && ((i+1)%24==0 || i+1==blocks)) {
            do {
                int count = live_poll();
                if (count >= 0) {
                    if (result >= 0) return -3;
                    result = count;
                }
            } while (live_pending());
        }
    }
    return result;
}
