/* One manually requested 1200-baud position beacon on the stock FM TX path. */
#include "aprs-j140-popup.h"

#pragma GCC optimize ("Os")

#define U8(a) (*(volatile const uint8_t *)(a))
#define U32(a) (*(volatile const uint32_t *)(a))
#define NOW U32(0x20381e08)

enum { TX_IDLE, TX_ARMED, TX_SOUND, TX_DRAIN, TX_RELEASE };
enum { PREAMBLE = 45*8, TAIL = 6*8, BIT_SAMPLES = 40, PCM_FRAMES = 36 };
enum { MAX_BEACON_FRAME = 16 + 2*7 + 11 + 67 + 6 + 2 };
enum { ARM_TIMEOUT_MS = 450, TX_TIMEOUT_MS = 2100 };
enum { OWN_REQUEST = 0x8000, REMOTE_REQUEST = 0x20, DSP_TX = 0x10 };
#define TX_INHIBITED (U8(0x203809c4) & 0xc0)
#define TX_REQUESTS U32(0x203809b0)
extern volatile uint32_t aprs_channel_hz;
extern uint8_t aprs_beacon_ssid, aprs_tx_enabled;
uint8_t aprs_auto_beacon APRS_KEEP, aprs_beacon_interval APRS_KEEP = 3;
const uint8_t aprs_beacon_minutes[5] = {1, 3, 5, 10, 30};
static uint32_t beacon_cycle_started;
#ifdef APRS_SLOT_UI
static uint32_t last_auto_attempt;
static unsigned auto_waiting;
static struct {
    char lat[9], lon[10];
    uint32_t sampled;
    unsigned ready, speed;
    int course, last_sent;
} motion;

/* Sample the same live local fixes as the transmitted position. The native RMC
   speed/course cache can retain old values when either field is missing. */
static uint32_t smart_interval(uint32_t now)
{
    uint32_t age = now - motion.sampled;
    if (aprs_gps_fix() != LIVE_FIX) {
        motion.ready = motion.speed = 0;
        motion.last_sent = -1;
    } else if (!motion.ready || age >= 10000u) {
        char lat[9], lon[10];
        const char *coords[] = {lat, lon, motion.lat, motion.lon};
        unsigned metres;
        int bearing = -1;
        motion.speed = 0;
        if (aprs_local_position(lat, lon) == LIVE_FIX) {
            if (motion.ready && age <= 20000u && aprs_geometry(coords, 0, &metres, &bearing)) {
                /* Reject a discontinuity on reacquisition; the supported speed is 0..500 km/h. */
                if (metres * 36u <= age * 5u)
                    motion.speed = (metres * 3600u + age / 2u) / age;
                else motion.last_sent = -1;
            } else motion.last_sent = -1;
            __builtin_memcpy(motion.lat, lat, sizeof(lat));
            __builtin_memcpy(motion.lon, lon, sizeof(lon));
            motion.ready = 1;
            motion.sampled = now;
        } else motion.ready = 0;
        motion.course = bearing;
    }
    if (motion.speed < 5) return 1800000u;
    if (motion.course >= 0 && motion.last_sent >= 0) {
        unsigned turn = __builtin_abs(motion.course - motion.last_sent);
        if (turn > 180) turn = 360 - turn;
        if (turn >= 28 + 260 / motion.speed) return 60000u;
    }
    return motion.speed >= 70 ? 120000u : 8400000u / motion.speed;
}
#endif
static volatile unsigned stage;
static struct {
    uint32_t started, frequency;
    unsigned bits, cursor, remaining, phase, tone, drain;
    uint8_t data[(MAX_BEACON_FRAME*6+4)/5];
} tx;

static int dsp_tx(void)
{
    return (U8(0x203809a1) & DSP_TX) != 0;
}

static int other_tx(unsigned flags, unsigned allowed)
{
    /* The stock PTT filter decides when a raw mic sample becomes a TX request. */
    return (flags & REMOTE_REQUEST) || TX_INHIBITED || (TX_REQUESTS & ~allowed);
}

#ifdef APRS_COMBINED
/* These aliases resolve against the matching FT and SSTV link maps. */
extern volatile unsigned ft_session_state, ft_tx_stage, sstv_tx_state;
extern unsigned sstv_rx_only(void);
extern unsigned ft_tx_requested(unsigned flags), ft_tx_source(unsigned configured), ft_tx_mod_block(void);
static unsigned beacon_paused_for_ft;

static int ft_owns_radio(void)
{
    return ft_session_state || ft_tx_stage;
}
#endif

