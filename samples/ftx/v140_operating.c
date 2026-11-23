/* Second-generation operating panel. The original FT engine owns RF, UTC
   admission, modulation and the SD journal. The panel owns operator intent. */
#include "j140_tx.h"
#include "ft_panel_words.h"
#include <stdint.h>
#include <string.h>
#include <stdatomic.h>
#include "v140_operating_labels.h"

enum { MANUAL, SEMI, FULL };
enum { IDLE, WAIT, KEY, SOUND, DRAIN, RELEASE };
enum { CQ, LOCATOR, REPORT, R_REPORT, END_RR, END_73 };
enum { AUTO_OFF, AUTO_FIND, AUTO_CQ };
enum { LIMIT_STOP, LIMIT_NEXT, LIMIT_CQ };
enum { LISTEN, QUEUED, ON_AIR, PICK, CONFIRM, SCAN, WAIT_RX, COMPLETE };

struct Preferences {
    char call[12], grid[5];
    uint8_t parity, follow, automatic;
    uint16_t hz;
    int8_t utc_q;
};
extern struct Preferences pref;
extern char partner[12], outgoing[36], edit[12];
extern unsigned kind, parity, audio_hz, attempts, tx_frequency, last_air;
extern unsigned sequence_on, has_sent, from_list, outcome, cached;
extern unsigned cq_only;
extern _Atomic unsigned stage, return_rx;
extern const char *notice;
extern int mode_ok(void);
extern int is_call(const char *);
extern const char *foreign_tx(void);
extern int arm_next(unsigned response_slot);
extern void halt(const char *);
extern void rectangle(const float *, unsigned, unsigned, unsigned, unsigned);
extern void draw_glyph(const uint8_t *,const uint16_t *,unsigned,unsigned,unsigned,unsigned);
extern int stock_ft_touch(unsigned, unsigned);
extern void ft_station_tick(void);

static struct {
    unsigned mode, tries, multiple_first, on_limit, auto_style;
    unsigned running, enabled_slot, manual_cq, offer_count, offer_slot, choosing;
    unsigned setup_for_send, completed, typing_target, target_ready;
    unsigned cooldown_until, cooldown_hz, cooldown_mode;
    char cooldown_call[7];
    struct DisplayRow offers[10];
    struct DisplayRow search_rows[6];
    unsigned search_count;
} operating = {.mode = SEMI, .tries = 3, .auto_style = AUTO_CQ};

#define RADIO_HZ (*(volatile uint32_t *)0x20380714)
#define TICKS (*(volatile uint32_t *)0x20381e08)
#define EXIT_KEY (*(volatile uint8_t *)0x20380431)

static unsigned age(unsigned now, unsigned then)
{
    const unsigned day = ftx_ft4 ? 11520 : 5760;
    return (now + day - then % day) % day;
}

static unsigned sender(char to[7], const struct DisplayRow *row)
{
    if (!row || !row->flag || row->flag > sizeof(row->text)) return 0;
    const char *p = row->text + row->flag - 1;
    unsigned n = 0;
    while (n < 6 && p+n < row->text+sizeof(row->text) && p[n] && p[n] != ' ') {
        to[n] = p[n];
        ++n;
    }
    if (p+n >= row->text+sizeof(row->text) || (p[n] && p[n] != ' ')) return 0;
    to[n] = 0;
    return n >= 3;
}

static int directed(const struct DisplayRow *r)
{
    return pref.call[0] && r->flag == strlen(pref.call)+2
        && !strncmp(r->text,pref.call,r->flag-2) && r->text[r->flag-2]==' ';
}

static void clear_workflow(void)
{
    operating.running = operating.manual_cq = operating.offer_count = 0;
    operating.choosing = operating.search_count = 0;
    operating.typing_target = operating.target_ready = 0;
    ft_auto_armed = 0;
}

static void stop_contact(void)
{
    clear_workflow();
    if (ft_page == FT_QSO) stock_ft_touch(440,249);
    else {
        halt(Z_stopped);
        ft_return_live();
    }
    view_invalidate();
}

void operating_open(void)
{
    ft_station_open();
    clear_workflow();
    operating.setup_for_send = operating.completed = 0;
}

void operating_close(void)
{
    clear_workflow();
    ft_station_close();
}

