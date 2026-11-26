/* J140 FT station. The UI chooses the message; the native request builder
   grants RF and the 48 kHz SSI consumer supplies the modulation clock. */
#include "j140_tx.h"
#include "ft8/encode.h"
#include <string.h>
#include <stdint.h>
#include <stdatomic.h>
#include "ftx_gauss.h"
#include "ft_panel_words.h"

#define U8(a) (*(volatile uint8_t *)(a))
#define U32(a) (*(volatile uint32_t *)(a))
#define NOW U32(0x20381e08)
enum { CQ, LOCATOR, REPORT, R_REPORT, END_RR, END_73 };
enum { IDLE, WAIT, KEY, SOUND, DRAIN, RELEASE };
struct Prefs {
    char call[12], grid[5];
    uint8_t parity, follow, automatic;
    uint16_t hz;
    int8_t utc_q;
};
static struct Prefs pref = {.hz = 1500, .follow = 1};
static char partner[12], edit[12], outgoing[36], suffix[8];
static unsigned kind, parity, audio_hz, attempts, waiting_slot, tx_frequency, last_air;
static unsigned peer_parity, peer_hz;
static int report;
static _Atomic unsigned stage;
static unsigned sequence_on, has_sent, config_sequence;
static uint8_t tones[FT4_NN];
static unsigned symbol, sample, phase, draining, start_tick, deadline, progress_at;
static const char *notice;
unsigned ft_page;
unsigned ft_auto_armed;
int ft_selected=-1;
static unsigned held_slot, auto_open, from_list, picked_slot, checked_partner;
static struct DisplayRow inspected;
enum { NORMAL, PICK_MESSAGE, OTHER_CALLS };
enum { IN_CONTACT, FINAL_SENT, LOG_PENDING, LOG_SAVED };
static unsigned overlay, outcome, receipt_index, others, other_index, caller_slot;
static char callers[48][7]; /* One decoder history window, unique standard senders. */
static void reset_contact(void){
    overlay=NORMAL; outcome=IN_CONTACT; others=other_index=0; caller_slot=~0u;
}
static unsigned setup_parent;
extern unsigned ftx_rtc;
__attribute__((section(".ftx_controls"),noinline)) static int recent(unsigned slot) {
    unsigned now, ms, day=ftx_ft4?11520:5760;
    return ft_clock(&now,&ms) && (now+day-slot%day)%day<=1;
}
static const char *const names[] = {"CQ", Z_locator, Z_report, Z_rreport, "RR73", "73"};
__attribute__((noinline)) static void select_channel(void) {
    parity = kind == CQ ? pref.parity : peer_parity;
    audio_hz = kind != CQ && pref.follow && peer_hz >= 200 && peer_hz <= 2800 ? peer_hz : pref.hz;
}