unsigned aprs_plain_fm(void)
{
#ifdef APRS_COMBINED
    if (ft_owns_radio() || sstv_tx_state || sstv_rx_only())
        return 0;
#endif
    return (U8(0x203e2128) >> 4) == 7 && !(U8(0x203e2129) & 1);
}

static int simplex_fm(unsigned frequency)
{
    unsigned bank = (U8(0x203e84c0) >> 1) & 1;
    return aprs_plain_fm() && (U8(0x203e212f + 7*bank) >> 4) == 7 &&
           !(U8(0x203e2130 + 7*bank) & 1) &&
           !((unsigned (*)(unsigned))0x2002eafc)(0) &&
           ((unsigned (*)(unsigned))0x201031dc)(0) == frequency;
}

static int coordinate(char *out, const char *raw, unsigned width, unsigned limit, char a, char b)
{
    unsigned degree = 0, minute = 0;
    for (unsigned i = 0; i < width+6; ++i) {
        unsigned digit = (unsigned)raw[i] - '0';
        if (digit > 9)
            return 0;
        if (i < width)
            degree = degree*10 + digit;
        else
            minute = minute*10 + digit;
    }
    char hemisphere = raw[width+6];
    if (degree > limit || minute >= 600000 || (degree == limit && minute) ||
        (hemisphere != a && hemisphere != b))
        return 0;
    for (unsigned i = 0; i < width+2; ++i)
        out[i] = raw[i];
    out[width+2] = '.';
    out[width+3] = raw[width+2];
    out[width+4] = raw[width+3];
    out[width+5] = hemisphere;
    return 1;
}

static void append_bit(unsigned bit)
{
    unsigned offset = tx.bits++;
    if ((offset & 7) == 0)
        tx.data[offset >> 3] = 0;
    tx.data[offset >> 3] |= bit << (offset & 7);
}

static void stuff_frame(const uint8_t *frame, unsigned length)
{
    unsigned run = 0;
    tx.bits = 0;
    for (unsigned i = 0; i < length; ++i) {
        unsigned byte = frame[i];
        for (unsigned n = 0; n < 8; ++n, byte >>= 1) {
            unsigned bit = byte & 1;
            append_bit(bit);
            run = bit ? run+1 : 0;
            if (run == 5) {
                append_bit(0);
                run = 0;
            }
        }
    }
}

static const char *prepare(const char *message)
{
    uint8_t frame[MAX_BEACON_FRAME];
    _Static_assert(sizeof(frame)*8 + sizeof(frame)*8/5 <= sizeof(tx.data)*8, "stuffed frame capacity");
    static const char destination[] = "APRS  ";
    for (unsigned i = 0; i < 6; ++i)
        frame[i] = destination[i] << 1;
    frame[6] = 0xe0;
    const volatile uint8_t *my_call = (const volatile uint8_t *)0x203e2499;
    unsigned call_size = 8, flags = 0;
    while (call_size && (my_call[call_size-1] == ' ' || !my_call[call_size-1]))
        --call_size;
    if (call_size < 3 || call_size > 6)
        return "Set My Call Sign";
    for (unsigned i = 0; i < 6; ++i) {
        unsigned ch = i < call_size ? my_call[i] : ' ';
        if (i < call_size) {
            if (ch >= 'A' && ch <= 'Z')
                flags |= 1;
            else if (ch >= '0' && ch <= '9')
                flags |= 2;
            else
                return "Set My Call Sign";
        }
        frame[7+i] = ch << 1;
    }
    if (flags != 3)
        return "Set My Call Sign";
    frame[13] = 0x60 | (aprs_beacon_ssid << 1);
    uint8_t *position = frame + 14;
    for (unsigned hops = aprs_tx_path; hops; --hops) {
        static const char wide[] = "WIDE";
        for (unsigned i = 0; i < 4; ++i)
            *position++ = wide[i] << 1;
        *position++ = (hops == 2 ? '1' : '2') << 1;
        *position++ = ' ' << 1;
        *position++ = 0x62;  /* SSID 1, reserved bits set, H and extension bits clear. */
    }
    position[-1] |= 1;
    *position++ = 3;
    *position++ = 0xf0;

    unsigned length = position - frame;
    if (message) {
        while (*message)
            frame[length++] = *message++;
    } else {
        char lat[9], lon[10];
        enum aprs_fix fix = aprs_local_position(lat, lon);
        if ((fix != LIVE_FIX && fix != MANUAL_FIX) ||
            !coordinate((char *)position+1, lat, 2, 90, 'N', 'S') ||
            !coordinate((char *)position+10, lon, 3, 180, 'E', 'W'))
            return "Check GPS position";
        position[0] = '!';
        const char *symbol = aprs_beacon_symbol();
        position[9] = symbol[0];
        position[19] = symbol[1];
        const char *comment = aprs_beacon_comment();
        length += 20;
        while (*comment)
            frame[length++] = *comment++;
    }
    aprs_track_prepared(frame+7, position, length-(position-frame), message != 0);
    unsigned crc = 0xffff;
    for (unsigned i = 0; i < length; ++i) {
        crc ^= frame[i];
        for (unsigned b = 0; b < 8; ++b)
            crc = (crc >> 1) ^ ((crc & 1) ? 0x8408 : 0);
    }
    crc ^= 0xffff;
    frame[length++] = crc;
    frame[length++] = crc >> 8;
    stuff_frame(frame, length);
    return 0;
}

