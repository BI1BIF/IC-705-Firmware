#ifndef FTX_LIVE_RX_H
#define FTX_LIVE_RX_H
#include <stdint.h>

/* J140 input is a single producer of six signed 8 kHz samples. The control
   task serializes open/close/poll and quiesces capture before re-anchoring.
   'phase' is the UTC position of the first sample in the named slot, in
   samples. Supply a fresh anchor after tuning or a UTC discontinuity. */
void live_open(unsigned ft4, uint32_t first_sample, unsigned slot, unsigned phase);
/* The board must timestamp the named UTC second edge on the ADC clock.
   A serial sentence's arrival alone does not supply that edge. */
int live_open_gps(unsigned ft4, unsigned edge_second_of_day, uint32_t edge_sample, uint32_t first_sample);
/* Foreground VFO observer. Supply the UTC anchor of the next capture block. */
void live_vfo(unsigned hz, uint32_t first_sample, unsigned slot, unsigned phase);
void live_capture(const int16_t pcm[6], uint32_t first_sample);
void live_close(void);
/* -1: no completed slot; 0: valid empty slot; positive: decoded row count. */
int live_poll(void);
#ifdef FTX_DEVICE
int ft_need_early_decode(unsigned slot);
#endif
unsigned live_last_slot(void);
unsigned live_pending(void);
unsigned live_overruns(void);
unsigned live_gaps(void);
unsigned live_enabled(void);
/* Called by the control task for a debounced J140 panel key. */
void live_panel_key(unsigned key);
void view_reset(unsigned ft4);
void view_publish(unsigned slot,unsigned count);
void view_draw(unsigned slot,unsigned phase);
void view_page(unsigned next);
#endif