static unsigned period(void) { return ftx_ft4 ? 7500 : 15000; }
static int is_call(const char *s) {
    size_t n = strlen(s);
    return n >= 3 && n <= 6 && pack_basecall(s, n) >= 0;
}
static int is_grid(const char *s) {
    return strlen(s) == 4 && s[0] >= 'A' && s[0] <= 'R' && s[1] >= 'A' && s[1] <= 'R' &&
           s[2] >= '0' && s[2] <= '9' && s[3] >= '0' && s[3] <= '9' && strcmp(s, "RR73");
}
static char *copy(char *dst, const char *s) {
    while ((*dst = *s++))
        ++dst;
    return dst;
}
static char *digits(char *p, unsigned n) {
    if (n >= 10)
        p = digits(p, n / 10);
    *p++ = '0' + n % 10;
    *p = 0;
    return p;
}
#include "j140_log.h"
static _Atomic unsigned log_complete, return_rx;
static void consume_complete(void){
    if(!atomic_exchange(&log_complete,0))return;
    struct Contact *q=&journal.current;
    if(q->on[0] && utc_stamp(q->off) && journal.count<LOG_QUEUE){
        receipt_index=(journal.head+journal.count)%LOG_QUEUE;
        journal.pending[receipt_index]=*q; outcome=LOG_PENDING;
        journal.count++;notice=Z_pending;
    }else {outcome=FINAL_SENT;notice="Check UTC date / SD";}
    q->on[0]=0;checked_partner=0;
    view_invalidate();
}
__attribute__((section(".ftx_controls"),noinline)) static void make_message(void) {
    char *p = suffix;
    suffix[0] = 0;
    if (kind == CQ || kind == LOCATOR) {
        if (pref.grid[0])
            copy(suffix, pref.grid);
        else
            ft_local_grid(suffix);
    } else if (kind == REPORT || kind == R_REPORT) {
        if (kind == R_REPORT)
            *p++ = 'R';
        *p++ = report < 0 ? '-' : '+';
        unsigned v = report < 0 ? -report : report;
        *p++ = '0' + v / 10;
        *p++ = '0' + v % 10;
        *p = 0;
    } else
        copy(suffix, kind == END_RR ? "RR73" : "73");
    p = copy(outgoing, kind == CQ ? "CQ" : partner);
    *p++ = ' ';
    p = copy(p, pref.call);
    if (*suffix) {
        *p++ = ' ';
        copy(p, suffix);
    }
}
static const char *foreign_tx(void) {
    unsigned own = atomic_load(&stage) >= KEY ? 0x8000u : 0u;
    unsigned flags = U8(0x203806f4);
    /* The debounced microphone request precedes DSP TX acknowledgement. */
    if (U8(0x203809c4) & 0xc1) return "Radio TX inhibit";
    if (flags & 0x20) return "Remote PTT";
    if (U32(0x203809b0) & ~own) return "Other TX request";
    if (!own && ((flags & 128) || (U8(0x203809a1) & 16))) return "Radio TX active";
    return 0;
}
__attribute__((section(".ftx_controls"),noinline)) static int mode_ok(void) {
    unsigned bank = (U8(0x203e84c0) >> 1) & 1;
    return U8(0x204bab5d)==1 && (U8(0x203e2128) >> 4) == 1 && (U8(0x203e2129) & 1) &&
           (U8(0x203e212f + bank * 7) >> 4) == 1 && (U8(0x203e2130 + bank * 7) & 1) &&
           U32(0x20380714) == tx_frequency;
}
static void halt(const char *why) {
    ft_auto_armed=0;
    sequence_on = has_sent = 0;
    unsigned s = atomic_load(&stage);
    atomic_store(&stage, s >= KEY ? RELEASE : IDLE);
    notice = why;
}
static int encode(void) {
    make_message();
    if (!is_call(pref.call)) {
        notice = "Set MY CALL";
        return 0;
    }
    if (kind != CQ && !is_call(partner)) {
        notice = "Select a decoded call";
        return 0;
    }
    if ((kind == LOCATOR || kind == CQ) && !is_grid(suffix)) {
        notice = "Set GRID or GPS position";
        return 0;
    }
    ftx_message_t msg;
    char check[FTX_MAX_MESSAGE_LENGTH];
    ftx_message_offsets_t fields;
    if (ftx_message_encode_std(&msg, 0, kind == CQ ? "CQ" : partner, pref.call, suffix) !=
            FTX_MESSAGE_RC_OK ||
        ftx_message_decode(&msg, 0, check, &fields) != FTX_MESSAGE_RC_OK ||
        strcmp(check, outgoing)) {
        notice = "Message cannot be encoded";
        return 0;
    }
    if (ftx_ft4)
        ft4_encode(msg.payload, tones);
    else
        ft8_encode(msg.payload, tones);
    return 1;
}
int ft_need_early_decode(unsigned slot) { return ft_page==FT_QSO && has_sent && !outcome && ((slot ^ parity) & 1); }
static int arm_next(unsigned response_slot) {
    unsigned ms;
    if (!ft_listen() || !ft_clock(&waiting_slot, &ms)) {
        notice = "Waiting for UTC";
        return 0;
    }
    if(!mode_ok()){notice="Check TX VFO USB-D";return 0;}
    if(((unsigned (*)(unsigned))0x201031dc)(0)!=tx_frequency){notice="Check split / TX frequency";return 0;}
    notice=foreign_tx();
    if(notice)return 0;
    if(journal.count==LOG_QUEUE){notice=Z_pending;return 0;}
    if (!encode())
        return 0;
    struct Contact *q=&journal.current;
    if(!q->on[0] || (kind!=CQ && strcmp(q->dx,partner)) || strcmp(q->own,pref.call)){
        checked_partner=0;
        char previous_grid[5];copy(previous_grid,q->grid);
        memset(q,0,sizeof(*q));utc_stamp(q->on);copy(q->own,pref.call);
        if(kind!=CQ){copy(q->dx,partner);copy(q->grid,previous_grid);}
        if(pref.grid[0])copy(q->mygrid,pref.grid);else ft_local_grid(q->mygrid);
    }
    q->freq=tx_frequency+audio_hz;q->band=log_band(tx_frequency);q->mode=ftx_ft4;
    if(kind==REPORT||kind==R_REPORT)copy(q->sent,suffix+(kind==R_REPORT));
    /* A just-decoded response may still use this edge before native keying.
       Ordinary button presses continue to select a future slot. */
    if(response_slot!=~0u && ms<=200 && (waiting_slot&1)==parity &&
       waiting_slot==(response_slot+1)%(86400000/period()))waiting_slot=response_slot;
    deadline = NOW + 2 * period() + 351;
    notice = 0;
    atomic_store(&stage, WAIT);
    return 1;
}
static int before(unsigned a, unsigned b) { return (int32_t)(a - b) < 0; }
unsigned ft_tx_requested(unsigned flags) {
    unsigned s = atomic_load(&stage);
    if (s == RELEASE && !(U8(0x203809a1) & 16))
        atomic_store(&stage, IDLE);
    if (s == IDLE || s == RELEASE)
        return ((unsigned (*)(unsigned))0x20376320)(flags);
    const char *busy=foreign_tx();
    if (!mode_ok() || busy || !ft_listen()) {
        halt(busy ? busy : "TX stopped");
        return flags;
    }
    if (s == WAIT) {
        unsigned slot, ms;
        if (!ft_clock(&slot, &ms)) {
            halt("UTC lost");
            return flags;
        }
        if (!before(NOW, deadline)) {
            halt("TX missed slot");
            return flags;
        }
        if(slot==waiting_slot || (slot&1)!=parity)return flags;
        /* Leave at least 150 ms for the native grant before the 500 ms audio edge. */
        if(ms>350){halt("TX slot missed");return flags;}
        if (((unsigned (*)(unsigned))0x201031dc)(0) != tx_frequency) {
            halt("TX frequency changed");
            return flags;
        }
        last_air = slot;
        start_tick = NOW - ms + 500;
        deadline = start_tick + (ftx_ft4 ? 5040 : 12640) + 160;
        symbol = sample = phase = draining = 0;
        progress_at = NOW;
        if(!atomic_compare_exchange_strong(&stage,&s,KEY))return flags;
    } else if (!before(NOW, deadline) || (s == KEY && !before(NOW, start_tick + 100)) ||
               (s >= SOUND && (!(U8(0x203809a1) & 16) || NOW - progress_at > 150))) {
        halt(s==KEY ? ((U32(0x203809b0)&0x8000)?"No DSP TX ack":"Radio denied TX") : "TX timing lost");
        return flags;
    }
    return flags | 32;
}
__attribute__((section(".ftx_controls"))) unsigned ft_tx_source(unsigned original) {
    if (atomic_load(&stage) >= KEY)
        return 3;
    return ((unsigned (*)(unsigned))0x2037625c)(original);
}
static int16_t tone_sample(void) {
    const unsigned span = ftx_ft4 ? 2304 : 7680, count = ftx_ft4 ? FT4_NN : FT8_NN;
    const uint16_t *weight = ftx_gauss[ftx_ft4 != 0];
    unsigned i = sample / (ftx_ft4 ? 36 : 120);
    int current = tones[symbol], left = tones[symbol ? symbol - 1 : symbol],
        right = tones[symbol + 1 < count ? symbol + 1 : symbol];
    int q = current * 32768 + (left - current) * weight[i] + (right - current) * weight[63 - i];
    unsigned inc = (unsigned)(((uint64_t)(unsigned)q * (ftx_ft4 ? 58254u : 17476u)) >> 10);
    /* q/32768 tones spaced by 48000/span Hz, in a 32-bit phase accumulator. */
    phase += audio_hz * 89478u + inc;
    unsigned pos = phase >> 24, k = pos & 63;
    const int16_t *wave = (const int16_t *)0x2037a874;
    int out = wave[pos & 64 ? 64 - k : k];
    if (pos & 128)
        out = -out;
    unsigned ramp = ftx_ft4 ? span : span / 8;
    unsigned edge = symbol == 0 ? sample : symbol == count - 1 ? span - 1 - sample : ramp;
    if (edge < ramp) {
        int v = wave[edge * 64 / ramp];
        /* Exact squared ramp, split at the first division to fit 32 bits. */
        unsigned t=(unsigned)(out<0?-out:out)*(unsigned)v;
        int level=(int)((t/13000*v + (t%13000)*v/13000)/13000);
        out=out<0?-level:level;
    }
    if (++sample == span) {
        sample = 0;
        ++symbol;
    }
    return out;
}
unsigned ft_tx_mod_block(void) {
    unsigned s = atomic_load(&stage);
    if (s < KEY)
        return ((unsigned (*)(void))0x20376f10)();
    int16_t *out = (int16_t *)0x20401c14;
    memset(out, 0, 72);
    if (s == RELEASE)
        return 4;
    if (!mode_ok() || foreign_tx() || !before(NOW, deadline)) {
        halt("TX stopped");
        return 4;
    }
    if (s == KEY) {
        if (before(NOW, start_tick) || !(U8(0x203809a1) & 16))
            return 4;
        if (!before(NOW, start_tick + 100)) {
            halt("TX missed slot");
            return 4;
        }
        if(!atomic_compare_exchange_strong(&stage,&s,SOUND))return 4;
    } else if (!(U8(0x203809a1) & 16)) {
        halt("TX stopped");
        return 4;
    }
    progress_at = NOW;
    if (s == DRAIN) {
        if (++draining >= 2 && atomic_compare_exchange_strong(&stage,&s,RELEASE)) {
            if(checked_partner && (kind==END_RR||kind==END_73)) atomic_store(&log_complete,1);
            if(kind==END_RR || kind==END_73)atomic_store(&return_rx,1);
            has_sent = 1;
            ++attempts;
        }
    } else {
        unsigned n = 0, count = ftx_ft4 ? FT4_NN : FT8_NN;
        while (n < 36 && symbol < count)
            out[n++] = tone_sample();
        if (atomic_load(&stage) != SOUND)
            memset(out, 0, 72);
        else if (symbol == count){
            unsigned playing=SOUND;
            atomic_compare_exchange_strong(&stage,&playing,DRAIN);
        }
    }
    return 4;
}
/* Two fixed SD records keep the last saved station intact on a short write.
   Only operator preferences are restored. Arming is always session-local. */
