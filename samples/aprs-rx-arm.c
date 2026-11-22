/* Receive-only Bell 202 and AX.25 UI frame decoder for signed 48 kHz PCM. */
#include "aprs-rx-arm.h"

enum {
    SYMBOL_SAMPLES = 40, CORRELATOR_SAMPLES = 52, DEMOD_STEP = 4,
    CLOCK_PERIOD = SYMBOL_SAMPLES * 64,
    SLICERS = 3,
};

struct slicer {
    int phase;
    uint8_t tone, previous_symbol;
    uint8_t pending, pending_bits, collecting, ones, bits, octet;
    uint16_t length, crc;
    uint8_t bytes[FRAME_MAX];
};

struct output_frame aprs_rx_frames[OUT_SLOTS];
uint32_t aprs_rx_read, aprs_rx_written, aprs_rx_overrun, aprs_rx_bad_fcs, aprs_rx_samples;

static struct slicer slicers[SLICERS];
static int16_t history[2 * CORRELATOR_SAMPLES];
static unsigned head, step, inactive;

/* Signed Q9 quadrature references. Rows are cos/sin at 1200 and 2200 Hz. */
static const int16_t tones[CORRELATOR_SAMPLES][4] = {
    { 512,    0,  512,    0},
    { 506,   80,  491,  145},
    { 487,  158,  429,  279},
    { 456,  232,  333,  389},
    { 414,  301,  208,  468},
    { 362,  362,   67,  508},
    { 301,  414,  -80,  506},
    { 232,  456, -220,  462},
    { 158,  487, -343,  380},
    {  80,  506, -437,  268},
    {   0,  512, -495,  133},
    { -80,  506, -512,  -13},
    {-158,  487, -487, -158},
    {-232,  456, -422, -290},
    {-301,  414, -322, -398},
    {-362,  362, -196, -473},
    {-414,  301,  -54, -509},
    {-456,  232,   93, -503},
    {-487,  158,  232, -456},
    {-506,   80,  352, -371},
    {-512,    0,  443, -256},
    {-506,  -80,  498, -120},
    {-487, -158,  511,   27},
    {-456, -232,  483,  171},
    {-414, -301,  414,  301},
    {-362, -362,  312,  406},
    {-301, -414,  183,  478},
    {-232, -456,   40,  510},
    {-158, -487, -106,  501},
    { -80, -506, -244,  450},
    {   0, -512, -362,  362},
    {  80, -506, -450,  244},
    { 158, -487, -501,  106},
    { 232, -456, -510,  -40},
    { 301, -414, -478, -183},
    { 362, -362, -406, -312},
    { 414, -301, -301, -414},
    { 456, -232, -171, -483},
    { 487, -158,  -27, -511},
    { 506,  -80,  120, -498},
    { 512,    0,  256, -443},
    { 506,   80,  371, -352},
    { 487,  158,  456, -232},
    { 456,  232,  503,  -93},
    { 414,  301,  509,   54},
    { 362,  362,  473,  196},
    { 301,  414,  398,  322},
    { 232,  456,  290,  422},
    { 158,  487,  158,  487},
    {  80,  506,   13,  512},
    {   0,  512, -133,  495},
    { -80,  506, -268,  437},
};

static void emit(struct slicer *lane)
{
    unsigned address = 7;
    while (address < 70 && address + 7 <= lane->length - 4u) {
        address += 7;
        if (lane->bytes[address - 1] & 1)
            break;
    }
    if ((lane->bytes[6] & 1) || !(lane->bytes[address - 1] & 1) ||
        (lane->bytes[address] & 0xef) != 3 || lane->bytes[address + 1] != 0xf0 ||
        lane->length - address > 260)
        return;
    if (lane->crc != 0xf0b8) {
        ++aprs_rx_bad_fcs;
        return;
    }
    if (aprs_rx_written) {
        const struct output_frame *last = &aprs_rx_frames[(aprs_rx_written - 1) % OUT_SLOTS];
        // The slicers can see the same closing flag a few samples apart.
        if (aprs_rx_samples - last->end_sample <= SYMBOL_SAMPLES &&
            last->length == lane->length) {
            unsigned i = 0;
            while (i < last->length && last->bytes[i] == lane->bytes[i])
                ++i;
            if (i == last->length)
                return;
        }
    }
    if (aprs_rx_written - aprs_rx_read >= OUT_SLOTS) {
        ++aprs_rx_overrun;
        return;
    }
    struct output_frame *event = &aprs_rx_frames[aprs_rx_written % OUT_SLOTS];
    event->end_sample = aprs_rx_samples;
    event->length = lane->length;
    for (unsigned i = 0; i < lane->length; ++i)
        event->bytes[i] = lane->bytes[i];
    ++aprs_rx_written;
}

