/* Second-generation operating panel. The original FT engine owns RF, UTC
   admission, modulation and the SD journal. The panel owns operator intent. */
#define FTX_DEVICE 1
#include "j140_tx.h"
#include "ft_panel_words.h"
#include <stdint.h>
#include <string.h>
#include <stdatomic.h>
#include "v140_operating_labels.h"
#include "operating-card.h"
#include "ab_key_art.h"

enum { MANUAL, SEMI, FULL };
enum { IDLE, WAIT, KEY, SOUND, DRAIN, RELEASE };
enum { CQ, LOCATOR, REPORT, R_REPORT, END_RR, END_73 };
enum { AUTO_OFF, AUTO_FIND, AUTO_CQ };
enum { LIMIT_STOP, LIMIT_NEXT, LIMIT_CQ };
enum { LISTEN, QUEUED, ON_AIR, PICK, CONFIRM, SCAN, WAIT_RX, COMPLETE, REST };
enum { CAPTION_RAIL, CAPTION_ROW, CAPTION_HEADER, CAPTION_KEY, CAPTION_DIM_KEY, CAPTION_DIM_ROW };
enum { run_ms=45*60*1000, rest_ms=5*60*1000 };
enum { row_top=106, row_step=18, setup_top=108, setup_step=23, filter_page=1 };
enum { menu_top=108, menu_step=31 };
enum { value_x=250, tone_minus=191, tone_plus=314, tone_width=44,
       tone_y=setup_top+4*setup_step+1,tone_height=setup_step-2 };
unsigned overlay_page;
static unsigned menu_sheet,auto_sheet,history_offset,history_end;
void operating_index_rows(void);
extern char *digits(char *,unsigned);
extern int read_at(int,unsigned,char *,unsigned);
static volatile unsigned *const journal_state=(volatile unsigned *)0x2082746c;
static _Atomic unsigned *const journal_io=(_Atomic unsigned *)0x208274ac;
struct LogRow {char call[8],grid[9],band[6],utc[11]; unsigned place;};
/* The replaced single-record view already owns a 321-byte buffer. The card
   worker reads through its adjacent scratch line and publishes here at io=2. */
_Static_assert(7*sizeof(struct LogRow)+3<=320,"log page must fit native detail buffer");
static struct LogRow *log_rows;
static unsigned log_count, log_offset;
static unsigned displayed_second, displayed_edge;

void operating_capture_frame(void)
{
    /* Both stock capture formats borrow OpenVG surface 7 as scratch RAM. */
    if (*(volatile uint8_t *)0x20380747 || *(volatile uint8_t *)0x204bd689) {
        view_invalidate();
        return;
    }
    ((void (*)(void))FT_NATIVE_FRAME)();
}

static unsigned screen_page(void) {return overlay_page?overlay_page:ft_page;}
static void screen_to(unsigned page)
{
    if (overlay_page) overlay_page=page==FT_LIST?0:page;
    else ft_page=page;
    view_invalidate();
}
static void history_show(unsigned page)
{
    unsigned pages=FT_COUNT?(FT_COUNT+9)/10:1;
    history_offset=page<pages?page:pages-1;
    FT_BROWSE=1;FT_SELECTED=~0u;
    FT_FIRST=history_offset*10;
    view_invalidate();
}

static void history_open(void)
{
    unsigned front=*(volatile unsigned *)0x20827e48;
    history_end=FT_SERIAL[front];
    FT_BROWSE=1;
    operating_index_rows();
    history_show(0);
}

static void history_leave(void)
{
    FT_BROWSE=0;
    operating_index_rows();
    ft_return_live();
}

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
extern void origin(int,int,int *,int *);
extern int stock_ft_touch(unsigned, unsigned);
extern void ft_station_tick(void);
extern void save_prefs(void);
extern char *tag(char *,const char *,const char *,unsigned);
extern int field_get(const char *,const char *,char *,unsigned);
extern unsigned ftx_position(void), sender_grid(const struct DisplayRow *);
extern int ftx_km(unsigned);

enum { NATIVE_RECEIVE, NATIVE_SEND_SETUP, NATIVE_PARKED_MENU };
static const uint8_t *const operating_modes[] = {v2_manual,v2_semi,v2_full};

static struct {
    unsigned mode, tries, multiple_first, on_limit, auto_style;
    unsigned running, enabled_slot, manual_cq, offer_count, offer_slot, choosing;
    unsigned native_context, completed, typing_target, target_ready;
    unsigned cycle_started, rest_until, rest_mode, timed, order, cool, page, filter_edit;
    unsigned signal_sort, next_cooldown, rx_slot, elapsed;
    char include[7], exclude[7];
    struct { unsigned until, hz; char call[7]; uint8_t mode; } cooldown[16];
    struct DisplayRow offers[10];
    struct DisplayRow search_rows[6];
    unsigned search_count;
} operating = {.mode = SEMI, .tries = 3, .on_limit=LIMIT_CQ, .auto_style = AUTO_CQ,
    .timed = 1, .order = 1, .signal_sort = 1};

#define RADIO_HZ (*(volatile uint32_t *)0x20380714)
#define TICKS (*(volatile uint32_t *)0x20381e08)
#define EXIT_KEY (*(volatile uint8_t *)0x20380431)

struct FtOptions {
    uint32_t tag, sequence;
    uint8_t mode, tries, first, limit, style, timed, order, cool, signal;
    char include[7], exclude[7];
    uint32_t hash;
};
static unsigned options_sequence;

static unsigned option_hash(const struct FtOptions *options)
{
    const uint8_t *bytes=(const uint8_t *)options;
    unsigned hash=2166136261u;
    for (unsigned i=0;i<__builtin_offsetof(struct FtOptions,hash);++i) hash=(hash^bytes[i])*16777619u;
    return hash;
}

static int option_io(struct FtOptions *options,unsigned bank,int write)
{
    unsigned state=*(volatile uint8_t *)0x20380172;
    if (state!=3 && state!=7) return 0;
    char path[]="C:\\IC-705\\FTU0.CFG";
    path[13]='0'+bank;
    int fd;unsigned n=0;
    if (((int (*)(const char *,unsigned,int *))CARD_OPEN)(path,write?0x201:0,&fd)) return 0;
    uintptr_t fn=write?CARD_WRITE:CARD_READ;
    int rc=((int (*)(int,void *,unsigned,unsigned *))fn)(fd,options,sizeof(*options),&n);
    return !((int (*)(int))CARD_CLOSE)(fd) && !rc && n==sizeof(*options);
}

static void options_save(void)
{
    struct FtOptions options;
    memset(&options,0,sizeof(options));
    options.tag=0x31555446;options.sequence=options_sequence+1;
    options.mode=operating.mode;options.tries=operating.tries;options.first=operating.multiple_first;
    options.limit=operating.on_limit;options.style=operating.auto_style;options.timed=operating.timed;
    options.order=operating.order;options.cool=operating.cool;options.signal=operating.signal_sort;
    memcpy(options.include,operating.include,7);memcpy(options.exclude,operating.exclude,7);
    options.hash=option_hash(&options);
    if (option_io(&options,options.sequence&1,1)) options_sequence=options.sequence;
}