struct Record {
    uint32_t magic, seq;
    struct Prefs p;
    uint32_t sum;
};
static uint32_t checksum(const struct Record *r) {
    const uint8_t *p = (const uint8_t *)r;
    uint32_t h = 2166136261u;
    for (unsigned i = 0; i < __builtin_offsetof(struct Record, sum); i++)
        h = (h ^ p[i]) * 16777619u;
    return h;
}
__attribute__((noinline,section(".ftx_controls"))) static int record_io(struct Record *r, unsigned bank, int write) {
    if (U8(0x20380172) != 3)
        return 0;
    char path[] = "C:\\IC-705\\FTX0.CFG";
    path[13] = (char)('0' + bank);
    int fd;
    unsigned n = 0;
    if (((int (*)(const char *, unsigned, int *))0x2023fec8)(path, write ? 0x201 : 0, &fd))
        return 0;
    uintptr_t fn = write ? 0x2023ff18 : 0x2023ff00;
    int rc = ((int (*)(int, void *, unsigned, unsigned *))fn)(fd, r, sizeof(*r), &n);
    return !((int (*)(int))0x2023fee4)(fd) && !rc && n == sizeof(*r);
}
static int valid(const struct Record *r) {
    return (r->magic == 0x31585446 || r->magic == 0x32585446) && r->sum == checksum(r) && !r->p.call[11] && !r->p.grid[4] &&
           (!r->p.call[0] || is_call(r->p.call)) && (!r->p.grid[0] || is_grid(r->p.grid)) &&
           r->p.parity <= 1 && r->p.follow <= 1 && r->p.automatic <= 1 && r->p.hz >= 200 &&
           r->p.hz <= 2800;
}
__attribute__((section(".tx_clock"),noinline)) static void save_prefs(void) {
    struct Record r = {.magic = 0x32585446, .seq = config_sequence + 1, .p = pref};
    r.sum = checksum(&r);
    if (record_io(&r, r.seq & 1, 1)) {
        config_sequence = r.seq;
        notice = "Saved on SD";
    } else
        notice = "Applied for this session";
}
__attribute__((noinline,section(".ftx_controls"))) void ft_station_open(void) {
    struct Record r;
    for (unsigned i = 0; i < 2; ++i)
        if (record_io(&r, i, 0) && valid(&r) && (int32_t)(r.seq - config_sequence) > 0) {
            pref = r.p;
            if(r.magic==0x31585446 || pref.utc_q < -48 || pref.utc_q>56)pref.utc_q=0;
            config_sequence = r.seq;
        }
    reset_contact();ft_page = FT_LIST;
    atomic_store(&return_rx,0);ft_auto_armed=from_list=checked_partner=0;ft_selected=-1;
    kind = CQ;
    partner[0] = 0;
    parity = pref.parity;
    audio_hz = pref.hz;
    has_sent = sequence_on = attempts = 0;
    notice = 0;
}
void ft_station_close(void) {
    consume_complete();
    halt(0);journal.current.on[0]=0;
    ft_page = FT_LIST;
    has_sent = 0;
}
static int parse_report(const char *s) {
    return (s[0] == '+' || s[0] == '-') && s[1] >= '0' && s[1] <= '9' && s[2] >= '0' &&
           s[2] <= '9' && !s[3];
}
int ft_row_eligible(const struct DisplayRow *r) {
    if(!r || ft_is_history() || !r->flag || r->db==-128 || !recent(r->slot))return 0;
    const char *from=r->text+r->flag-1;
    unsigned len=strcspn(from," ");
    if(len<3 || len>6 || (!strncmp(pref.call,from,len)&&!pref.call[len]))return 0;
    char call[8];memcpy(call,from,len);call[len]=0;
    if(!is_call(call))return 0;
    if(from==r->text+3 && !strncmp(r->text,"CQ ",3))return 1;
    unsigned n=strlen(pref.call);
    if(!n || strncmp(r->text,pref.call,n) || r->text[n]!=' ' || from[len]!=' ')return 0;
    const char *extra=from+len+1;
    return is_grid(extra)||parse_report(extra)||
        (has_sent && !strcmp(partner,call) &&
        ((kind==REPORT && *extra=='R' && parse_report(extra+1))||
         (kind==R_REPORT && (!strcmp(extra,"RR73") || !strcmp(extra,"RRR")))));
}
__attribute__((section(".tx_clock"),noinline)) void ft_receive_row(const struct DisplayRow *r, int selected) {
    consume_complete();
    unsigned first_auto=!selected && ft_auto_armed;
    if(first_auto && r) {
        if(r->slot%(ftx_ft4?11520u:5760u)==held_slot || !recent(r->slot) || !ft_row_eligible(r) || (!auto_open && !strncmp(r->text,"CQ ",3)) ||
           ft_worked(r->text+r->flag-1))return;
        selected=1;
    }
    if (!r || !r->flag || (!selected && (ft_page!=FT_QSO || !recent(r->slot))))
        return;
    const char *sender = r->text + r->flag - 1;
    unsigned len = strcspn(sender, " ");
    if (!len || len > 6 || r->db == -128) {
        if (selected)
            notice = "No standard call or report";
        return;
    }
    char who[8];
    memcpy(who, sender, len);
    who[len] = 0;
    if (!is_call(who) || !strcmp(who, pref.call))
        return;
    const char *extra = sender + len;
    if (*extra == ' ')
        ++extra;
    int to_me = pref.call[0] && !strncmp(r->text, pref.call, strlen(pref.call)) &&
                r->text[strlen(pref.call)] == ' ';
    if(!selected && to_me && kind!=CQ && !outcome && r->slot==caller_slot &&
       strcmp(who,partner) && (is_grid(extra)||parse_report(extra))){
        unsigned i=0;
        while(i<others && strcmp(callers[i],who))++i;
        if(i==others && others<48){copy(callers[others++],who);view_invalidate();}
        return;
    }
    unsigned day_slots=86400000/period(),rx_slot=r->slot%day_slots;
    unsigned elapsed=(day_slots+rx_slot-last_air)%day_slots;
    /* A parked manual QSO may hear the same peer repeat on a later RX turn. */
    if (!selected && (!has_sent || outcome || !to_me || !mode_ok() || (kind==CQ && !sequence_on) ||
        (kind != CQ && strcmp(partner,who)) || stage>=KEY ||
        (elapsed!=1 && (sequence_on || !(elapsed&1) || elapsed>=day_slots/2))))
        return;
    unsigned next = LOCATOR;
    if (to_me) {
        if (is_grid(extra))
            next = REPORT;
        else if (parse_report(extra))
            next = R_REPORT;
        else if (*extra == 'R' && parse_report(extra + 1))
            next = END_RR;
        else if (!strcmp(extra, "RR73") || !strcmp(extra, "RRR"))
            next = END_73;
        else if (!strcmp(extra, "73")) {
            if (!selected && !strcmp(partner, who))
                halt("QSO complete");
            return;
        } else
            return;
    } else if (strncmp(r->text, "CQ ", 3))
        return;
    if (!selected) {
        if ((kind==CQ && ft_worked(sender)==1) || (kind==LOCATOR && next!=R_REPORT) ||
            (kind==REPORT && next!=END_RR) || (kind==R_REPORT && next!=END_73) || (kind != CQ && next <= kind))
            return;
        unsigned queued=WAIT;
        if(!atomic_compare_exchange_strong(&stage,&queued,IDLE) && queued!=IDLE)return;
    } else if (stage != IDLE)
        return;
    if(selected){reset_contact();tx_frequency=U32(0x20380714);}
    else if(kind==CQ)caller_slot=r->slot;
    overlay=NORMAL;
    checked_partner = (next==END_RR || next==END_73) && has_sent && (elapsed==1 || (!selected && !sequence_on)) && !strcmp(partner,who) &&
        ((kind==REPORT && next==END_RR)||(kind==R_REPORT && next==END_73));
    struct Contact *q=&journal.current;
    if(selected || !q->on[0] || strcmp(q->dx,who)){
        memset(q,0,sizeof(*q));copy(q->dx,who);copy(q->own,pref.call);utc_stamp(q->on);
        if(pref.grid[0])copy(q->mygrid,pref.grid);else ft_local_grid(q->mygrid);
    }
    if(is_grid(extra))copy(q->grid,extra);
    if(to_me && (parse_report(extra)||(*extra=='R'&&parse_report(extra+1))))copy(q->rcvd,extra+(*extra=='R'));
    inspected=*r;
    copy(partner, who);
    peer_parity = 1 - (r->slot & 1);
    peer_hz = r->hz;
    report = r->db < -50 ? -50 : r->db > 49 ? 49 : r->db;
    kind = next;
    attempts = has_sent = 0;
    notice = 0;
    select_channel();
    if (selected) {
        sequence_on = 0;
        ft_page = FT_QSO;
        from_list=1;picked_slot=r->slot;
        if(first_auto){ft_auto_armed=0;tx_frequency=U32(0x20380714);if(arm_next(r->slot%(86400000/period())))sequence_on=pref.automatic;}
    } else if (!sequence_on || !pref.automatic) {
        picked_slot=r->slot;
        from_list=2;
        sequence_on=0;
    } else if (!arm_next(r->slot%(86400000/period())))sequence_on=0;
    view_invalidate();
}
static const char *tx_status(void) {
    if (stage == WAIT)
        return parity ? "WAIT TX B" : "WAIT TX A";
    if (stage == KEY)
        return "KEYING";
    if (stage == SOUND || stage == DRAIN)
        return "ON AIR";
    if (stage == RELEASE)
        return "RELEASING";
    if (outcome==LOG_SAVED)return Z_saved;
    if (outcome==LOG_PENDING)return Z_pending;
    if (notice)return notice;
    if (outcome)return Z_complete;
    if(has_sent)return Z_waiting;
    if(!is_call(pref.call))return Z_call " ?  > SET";
    if((kind==CQ || kind==LOCATOR) && !is_grid(suffix))return Z_grid " ?  > SET";
    return Z_idle;
}
void ft_station_tick(void) {
    consume_complete();log_poll();
    /* A skipped native request callback must not leave an apparently armed station. */
    unsigned active=atomic_load(&stage);
    if(active==WAIT && (!before(NOW,deadline) || (U8(0x203809c4)&0xc0)))
        halt((U8(0x203809c4)&0xc0)?"Radio TX inhibit":"No TX poll in slot");
    if(active==KEY && !before(NOW,start_tick+100))
        halt((U32(0x203809b0)&0x8000)?"No DSP TX ack":"Radio denied TX");
    if(active==RELEASE && !(U8(0x203809a1)&16) && !(U32(0x203809b0)&0x8000))
        atomic_store(&stage,IDLE);
    if(stage==IDLE && atomic_exchange(&return_rx,0) && ft_page==FT_QSO){
        sequence_on=0;if(!outcome)outcome=FINAL_SENT;view_invalidate();
    }
    unsigned check_slot,check_ms;
    if(ft_auto_armed && (!mode_ok() || foreign_tx() || !ft_listen() || !ft_clock(&check_slot,&check_ms))){halt("TX stopped");view_invalidate();}
    if (!sequence_on || stage != IDLE || !has_sent)
        return;
    if (kind == END_RR || kind == END_73) {
        sequence_on = 0;
        notice = "QSO complete";
        return;
    }
    unsigned slot, ms, slots = 86400000 / period();
    if (!mode_ok() || foreign_tx()) {
        halt("TX stopped");
        return;
    }
    if (!ft_clock(&slot, &ms)) {
        if (NOW - progress_at > 2500)
            halt("UTC lost");
        return;
    }
    unsigned elapsed = (slot + slots - last_air) % slots;
    /* Reserve the next own slot while the opposite slot is listening.
       A decoded directed response may replace WAIT until the native grant. */
    if (!elapsed || (attempts >= 3 && elapsed == 1))
        return;
    if (attempts >= 3) {
        halt("No reply - stopped");
        return;
    }
    if (!arm_next(~0u))
        sequence_on = 0;
}
static void show(unsigned p) {
    ft_page = p;
    view_invalidate();
}
static int edit_field(void) {
    if (ft_page == FT_CALL && !is_call(edit)) {
        notice = "Enter standard call";
        return 0;
    }
    if (ft_page == FT_GRID && edit[0] && !is_grid(edit)) {
        notice = "Enter 4-character grid";
        return 0;
    }
    copy(ft_page == FT_CALL ? pref.call : pref.grid, edit);
    notice = 0;
    show(FT_SETUP);
    return 1;
}
static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
int ft_panel_touch(unsigned x, unsigned y) {
    if (x >= 478 || (x >= 417 && y >= 268))
        return 0;
    if(ft_page==FT_LIST){
        if(x<397 && y>=102 && !ft_auto_armed)return ft_choose_row(y);
        if(x<399 || x>=476 || y<89 || y>=266 || (y-89)%36>=33)return 0;
        unsigned key=(y-89)/36;
        const struct DisplayRow *r=ft_choice_row();
        if(ft_auto_armed){if(!key){halt(0);return 1;}return 0;}
        if(!key){
            notice=0;
            if(r){inspected=*r;if(!ft_row_eligible(r)){show(FT_INFO);return 1;}ft_receive_row(r,1);}
            else {reset_contact();memset(&journal.current,0,sizeof(journal.current));kind=CQ;partner[0]=0;attempts=has_sent=checked_partner=from_list=0;select_channel();show(FT_QSO);}
        }else if(key==1){
            if(ft_is_history())ft_return_live();
            else if(r) ft_selected=-1;
            else show(FT_AUTO);
        }else if(key==2){
            if(x>=436 && x<439)return 0;
            unsigned newer=x>=439;if(!ft_history_enabled(newer))return 0;ft_history_action(newer);
        }else if(key==3)ft_history_action(2);
        else show(FT_MENU);
        return 1;
    }
    if(ft_page>=FT_MENU){
        if(x>=399 && x<476 && y>=233 && y<266){show(FT_LIST);return 1;}
        if(ft_page==FT_MENU){
            if(x>=399 && x<476 && y>=197 && y<230){ft_exit();return 1;}
            if(x>=395 || y<111 || y>=266)return 0;
            const uint8_t pages[]={FT_LOG,FT_TIME,FT_SETUP,FT_AUTO};
            if((y-111)/31==4){pref.automatic^=1;save_prefs();return 1;}
            setup_parent=FT_MENU;show(pages[(y-111)/31]);if(ft_page==FT_LOG){journal.offset=0;journal.reset=1;}return 1;
        }
        if(ft_page==FT_TIME && x<354 && y>=177 && y<208){
            int q=pref.utc_q+(x<179?-1:1);if(q < -48 || q>56)return 0;
            pref.utc_q=q;save_prefs();return 1;
        }
        if(ft_page==FT_TIME && x<395 && y>=111 && y<173){ft_set_time(y>=142);return 1;}
        if(ft_page==FT_AUTO){
            if(x<395 && y>=111 && y<142){auto_open^=1;return 1;}
            if(x>=399 && y>=89 && y<122){
                unsigned sl,ms;if(!ft_listen() || !is_call(pref.call)){setup_parent=FT_AUTO;show(FT_SETUP);return 1;}
                if(!ft_clock(&sl,&ms)){show(FT_TIME);return 1;}
                tx_frequency=U32(0x20380714); if(!mode_ok() || foreign_tx())return 0;
                ft_auto_armed=1;held_slot=sl;memset(&journal.current,0,sizeof(journal.current));has_sent=0;ft_return_live();show(FT_LIST);return 1;
            }
        }
        if(ft_page==FT_LOG)return log_touch(x,y);
        return 0;
    }
    if (ft_page == FT_CALL || ft_page == FT_GRID) {
        if (x >= 417) {
            if (y >= 228) {
                notice = 0;
                show(FT_SETUP);
                return 1;
            }
            if (y >= 156 && y < 188) {
                edit_field();
                return 1;
            }
            if (y >= 121 && y < 152) {
                size_t n = strlen(edit);
                if (n)
                    edit[n - 1] = 0;
                return n != 0;
            }
        }
        if (x >= 3 && x < 354 && y >= 127 && y < 259) {
            unsigned k = ((y - 127) / 33) * 9 + (x - 3) / 39;
            size_t n = strlen(edit);
            if ((x - 3) % 39 < 37 && (y - 127) % 33 < 30 && k < 36 &&
                n < (ft_page == FT_CALL ? 6 : 4)) {
                edit[n] = alphabet[k];
                edit[n + 1] = 0;
                notice = 0;
                return 1;
            }
        }
        return 0;
    }
    if (ft_page == FT_SETUP) {
        if (x >= 417 && y >= 228) {
            select_channel();
            save_prefs();
            show(setup_parent);
            return 1;
        }
        if (x >= 357 || x < 4 || y < 116 || y >= 248)
            return 0;
        if ((x - 4) % 177 >= 172 || (y - 116) % 33 >= 30)
            return 0;
        unsigned key = (y - 116) / 33 * 2 + (x >= 181);
        switch (key) {
        case 0:
            copy(edit, pref.call);
            show(FT_CALL);
            break;
        case 1:
            copy(edit, pref.grid);
            show(FT_GRID);
            break;
        case 2:
            pref.parity ^= 1;
            parity = pref.parity;
            break;
        case 3:
            pref.follow ^= 1;
            break;
        case 4:
            if (pref.hz == 200)
                return 0;
            pref.hz = pref.hz < 250 ? 200 : pref.hz - 50;
            audio_hz = pref.hz;
            break;
        case 5:
            if (pref.hz == 2800)
                return 0;
            pref.hz = pref.hz > 2750 ? 2800 : pref.hz + 50;
            audio_hz = pref.hz;
            break;
        case 6:
            pref.automatic ^= 1;
            break;
        case 7:
            pref.grid[0] = 0;
            break;
        }
        notice = 0;
        return 1;
    }
    if (x >= 399 && x < 476 && y >= 233 && y < 266) {
        consume_complete();atomic_store(&return_rx,0);
        halt(0);has_sent=0;reset_contact();ft_return_live();
        show(FT_LIST);
        return 1;
    }
    if (x >= 399 && x < 476 && y >= 89 && y < 122 && stage!=RELEASE && (stage != IDLE || sequence_on)) {
        halt(stage==WAIT || stage==IDLE?Z_canceled:Z_cutdone);
        overlay=NORMAL;view_invalidate();
        has_sent = 0;
        return 1;
    }
    if (x>=399 && x<476 && y>=161 && y<194 && others && !outcome) {
        other_index=overlay==OTHER_CALLS?(other_index+1)%others:0;
        overlay=OTHER_CALLS;return 1;
    }
    if(overlay==OTHER_CALLS && x>=399 && x<476 && y>=125 && y<158){overlay=NORMAL;return 1;}
    if (stage != IDLE || sequence_on || outcome)return 0;
    if (x >= 399 && x < 476 && y >= 125 && y < 158) {
        if(partner[0]){
            overlay=overlay==PICK_MESSAGE?NORMAL:PICK_MESSAGE;
            return 1;
        }
        setup_parent=FT_QSO;show(FT_SETUP);
        notice = 0;
        return 1;
    }
    if(!has_sent && partner[0] && x>=399 && x<476 && y>=197 && y<230){
        overlay=NORMAL;setup_parent=FT_QSO;show(FT_SETUP);return 1;
    }
    if (x >= 399 && x < 476 && y >= 89 && y < 122 && overlay==NORMAL) {
        make_message();
        if(!is_call(pref.call) || ((kind==CQ || kind==LOCATOR) && !is_grid(suffix))){
            setup_parent=FT_QSO;
            notice=!is_call(pref.call)?Z_call " ?":Z_grid " ?";
            show(FT_SETUP);return 1;
        }
        if(kind!=CQ && from_list==1 && !recent(picked_slot)){notice="Select a fresh decode";return 1;}
        if(partner[0] && tx_frequency!=U32(0x20380714)){notice="TX frequency changed";return 1;}
        tx_frequency = U32(0x20380714);
        if (arm_next(from_list==2?picked_slot%(86400000/period()):~0u)){
            attempts=has_sent=from_list=0;
            sequence_on=(kind==CQ || pref.automatic);
        }
        return 1;
    }
    if (overlay==PICK_MESSAGE && x >= 4 && x < 358 && y >= 171 && y < 239) {
        if ((x - 4) % 118 >= 114 || (y - 171) % 34 >= 31)
            return 0;
        unsigned k = (y - 171) / 34 * 3 + (x - 4) / 118;
        if (!partner[0])
            return 0;
        if(k!=kind){checked_partner=0;has_sent=0;caller_slot=~0u;}
        if(k==CQ){reset_contact();partner[0]=0;from_list=0;journal.current.on[0]=0;}
        overlay=NORMAL;kind = k;
        notice = 0;
        select_channel();
        return 1;
    }
    return 0;
}
__attribute__((section(".ftx_controls"),noinline)) static void value_key(const char *title, const char *value, unsigned x, unsigned y) {
    char s[32];
    copy(copy(s, title), value);
    ft_key(s, x, y, 172, 30);
}
__attribute__((section(".tx_clock"), noinline)) static void slot_label(void) {
    unsigned slot, ms;
    unsigned s_now = atomic_load(&stage);
    if (s_now >= KEY && s_now <= DRAIN) {
        slot = last_air;
        ms = NOW - (start_tick - 500);
    } else if (!ft_clock(&slot, &ms)) {
        if(ft_page==FT_QSO)ft_slot_bar(0,~0u);
        return;
    }
    if(ft_page==FT_QSO)ft_slot_bar(slot,ms);
    char s[] = "A  00.0s";
    if(s_now==WAIT){
        unsigned distance=(waiting_slot+1+(((waiting_slot+1)&1)!=parity)+86400000/period()-slot)%(86400000/period());
        ms=distance<=2 && distance*period()>ms ? distance*period()-ms : 0;
        if(ft_page==FT_QSO)ft_label(slot==waiting_slot && (slot&1)==parity?Z_late:Z_next,165,249,12,15);
        slot=parity;s[2]='-';
    }
    s[0] += (slot & 1);
    s[3] += ms / 10000;
    s[4] += ms / 1000 % 10;
    s[6] += ms / 100 % 10;
    ft_label(s, 283, 249, 13, 15);
}
void ft_panel_draw(unsigned full) {
    static unsigned previous_phase,previous_grid;
    if(ft_page==FT_SETUP && !full)goto setup_clock;
    if(ft_page==FT_QSO){
        unsigned phase=stage, busy=phase!=IDLE || sequence_on,grid=0;
        if(!phase && sequence_on)phase=6;
        if(!busy)make_message();
        memcpy(&grid,suffix,sizeof(grid));
        grid ^= has_sent << 31 | outcome << 28;
        if(!full && phase==previous_phase && grid==previous_grid){
            ft_blank(247);
            ft_label(tx_status(),6,249,13,15);
            slot_label();return;
        }
        previous_phase=phase;previous_grid=grid;
    }
    ft_blank(0);
    if(ft_page>=FT_MENU){
        if(ft_page==FT_MENU){
            ft_label(Z_menu,6,88,15,15);
            const char *items[]={Z_log,Z_time,Z_station,Z_auto,pref.automatic?Z_seq " AUTO":Z_seq " MANUAL"};
            for(unsigned i=0;i<5;i++)ft_key(items[i],4,111+31*i,350,30);
            ft_key(Z_exit,399,197,77,33);
        }else if(ft_page==FT_TIME){
            ft_label(Z_time,6,88,15,15);ft_key(Z_gps,4,111,350,30);ft_key(Z_rtc,4,142,350,30);
            ft_key("-15 min",4,177,169,30);ft_key("+15 min",181,177,169,30);
            char zone[]="RTC UTC+00:00";int q=pref.utc_q;if(q<0){zone[7]='-';q=-q;}
            number2(zone+8,q/4);number2(zone+11,(q%4)*15);
            ft_label(ftx_rtc?zone:"GPS UTC",8,220,14,15);
        }else if(ft_page==FT_AUTO){
            ft_label(Z_auto,6,88,15,15);ft_key(auto_open?Z_open:Z_direct,4,111,350,30);
            ft_label(pref.automatic?Z_seq " ON":Z_seq " OFF",8,149,13,15);ft_key(Z_start,399,89,77,33);
        }else if(ft_page==FT_INFO){
            ft_label(Z_heard,6,88,15,15);ft_label(inspected.text,6,119,14,15);
            ft_place_label(ft_place_id(&inspected),8,153);
        }else log_draw();
        ft_key(Z_back,399,233,77,33);return;
    }
    ft_header();
    ft_label(ft_page == FT_QSO ? (partner[0]?partner:Z_cq)
             : ft_page == FT_SETUP ? Z_set : ft_page == FT_CALL ? Z_call : Z_grid,
             46,86,13,15);
    if (ft_page == FT_SETUP) {
        char hz[8];
        digits(hz, pref.hz);
        value_key(Z_call, pref.call, 4, 116);
        value_key(Z_grid, pref.grid[0] ? pref.grid : "AUTO", 181, 116);
        value_key(Z_slot, pref.parity ? "B" : "A", 4, 149);
        value_key(Z_frequency, pref.follow ? "FOLLOW" : "FIXED", 181, 149);
        value_key("-50 Hz  ", hz, 4, 182);
        ft_key("+50 Hz", 181, 182, 172, 30);
        value_key(Z_seq, pref.automatic ? "ON" : "OFF", 4, 215);
        ft_key(Z_position, 181, 215, 172, 30);
        ft_key(Z_save, 417, 229, 61, 39);
setup_clock:
        ft_blank(247);
        slot_label();
    } else if (ft_page == FT_CALL || ft_page == FT_GRID) {
        ft_label(edit, 6, 107, 15, 15);
        for (unsigned i = 0; i < 36; ++i) {
            char s[2] = {alphabet[i], 0};
            ft_key(s, 3 + 39 * (i % 9), 127 + 33 * (i / 9), 37, 30);
        }
        ft_key(Z_del, 417, 122, 61, 29);
        ft_key(Z_ok, 417, 156, 61, 32);
        ft_key(Z_back, 417, 229, 61, 39);
    } else {
        unsigned busy=previous_phase!=IDLE;
        if(partner[0]){
            ft_label(inspected.text,8,128,16,15);
            ft_label(Z_rxmsg,8,106,12,15);
        }
        if(overlay==PICK_MESSAGE){
            for(unsigned i=0;i<6;i++)ft_key(names[i],4+i%3*118,171+i/3*34,114,31);
        }else if(overlay==OTHER_CALLS && others){
            ft_label(Z_other,8,165,13,15);
            ft_label(callers[other_index],8,190,16,15);
        }else{
            const char *label=previous_phase==SOUND||previous_phase==DRAIN?Z_sending:previous_phase==WAIT?Z_queued:
                has_sent?Z_lasttx:Z_draft;
            ft_label(label,8,157,12,15);
            ft_label(outgoing,8,179,16,15);
            char buf[40],*p=copy(buf,parity?"TX B   ":"TX A   ");
            p=digits(p,audio_hz);p=copy(p," Hz    ");
            copy(p,kind==CQ?"CQ x3":pref.automatic?"AUTO x3":"MANUAL");
            ft_label(buf,75,222,13,15);
            if(partner[0])ft_place_label(ft_place_id(&inspected),8,203);
        }
        if(!outcome && (busy || !overlay)){
            const char *action=previous_phase==KEY||previous_phase==SOUND||previous_phase==DRAIN?Z_cut:
                busy?Z_cancel:has_sent?Z_resend:Z_send;
            if(previous_phase!=RELEASE)ft_key(action,399,89,77,33);
        }
        if(!outcome){
            if(overlay==OTHER_CALLS || !busy)
                ft_key(overlay?Z_back:partner[0]?Z_change:Z_set,399,125,77,33);
            if(others){
                char s[12];digits(copy(s,Z_other " "),others);
                ft_key(s,399,161,77,33);
            }
            if(partner[0]&&!busy&&!has_sent)ft_key(Z_set,399,197,77,33);
        }
        ft_label(previous_phase==WAIT?Z_queued:previous_phase==SOUND||previous_phase==DRAIN?"ON AIR":outcome==FINAL_SENT?Z_complete:outcome?Z_finished:
            has_sent?Z_waiting:previous_phase==KEY?Z_keying:Z_idle,225,86,13,15);
        ft_key(outcome?Z_home:Z_end,399,233,77,33);
        ft_label(tx_status(),6,249,13,15);
        slot_label();
    }
    if (notice && ft_page != FT_QSO)
        ft_label(notice, 8, 255, 12, 15);
}