static int running_contact(void)
{
    return operating.running || operating.choosing || stage != IDLE
        || sequence_on || (ft_page == FT_QSO && (has_sent || from_list == 2));
}

static void make_target_row(struct DisplayRow *target,const char *call,unsigned slot,unsigned hz)
{
    memset(target,0,sizeof(*target));
    memcpy(target->text,"CQ ",3);
    memcpy(target->text+3,call,strlen(call)+1);
    target->flag = 4;
    target->slot = slot;
    target->hz = hz;
    target->db = -15; /* Locator first, actual report once the station answers. */
}

static int tail_target(const struct DisplayRow *row,char who[7])
{
    if (!row || directed(row) || !sender(who,row) || !is_call(who)) return 0;
    unsigned end = row->flag-1+strlen(who);
    if (end+6>sizeof(row->text)) return 0;
    const char *body = row->text+end;
    if (strcmp(body," RR73") && strcmp(body," 73")) return 0;
    unsigned slot,ms;
    if (!ft_clock(&slot,&ms) || age(slot,row->slot)>1) return 0;
    for (unsigned y=102;y<272;y+=17) {
        const struct DisplayRow *newer=ft_row_at(y);
        char call[7];
        if (newer && age(slot,newer->slot)<age(slot,row->slot) &&
            sender(call,newer) && !strcmp(call,who)) return 0;
    }
    return 1;
}

static int start_contact(void)
{
    operating.completed = 0;
    pref.automatic = operating.mode != MANUAL;
    if (ft_page == FT_LIST) {
        const struct DisplayRow *row=ft_choice_row();
        char who[7];
        if (tail_target(row,who)) {
            struct DisplayRow target;
            make_target_row(&target,who,row->slot,row->hz);
            ft_receive_row(&target,1);
        } else if (!stock_ft_touch(440,104)) return 0;
    }
    if (ft_page != FT_QSO) return 1;
    const int action = stock_ft_touch(440,104);
    if (ft_page == FT_SETUP) operating.setup_for_send = 1;
    if (stage == WAIT) {
        operating.manual_cq = kind == CQ && operating.mode == MANUAL;
        operating.target_ready = 0;
    }
    view_invalidate();
    return action;
}

static int start_automatic(unsigned type)
{
    unsigned slot, ms;
    tx_frequency = RADIO_HZ;
    if (!ft_listen() || !mode_ok() || foreign_tx() ||
        !ft_clock(&slot,&ms) || !pref.call[0]) return 0;
    ft_return_live();
    ft_page = FT_LIST;
    operating.running = type;
    operating.enabled_slot = slot;
    operating.search_count = 0;
    if (type == AUTO_CQ) {
        start_contact();
        if (stage != WAIT) operating.running = AUTO_OFF;
    }
    view_invalidate();
    return 1;
}

static int supply_offer(const struct DisplayRow *row)
{
    if (!ft_row_eligible(row) || !directed(row) || age(row->slot,last_air) != 1
        || stage >= KEY) return 0;
    char who[7];
    if (!sender(who,row)) return 0;
    if (operating.offer_count && row->slot != operating.offer_slot) return 0;
    operating.offer_slot = row->slot;
    unsigned n = operating.offer_count;
    for (unsigned i=0; i<n; ++i) {
        char previous[7];
        if (sender(previous,&operating.offers[i]) && !strcmp(previous,who)) return 1;
    }
    if (n < sizeof(operating.offers)/sizeof(operating.offers[0])) {
        operating.offers[n] = *row;
        operating.offer_count = n+1;
    }
    return 1;
}

static void choose_offer(const struct DisplayRow *r)
{
    if (!ft_row_eligible(r) || !directed(r)) return;
    ft_receive_row(r,0);
    if (kind != CQ) {
        operating.choosing = operating.offer_count = operating.manual_cq = 0;
        view_invalidate();
    }
}

static void collect_search_row(const struct DisplayRow *r)
{
    char who[7];
    if (r->slot == operating.enabled_slot || !ft_row_eligible(r) || !sender(who,r))
        return;
    if (!strcmp(who,operating.cooldown_call) && (int32_t)(TICKS-operating.cooldown_until)<0 &&
        operating.cooldown_hz == RADIO_HZ && operating.cooldown_mode == ftx_ft4 && !directed(r))
        return;
    for (unsigned i=0;i<operating.search_count;++i) {
        char prior[7];
        if (sender(prior,&operating.search_rows[i]) && !strcmp(prior,who)) {
            operating.search_rows[i] = *r;
            return;
        }
    }
    if (operating.search_count < sizeof(operating.search_rows)/sizeof(operating.search_rows[0]))
        operating.search_rows[operating.search_count++] = *r;
}