static void options_load(void)
{
    struct FtOptions o;
    for (unsigned bank=0;bank<2;++bank) {
        if (!option_io(&o,bank,0) || o.tag!=0x31555446 || o.hash!=option_hash(&o) || (int32_t)(o.sequence-options_sequence)<=0 ||
            o.mode>FULL || !o.tries || o.tries>9 || o.first>1 || o.limit>LIMIT_CQ ||
            (o.style!=AUTO_FIND && o.style!=AUTO_CQ) || o.timed>1 || o.order>3 || o.signal>1 || o.include[6] || o.exclude[6] ||
            (o.cool && o.cool!=10 && o.cool!=30 && o.cool!=60)) continue;
        operating.mode=o.mode;operating.tries=o.tries;operating.multiple_first=o.first;operating.on_limit=o.limit;
        operating.auto_style=o.style;operating.timed=o.timed;operating.order=o.order;operating.cool=o.cool;
        operating.signal_sort=o.signal;memcpy(operating.include,o.include,7);memcpy(operating.exclude,o.exclude,7);
        options_sequence=o.sequence;
    }
}

/* A standard callsign occupies at most six bytes and its NUL. Packed
   locator detail in the unused tail keeps both original SD banks readable. */
static unsigned grid_detail(const char *grid)
{
    if (strlen(grid) < 6) return 0;
    unsigned square = (grid[4]-'A')*24u + grid[5]-'A';
    return grid[6] ? 577+100*square+10u*(grid[6]-'0')+grid[7]-'0' : 1+square;
}

static unsigned station_detail(void)
{
    if (!pref.grid[0] || pref.call[7] != 'G') return 0;
    return (uint8_t)pref.call[8] | (uint8_t)pref.call[9]<<8;
}

static void expand_grid(char grid[9], const char *base, unsigned detail)
{
    memcpy(grid,base,5);
    if (!grid[0] || !detail || detail > 58176) return;
    unsigned square = detail-1;
    if (detail >= 577) {
        unsigned digits = (detail-577)%100;
        square = (detail-577)/100;
        grid[6] = '0'+digits/10;
        grid[7] = '0'+digits%10;
        grid[8] = 0;
    } else grid[6] = 0;
    grid[4] = 'A'+square/24;
    grid[5] = 'A'+square%24;
}

static int grid_valid(const char *g)
{
    unsigned n = strlen(g);
    return !n || ((n==4 || n==6 || n==8) && (unsigned)(g[0]-'A')<18 && (unsigned)(g[1]-'A')<18 &&
        (unsigned)(g[2]-'0')<10 && (unsigned)(g[3]-'0')<10 && strncmp(g,"RR73",4) &&
        (n<6 || ((unsigned)(g[4]-'A')<24 && (unsigned)(g[5]-'A')<24)) &&
        (n<8 || ((unsigned)(g[6]-'0')<10 && (unsigned)(g[7]-'0')<10)));
}

void *operating_log_snapshot(void *dest,const void *src,unsigned bytes)
{
    memcpy(dest,src,bytes);
    /* Contact's original copier copies all 76 bytes, including the two
       bytes before its aligned frequency field. Keep each queued log stable. */
    uint8_t *contact=dest;
    unsigned detail=!strncmp((const char *)contact+19,pref.grid,5) ? station_detail() : 0;
    contact[62]=detail;
    contact[63]=detail>>8;
    return dest;
}

char *operating_log_grid(char *dst,const char *field,const char *base,unsigned size)
{
    char grid[9];
    if (size != 4) return tag(dst,field,base,size);
    expand_grid(grid,base,(uint8_t)base[43] | (uint8_t)base[44]<<8);
    return tag(dst,field,grid,strlen(grid));
}

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

void operating_list_tile(const uint16_t *tile,int stride,unsigned format,int x,int y,int width,int height)
{
    const struct DisplayRow *row=ft_row_at(272-y-height);
    ++y; /* Center the taller 14-pixel tile in the 16-pixel row body. */
    void (*draw)(const uint16_t *,int,unsigned,int,int,int,int)=(void *)PANEL_TILE;
    if (!row || !directed(row)) {
        draw(tile,stride,format,x,y,width,height);
        return;
    }
    uint16_t recolored[8*14];
    for (int iy=0;iy<14;++iy) for (int ix=0;ix<8;++ix) {
        unsigned rgb=tile[ix-8*iy];
        if ((rgb>>11)>12 && (rgb>>5&63)>28)
            rgb=((rgb>>11)/2<<11) | (rgb&0x7e0) | ((rgb&31)*5/8);
        recolored[(13-iy)*8+ix]=rgb;
    }
    draw(recolored+104,stride,format,x,y,width,height);
}

void operating_index_rows(void)
{
    unsigned *count=(unsigned *)0x20827e34;
    uint8_t *rows=(uint8_t *)0x20827e04;
    unsigned front=*(volatile unsigned *)0x20827e48;
    *count=0;
    if (!ftx_memory) return;
    const struct DisplayBatch *batch=&ftx_memory->batches[front];
    for (unsigned i=0;i<batch->count;++i) {
        const struct DisplayRow *row=&batch->rows[i];
        if (FT_BROWSE && (int32_t)(FT_SERIAL[front]-batch->count+i-history_end)>=0) continue;
        if (cq_only && strncmp(row->text,"CQ ",3) && !directed(row)) continue;
        unsigned next=*count;
        while (next && (operating.signal_sort || FT_BROWSE)) {
            const struct DisplayRow *prev=&batch->rows[rows[next-1]];
            if (prev->slot==row->slot) {
                if(!operating.signal_sort || prev->db>=row->db) break;
            } else if(!FT_BROWSE || (int32_t)(row->slot-prev->slot)<=0) break;
            rows[next]=rows[next-1];--next;
        }
        rows[next]=i;
        ++*count;
    }
}

static void clear_workflow(void)
{
    operating.running = operating.manual_cq = operating.offer_count = 0;
    operating.choosing = operating.search_count = 0;
    operating.typing_target = operating.target_ready = 0;
    operating.native_context = NATIVE_RECEIVE;
    operating.rest_mode = 0;
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
    /* The radio owns clock synchronization. Select its RTC before starting RX. */
    FT_RTC=1;
    ft_station_open();
    clear_workflow();
    operating.completed = 0;
    operating.page=operating.filter_edit=0;
    overlay_page=menu_sheet=auto_sheet=0;
    options_load();
    operating.elapsed=~0u;
    displayed_second=~0u;
}

void operating_close(void)
{
    overlay_page=0;
    clear_workflow();
    ft_station_close();
}

static int running_contact(void)
{
    return operating.running || operating.rest_mode || operating.choosing || stage != IDLE
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
    if (ft_page != FT_QSO) { overlay_page=0; return 1; }
    const int action = stock_ft_touch(440,104);
    if (ft_page == FT_SETUP) {
        overlay_page=0;
        operating.native_context = NATIVE_SEND_SETUP;
    }
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
    notice=(!ft_listen() || !mode_ok())?"Check TX VFO USB-D":foreign_tx();
    if (notice) {view_invalidate();return 0;}
    if (!ft_clock(&slot,&ms) || !pref.call[0]) return 0;
    ft_return_live();
    ft_page = FT_LIST;
    operating.running = type;
    operating.cycle_started = TICKS;
    operating.enabled_slot = slot;
    operating.search_count = 0;
    if (type == AUTO_CQ) {
        start_contact();
        if (stage != WAIT) operating.running = AUTO_OFF;
    }
    view_invalidate();
    return 1;
}

