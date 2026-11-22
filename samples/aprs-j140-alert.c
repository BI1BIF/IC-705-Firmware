#include "aprs-j140-popup.h"

#pragma GCC optimize ("Os")

#define NOW (*(volatile uint32_t *)0x20381e08)
extern volatile uint32_t aprs_channel_hz;
extern uint8_t aprs_beacon_ssid, aprs_tx_enabled;
uint8_t aprs_alert_styles[ALERT_COUNT] APRS_KEEP = {
    SILENT_POPUP, SHORT_TONE, DOUBLE_TONE, SHORT_LONG, SHORT_TONE, LIST_ONLY, LIST_ONLY
};

struct beacon_copy {
    uint8_t source[7], info[20+APRS_BEACON_COMMENT_MAX], size;
    uint32_t hz, at;
};
static struct beacon_copy prepared, sent;
static unsigned prepared_message;
#ifndef APRS_SLOT_UI
static unsigned reply_slot;
#endif
static struct receipt {
    char sender[10], id[6];
    uint32_t at, hz;
} incoming[8];
#ifndef APRS_SLOT_UI
static struct receipt outgoing[4] APRS_KEEP;
static unsigned out_slot APRS_KEEP;
#endif
static unsigned in_slot;
static unsigned second_note;
static uint32_t started_note;

static int equal(const char *a, const char *b)
{
    while (*a && *a == *b) {
        ++a;
        ++b;
    }
    return *a == *b;
}

static void save_receipt(struct receipt *r, const char *call, const char *id)
{
    unsigned i = 0;
    while (i < sizeof(r->sender)-1 && call[i]) {
        r->sender[i] = call[i];
        ++i;
    }
    r->sender[i] = 0;
    i = 0;
    while (i < sizeof(r->id)-1 && id[i]) {
        r->id[i] = id[i];
        ++i;
    }
    r->id[i] = 0;
    r->at = NOW;
    r->hz = aprs_channel_hz;
}

static int match(const struct receipt *r, const char *sender, const char *id)
{
    return r->hz && r->hz == aprs_channel_hz && NOW-r->at < 600000 &&
           equal(r->sender,sender) && equal(r->id,id);
}

void aprs_track_prepared(const uint8_t *source, const uint8_t *info, unsigned size, unsigned message)
{
    prepared_message = message;
    prepared.size = 0;
    if (message || size > sizeof(prepared.info))
        return;
    for (unsigned i=0; i<7; ++i)
        prepared.source[i] = source[i];
    for (unsigned i=0; i<size; ++i)
        prepared.info[i] = info[i];
    prepared.size = size;
}

#ifndef APRS_SLOT_UI
void aprs_track_reply(const char *recipient, const char *id)
{
    reply_slot = out_slot++ % 4;
    save_receipt(&outgoing[reply_slot],recipient,id);
    outgoing[reply_slot].hz = 0; /* Only the completed AFSK burst qualifies. */
}

#endif
void aprs_track_transmitted(uint32_t hz)
{
    if (prepared_message) {
#ifndef APRS_SLOT_UI
        outgoing[reply_slot].at = NOW;
        outgoing[reply_slot].hz = hz;
#endif
    } else {
        sent = prepared;
        sent.at = NOW;
        sent.hz = hz;
    }
}

static int relayed(const uint8_t *frame, unsigned addresses, unsigned length)
{
    if (!sent.hz || sent.hz != aprs_channel_hz || NOW-sent.at > 120000 ||
        !sent.size || sent.size != length || addresses < 21)
        return 0;
    for (unsigned i=0; i<6; ++i)
        if (sent.source[i] != frame[7+i])
            return 0;
    if ((sent.source[6]^frame[13]) & 0x1e)
        return 0;
    for (unsigned i=0; i<length; ++i)
        if (sent.info[i] != frame[addresses+2+i])
            return 0;
    for (unsigned i=20; i<addresses; i+=7)
        if (frame[i] & 0x80)
            return 1;
    return 0;
}

