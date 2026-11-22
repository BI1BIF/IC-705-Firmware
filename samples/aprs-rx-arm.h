#ifndef APRS_RX_ARM_H
#define APRS_RX_ARM_H

#include <stdint.h>

enum { FRAME_MAX = 330, OUT_SLOTS = 4 };

struct output_frame {
    uint32_t end_sample;
    uint32_t length;
    uint8_t bytes[FRAME_MAX];
    uint16_t distance; /* Receive history only, uses the former tail padding. */
};
_Static_assert(sizeof(struct output_frame) == 340, "history and demodulator ring stride");

extern struct output_frame aprs_rx_frames[OUT_SLOTS];
extern uint32_t aprs_rx_read, aprs_rx_written;

void aprs_rx_gap(void);
void aprs_rx_feed(const int16_t *pcm, unsigned samples);

#endif