static unsigned message_tag;
static const char *start(const char *message,unsigned tag)
{
    unsigned hz = U32(0x20380714);
    unsigned flags = U8(0x203806f4);
    if (!aprs_tx_enabled || !aprs_channel_hz)
        return "Set APRS RX & TX";
    if (hz != aprs_channel_hz)
        return "Tune APRS FM channel";
    if (!simplex_fm(hz))
        return "Use simplex FM";
    if (TX_INHIBITED)
        return "Radio TX inhibit";
    if (flags & REMOTE_REQUEST)
        return "Remote PTT active";
    if (stage != TX_IDLE)
        return "Beacon already active";
    if (dsp_tx() || (flags & 0x80))
        return "Radio TX active";
    if (TX_REQUESTS)
        return "Other TX request";
    if (U8(0x2038026c))
        return "APRS channel busy";
    const char *invalid = prepare(message);
    if (invalid)
        return invalid;
    message_tag=tag;
    tx.frequency = hz;
    tx.started = NOW;
    if (!message) {
        beacon_cycle_started = tx.started;
#ifdef APRS_SLOT_UI
        auto_waiting = 0;
#endif
    }
    tx.cursor = tx.remaining = tx.phase = tx.tone = tx.drain = 0;
    __atomic_store_n(&stage, TX_ARMED, __ATOMIC_RELEASE);
    return 0;
}

const char *aprs_beacon_start(void)
{
    return start(0,0);
}

#ifdef APRS_SLOT_UI
const char *aprs_start_message(const char *info,unsigned tag) { return start(info,tag); }
unsigned aprs_message_active(void) { return stage!=TX_IDLE; }
#else
const char *aprs_send_reply(const char *recipient, const char *body)
{
    char info[11+67+1+3+1];
    static unsigned serial APRS_KEEP;
    unsigned length = 0;
    while (recipient[length] && length < 9)
        ++length;
    if (!length || recipient[length])
        return "Check recipient";
    info[0] = ':';
    for (unsigned i = 0; i < 9; ++i)
        info[1+i] = i < length ? recipient[i] : ' ';
    info[10] = ':';
    length = 0;
    while (body[length]) {
        unsigned ch = (unsigned char)body[length];
        if (length == 67 || ch < 32 || ch > 126 || ch == '{' || ch == '}' || ch == '|'
            || ch == '~')
            return "Check message text";
        info[11+length++] = ch;
    }
    if (!length)
        return "Enter message text";
    char *end = info+11+length;
    *end++ = '{';
    char *id = end;
    unsigned next = (serial+1)%1000;
    *end++ = '0'+next/100;
    *end++ = '0'+next/10%10;
    *end++ = '0'+next%10;
    *end = 0;
    const char *error = start(info,1);
    if (!error) {
        serial = next;
        aprs_track_reply(recipient, id);
    }
    return error;
}
#endif

void aprs_beacon_reschedule(void)
{
    beacon_cycle_started = NOW;
#ifdef APRS_SLOT_UI
    auto_waiting = 0;
    motion.ready = motion.speed = 0;
    motion.last_sent = -1;
#endif
}

#ifdef APRS_SLOT_UI
uint32_t aprs_return_hz;
static unsigned visit_hz, visit_vfo, visit_started, visit_sent;
static unsigned observed_hz, tuned_at;

static int ordinary_vfo(unsigned hz)
{
    return !(U8(0x203ebc78)&3) && !U8(0x20387140) && !U8(0x203ebc2b) &&
           !((unsigned (*)(unsigned))0x2020e224)(0) && simplex_fm(hz);
}