static void data_bit(struct slicer *lane, unsigned bit)
{
    if (!lane->collecting)
        return;
    if (!bit && lane->ones == 5) {
        lane->ones = 0;
        return;
    }
    lane->ones = bit ? lane->ones + 1 : 0;
    if (lane->ones > 5 || lane->length == FRAME_MAX) {
        lane->collecting = 0;
        return;
    }
    lane->octet |= bit << lane->bits;
    if (++lane->bits == 8) {
        lane->bytes[lane->length++] = lane->octet;
        lane->bits = lane->octet = 0;
    }
    unsigned feedback = (lane->crc ^ bit) & 1;
    lane->crc = (lane->crc >> 1) ^ (feedback ? 0x8408 : 0);
}

static void hdlc_bit(struct slicer *lane, unsigned bit)
{
    // Hold one flag's worth of raw bits back before removing stuffed zeroes.
    if (lane->pending_bits == 8)
        data_bit(lane, lane->pending >> 7);
    else
        ++lane->pending_bits;
    lane->pending = (lane->pending << 1) | bit;
    if (lane->pending_bits == 8 && lane->pending == 0x7e) {
        if (lane->collecting && lane->bits == 0 && lane->length >= 18)
            emit(lane);
        lane->pending_bits = lane->length = lane->ones = lane->bits = lane->octet = 0;
        lane->crc = 0xffff;
        lane->collecting = 1;
    }
}

static void symbol_clock(struct slicer *lane, unsigned tone)
{
    int phase = lane->phase;
    if (tone != lane->tone) {
        // The trailing correlator crosses near the delayed bit edge.
        int error = phase < CLOCK_PERIOD / 2 ? phase : phase - CLOCK_PERIOD;
        phase -= error / 4;
        lane->tone = tone;
    }
    int next = phase + DEMOD_STEP * 64;
    if (phase < CLOCK_PERIOD / 2 && next >= CLOCK_PERIOD / 2) {
        hdlc_bit(lane, tone == lane->previous_symbol);
        lane->previous_symbol = tone;
    }
    lane->phase = next >= CLOCK_PERIOD ? next - CLOCK_PERIOD : next;
}

void aprs_rx_gap(void)
{
    if (inactive)
        return;
    for (unsigned n = 0; n < 2 * CORRELATOR_SAMPLES; ++n)
        history[n] = 0;
    for (unsigned n = 0; n < SLICERS; ++n) {
        struct slicer *lane = &slicers[n];
        lane->phase = lane->tone = lane->previous_symbol = 0;
        lane->pending_bits = lane->collecting = 0;
    }
    head = step = 0;
    inactive = 1;
}

void aprs_rx_feed(const int16_t *pcm, unsigned samples)
{
    inactive = 0;
    while (samples--) {
        const int16_t sample = *pcm++;
        history[head] = history[head + CORRELATOR_SAMPLES] = sample;
        if (++head == CORRELATOR_SAMPLES)
            head = 0;
        ++aprs_rx_samples;
        if (++step != DEMOD_STEP)
            continue;
        step = 0;
        int mi = 0, mq = 0, si = 0, sq = 0;
        for (unsigned i = 0; i < CORRELATOR_SAMPLES; ++i) {
            int x = history[head + i];
            mi += x * tones[i][0];
            mq += x * tones[i][1];
            si += x * tones[i][2];
            sq += x * tones[i][3];
        }
        mi >>= 15;
        mq >>= 15;
        si >>= 15;
        sq >>= 15;
        int mark = mi * mi + mq * mq;
        int space = si * si + sq * sq;
        symbol_clock(&slicers[0], mark > space);
        symbol_clock(&slicers[1], mark > space + space / 2);
        symbol_clock(&slicers[2], mark + mark / 2 > space);
    }
}
