#ifndef APRS_J140_POPUP_H
#define APRS_J140_POPUP_H

#include "aprs-rx-arm.h"

enum popup_kind { BEACON, WEATHER, IGATE, PERSONAL, MESSAGE, STATUS, PACKET };
enum alert_event { ALERT_BEACON, ALERT_WEATHER, ALERT_RELAY, ALERT_MESSAGE, ALERT_ACK,
                   ALERT_STATUS, ALERT_OTHER, ALERT_COUNT };
enum alert_style { LIST_ONLY, SILENT_POPUP, SHORT_TONE, DOUBLE_TONE, SHORT_LONG };
extern uint8_t aprs_alert_styles[ALERT_COUNT];
void aprs_track_prepared(const uint8_t *source, const uint8_t *info, unsigned size, unsigned message);
void aprs_track_transmitted(uint32_t hz);
void aprs_track_reply(const char *recipient, const char *id);
const char *aprs_send_reply(const char *recipient, const char *body);
void aprs_alert_sound(unsigned style);
void aprs_alert_tick(unsigned listening);
enum aprs_fix { NO_FIX, LIVE_FIX, LAST_FIX, MANUAL_FIX };
enum { NO_READING = -32768, RECORD_SLOTS = 64 };
enum { APRS_BEACON_COMMENT_MAX = 43 };

/* Only plain settings, history metadata and the separately owned ring pointer
   survive a mode switch. UI callbacks and DSP work start fresh on reload. */
#ifdef APRS_OVERLAY
#define APRS_KEEP __attribute__((section("aprs_keep")))
#else
#define APRS_KEEP
#endif

/* The integration experiment reuses part of the menu copy source after startup.
   aprs_records holds the heap-backed remainder, or the whole standalone ring. */
extern struct output_frame *aprs_records;
#ifdef APRS_HISTORY_SPLIT
#ifndef APRS_PREFIX_SLOTS
#define APRS_PREFIX_SLOTS 58
#endif
enum { HISTORY_PREFIX_SLOTS = APRS_PREFIX_SLOTS };
extern struct output_frame aprs_history_prefix[HISTORY_PREFIX_SLOTS];
#else
enum { HISTORY_PREFIX_SLOTS = 0 };
#endif
static inline struct output_frame *aprs_record_slot(unsigned slot)
{
#ifdef APRS_LAST_BANK_SLOTS
    extern struct output_frame *aprs_history_last_bank;
    if (slot >= RECORD_SLOTS - APRS_LAST_BANK_SLOTS)
        return aprs_history_last_bank + (slot - (RECORD_SLOTS - APRS_LAST_BANK_SLOTS));
#endif
#ifdef APRS_HISTORY_SPLIT
    if (slot < HISTORY_PREFIX_SLOTS)
        return aprs_history_prefix + slot;
#endif
    return aprs_records + (slot - HISTORY_PREFIX_SLOTS);
}

const char *aprs_beacon_comment(void);
extern uint8_t aprs_tx_path;
extern uint8_t aprs_auto_beacon, aprs_beacon_interval;
extern const uint8_t aprs_beacon_minutes[5];
void aprs_beacon_reschedule(void);
void aprs_beacon_poll(void);
#ifdef APRS_SLOT_UI
enum { SMART_INTERVAL = 5 };
void aprs_history_card_poll(unsigned mount);
uint32_t aprs_card_checksum(const void *data, unsigned bytes);
int aprs_geometry(const char *coords[4], unsigned packet, unsigned *metres, int *bearing);
extern uint8_t aprs_beacon_ssid, aprs_tx_enabled, comment_saved, aprs_settings_dirty;
extern char saved_comment[APRS_BEACON_COMMENT_MAX+1], saved_symbol[2];
unsigned aprs_save_comment(const char *,uint8_t *);
unsigned aprs_catalog(unsigned group,unsigned overlays,unsigned base);
unsigned aprs_catalog_icon(unsigned index);
enum message_state { MSG_EMPTY, MSG_QUEUED, MSG_WAIT, MSG_ACK, MSG_REJECT, MSG_TIMEOUT, MSG_CANCEL };
struct sent_message {
    char station[10], text[68], id[4];
    uint8_t state, attempts, ssid;
    uint32_t hz, due, created;
};
extern struct sent_message aprs_outbox[4];
extern unsigned aprs_sent_count;
struct popup_packet;
void aprs_message_ack(const struct popup_packet *p);
void aprs_schedule_answer(const struct popup_packet *p);
extern char aprs_phrases[20][33],aprs_answer_text[65],aprs_answer_call[10];
extern uint8_t aprs_answer_on,aprs_answer_delay;
extern const uint8_t aprs_delays[5];
int aprs_phrases_load(void);
int aprs_phrase_save(unsigned index,const char *text);
void aprs_cancel_answer(const char *station);
int aprs_match_result(const char *station,const char *response);
void aprs_message_finished(unsigned tag);
const char *aprs_start_message(const char *info,unsigned tag);
unsigned aprs_message_active(void);
extern uint32_t aprs_return_hz;
int aprs_valid_recipient(const char *station);
void aprs_messages_poll(void);
void aprs_message_cancel(unsigned slot);
#endif
unsigned aprs_standby_ready(void);
unsigned aprs_plain_fm(void);
const char *aprs_beacon_symbol(void);

struct popup_packet {
    char route[104];
    char station[10];
    char latitude[9];
    char longitude[10];
    char symbol[3];
    char comment[FRAME_MAX];
    int16_t course, speed, temperature, humidity, pressure;
    uint8_t kind;
    char message_id[6];
    uint8_t ambiguous, alert_event;
#ifdef APRS_SLOT_UI
    char entity[10];
    uint8_t item, removed;
#endif
};
enum { APRS_NO_DISTANCE = 0xffff };
uint16_t aprs_packet_distance(const struct popup_packet *p, uint32_t *direction);
void aprs_distance_text(char *out, uint16_t distance);
void aprs_draw_direction(unsigned direction, unsigned x, unsigned y, uint16_t background);

unsigned aprs_alert_class(const struct popup_packet *p, const uint8_t *frame, unsigned addresses, unsigned length);
unsigned aprs_can_reply(const struct popup_packet *p);
extern struct popup_packet aprs_popup_packet;
unsigned aprs_call_text(char *out, const uint8_t *address);
void aprs_parse_packet(struct popup_packet *out, const struct output_frame *record);
unsigned aprs_open_history_detail(void);
void aprs_history_resume(void);
enum aprs_fix aprs_gps_fix(void);
enum aprs_fix aprs_local_position(char lat[9], char lon[10]);
void aprs_draw_icon(uint16_t icon, unsigned left, unsigned top, uint16_t background);
const char *aprs_symbol_label(uint16_t icon);
unsigned aprs_symbol_catalog_text(unsigned layer, unsigned rect, unsigned format, unsigned font,
                                  unsigned color, const uint16_t *xy, unsigned align, unsigned language);

#endif