void operating_receive(const struct DisplayRow *r, int selected)
{
    if (selected) {
        ft_receive_row(r,selected);
        return;
    }
    if (ft_page == FT_QSO && kind == CQ && has_sent && sequence_on && !outcome) {
        supply_offer(r);
        return;
    }
    if (operating.running == AUTO_FIND && ft_page == FT_LIST)
        collect_search_row(r);
    else
        ft_receive_row(r,0);
}

void operating_after_decode(void)
{
    if (operating.offer_count && !operating.choosing) {
        if (operating.offer_count == 1 || operating.multiple_first) {
            choose_offer(&operating.offers[0]);
            operating.offer_count = 0;
        } else {
            unsigned waiting = WAIT;
            atomic_compare_exchange_strong(&stage,&waiting,IDLE);
            operating.choosing = 1;
            view_invalidate();
        }
    }
    if (operating.running != AUTO_FIND || ft_page != FT_LIST || RADIO_HZ != tx_frequency) return;
    unsigned pending = 0;
    for (unsigned i=0;i<operating.search_count;++i) {
        const struct DisplayRow *candidate = &operating.search_rows[i];
        char who[7];
        if (!ft_row_eligible(candidate) || !sender(who,candidate)) continue;
        int worked = ft_worked(who);
        if (worked > 0) continue;
        if (worked < 0) {
            if (i != pending) operating.search_rows[pending] = *candidate;
            ++pending;
            continue;
        }
        ft_receive_row(candidate,1);
        start_contact();
        operating.search_count = 0;
        if (stage != WAIT) stop_contact();
        return;
    }
    operating.search_count = pending;
}

void operating_tick(void)
{
    unsigned slot, ms;
    int clock = ft_clock(&slot,&ms);
    if ((EXIT_KEY == 9 && running_contact()) ||
        ((operating.running || operating.choosing) &&
         (!clock || !ft_listen() || !mode_ok() || foreign_tx()))) stop_contact();

    if (operating.choosing && clock && age(slot,operating.offer_slot) > 1)
        stop_contact();

    const int idle = atomic_load(&stage) == IDLE;
    if (idle && sequence_on && has_sent && !operating.manual_cq && !operating.choosing &&
        kind < END_RR && attempts >= operating.tries && clock && age(slot,last_air) > 1) {
        unsigned next = operating.running ? operating.on_limit : LIMIT_STOP;
        if (kind == CQ && next == LIMIT_CQ) next = LIMIT_STOP;
        if (next == LIMIT_NEXT && partner[0]) {
            memcpy(operating.cooldown_call,partner,strlen(partner)+1);
            operating.cooldown_until = TICKS+30u*60u*1000u;
            operating.cooldown_hz = RADIO_HZ;
            operating.cooldown_mode = ftx_ft4;
        }
        stop_contact();
        if (next == LIMIT_NEXT) start_automatic(AUTO_FIND);
        else if (next == LIMIT_CQ) start_automatic(AUTO_CQ);
    }

    const int parked = (operating.choosing || operating.manual_cq) &&
        atomic_load(&stage) == IDLE && has_sent;
    unsigned old_sequence = sequence_on;
    if (parked) sequence_on = 0;
    /* The existing engine has a three-send ceiling. V2 keeps the same edge
       and native admission checks, with the operator's selected limit. */
    const int legacy_limit = sequence_on && has_sent && kind < END_RR &&
        (attempts >= 3 || attempts >= operating.tries);
    if (legacy_limit) sequence_on = 0;
    const unsigned finished = atomic_load(&return_rx);
    ft_station_tick();
    if (parked || legacy_limit) sequence_on = old_sequence;
    if (legacy_limit && clock && attempts < operating.tries && age(slot,last_air) > 0 &&
        mode_ok() && !foreign_tx() && atomic_load(&stage) == IDLE && !arm_next(~0u))
        stop_contact();

    if (finished && ft_page == FT_QSO && atomic_load(&stage) == IDLE &&
        !atomic_load(&return_rx)) {
        unsigned resume = operating.running;
        stop_contact();
        if (!resume || !start_automatic(resume)) operating.completed = 1;
    }
}

