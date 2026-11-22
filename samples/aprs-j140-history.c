/* Receive history in the stock QUICK picker. The audio task owns the ring. */
#include "aprs-j140-popup.h"

#pragma GCC optimize ("Os")

#ifdef APRS_SLOT_UI
enum { QUICK_MENU = 1, APRS_HISTORY = 170 };
extern void aprs_slot_history_open(void);
extern void aprs_ui_deferred(unsigned);
#else
enum { QUICK_MENU = 1, APRS_HISTORY = 281 };
#endif
#define REG8(a) (*(volatile uint8_t *)(a))
#define REG16(a) (*(volatile uint16_t *)(a))

extern uint32_t aprs_record_count;
extern volatile uint32_t aprs_channel_hz;
extern uint8_t aprs_tx_enabled;

struct timestamp {
    uint8_t date[3], time[3];
};

static struct received {
    unsigned sequence;
    uint16_t icon;
    struct timestamp stamp;
} arrival[RECORD_SLOTS] APRS_KEEP;

struct history_row {
    char station[10];
    uint16_t icon, distance;
    struct timestamp stamp;
#ifdef APRS_SLOT_UI
    char owner[10];
    uint8_t entity,removed;
#endif
};
static struct history_row aprs_history_rows[RECORD_SLOTS];
uint8_t aprs_history_last, aprs_history_choice;
const char aprs_history_title[] = "APRS RX List";

/* The installer fills these from the region's native picker data. */
extern const uint32_t aprs_quick_menu[5], aprs_history_descriptor;
static unsigned quick_extended;
static unsigned history_base, history_index;

void aprs_history_begin_record(unsigned sequence)
{
    __atomic_store_n(&arrival[sequence % RECORD_SLOTS].sequence, 0, __ATOMIC_RELAXED);
    __atomic_thread_fence(__ATOMIC_RELEASE);
}

static void local_timestamp(struct timestamp *stamp)
{
    /* Stock RTC cache: BCD year, month, day, weekday, hour, minute, second. */
    volatile const uint8_t *rtc = (volatile const uint8_t *)0x2038079a;
    unsigned second;
    do {
        second = rtc[6];
        for (unsigned i = 0; i < 3; ++i) {
            stamp->date[i] = rtc[i];
            stamp->time[i] = rtc[4+i];
        }
    } while (second != stamp->time[2]);
}

#ifdef APRS_SLOT_UI
static uint8_t unread_bits[8] APRS_KEEP;
#endif
void aprs_history_commit_record(unsigned sequence, unsigned icon)
{
    struct received *item = arrival + sequence % RECORD_SLOTS;
    local_timestamp(&item->stamp);
    item->icon = icon;
#ifdef APRS_SLOT_UI
    uint8_t mask=1u<<(sequence%8);
    if (icon==MESSAGE) __atomic_fetch_or(&unread_bits[sequence%64/8],mask,__ATOMIC_RELAXED);
    else __atomic_fetch_and(&unread_bits[sequence%64/8],(uint8_t)~mask,__ATOMIC_RELAXED);
#endif
    __atomic_store_n(&item->sequence, sequence + 1, __ATOMIC_RELEASE);
}

static unsigned stamp_text(char *out, const uint8_t *fields, unsigned date)
{
    static const uint8_t limits[2][3] = {{0x23, 0x59, 0x59}, {0x99, 0x12, 0x31}};
    unsigned valid = !date || (fields[1] && fields[2]);
    for (unsigned i = 0; i < 3; ++i) {
        if (fields[i] > limits[date][i] || (fields[i] & 15) > 9)
            valid = 0;
    }
    for (unsigned i = 0; i < 3; ++i) {
        *out++ = valid ? '0' + (fields[i] >> 4) : '-';
        *out++ = valid ? '0' + (fields[i] & 15) : '-';
        *out++ = date ? '-' : ':';
    }
    out[-1] = 0;
    return valid;
}