/* The stock frequency keypad selects the working VFO before committing its scratch record. */
static int tune_vfo(unsigned hz)
{
    if ((((unsigned (*)(unsigned))0x2002e850)(hz)&0x80) ||
        ((unsigned (*)(unsigned,unsigned,unsigned))0x201045c4)(0,hz,7)!=hz)
        return 0;
    ((void (*)(unsigned))0x20102a7c)(0);
    ((void (*)(unsigned))0x20102c5c)(0);
    *(volatile uint32_t *)0x203e20fc=hz;
    ((void (*)(unsigned,unsigned,unsigned))0x20103d58)(0,0,1);
    return U32(0x20380714)==hz;
}

static void poll_visit(uint32_t now, unsigned hz)
{
    /* A new VFO, frequency or mode belongs to the operator. Never tune over it. */
    if (hz!=visit_hz || (U8(0x203ebc78)&7)!=visit_vfo || !aprs_plain_fm()) {
        aprs_return_hz=0;
        aprs_beacon_reschedule();
        return;
    }
    if (stage!=TX_IDLE || dsp_tx() || TX_REQUESTS || (U8(0x203806f4)&(REMOTE_REQUEST|0x80)))
        return;
    if (!ordinary_vfo(hz)) {
        aprs_return_hz=0;
        aprs_beacon_reschedule();
        return;
    }
    if (!visit_sent && aprs_channel_hz==hz && aprs_tx_enabled && aprs_auto_beacon && aprs_standby_ready()) {
        if (now-visit_started<400u) return;  /* Allow the newly selected channel's squelch to settle. */
        if (!aprs_beacon_start()) { visit_sent=1;return; }
    }
    /* A busy destination gets one short visit per interval. */
    if (!visit_sent) aprs_beacon_reschedule();
    if (tune_vfo(aprs_return_hz)) {
        observed_hz=aprs_return_hz;tuned_at=now;
        aprs_return_hz=0;
    }
}
#endif

void aprs_beacon_poll(void)
{
    uint32_t now = NOW;
#ifdef APRS_COMBINED
    if (ft_owns_radio()) {
#ifdef APRS_SLOT_UI
        aprs_return_hz=0;
#endif
        beacon_paused_for_ft = 1;
        return;
    }
    if (beacon_paused_for_ft) {
        if (aprs_plain_fm()) {
            beacon_paused_for_ft = 0;
            aprs_beacon_reschedule();
        }
        return;
    }
#endif
#ifdef APRS_SLOT_UI
    unsigned hz=U32(0x20380714);
    if (aprs_return_hz) {
        poll_visit(now,hz);
        return;
    }
    if (hz!=observed_hz) { observed_hz=hz;tuned_at=now; }
#endif
    if (!aprs_auto_beacon || !aprs_tx_enabled || !aprs_channel_hz)
        return;
    uint32_t elapsed = now - beacon_cycle_started;
    uint32_t interval =
#ifdef APRS_SLOT_UI
        aprs_beacon_interval == SMART_INTERVAL ? smart_interval(now) :
#endif
        60000u * aprs_beacon_minutes[aprs_beacon_interval];
    if (elapsed < interval
#ifdef APRS_SLOT_UI
        && !auto_waiting
#endif
    )
        return;
#ifdef APRS_SLOT_UI
    if (!aprs_plain_fm()) {
        aprs_beacon_reschedule();
        return;
    }
    /* Keep one due beacon while the channel, position or front panel is busy. */
    if (auto_waiting && now-last_auto_attempt < 1000u)
        return;
    last_auto_attempt = now;
    auto_waiting = 1;
    if (hz!=aprs_channel_hz) {
        enum aprs_fix fix = aprs_gps_fix();
        if (fix != LIVE_FIX && fix != MANUAL_FIX) return;
        if (hz && now-tuned_at>=400u && aprs_standby_ready() && ordinary_vfo(hz) && stage==TX_IDLE &&
            !dsp_tx() && !other_tx(U8(0x203806f4),0) && !(U8(0x203806f4)&0x80) && !U8(0x2038026c)) {
            visit_vfo=U8(0x203ebc78)&7;
            if (tune_vfo(aprs_channel_hz)) {
                aprs_return_hz=hz;visit_hz=aprs_channel_hz;visit_started=now;visit_sent=0;
            } else aprs_beacon_reschedule();
        }
        return;
    }
    /* start() checks the published PTT requests, just as it does for QUICK. */
    if (aprs_standby_ready())
        (void)aprs_beacon_start();
#else
    beacon_cycle_started = now;  /* Both a send and a skipped cycle start a new interval. */
    if (elapsed < 2*interval && !(U8(0x203809c4) & 1) && aprs_standby_ready())
        (void)aprs_beacon_start();
#endif
}