static int run_due(void)
{
    return operating.timed && operating.running && (unsigned)(TICKS-operating.cycle_started)>=run_ms;
}

static void enter_rest(void)
{
    unsigned resume=operating.running;
    stop_contact();
    operating.rest_mode=resume;
    operating.rest_until=TICKS+rest_ms;
}

static int primary_start(void)
{
    if (operating.mode == FULL && ft_page == FT_LIST && !ft_choice_row() && is_call(pref.call)) {
        unsigned slot, ms;
        if (!ft_clock(&slot,&ms)) {
            notice="Waiting for UTC";
            view_invalidate();
            return 1;
        }
        return start_automatic(operating.auto_style) || notice;
    }
    int result = start_contact();
    if (operating.mode == FULL && stage == WAIT && !operating.running) {
        operating.running = operating.auto_style;
        operating.cycle_started = TICKS;
    }
    return result;
}

static void continue_automatic(unsigned type)
{
    unsigned started = operating.cycle_started;
    if (start_automatic(type)) operating.cycle_started = started;
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

static int cooling(const char *who)
{
    for (unsigned i=0;i<16;++i) {
        if (operating.cooldown[i].hz==RADIO_HZ && operating.cooldown[i].mode==ftx_ft4 &&
            (int32_t)(TICKS-operating.cooldown[i].until)<0 && !strcmp(who,operating.cooldown[i].call)) return 1;
    }
    return 0;
}

static void collect_search_row(const struct DisplayRow *r)
{
    char who[7];
    if (r->slot == operating.enabled_slot || !ft_row_eligible(r) || !sender(who,r))
        return;
    if (!directed(r) && cooling(who)) return;
    if (!directed(r) && ((operating.include[0] && strncmp(who,operating.include,strlen(operating.include))) ||
        (operating.exclude[0] && !strncmp(who,operating.exclude,strlen(operating.exclude))))) return;
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
    if (!selected && (operating.rest_mode || run_due())) return;
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
    if (operating.rest_mode || run_due()) return;
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
    int best_group = -1, best_score = INT32_MIN;
    struct DisplayRow chosen;
    unsigned positioned = operating.order > 1 && ftx_position();
    for (unsigned i=0;i<operating.search_count;++i) {
        const struct DisplayRow *candidate = &operating.search_rows[i];
        char who[7];
        if (!ft_row_eligible(candidate) || !sender(who,candidate)) continue;
        int worked = directed(candidate) ? 0 : ft_worked(who);
        if (worked > 0) continue;
        if (worked < 0) {
            if (i != pending) operating.search_rows[pending] = *candidate;
            ++pending;
            continue;
        }
        int group=directed(candidate)?2:!strncmp(candidate->text,"CQ ",3)?1:0;
        int score=operating.order==1?candidate->db:0;
        if (positioned) {
            int km=ftx_km(sender_grid(candidate));
            score=km<0?INT32_MIN:(operating.order==2?-km:km);
        }
        if (group>best_group || (group==best_group && score>best_score)) {
            chosen=*candidate;best_group=group;best_score=score;
        }
    }
    if (best_group >= 0) {
        ft_receive_row(&chosen,1);
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
        ((operating.running || operating.rest_mode || operating.choosing) &&
         (!clock || !ft_listen() || !mode_ok() || foreign_tx()))) stop_contact();

    if (operating.rest_mode) {
        ft_station_tick();
        if ((int32_t)(TICKS-operating.rest_until)>=0) {
            unsigned resume=operating.rest_mode;
            operating.rest_mode=0;
            start_automatic(resume);
        }
        return;
    }
    if (run_due()) {
        if (stage < KEY) enter_rest();
        else sequence_on=0;
        ft_station_tick();
        if (run_due() && stage < KEY) enter_rest();
        return;
    }

    if (operating.choosing && clock && age(slot,operating.offer_slot) > 1)
        stop_contact();

    const int idle = atomic_load(&stage) == IDLE;
    if (idle && sequence_on && has_sent && !operating.manual_cq && !operating.choosing &&
        kind < END_RR && attempts >= operating.tries && clock && age(slot,last_air) > 1) {
        unsigned next = operating.running ? operating.on_limit : LIMIT_STOP;
        if (next != LIMIT_STOP && partner[0]) {
            unsigned i=operating.next_cooldown++%16;
            memcpy(operating.cooldown[i].call,partner,strlen(partner)+1);
            unsigned limit=(operating.cool?operating.cool*60:86400-((ftx_ft4?15:30)*slot+ms/500)/2);
            operating.cooldown[i].until=TICKS+limit*1000u;
            operating.cooldown[i].hz=RADIO_HZ;
            operating.cooldown[i].mode=ftx_ft4;
        }
        stop_contact();
        if (next == LIMIT_NEXT) continue_automatic(AUTO_FIND);
        else if (next == LIMIT_CQ) continue_automatic(AUTO_CQ);
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
        if (resume) continue_automatic(resume);
        if (!operating.running) operating.completed = 1;
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

/* Let station setup, time and keyboards use their real pages. The parked
   contact stays intact while the menu temporarily owns the foreground. */
static void open_native_menu(void)
{
    if (overlay_page) {
        operating.native_context = NATIVE_PARKED_MENU;
        ft_page=FT_MENU;
        overlay_page=0;
    }
}

static void close_native_menu(void)
{
    if (operating.native_context == NATIVE_PARKED_MENU) {
        operating.native_context = NATIVE_RECEIVE;
        ft_page=FT_QSO;
        overlay_page=FT_MENU;
    }
}

int operating_touch(unsigned x, unsigned y)
{
    unsigned page=screen_page();
    int busy=running_contact();
    if (overlay_page && !busy && ft_page==FT_LIST) {ft_page=overlay_page;overlay_page=0;}
    if (overlay_page && busy && rail_hit(x,y,202)) {overlay_page=0;stop_contact();return 1;}
    if (page==FT_LOG) {
        if (rail_hit(x,y,237)) {screen_to(FT_MENU);return 1;}
        unsigned offset=journal_state[2],total=journal_state[1];
        if (atomic_load(journal_io)==0 && (rail_hit(x,y,89)||rail_hit(x,y,125))) {
            if(y<125 && offset>=7) offset-=7;
            if(y>=125 && total>offset+7) offset+=7;
            if(offset!=journal_state[2]) {journal_state[2]=offset;journal_state[15]=1;view_invalidate();}
        }
        return 1;
    }
    if (page == FT_LIST || page == FT_QSO) {
        if (ft_is_history() && x>=399) {
            unsigned top=busy?125:89;
            if (busy && rail_hit(x,y,89)) stop_contact();
            else if (rail_hit(x,y,top)) history_show(history_offset+1);
            else if (rail_hit(x,y,top+36)) history_show(history_offset?history_offset-1:0);
            else if (rail_hit(x,y,top+72)) history_leave();
            return 1;
        }
        if (ft_is_history()) {
            if(x<395 && ft_row_at(y)) ft_choose_row(y);
            return 1;
        }
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
            return primary_start();
        }
        if (rail_hit(x,y,237)) {
            if (is_confirmation()) return start_contact();
            menu_sheet=auto_sheet=operating.page=0;
            if (busy || ft_page==FT_QSO) overlay_page=FT_MENU;
            else ft_page=FT_MENU;
            view_invalidate(); return 1;
        }
        if (!running_contact() && !ft_is_history() && !ft_choice_row() && !operating.target_ready &&
            x>=399 && x<476 && y>=201 && y<234 && (x<436 || x>=439)) {
            pref.parity=x>=439;
            parity=pref.parity;
            save_prefs();
            view_invalidate();
            return 1;
        }
        return 0;
    }
    if (page==FT_MENU || page==FT_AUTO) {
        if (rail_hit(x,y,237)) {
            if (page==FT_AUTO) screen_to(FT_MENU);
            else if (operating.page == filter_page) operating.page=0;
            else screen_to(FT_LIST);
            view_invalidate();return 1;
        }
        unsigned *sheet=page==FT_MENU?&menu_sheet:&auto_sheet;
        if (operating.page!=filter_page && (rail_hit(x,y,89)||rail_hit(x,y,125))) {
            *sheet=y>=125;view_invalidate();return 1;
        }
        if (x>=395 || y<menu_top || y>=menu_top+5*menu_step || (y-menu_top)%menu_step>=27) return 1;
        unsigned row=(y-menu_top)/menu_step;
        if (page==FT_MENU) {
            if (operating.page!=filter_page) row+=5*menu_sheet;
            if (row>=8) return 0;
            if (busy && row!=0 && row!=2 && row!=3 && row!=5 && row!=6) return 1;
            if (operating.page==filter_page) {
                if (row>1) return 0;
                memcpy(edit,row?operating.exclude:operating.include,7);
                open_native_menu();
                operating.filter_edit=row+1;ft_page=FT_CALL;
            } else switch (row) {
                case 0: auto_sheet=0;screen_to(FT_AUTO);break;
                case 1: open_native_menu();edit[0]=0;operating.typing_target=1;ft_page=FT_CALL;break;
                case 2: history_open();screen_to(FT_LIST);break;
                case 3: journal_state[2]=0;journal_state[15]=1;screen_to(FT_LOG);break;
                case 4:
                    open_native_menu();return stock_ft_touch(100,177);
                case 5: operating.signal_sort^=1;operating_index_rows();ft_return_live();options_save();break;
                case 6: ft_history_action(2);screen_to(FT_LIST);break;
                case 7: operating.page=filter_page;break;
            }
            view_invalidate();return 1;
        }
        if (busy) return 1;
        unsigned choice=row+5*auto_sheet;
        if ((choice==1||choice==3||choice==5) && operating.mode!=FULL) return 1;
        if (choice==4 && operating.mode==FULL) return 1;
        switch (choice) {
            case 0: operating.mode = (operating.mode+1)%3; break;
            case 1: operating.auto_style = operating.auto_style == AUTO_CQ ? AUTO_FIND : AUTO_CQ; break;
            case 2: operating.tries = operating.tries%9+1; break;
            case 3: operating.order=(operating.order+1)%4;break;
            case 4: operating.multiple_first ^= 1; break;
            case 5: operating.on_limit = (operating.on_limit+1)%3; break;
            case 6: operating.cool=operating.cool==0?10:operating.cool==10?30:operating.cool==30?60:0;break;
            case 7: operating.timed^=1;break;
        }
        options_save();
        view_invalidate();
        return 1;
    } else if (ft_page == FT_SETUP && x<395 && y>=setup_top && y<setup_top+6*setup_step) {
        unsigned row=(y-setup_top)/setup_step;
        static const uint8_t native_y[]={130,130,163,163,196,229};
        if (row==4 && (y-tone_y>=tone_height ||
            (x-tone_minus>=tone_width && x-tone_plus>=tone_width))) return 0;
        unsigned right=(row==1 || row==3 || row==5 || (row==4 && x>=tone_plus));
        if (row==5) pref.call[7]=0;
        int handled=stock_ft_touch(right?265:90,native_y[row]);
        if (ft_page==FT_GRID) expand_grid(edit,pref.grid,station_detail());
        view_invalidate();return handled;
    } else if (ft_page==FT_GRID) {
        if (x>=417 && y>=156 && y<188) {
            if (!grid_valid(edit)) { notice="Use 4, 6 or 8 characters";view_invalidate();return 1; }
            memset(pref.grid,0,sizeof(pref.grid));
            for (unsigned i=0;i<4 && edit[i];++i) pref.grid[i]=edit[i];
            unsigned detail=grid_detail(edit);
            pref.call[7]='G';pref.call[8]=detail;pref.call[9]=detail>>8;
            notice=0;ft_page=FT_SETUP;view_invalidate();return 1;
        }
        unsigned n=strlen(edit);
        if (n>=4 && n<8 && x>=3 && x<354 && y>=127 && y<259 && (x-3)%39<37 && (y-127)%33<30) {
            unsigned key=(y-127)/33*9+(x-3)/39;
            if (key<36) { edit[n]="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"[key];edit[n+1]=0;notice=0;view_invalidate();return 1; }
        }
    } else if (ft_page == FT_CALL && operating.filter_edit && x>=417 && y>=156) {
        if (y>=228 || y<188) {
            if (y<188) { memcpy(operating.filter_edit==1?operating.include:operating.exclude,edit,strlen(edit)+1);options_save(); }
            operating.filter_edit=0;ft_page=FT_MENU;close_native_menu();view_invalidate();return 1;
        }
    } else if (ft_page == FT_CALL && operating.typing_target && x >= 417) {
        if (y >= 228) {
            operating.typing_target = 0;
            ft_page = FT_MENU;
            close_native_menu();
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
            operating.native_context = NATIVE_RECEIVE;
            return 1;
        }
    }
    page = ft_page;
    int handled = stock_ft_touch(x,y);
    if (page == FT_SETUP && ft_page == FT_QSO &&
        operating.native_context == NATIVE_SEND_SETUP) {
        operating.native_context = NATIVE_RECEIVE;
        ft_page = FT_LIST;
        view_invalidate();
    }
    if (ft_page==FT_MENU) close_native_menu();
    return handled;
}

static unsigned selected_flash(void)
{
    return *(volatile uint8_t *)0x2038089d ? 0x18000000u : 0x185f0000u;
}

static void label(const uint8_t *word,unsigned x,unsigned y,unsigned surface)
{
    uint8_t mask[120];
    unsigned ink=5;
    if(surface==CAPTION_DIM_KEY || surface==CAPTION_DIM_ROW) {
        ink=3;
        surface=surface==CAPTION_DIM_KEY?CAPTION_KEY:CAPTION_ROW;
    }
    unsigned flash=selected_flash();
    const uint16_t *colors=surface==CAPTION_KEY?(const uint16_t *)(flash+KEY_CAPTION_PALETTE):
        (const uint16_t *)(flash+FT_ART+CAPTION_PALETTE)+16*surface;
    if (surface==CAPTION_KEY) KEY_HEIGHT=33;
    for (;*word;++word,x+=16) {
        unsigned id=*word-1;
        unsigned offset=id<55?0x233300+60*id:id<77?0x235ac0+60*(id-55):
            id<95?0x261bc0+60*(id-77):0x5efa80+60*(id-95);
        const uint8_t *packed=id<118?(const uint8_t *)(flash+offset):(const uint8_t *)(flash+FT_ART+EXTRA_MASKS_OFFSET)+60*(id-118);
        for (unsigned i=0;i<60;++i) {
            unsigned value=packed[i];
            mask[2*i]=ink*(value&3)|(ink<<4)*((value>>2)&3);
            mask[2*i+1]=ink*((value>>4)&3)|(ink<<4)*(value>>6);
        }
        draw_glyph(mask,colors,x,y,16,surface==CAPTION_KEY?1:2);
    }
    if (surface==CAPTION_KEY) KEY_HEIGHT=0;
}

void operating_header(void)
{
    const float *background=v2_caption_background[CAPTION_HEADER];
    rectangle(background,0,86,360,16);
    rectangle(background,360,86,35,16);

}

static unsigned blend_channel(unsigned background,unsigned foreground,unsigned alpha)
{
    unsigned weighted=background*(255-alpha)+foreground*alpha+128;
    return (weighted+(weighted>>8))>>8; /* Round the 8-bit coverage without division. */
}

static uint16_t mix565(uint16_t background,uint16_t foreground,unsigned alpha)
{
    unsigned r=blend_channel(background>>11,foreground>>11,alpha);
    unsigned g=blend_channel(background>>5&63,foreground>>5&63,alpha);
    unsigned b=blend_channel(background&31,foreground&31,alpha);
    return (r<<11)|(g<<5)|b;
}

static void draw_slot_keys(unsigned selected,unsigned disabled)
{
    /* All three painters run in the LCD draw task and finish each write
       before reusing the native draw_glyph scratch. */
    uint16_t (*pixels)[48]=(void *)FT_GLYPH_PIXELS;
    static const uint16_t text_colors[]={0xffff,0xd77f,0x7c51,0x9d98};
    void (*blit)(const uint16_t *,int,unsigned,int,int,int,int)=(void *)PANEL_TILE;
    for (unsigned key=0;key<2;++key) {
        unsigned state=2*disabled+(key==selected);
        const uint8_t *atlas=(const uint8_t *)(selected_flash()+FT_ART);
        const uint16_t *colors=(const uint16_t *)(atlas+AB_COLORS_OFFSET);
        const uint8_t *face=atlas+face_offsets[state];
        for (unsigned row=0;row<33;) {
            /* The fold at y=221 falls on the boundary between chunks. */
            unsigned rows=33-row<4?33-row:4;
            for (unsigned i=0;i<rows;++i) {
                uint16_t *line=pixels[i];
                for (unsigned col=0;col<37;) {
                    unsigned count=*face++, rgb=colors[*face++];
                    for (unsigned end=col+count;col<end;++col) line[col]=rgb;
                }
                unsigned y=row+i;
                if (y>=9 && y<24) {
                    const uint8_t *caption=atlas+AB_LETTERS_OFFSET+135*key+(y-9)*9;
                    for (unsigned col=0;col<9;++col)
                        line[14+col]=mix565(line[14+col],text_colors[state],caption[col]);
                }
                for (unsigned col=0;col<48;col+=16)
                    __asm__ volatile("mcr p15,0,%0,c7,c10,1"::"r"(line+col):"memory");
            }
            __asm__ volatile("dsb sy":::"memory");
            int x=399+40*key, dx, dy;
            origin(x,201+row,&dx,&dy);
            blit(pixels[rows-1],-96,3,x+dx,272-201-row-rows-dy,37,rows);
            ((void (*)(void))PANEL_FINISH)();
            row+=rows;
        }
    }
}

static void slot_timer(void)
{
    unsigned period=ftx_ft4?7500:15000;
    if (operating.elapsed>=period) {
        ft_label("--.-s",401,153,13,15);
        return;
    }
    unsigned left=(period-operating.elapsed)/100;
    char timer[]="A 00.0s";
    timer[0]+=operating.rx_slot&1;timer[2]+=left/100;timer[3]+=left/10%10;timer[5]+=left%10;
    ft_label(timer,401,153,13,15);
}

static void page_number(unsigned index,unsigned total,unsigned x,unsigned y)
{
    char text[24], *end=digits(text,index+1);
    *end++='/';digits(end,total?total:1);ft_label(text,x,y,12,15);
}

static void word_key(const uint8_t *word,unsigned y,int enabled)
{
    unsigned n=0;
    while(word[n]) ++n;
    ft_key("",399,y,77,33);
    label(word,399+(77-16*n)/2,y+9,enabled?CAPTION_KEY:CAPTION_DIM_KEY);
}

static void action_key(unsigned y,int stop)
{
    ft_key("",399,y,77,33);
    unsigned stamp=stop ? 1+(ft_page==FT_LIST && ft_auto_armed && y!=89) : 0;
    const uint16_t *pixels=(const uint16_t *)(selected_flash()+FT_ART+ACTION_CAPTIONS)+stamp*48*16;
    void (*blit)(const uint16_t *,int,unsigned,int,int,int,int)=(void *)PANEL_TILE;
    unsigned top=y+8,bottom=top+16;
    unsigned fold=ft_page>=FT_MENU?231:221;
    for(unsigned at=top;at<bottom;) {
        unsigned end=at<fold && fold<bottom?fold:bottom;
        int dx,dy;
        origin(413,at,&dx,&dy);
        blit(pixels+(end-top-1)*48,-96,3,413+dx,272-end-dy,48,end-at);
        at=end;
    }
}

static unsigned preview_kind(const struct DisplayRow *r,const char *who)
{
    if (!r || !directed(r)) return LOCATOR;
    const char *last=r->text+r->flag-1+strlen(who);
    if (*last++!=' ') return LOCATOR;
    if (*last=='+'||*last=='-') return R_REPORT;
    if (!strcmp(last,"RR73")||!strcmp(last,"RRR")) return END_73;
    return *last=='R' && (last[1]=='-'||last[1]=='+')?END_RR:REPORT;
}

static __attribute__((noinline)) void preview_text(const char *who,unsigned step,int db,char *text)
{
    char suffix[6]={0};
    if (step==LOCATOR || step==CQ) {
        if (pref.grid[0]) memcpy(suffix,pref.grid,4);else ft_local_grid(suffix);
    } else if(step==REPORT || step==R_REPORT) {
        char *p=suffix;
        if(step==R_REPORT) *p++='R';
        db=db < -50?-50:db>49?49:db;
        *p++=db<0?'-':'+';
        unsigned v=db<0?-db:db;
        *p++='0'+v/10;*p='0'+v%10;
    } else memcpy(suffix,step==END_RR?"RR73":"73",step==END_RR?5:3);
    unsigned n=strlen(who), own=strlen(pref.call);
    memcpy(text,who,n);text[n++]=' ';memcpy(text+n,pref.call,own);n+=own;
    if(suffix[0]) text[n++]=' ';
    memcpy(text+n,suffix,strlen(suffix)+1);
}

void operating_draw_rail(void)
{
    const float *background=v2_caption_background[CAPTION_RAIL];
    static const float highlight[] = {.24f,.66f,.37f,1};
    /* The factory compositor folds the rightmost 120 pixels into three
       tiles. Each filled rectangle stays inside a single tile. */
    rectangle(background,397,89,83,64);
    rectangle(background,397,153,83,68);
    rectangle(background,397,221,83,51);
    const int running = running_contact();
    const struct DisplayRow *choice = ft_choice_row();
    char selected[7];
    const int can_chase = !running && !ft_is_history() && tail_target(choice,selected);
    const int history = ft_is_history();
    const int action = running || (!history && (operating.target_ready || !choice || ft_row_eligible(choice) || can_chase));
    if (action) action_key(89,running);
    else ft_key(history ? Z_live : Z_info,399,89,77,33);
    if (history) {
        unsigned top=running?125:89;
        word_key(v2_up,top,FT_FIRST+10<FT_COUNT);word_key(v2_down,top+36,history_offset!=0);word_key(v2_real,top+72,1);
        page_number(history_offset,(FT_COUNT+9)/10,400,254);
    } else {
        label(operating_modes[operating.mode],402,123,CAPTION_RAIL);
        ft_label(ftx_ft4?"FT4":"FT8",401,138,13,15);
        label(stage==SOUND||stage==DRAIN?v2_tx:v2_rx,427,137,CAPTION_RAIL);
        slot_timer();
        if(operating.rest_mode) {
            char seconds[12];digits(seconds,(operating.rest_until-TICKS+999)/1000);
            label(v2_rest,401,168,CAPTION_RAIL);ft_label(seconds,435,168,13,15);
        } else if(operating.choosing) label(v2_offered,401,168,CAPTION_RAIL);
        else if ((running && outgoing[0]) || choice || operating.target_ready) {
            unsigned k=choice && !running && sender(selected,choice)?preview_kind(choice,selected):kind;
            static const uint8_t *const steps[]={0,v2_first_call,v2_report,v2_reply_report,0,v2_ending};
            if(k<=END_73) {
                char number[]="1/6";number[0]+=k;ft_label(number,401,168,13,15);
                if(steps[k]) label(steps[k],429,167,CAPTION_RAIL);
                else ft_label(k==CQ?"CQ":"RR73",429,168,13,15);
            }
            if(running && attempts) {
                char count[12];digits(count,attempts);
                label(v2_n_sent,401,183,CAPTION_RAIL);ft_label(count,435,184,12,15);
                label(v2_times,452,183,CAPTION_RAIL);
            }
        }
        unsigned active=running?parity:choice?1-(choice->slot&1):pref.parity;
        draw_slot_keys(active,running || choice || operating.target_ready);
    }
    for (unsigned row=0;row<10;++row) {
        const unsigned y = 102+17*row;
        const struct DisplayRow *r = ft_row_at(y);
        if (r && directed(r)) {
            unsigned end = y < 153 ? 153 : y < 221 ? 221 : 272;
            rectangle(highlight,395,y,2,end-y < 15 ? end-y : 15);
        }
    }
    if (!history) ft_key(is_confirmation() ? Z_send : Z_menu,399,237,77,33);

}

static unsigned phase_tile(unsigned char c)
{
    if (c == ' ') return 0;
    if (c >= '0' && c <= '9') return 1+c-'0';
    if (c >= 'A' && c <= 'Z') return 11+c-'A';
    static const char punctuation[]="+-./?<>";
    for (unsigned i=0;punctuation[i];++i)
        if (c == punctuation[i]) return 37+i;
    return 41; /* Question mark. */
}

static void phase_message(const char *text,unsigned x,int transmitting)
{
    #include "phase-widths.h"
    static const uint16_t tx_colors[] = {
        0xa0a4,0xa926,0xa987,0xb209,0xba8b,0xbb0d,0xc36e,0xcbf0,
        0xcc72,0xd4f4,0xdd55,0xddd7,0xe659,0xeedb,0xef3c,0xf7be
    };
    unsigned flash=selected_flash();
    const uint16_t *colors=transmitting?tx_colors:
        (const uint16_t *)(flash+FT_ART+CAPTION_PALETTE)+16*CAPTION_HEADER;
    uint16_t *pixels=(void *)FT_GLYPH_PIXELS;
    void (*blit)(const uint16_t *,int,unsigned,int,int,int,int)=(void *)PANEL_TILE;
    for (;*text;++text) {
        unsigned index=phase_tile(*text);
        unsigned width=phase_width[index];
        if (!width) { x+=5; continue; }
        if (x+width>213) break;
        /* RX_CHARS splits before T, and '-' is the eighth tile after T. */
        unsigned offset=index<30?ROW_DIGITS+(index-1)*448:ROW_MINUS+(index-38)*448;
        const uint16_t *source=(const uint16_t *)(flash+offset);
        /* In the normal RX palette the four high red bits are exactly the
           original 4-bit Manrope coverage. Reuse it on either header color. */
        for (unsigned i=0;i<8*14;++i) pixels[i]=colors[source[i]>>12];
        for (unsigned i=0;i<8*14;i+=16)
            __asm__ volatile("mcr p15,0,%0,c7,c10,1"::"r"(pixels+i):"memory");
        __asm__ volatile("dsb sy":::"memory");
        blit(pixels+104,-16,3,x,171,width,14); /* Screen y=87..100. */
        ((void (*)(void))PANEL_FINISH)();
        x+=width+1;
    }
}

static void menu_path(const uint8_t *parent,const uint8_t *child,unsigned surface)
{
    ft_label(Z_menu " >",6,86,13,15);
    label(parent,55,86,surface);
    if (child) {
        ft_label(">",126,87,13,15);
        label(child,140,86,surface);
    }
}

static void draw_phase(void)
{
    const float *idle=v2_caption_background[CAPTION_HEADER];
    static const float tx[] = {165/255.f,20/255.f,33/255.f,1}; /* RGB565 0xa0a4. */
    const unsigned phase = atomic_load(&stage);
    const int transmitting = phase == SOUND || phase == DRAIN;
    if (ft_is_history()) {
        menu_path(v2_history,0,CAPTION_HEADER);
    } else {
        const int confirming=is_confirmation();
        const int sending=running_contact() && outgoing[0] && !operating.rest_mode;
        const struct DisplayRow *picked=ft_page==FT_LIST?ft_choice_row():0;
        char target[7];
        const char *selected=ft_page==FT_QSO && partner[0]?partner:sender(target,picked)?target:0;
        rectangle(transmitting && sending ? tx : idle,0,86,213,16);
        if (phase==IDLE && !sequence_on && notice) {
            ft_label(notice,3,86,13,15);
            return;
        }
        if (transmitting && sending) phase_message("TX",4,1);
        else label(confirming?v2_confirm:sending ? (phase==WAIT || phase==KEY?v2_pending:v2_sent) : selected?v2_draft :
                   (operating.rest_mode?v2_rest:v2_listen),3,86,CAPTION_HEADER);
        if (sending && !confirming) phase_message(outgoing,36,transmitting);
        else if (confirming || selected) {
            char packet[32];
            /* The TX encoder will rebuild outgoing on confirmation. Preview
               the selected QSO fields now, without editing the TX buffer. */
            preview_text(confirming?partner:selected,confirming?kind:preview_kind(picked,selected),
                         confirming?*(const int *)FT_TX_REPORT:picked?picked->db:0,packet);
            phase_message(packet,confirming?54:36,0);
        }
    }
}

void operating_slot_bar(unsigned slot, unsigned elapsed)
{
    static const float track[] = {.055f,.09f,.12f,1};
    static const float fill[] = {.22f,.70f,.90f,1};
    unsigned period = ftx_ft4 ? 7500 : 15000;
    unsigned stage_now=atomic_load(&stage);
    if (stage_now>=KEY && stage_now<=DRAIN) {
        /* RX sample timing stops on PTT. Use the same slot edge as the modulator. */
        slot=last_air;
        elapsed=TICKS-(FT_START_TICK-500u);
    } else {
        /* Both FT modes repeat their A/B cycle within a minute. Use the
           selected stock clock directly, even while the audio task is idle. */
        unsigned bcd=*(volatile uint8_t *)0x203807a0;
        if (bcd!=displayed_second) {
            displayed_second=bcd;
            displayed_edge=TICKS;
        }
        unsigned age=TICKS-displayed_edge;
        elapsed=~0u;
        if (bcd<0x60 && (bcd&15)<10 && age<2000) {
            unsigned minute=((bcd>>4)*10+(bcd&15))*1000+(age<1000?age:999);
            slot=minute/period;
            elapsed=minute%period;
        }
    }
    operating.rx_slot=slot;
    operating.elapsed=elapsed;
    unsigned width = elapsed<period?395*elapsed/period:0;
    rectangle(track,0,84,360,2);rectangle(track,360,84,35,2);
    if (width) rectangle(fill,0,84,width<360?width:360,2);
    if (width>360) rectangle(fill,360,84,width-360,2);
}

void operating_draw_slot(unsigned slot, unsigned elapsed)
{
    operating_slot_bar(slot,elapsed);
    operating_draw_rail();
    draw_phase();
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

void operating_row_digits(const char *text,unsigned x,unsigned y)
{
    unsigned flash=selected_flash();
    unsigned variant=ft_choice_row()==ft_row_at(y)?224:0;
    void (*blit)(const uint16_t *,int,unsigned,int,int,int,int)=(void *)PANEL_TILE;
    for (;*text;++text,x+=8) {
        unsigned glyph=*text=='-'?ROW_MINUS:ROW_DIGITS+448*(*text-'0');
        int dx,dy;
        origin(x,y-1,&dx,&dy);
        blit((const uint16_t *)(flash+glyph+variant+208),-16,3,x+dx,259-y-dy,8,14);
    }
}

void operating_row_number(int value,unsigned x,unsigned y)
{
    char text[8]={'-'};
    if (x==310 && value<0) {
        operating_row_digits("--",x,y);
        return;
    }
    if (x==280 && value<-99) x-=2;
    digits(text+1,value<0?-value:value);
    operating_row_digits(value<0?text:text+1,x,y);
}

void operating_distance_heading(void)
{
    operating_distance_text("km",352,88,13);
    if (!ft_is_history()) {
        rectangle(v2_caption_background[CAPTION_RAIL],401,153,76,15);
        slot_timer();
    }
    /* Even the cached RX-paused frame finishes its headings here. */
    draw_phase();
}

extern void ft_panel_draw(unsigned);

static void menu_band(unsigned y,unsigned height)
{
    const float *dark=v2_caption_background[CAPTION_ROW];
    static const float line[]={.16f,.22f,.27f,1};
    rectangle(dark,4,y,356,height-1);
    unsigned first=ft_page>=FT_MENU?159:153,second=ft_page>=FT_MENU?231:221;
    for(unsigned at=y,end=y+height-1;at<end;) {
        unsigned next=at<first?first:at<second?second:end;
        if(next>end)next=end;
        rectangle(dark,360,at,33,next-at);
        at=next;
    }
    rectangle(line,4,y+height-1,356,1);rectangle(line,360,y+height-1,33,1);
}

static void menu_value(unsigned y,unsigned h,const uint8_t *title,const uint8_t *value,const char *plain)
{
    unsigned surface=CAPTION_ROW;
    if (screen_page()==FT_MENU || screen_page()==FT_AUTO) {
        unsigned row=(y-row_top)/row_step, sheet=operating.page==filter_page?0:screen_page()==FT_MENU?menu_sheet:auto_sheet;
        if(row/5!=sheet)return;
        int busy=running_contact();
        if(screen_page()==FT_AUTO ? busy || (operating.mode!=FULL && (row==1 || row==3 || row==5)) || (operating.mode==FULL && row==4)
            : busy && (row==1 || row==4 || row>=7)) surface=CAPTION_DIM_ROW;
        y=menu_top+row%5*menu_step;h=27;
    }
    menu_band(y,h);
    y+=(h-17)/2;
    label(title,10,y+1,surface);
    if (value) label(value,value_x,y+1,surface);
    else ft_label(plain,value_x,y+2,12,15);
}

static void draw_page_background(void)
{
    const float *dark=v2_caption_background[CAPTION_RAIL];
    unsigned first=ft_page>=FT_MENU?159:153, second=ft_page>=FT_MENU?231:221;
    rectangle(dark,0,84,360,188);
    rectangle(dark,360,84,120,first-84);
    rectangle(dark,360,first,120,second-first);
    rectangle(dark,360,second,120,272-second);
}

/* Called by the existing card worker with the journal's selected, validated record. */
int operating_log_read(int fd,unsigned pos,char *view,unsigned size)
{
    unsigned count=0;
    if(size!=320)return 0;
    char *detail=view-(size+1);
    log_rows=(struct LogRow *)(((uintptr_t)view+3)&~(uintptr_t)3);
    log_count=0;
    for (;count<7 && pos>=40;++count) {
        if (!read_at(fd,pos,detail,size)) return 0;
        detail[size]=0;
        struct LogRow *row=&log_rows[count];
        char date[9],time[7];
        struct DisplayRow signal={0};
        field_get(detail,"<CALL:",row->call,sizeof(row->call));
        field_get(detail,"<GRIDSQUARE:",row->grid,sizeof(row->grid));
        field_get(detail,"<BAND:",row->band,sizeof(row->band));
        field_get(detail,"<QSO_DATE:",date,sizeof(date));field_get(detail,"<TIME_ON:",time,sizeof(time));
        row->utc[0]=0;
        if(strlen(date)==8 && strlen(time)>=4) {
            memcpy(row->utc,date+2,6);memcpy(row->utc+6,time,4);row->utc[10]=0;
        }
        memcpy(signal.text,row->call,strlen(row->call)+1);signal.flag=1;
        row->place=ft_place_id(&signal);
        if(row->place>FT_REGIONS+1)row->place=FT_CHINA;
        if (pos<40+size) {++count;break;}
        pos-=size;
    }
    log_count=count;log_offset=journal_state[2];return 1;
}

static void draw_log(void)
{
    draw_page_background();menu_path(v2_log,0,CAPTION_RAIL);
    label(v2_hdr_call,5,107,CAPTION_RAIL);ft_label("DXCC",95,108,12,15);
    label(v2_hdr_grid,182,107,CAPTION_RAIL);label(v2_hdr_band,238,107,CAPTION_RAIL);ft_label("UTC",280,108,12,15);
    unsigned offset=journal_state[2],total=journal_state[1];
    if(atomic_load(journal_io)!=1 && !journal_state[15] && !journal_state[12] && total && offset==log_offset) {
        for(unsigned i=0;i<log_count;++i) {
            const struct LogRow *r=&log_rows[i];unsigned y=123+21*i;
            ft_label(r->call,5,y,12,15);ft_place_label(r->place,95,y);
            ft_label(r->grid,182,y,12,15);ft_label(r->band,238,y,12,15);
            operating_distance_text(r->utc,280,y,12);
        }
    } else if (!total) ft_label(Z_empty,6,130,13,15);
    word_key(v2_up,89,offset>0);word_key(v2_down,125,total>offset+7);
    if(total>7)page_number(offset/7,(total+6)/7,424,165);
    if(overlay_page && running_contact()) action_key(202,1);
    ft_key(Z_back,399,237,77,33);
}

void operating_draw_page(unsigned full)
{
    if (screen_page() == FT_LOG) {
        draw_log();
        return;
    }
    if (screen_page() == FT_SETUP) {
        char grid[9], hz[]="0000 Hz";
        expand_grid(grid,pref.grid,station_detail());
        unsigned f=pref.hz;
        for (int i=3;i>=0;--i){hz[i]='0'+f%10;f/=10;}
        draw_page_background();menu_path(v2_station,0,CAPTION_RAIL);
        menu_value(setup_top,setup_step,v2_mycall,0,pref.call);
        menu_value(setup_top+setup_step,setup_step,v2_mygrid,0,grid[0]?grid:"AUTO");
        menu_value(setup_top+2*setup_step,setup_step,v2_slot,0,pref.parity?"B":"A");
        menu_value(setup_top+3*setup_step,setup_step,v2_follow,pref.follow?v2_follow:0,"FIXED");
        menu_value(setup_top+4*setup_step,setup_step,v2_tone,0,hz);
        ft_key("-",tone_minus,tone_y,tone_width,tone_height);
        ft_key("+",tone_plus,tone_y,tone_width,tone_height);
        menu_value(setup_top+5*setup_step,setup_step,v2_gps,0,">");
        ft_key(Z_save,417,229,61,39);
        if (notice) ft_label(notice,6,251,12,15);
        return;
    }
    if (screen_page() != FT_MENU && screen_page() != FT_AUTO) {
        ft_panel_draw(full);
        if (ft_page==FT_CALL || ft_page==FT_GRID || ft_page==FT_INFO) {
            const float *bar=v2_caption_background[CAPTION_HEADER];
            rectangle(bar,0,86,360,16);
            if (ft_page==FT_INFO) {
                ft_label(Z_menu " >",6,86,13,15);
                ft_label(Z_heard,55,86,13,15);
            }
            else if (operating.typing_target) menu_path(v2_target,0,CAPTION_HEADER);
            else if (operating.filter_edit)
                menu_path(v2_filter,operating.filter_edit==1?v2_include:v2_exclude,CAPTION_HEADER);
            else menu_path(v2_station,ft_page==FT_CALL?v2_mycall:v2_mygrid,CAPTION_HEADER);
        }
        if (ft_page==FT_GRID && notice) ft_label(notice,6,105,12,15);
        return;
    }
    draw_page_background();
    if (screen_page() == FT_MENU) {
        if (operating.page==filter_page) {
            menu_path(v2_filter,0,CAPTION_RAIL);
            menu_value(row_top,row_step,v2_include,0,operating.include);
            menu_value(row_top+row_step,row_step,v2_exclude,0,operating.exclude);
        } else {
            ft_label(Z_menu,6,86,13,15);
            menu_value(row_top,row_step,v2_mode,operating_modes[operating.mode],0);
            menu_value(row_top+row_step,row_step,v2_target,0,">");
            menu_value(row_top+2*row_step,row_step,v2_history,0,">");
            menu_value(row_top+3*row_step,row_step,v2_log,0,">");
            menu_value(row_top+4*row_step,row_step,v2_station,0,">");
            menu_value(row_top+5*row_step,row_step,v2_sort,operating.signal_sort?v2_strong:v2_arrival,0);
            menu_value(row_top+6*row_step,row_step,cq_only?v2_all:v2_cq,0,"");
            menu_value(row_top+7*row_step,row_step,v2_filter,0,">");
        }

    } else {
        static const uint8_t *const limits[] = {v2_stop,v2_next,0};
        static const uint8_t *const orders[] = {v2_first_rx,v2_strong,v2_near,v2_far};
        char retry[]={(char)('0'+operating.tries),0};
        char cool[]="00 min";cool[0]+=operating.cool/10;cool[1]+=operating.cool%10;
        menu_path(v2_mode,0,CAPTION_RAIL);
        menu_value(row_top,row_step,v2_mode,operating_modes[operating.mode],0);
        menu_value(row_top+row_step,row_step,v2_start_as,operating.auto_style==AUTO_CQ?0:v2_scan,"CQ");
        menu_value(row_top+2*row_step,row_step,v2_tries,0,retry);
        menu_value(row_top+3*row_step,row_step,v2_order,orders[operating.order],0);
        menu_value(row_top+4*row_step,row_step,v2_multi,operating.multiple_first?v2_first:v2_choose,0);
        menu_value(row_top+5*row_step,row_step,v2_limit,limits[operating.on_limit],"CQ");
        menu_value(row_top+6*row_step,row_step,v2_cool,operating.cool?0:v2_day,cool);
        menu_value(row_top+7*row_step,row_step,v2_timer,operating.timed?0:v2_continuous,"45 / 5 min");

    }
    if(operating.page!=filter_page) {
        unsigned sheet=screen_page()==FT_MENU?menu_sheet:auto_sheet;
        word_key(v2_up,89,sheet!=0);word_key(v2_down,125,sheet==0);
        page_number(sheet,2,424,165);
    }
    if(overlay_page && running_contact()) action_key(202,1);
    ft_key(Z_back,399,237,77,33);
}

int operating_overlay_draw(void)
{
    if(ft_is_history()) {
        unsigned pages=FT_COUNT?(FT_COUNT+9)/10:1;
        if(history_offset>=pages) history_offset=pages-1;
        FT_FIRST=history_offset*10;
    }
    if(!overlay_page)return 0;
    operating_draw_page(1);return 1;
}