#ifdef APRS_SLOT_UI
static uint8_t message_rows[RECORD_SLOTS], inbox, visible_rows;
static unsigned stations, order;
unsigned aprs_station_filter;
static int cmp(const char *a,const char *b)
{
    while (*a && *a==*b) { ++a;++b; }
    return (uint8_t)*a-(uint8_t)*b;
}
static void identity(struct history_row *row,const struct output_frame *record,unsigned slot,unsigned sequence)
{
    unsigned n=7;
    while (n+2<record->length && !(record->bytes[n-1]&1)) n+=7;
    if (n+2>=record->length) return;
    unsigned type=record->bytes[n+2];
    if (type!='}' && type!=';' && type!=')') return;
    struct output_frame copy=*record;
    if (__atomic_load_n(&arrival[slot].sequence,__ATOMIC_ACQUIRE)!=sequence) return;
    static struct popup_packet parsed;
    aprs_parse_packet(&parsed,&copy);
    __builtin_memcpy(row->owner,parsed.station,sizeof(row->owner));
    row->entity=parsed.entity[0] ? 1+parsed.item : 0;
    row->removed=parsed.removed;
    __builtin_memcpy(row->station,row->entity ? parsed.entity : parsed.station,sizeof(row->station));
}
static void station_view(void)
{
    unsigned unique=0,shown=0;
    for (unsigned i=0;i<visible_rows;++i) {
        struct history_row *r=&aprs_history_rows[i];
        if (!r->station[0]) continue;
        unsigned j=0;
        while (j<unique) {
            struct history_row *old=&aprs_history_rows[j];
            if (r->entity==old->entity && !cmp(r->station,old->station) &&
                (!r->entity || !cmp(r->owner,old->owner))) break;
            ++j;
        }
        if (j==unique) {
            aprs_history_rows[j]=*r;message_rows[j]=message_rows[i];++unique;
        }
    }
    for (unsigned i=0;i<unique;++i) {
        struct history_row r=aprs_history_rows[i];
        if (r.removed || (aprs_station_filter==1 && r.distance==APRS_NO_DISTANCE) ||
            (aprs_station_filter==2 && (r.icon&255)!='_') ||
            (aprs_station_filter==3 && !r.entity)) continue;
        unsigned offset=message_rows[i],j=shown++;
        while (j) {
            struct history_row *prev=&aprs_history_rows[j-1];
            if (!(order==1 ? cmp(prev->station,r.station)>0 :
                  order==2 && (prev->distance&0x7fff)>(r.distance&0x7fff))) break;
            aprs_history_rows[j]=*prev;message_rows[j]=message_rows[j-1];--j;
        }
        aprs_history_rows[j]=r;message_rows[j]=offset;
    }
    visible_rows=shown;
}
#endif
static void history_snapshot(void)
{
    history_base = __atomic_load_n(&aprs_record_count, __ATOMIC_ACQUIRE);
    history_index = 0;
#ifdef APRS_SLOT_UI
    visible_rows=0;
#endif
    unsigned count = history_base < RECORD_SLOTS ? history_base : RECORD_SLOTS;
    aprs_history_last = count ? count - 1 : 0;
    if (!count) {
        aprs_history_rows[0].station[0] = 0;
        return;
    }
    for (unsigned i = 0; i < count; ++i) {
        unsigned sequence = history_base - i;
        unsigned slot = (sequence - 1) % RECORD_SLOTS;
        const struct received *item = arrival + slot;
#ifdef APRS_SLOT_UI
        if (inbox && item->icon!=MESSAGE) continue;
        message_rows[visible_rows]=i;
        struct history_row *row=aprs_history_rows+visible_rows++;
#else
        struct history_row *row = aprs_history_rows + i;
#endif
        unsigned start = __atomic_load_n(&item->sequence, __ATOMIC_ACQUIRE);
        row->station[aprs_call_text(row->station, aprs_record_slot(slot)->bytes + 7)] = 0;
        row->stamp = item->stamp;
        row->icon = item->icon == 0xfffe ? MESSAGE : item->icon;
        row->distance = aprs_record_slot(slot)->distance;
#ifdef APRS_SLOT_UI
        row->entity=row->removed=0;
        identity(row,aprs_record_slot(slot),slot,sequence);
#endif
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if (start != sequence || __atomic_load_n(&item->sequence, __ATOMIC_RELAXED) != sequence)
            row->station[0] = 0;
    }
#ifdef APRS_SLOT_UI
    if (stations) station_view();
    aprs_history_last=visible_rows ? visible_rows-1 : 0;
    if (!visible_rows) aprs_history_rows[0].station[0]=0;
#endif
}

