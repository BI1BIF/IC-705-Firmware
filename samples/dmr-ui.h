#ifndef IC705_DMR_UI_H
#define IC705_DMR_UI_H

#include <stdint.h>

/* The receiver publishes unknown fields as UINT32_MAX. */
struct dmr_ui_status {
    uint32_t enabled, phase, color_code, source_id, talkgroup;
    uint32_t sample_blocks, varying_blocks;
    uint32_t decoded_samples, playback_samples;
    char row[48];
};
enum { DMR_SEARCH, DMR_SYNC, DMR_GROUP, DMR_END, DMR_SD_ERROR, DMR_RESOURCE_ERROR,
       DMR_MODE_PENDING, DMR_RETIRING, DMR_TX_BUSY, DMR_OTHER_RX, DMR_APRS_BUSY,
       DMR_NO_RAM, DMR_NO_THREAD };
int dmr_rx_set_enabled(unsigned enabled);
const volatile struct dmr_ui_status *dmr_ui_get_status(void);

#endif