static int rail_hit(unsigned x, unsigned y, unsigned top)
{
    return x >= 399 && x < 476 && y >= top && y < top+33;
}

static int is_confirmation(void)
{
    return ft_page == FT_QSO && stage == IDLE && !sequence_on &&
        !operating.choosing && from_list == 2;
}

unsigned operating_status(void)
{
    if (operating.choosing) return PICK;
    if (stage == WAIT) return QUEUED;
    if (stage >= KEY && stage <= DRAIN) return ON_AIR;
    if (is_confirmation()) return CONFIRM;
    if (operating.running == AUTO_FIND && ft_page == FT_LIST) return SCAN;
    if (ft_page == FT_QSO && has_sent) return WAIT_RX;
    return operating.completed ? COMPLETE : LISTEN;
}

int operating_touch(unsigned x, unsigned y)
{
    if (ft_page == FT_LIST || ft_page == FT_QSO) {
        if (x < 397 && y >= 102) {
            const struct DisplayRow *row = ft_row_at(y);
            if (operating.choosing && row) {
                char who[7], offered[7];
                if (sender(who,row)) for (unsigned i=0; i<operating.offer_count; ++i)
                    if (row->slot == operating.offer_slot && sender(offered,&operating.offers[i]) &&
                        !strcmp(who,offered)) { choose_offer(&operating.offers[i]); break; }
                return 1;
            }
            if (!running_contact()) {
                if (operating.target_ready) {
                    operating.target_ready = 0;
                    ft_page = FT_LIST;
                }
                return ft_choose_row(y);
            }
            return row != 0;
        }
        if (rail_hit(x,y,89)) {
            if (running_contact()) { stop_contact(); return 1; }
            if (ft_is_history()) { ft_return_live(); return 1; }
            return start_contact();
        }
        if (rail_hit(x,y,233)) {
            if (is_confirmation()) return start_contact();
            if (running_contact()) return 0;
            operating.target_ready = 0;
            ft_page = FT_MENU; view_invalidate(); return 1;
        }
        if (ft_is_history() && rail_hit(x,y,161)) {
            unsigned newer = x >= 439;
            if (x >= 436 && !newer) return 0;
            if (!ft_history_enabled(newer)) return 0;
            ft_history_action(newer); return 1;
        }
        return 0;
    }
    if (ft_page == FT_MENU) {
        if (rail_hit(x,y,233)) { ft_page = FT_LIST; return 1; }
        if (rail_hit(x,y,161)) { ft_history_action(2); return 1; }
        if (rail_hit(x,y,125)) {
            edit[0] = 0;
            operating.typing_target = 1;
            ft_page = FT_CALL;
            return 1;
        }
        if (x < 395 && y >= 204 && y < 235) { ft_page = FT_AUTO; return 1; }
        if (x < 395 && y >= 235 && y < 266) {
            if (!ft_is_history()) ft_history_action(0);
            else ft_return_live();
            ft_page = FT_LIST; return 1;
        }
    } else if (ft_page == FT_AUTO) {
        if (rail_hit(x,y,233)) { ft_page = FT_MENU; return 1; }
        if (rail_hit(x,y,89)) return operating.mode == FULL && start_automatic(operating.auto_style);
        if (x >= 395 || y < 111 || y >= 266) return 0;
        switch ((y-111)/31) {
            case 0: operating.mode = (operating.mode+1)%3; break;
            case 1: operating.tries = operating.tries%9+1; break;
            case 2: operating.multiple_first ^= 1; break;
            case 3: operating.auto_style = operating.auto_style == AUTO_CQ ? AUTO_FIND : AUTO_CQ; break;
            case 4: operating.on_limit = (operating.on_limit+1)%3; break;
        }
        return 1;
    } else if (ft_page == FT_CALL && operating.typing_target && x >= 417) {
        if (y >= 228) {
            operating.typing_target = 0;
            ft_page = FT_MENU;
            return 1;
        }
        if (y >= 156 && y < 188) {
            unsigned slot,ms;
            if (!is_call(edit) || !strcmp(pref.call,edit) || !ft_clock(&slot,&ms)) return 0;
            struct DisplayRow target;
            make_target_row(&target,edit,(slot&~1u)+(1-pref.parity),pref.hz);
            ft_return_live();
            ft_receive_row(&target,1);
            if (ft_page != FT_QSO) return 0;
            from_list = 0;
            operating.typing_target = 0;
            operating.target_ready = 1;
            return 1;
        }
    }
    unsigned page = ft_page;
    int handled = stock_ft_touch(x,y);
    if (page == FT_SETUP && ft_page != FT_SETUP && ft_page != FT_CALL && ft_page != FT_GRID &&
        operating.setup_for_send) {
        operating.setup_for_send = 0;
        ft_page = FT_LIST;
        view_invalidate();
    }
    return handled;
}