void aprs_history_resume(void)
{
    if ((REG8(0x203e2128) >> 4) != 7)
        return;
#ifdef APRS_SLOT_UI
    aprs_slot_history_open();
#else
    *(uint8_t *)(aprs_history_descriptor + 1) = aprs_history_last;
    REG16(0x203e1b1a) = 0x0202;
    ((void (*)(unsigned, unsigned))0x200cd628)(APRS_HISTORY, 0xffff);
#endif
}

#ifdef APRS_SLOT_UI
unsigned aprs_inbox_active(void) { return inbox; }
unsigned aprs_stations_active(void) { return stations; }
void aprs_stations_open(unsigned sort) { inbox=0;stations=1;order=sort;history_snapshot();aprs_history_resume(); }
void aprs_inbox_open(void) { stations=0;inbox=1;history_snapshot();aprs_history_resume(); }
#endif
void aprs_history_open(void)
{
#ifdef APRS_SLOT_UI
    inbox=stations=0;
#endif
    history_snapshot();
    aprs_history_resume();
}

unsigned aprs_quick_history(unsigned *result)
{
    /* QUICK child callbacks return "handled"; the stock picker reads the tone here. */
    *result = 1;
    ((void (*)(void (*)(void)))0x200cd7dc)(aprs_history_open);
    return 1;
}

unsigned aprs_quick_hide(unsigned index)
{
    if (index < quick_extended)
        return 0;
    return ((unsigned (*)(unsigned))0x200ce880)(index - quick_extended);
}

unsigned aprs_quick_open(unsigned id, unsigned parent)
{
    if (id == QUICK_MENU) {
        quick_extended = aprs_channel_hz && aprs_plain_fm() && !(REG8(0x203809a1) & 0x10)
            ? 1 + aprs_tx_enabled : 0;
        uint32_t *menu = (uint32_t *)aprs_quick_menu[0];
        ((uint8_t *)menu)[1] = 14 + quick_extended;
        menu[68/4] = aprs_quick_menu[1 + quick_extended];
        /* Keep the original saved choice in stock row numbering. */
        menu[36/4] = quick_extended ? 0 : aprs_quick_menu[4];
    }
    return ((unsigned (*)(unsigned, unsigned))0x200cd628)(id, parent);
}

unsigned aprs_history_initial(void)
{
    return history_index;
}

unsigned aprs_history_hide(unsigned index)
{
    (void)index;
    return 0;
}

static void history_show_packet(void)
{
#ifdef APRS_SLOT_UI
    /* Opening the stock position popup closes its selector internally. Its
       close callback must not navigate to the stations menu as a user EXIT. */
    aprs_ui_deferred(1);
#endif
#ifdef APRS_SLOT_UI
    unsigned sequence=history_base-message_rows[history_index];
#else
    unsigned sequence = history_base - history_index;
#endif
    unsigned slot = (sequence - 1) % RECORD_SLOTS;
    const struct received *item = arrival + slot;
    struct output_frame copy;
    if (__atomic_load_n(&item->sequence, __ATOMIC_ACQUIRE) == sequence) {
        const struct output_frame *record = aprs_record_slot(slot);
        copy.length = record->length;
        if (copy.length >= 18 && copy.length <= FRAME_MAX) {
            for (unsigned i = 0; i < copy.length; ++i)
                copy.bytes[i] = record->bytes[i];
            __atomic_thread_fence(__ATOMIC_ACQUIRE);
            if (__atomic_load_n(&item->sequence, __ATOMIC_RELAXED) == sequence) {
                aprs_parse_packet(&aprs_popup_packet, &copy);
                unsigned opened=aprs_open_history_detail();
#ifdef APRS_SLOT_UI
                aprs_ui_deferred(0);
#endif
                if (opened)
                    return;
            }
        }
    }
#ifdef APRS_SLOT_UI
    aprs_ui_deferred(0);
    if (inbox) { aprs_inbox_open();return; }
    if (stations) { aprs_stations_open(order);return; }
#endif
    aprs_history_open();  /* The selected record expired while the list was open. */
}