unsigned aprs_tx_requested(unsigned flags)
{
    unsigned current = __atomic_load_n(&stage, __ATOMIC_ACQUIRE);
#ifdef APRS_COMBINED
    if (current != TX_IDLE && ft_owns_radio()) {
        stage = TX_IDLE;
        return ft_tx_requested(flags);
    }
#endif
    if (current == TX_RELEASE) {
        if (!dsp_tx())
            stage = TX_IDLE;
        return flags;
    }
    if (current == TX_IDLE)
        return flags;
    if (!aprs_tx_enabled || aprs_channel_hz != tx.frequency || U32(0x20380714) != tx.frequency ||
        U8(0x204bab5d) != 1 || !simplex_fm(tx.frequency) || other_tx(flags, OWN_REQUEST) ||
        (current == TX_ARMED ? NOW - tx.started >= ARM_TIMEOUT_MS || (!dsp_tx() && U8(0x2038026c)) :
                               NOW - tx.started >= TX_TIMEOUT_MS || !dsp_tx())) {
        stage = TX_RELEASE;
        return flags;
    }
    return flags | REMOTE_REQUEST;  /* Original request filter still decides whether to key. */
}

unsigned aprs_tx_source(unsigned configured)
{
#ifdef APRS_COMBINED
    if (ft_owns_radio())
        return ft_tx_source(configured);
#endif
    return stage != TX_IDLE && !other_tx(U8(0x203806f4), OWN_REQUEST) ? 3 : configured;
}

static unsigned next_bit(unsigned offset)
{
    if (offset >= PREAMBLE) {
        offset -= PREAMBLE;
        if (offset < tx.bits)
            return (tx.data[offset >> 3] >> (offset & 7)) & 1;
        offset -= tx.bits;
    }
    return (0x7e >> (offset & 7)) & 1;
}

static int16_t tone(void)
{
    static const int16_t sine[61] = {
        0,314,628,942,1254,1566,1877,2187,2495,2801,3106,3408,3708,4006,4300,
        4592,4881,5166,5448,5726,6000,6270,6536,6797,7053,7305,7552,7793,8030,8260,
        8485,8704,8918,9125,9326,9520,9708,9889,10064,10231,10392,10546,10692,10831,
        10963,11087,11203,11314,11413,11507,11591,11668,11738,11799,11852,11898,
        11934,11963,11984,11996,12000
    };
    unsigned phase = tx.phase;
    tx.phase += tx.tone ? 11 : 6;
    if (tx.phase >= 240)
        tx.phase -= 240;
    unsigned half = phase >= 120 ? phase-120 : phase;
    int16_t sample = sine[half > 60 ? 120-half : half];
    return phase >= 120 ? -sample : sample;
}

unsigned aprs_tx_mod_block(void)
{
#ifdef APRS_COMBINED
    if (ft_owns_radio())
        return ft_tx_mod_block();
#endif
    if (stage == TX_IDLE || other_tx(U8(0x203806f4), OWN_REQUEST))
        return ((unsigned (*)(void))0x201f644c)();
    int16_t *pcm = (int16_t *)0x20401c14;
    unsigned n = 0;
    if (stage == TX_DRAIN && ++tx.drain >= 2)
        stage = TX_RELEASE;  /* Retire both native DMA banks before releasing PTT. */
    if ((stage == TX_ARMED || stage == TX_SOUND) && dsp_tx()) {
        stage = TX_SOUND;
        while (n < PCM_FRAMES) {
            if (!tx.remaining) {
                if (tx.cursor == PREAMBLE + tx.bits + TAIL) {
                    aprs_track_transmitted(tx.frequency);
#ifdef APRS_SLOT_UI
                    if (!message_tag && aprs_beacon_interval == SMART_INTERVAL)
                        motion.last_sent = motion.speed >= 5 ? motion.course : -1;
                    if (message_tag) aprs_message_finished(message_tag);
#endif
                    stage = TX_DRAIN;
                    break;
                }
                tx.tone ^= !next_bit(tx.cursor++);
                tx.remaining = BIT_SAMPLES;
            }
            pcm[n++] = tone();
            --tx.remaining;
        }
    }
    while (n < PCM_FRAMES)
        pcm[n++] = 0;
    return 4;  /* Select the original full-rate WLAN MOD scaling. */
}