static void label(const uint8_t *word,unsigned x,unsigned y,unsigned palette)
{
    uint8_t mask[120];
    for (;*word;++word,x+=16) {
        const uint8_t *packed = v2_masks[*word-1];
        for (unsigned i=0;i<sizeof(v2_masks[0]);++i) {
            unsigned value=packed[i];
            mask[2*i]=5*(value&3)|80*((value>>2)&3);
            mask[2*i+1]=5*((value>>4)&3)|80*(value>>6);
        }
        draw_glyph(mask,v2_palette[palette],x,y,16,2);
    }
}

void operating_draw_rail(void)
{
    static const float background[] = {.035f,.055f,.065f,1};
    static const float highlight[] = {.24f,.66f,.37f,1};
    static const uint8_t *const modes[] = {v2_manual,v2_semi,v2_full};
    static const uint8_t *const states[] = {v2_listen,v2_queued,v2_on_air,v2_pick,
        v2_confirm,v2_scan,v2_wait_rx,v2_completed};
    /* The factory compositor folds the rightmost 120 pixels into three
       tiles. Each filled rectangle stays inside a single tile. */
    rectangle(background,397,89,83,64);
    rectangle(background,397,153,83,68);
    rectangle(background,397,221,83,51);
    const int running = running_contact();
    const struct DisplayRow *choice = ft_choice_row();
    char selected[7];
    const int can_chase = !running && !ft_is_history() && tail_target(choice,selected);
    const char *key = running ? Z_stop : ft_is_history() ? Z_live :
        operating.target_ready || can_chase ? "CALL" :
        choice ? (ft_row_eligible(choice) ? Z_reply : Z_info) : Z_cq;
    ft_key(key,399,89,77,33);
    if (ft_is_history()) {
        ft_key(Z_old,399,161,37,33); ft_key(Z_new,439,161,37,33);
    } else {
        label(modes[operating.mode],402,123,0);
        label(states[operating_status()],402,138,0);
        if (!running && sender(selected,choice)) ft_label(selected,402,154,13,15);
        else if (ft_page == FT_QSO && partner[0]) ft_label(partner,402,154,13,15);
        else if (pref.call[0]) ft_label(pref.call,402,154,13,15);
        if (kind == CQ && pref.grid[0]) ft_label(pref.grid,402,171,13,15);
        else if (partner[0]) {
            const char *end = outgoing+strlen(outgoing);
            while (end > outgoing && end[-1] != ' ') --end;
            if (strlen(end) < 10) ft_label(end,402,171,13,15);
        }
        char channel[]="A 0000 Hz";
        channel[0] += parity;
        unsigned hz = audio_hz;
        for (int i=5; i>=2; --i) { channel[i]='0'+hz%10; hz/=10; }
        ft_label(channel,402,188,13,15);
        if (running) {
            char count[]="TX 0 / 0";
            count[3] += attempts > 9 ? 9 : attempts;
            count[7] += operating.tries;
            ft_label(count,402,205,13,15);
        }
    }
    if (operating.choosing) for (unsigned row=0;row<10;++row) {
        const unsigned y = 102+17*row;
        const struct DisplayRow *r = ft_row_at(y);
        if (r && r->slot == operating.offer_slot && directed(r) && ft_row_eligible(r)) {
            unsigned end = y < 153 ? 153 : y < 221 ? 221 : 272;
            rectangle(highlight,395,y,2,end-y < 15 ? end-y : 15);
        }
    }
    if (!running || is_confirmation()) ft_key(is_confirmation() ? Z_send : Z_menu,399,233,77,33);
}