#ifdef APRS_SLOT_UI
void aprs_inbox_mark(unsigned unread)
{
    unsigned seq=history_base-message_rows[history_index], slot=(seq-1)%RECORD_SLOTS;
    if (__atomic_load_n(&arrival[slot].sequence,__ATOMIC_ACQUIRE)!=seq) return;
    uint8_t mask=1u<<(slot%8);
    if (unread) __atomic_fetch_or(&unread_bits[slot/8],mask,__ATOMIC_RELAXED);
    else __atomic_fetch_and(&unread_bits[slot/8],(uint8_t)~mask,__ATOMIC_RELAXED);
}
void aprs_inbox_read(void) { aprs_inbox_mark(0);history_show_packet(); }
#endif
unsigned aprs_history_select(void)
{
#ifdef APRS_SLOT_UI
    if (!visible_rows) return 0;
#endif
    if (!history_base)
        return 0;
    history_index = aprs_history_choice;
#ifdef APRS_SLOT_UI
    aprs_ui_deferred(1);
    if (inbox) {
        extern void aprs_inbox_actions(void);
        ((void (*)(void (*)(void)))0x200cd7dc)(aprs_inbox_actions);return 1;
    }
#endif
    ((void (*)(void (*)(void)))0x200cd7dc)(history_show_packet);
    return 1;
}

void aprs_history_text(unsigned layer, unsigned rect, const char *title, unsigned length,
                       unsigned format, unsigned font, unsigned color, const uint16_t *xy,
                       unsigned align, unsigned language)
{
    typedef void (*stock_text)(unsigned, unsigned, const char *, unsigned, unsigned, unsigned,
                               unsigned, const uint16_t *, unsigned, unsigned);
    stock_text draw = (stock_text)0x20142698;
#ifdef APRS_SLOT_UI
    /* The input task can already be in the detail popup while this LCD frame
       is halfway through its four rows. Match the compositor's snapshot. */
    unsigned picker=REG16(0x204bd0f8);
    unsigned first=4u*(REG8(0x204bd0fa)-1u);
#else
    unsigned picker=REG16(0x203e1a28),first=REG8(0x203e1a2b);
#endif
    if (picker != APRS_HISTORY || rect < 1608 || rect > 1611) {
        if (aprs_symbol_catalog_text(layer,rect,format,font,color,xy,align,language)) return;
        draw(layer, rect, title, length, format, font, color, xy, align, language);
        return;
    }
    unsigned index = first + rect - 1608;
    if (index > aprs_history_last)
        return;
    const struct history_row *row = aprs_history_rows + index;
    if (!history_base || !row->station[0]) {
        const char *message = history_base ? "Record expired" : "No APRS packets";
        unsigned n=history_base ? 14 : 15;
#ifdef APRS_SLOT_UI
        if (inbox && !visible_rows) { message="No messages";n=11; }
        if (stations && !visible_rows) { message="No stations";n=11; }
#endif
        draw(layer, rect, message, n, format, font, color, xy, align, language);
        return;
    }
    length = 0;
    while (row->station[length])
        ++length;
    uint16_t box[8], call_xy[] = {42, xy[1]}, clock_xy[] = {292, xy[1]-11};
    ((void (*)(uint16_t *, unsigned, unsigned))0x201420b4)(box, 0, rect);
    aprs_draw_icon(row->icon, box[1]+10, box[2]+19, color == 17 ? 0x5d19 : 0);
#ifdef APRS_SLOT_UI
    if (inbox) {
        unsigned slot=(history_base-1-message_rows[index])%RECORD_SLOTS;
        if (unread_bits[slot/8] & (1u<<(slot%8))) {
            uint16_t star_xy[]={28,xy[1]};
            draw(layer,rect,"*",1,format,font,color,star_xy,align,language);
        }
    }
#endif
    if (row->distance != APRS_NO_DISTANCE)
        call_xy[1] = clock_xy[1];
    draw(layer, rect, row->station, length, format, font, color, call_xy, align, language);
    if (row->distance != APRS_NO_DISTANCE) {
        char distance[16];
        aprs_distance_text(distance, row->distance);
        unsigned n = 0;
        while (distance[n])
            ++n;
        call_xy[1] += 22;
        draw(layer, rect, distance, n, format, font, color, call_xy, align, language);
    }
    char time[9], date[11];
    stamp_text(time, row->stamp.time, 0);
    unsigned valid_date = stamp_text(date+2, row->stamp.date, 1);
    date[0] = valid_date ? '2' : '-';
    date[1] = valid_date ? '0' : '-';
    draw(layer, rect, time, 8, format, font, color, clock_xy, 2, language);
    clock_xy[1] += 22;
    draw(layer, rect, date, 10, format, font, color, clock_xy, 2, language);
}
