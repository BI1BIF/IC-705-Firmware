#ifndef IC705_DIGITAL_RX_H
#define IC705_DIGITAL_RX_H
#include <stdint.h>
enum { RX_DMR=1, RX_YSF, RX_P25 };
enum { CALL_UNKNOWN, CALL_GROUP, CALL_PRIVATE, CALL_ALL };
struct digital_call {
    unsigned active, kind, code, source, target, format;
    char callsign[11];
};
extern struct digital_call digital_call;
void digital_reset(void);
void digital_block(unsigned mode, const int16_t pcm[36]);
void dmr_audio_reset(void);
void digital_alert(unsigned kind);
int dmr_audio_frame(const uint8_t voice[9]);
int fusion_ambe_frame(const uint8_t voice[9]);
int digital_imbe(const uint8_t *packed, int fusion);
int digital_ambe(const char bits[49]);
#endif