void operating_slot_bar(unsigned slot, unsigned elapsed)
{
    static const float bar[] = {.09f,.14f,.16f,1};
    static const float edge[] = {.43f,.56f,.62f,1};
    static const float track[] = {.055f,.09f,.12f,1};
    static const float fill[] = {.22f,.70f,.90f,1};
    enum { slot_x = 42, bar_x = 56, bar_width = 82 };
    unsigned period = ftx_ft4 ? 7500 : 15000;

    rectangle(bar,slot_x-3,86,bar_x-slot_x+3,16);
    rectangle(edge,bar_x,90,bar_width,8);
    rectangle(track,bar_x+1,91,bar_width-2,6);
    if (elapsed >= period) return;
    ft_label(slot&1 ? "B" : "A",slot_x,88,13,15);
    unsigned width = (bar_width-2)*elapsed/period;
    if (width) rectangle(fill,bar_x+1,91,width,6);
}

void operating_draw_slot(unsigned slot, unsigned elapsed)
{
    operating_slot_bar(slot,elapsed);
    operating_draw_rail();
}

/* At x=360 the factory LCD folds into another tile. Draw each digit in
   its own cell so five-digit distances survive the boundary. */
void operating_distance_text(const char *text,unsigned x,unsigned y,unsigned size)
{
    for (; *text; ++text,x+=8) {
        char cell[2] = {*text,0};
        ft_label(cell,x,y,size,15);
    }
}

void operating_distance_number(unsigned value,unsigned x,unsigned y)
{
    char digits[11];
    char *end = digits+sizeof(digits)-1;
    *end = 0;
    do {
        *--end = '0'+value%10;
        value /= 10;
    } while (value);
    operating_distance_text(end,x,y,12);
}

void operating_distance_heading(const char *heading)
{
    operating_distance_text("km",352,88,13);
    if (heading[2]) ft_label(heading+3,376,88,12,15);
}

extern void ft_panel_draw(unsigned);

static void menu_value(unsigned y,const uint8_t *title,const uint8_t *value,const char *plain)
{
    ft_key("",4,y,350,30);
    label(title,8,y+7,1);
    if (value) {
        unsigned n=0;
        while(value[n]) ++n;
        label(value,337-16*n,y+7,1);
    } else {
        ft_label(plain,337-8*strlen(plain),y+7,12,15);
    }
}

void operating_draw_page(unsigned full)
{
    if (ft_page != FT_MENU && ft_page != FT_AUTO) {
        ft_panel_draw(full);
        if (operating.typing_target && ft_page == FT_CALL) {
            static const float bar[] = {.09f,.14f,.16f,1};
            rectangle(bar,45,86,260,17);
            label(v2_target,46,86,0);
        }
        return;
    }
    ft_blank(0);
    if (ft_page == FT_MENU) {
        ft_label(Z_menu,6,88,15,15);
        ft_key(Z_log,4,111,350,30);
        ft_key(Z_time,4,142,350,30);
        ft_key(Z_station,4,173,350,30);
        ft_key(Z_auto,4,204,350,30);
        if (ft_is_history()) ft_key(Z_live,4,235,350,30);
        else menu_value(235,v2_history,0,">");
        ft_key("CALL",399,125,77,33);
        ft_key(cq_only ? Z_all : Z_cq_only,399,161,77,33);
        ft_key(Z_exit,399,197,77,33);
    } else {
        static const uint8_t *const modes[] = {v2_manual,v2_semi,v2_full};
        static const uint8_t *const limits[] = {v2_stop,v2_next,0};
        char retry[]={(char)('0'+operating.tries),0};
        ft_label(Z_auto,6,88,15,15);
        menu_value(111,v2_mode,modes[operating.mode],0);
        menu_value(142,v2_tries,0,retry);
        menu_value(173,v2_multi,operating.multiple_first ? v2_first : v2_choose,0);
        menu_value(204,v2_start_as,operating.auto_style == AUTO_CQ ? 0 : v2_scan,"CQ");
        menu_value(235,v2_limit,limits[operating.on_limit],"CQ");
        if (operating.mode == FULL) ft_key(Z_start,399,89,77,33);
    }
    ft_key(Z_back,399,233,77,33);
}