static int addressed(const char *dest)
{
    uint8_t address[7];
    const volatile uint8_t *call = (const volatile uint8_t *)0x203e2499;
    for (unsigned i=0; i<6; ++i)
        address[i] = (call[i] ? call[i] : ' ') << 1;
    address[6] = aprs_beacon_ssid << 1;
    char mine[10];
    mine[aprs_call_text(mine,address)] = 0;
    return mine[0] && equal(mine,dest);
}

static int receipt(const char *text)
{
    if (!((text[0]=='a' && text[1]=='c' && text[2]=='k') ||
          (text[0]=='r' && text[1]=='e' && text[2]=='j')))
        return 0;
    unsigned n=3;
    while (text[n] && n<8) {
        char c=text[n++];
        if (!(c>='0' && c<='9') && !(c>='a' && c<='z') && !(c>='A' && c<='Z'))
            return 0;
    }
    return n>3 && !text[n];
}

unsigned aprs_can_reply(const struct popup_packet *p)
{
    return aprs_tx_enabled && p->kind == MESSAGE && addressed(p->longitude) && !receipt(p->comment);
}

unsigned aprs_alert_class(const struct popup_packet *p, const uint8_t *frame, unsigned addresses, unsigned length)
{
    if (relayed(frame,addresses,length)) {
        /* Keep the fingerprint until expiry so subsequent paths are list-only. */
        if (sent.source[6] & 0x80)
            return ALERT_COUNT;
        sent.source[6] |= 0x80;
        return ALERT_RELAY;
    }
    if (p->kind == WEATHER || (p->kind == PACKET && length && frame[addresses+2] == '_'))
        return ALERT_WEATHER;
    if (p->kind <= PERSONAL)
        return ALERT_BEACON;
    if (p->kind == STATUS)
        return ALERT_STATUS;
    if (p->kind != MESSAGE || !addressed(p->longitude))
        return ALERT_OTHER;
    if (receipt(p->comment)) {
#ifdef APRS_SLOT_UI
        return aprs_match_result(p->station,p->comment) ? ALERT_ACK : ALERT_COUNT;
#else
        for (unsigned i=0; i<4; ++i)
            if (match(&outgoing[i],p->station,p->comment+3)) {
                outgoing[i].hz=0;
                return ALERT_ACK;
            }
        return ALERT_COUNT;
#endif
    }
    if (*p->message_id) {
#ifdef APRS_SLOT_UI
        aprs_message_ack(p);
#endif
        for (unsigned i=0; i<8; ++i)
            if (match(&incoming[i],p->station,p->message_id))
                return ALERT_COUNT;
        save_receipt(&incoming[in_slot++ % 8],p->station,p->message_id);
    }
#ifdef APRS_SLOT_UI
    aprs_schedule_answer(p);
#endif
    return ALERT_MESSAGE;
}

void aprs_alert_sound(unsigned style)
{
    second_note = style == SHORT_LONG;
    if (style >= SHORT_TONE && style <= SHORT_LONG) {
        started_note = NOW;
        ((void (*)(unsigned))0x2007d478)(style == DOUBLE_TONE ? 3 : 8);
    }
}

void aprs_alert_tick(unsigned listening)
{
    if (second_note && (!listening || NOW-started_note >= 160)) {
        second_note = 0;
        if (listening && NOW-started_note < 600)
            /* Native pattern 5 holds the same pitch for 63+62 ticks.
               Pattern 8 uses 50 ticks. Neither reserves the key-click sequence. */
            ((void (*)(unsigned))0x2007d478)(5);
    }
}

/* Freestanding ARM build also uses this for whole history and menu structures. */
void *memcpy(void *dest, const void *source, __SIZE_TYPE__ size)
{
    uint8_t *out=dest;
    const uint8_t *in=source;
    while (size--)
        *out++=*in++;
    return dest;
}
