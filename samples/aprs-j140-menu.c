/* APRS settings reached from the stock GPS list. */
#include "aprs-j140-popup.h"

#pragma GCC optimize ("Os")

enum { GPS_MENU = 218, STOCK_COMMENT_EDITOR = 349, GPS_TX_SETTING = 478,
       APRS_RX_MENU = 277, APRS_SSID_MENU = 285, APRS_SYMBOL_LIST = 306 };
enum { SETTINGS, MODE, NOTICE, COMMENT, PATH, SYMBOL, SYMBOL_LIST, OVERLAY_BASE, OVERLAY_LIST, AUTO, INTERVAL };
#define REG8(a) (*(volatile const uint8_t *)(a))

extern volatile uint32_t aprs_channel_hz;
uint32_t aprs_active_frequency(void);
void aprs_set_channel(uint32_t hz);

uint32_t aprs_menu_choice;
uint8_t aprs_beacon_ssid APRS_KEEP, aprs_ssid_choice, aprs_tx_enabled APRS_KEEP;
char aprs_menu_title[16];
char aprs_menu_mode[32], aprs_menu_channel[32], aprs_menu_beacon[24];
char aprs_settings_path[26];
char aprs_settings_symbol[14], aprs_settings_auto[18], aprs_settings_interval[26];
const char aprs_gps_mode_name[] = "APRS";
const char aprs_beacon_title[] = "Send APRS Beacon";
const char aprs_ssid_title[] = "Beacon SSID";
const char aprs_comment_title[] = "Beacon Comment";
const char aprs_path_title[] = "TX Path";
const char aprs_symbol_title[] = "Beacon Symbol";
static const char auto_title[] = "Auto Beacon", interval_title[] = "Beacon Interval";
static const char *const tx_paths[] = {"Direct", "WIDE2-1", "WIDE1-1,WIDE2-1"};
uint8_t aprs_tx_path APRS_KEEP;
extern const uint32_t aprs_settings_descriptor, aprs_symbol_descriptor;
const char *aprs_beacon_start(void);
static uint32_t selected_hz APRS_KEEP, offered_hz;
static uint8_t page, settings_index;
uint8_t comment_saved APRS_KEEP;
char saved_comment[APRS_BEACON_COMMENT_MAX+1] APRS_KEEP;
char saved_symbol[2] APRS_KEEP;
static uint16_t catalog_symbols[94];
static uint8_t catalog_count, symbol_group;
static uint16_t overlay_base;

const char *aprs_beacon_symbol(void)
{
    return saved_symbol[0] ? saved_symbol : "/-";
}

const char *aprs_beacon_comment(void)
{
    return comment_saved ? saved_comment : "ICOM IC-705 APRS TEST";
}

static uint32_t current_fm(void)
{
    return aprs_plain_fm() && !(REG8(0x203809a1) & 0x10)
        ? *(volatile const uint32_t *)0x20380714 : 0;
}

static char *append(char *out, const char *text)
{
    while (*text)
        *out++ = *text++;
    *out = 0;
    return out;
}

__attribute__((optimize("O2"), noinline)) static void frequency_text(char *out, uint32_t hz)
{
    unsigned mhz = hz / 1000000;
    if (mhz >= 100)
        *out++ = '0' + mhz / 100;
    if (mhz >= 10)
        *out++ = '0' + mhz / 10 % 10;
    *out++ = '0' + mhz % 10;
    *out++ = '.';
    hz %= 1000000;
    for (unsigned scale = 100000; scale; scale /= 10) {
        unsigned digit = 0;
        while (hz >= scale) {
            hz -= scale;
            ++digit;
        }
        *out++ = '0' + digit;
        if (scale <= 1000 && !hz)
            break;
    }
    append(out, " MHz");
}

static void show_selector(unsigned id)
{
    *(volatile uint16_t *)0x203e1b1a = 0x0202;
    ((void (*)(unsigned, unsigned))0x200cd628)(id, 0xffff);
}

static void show_settings(unsigned last)
{
    *(uint8_t *)(aprs_settings_descriptor+1) = last;
    show_selector(APRS_RX_MENU);
}

void aprs_menu_open(void);
void aprs_ssid_open(void);
static void show_aprs_settings(void);

unsigned aprs_save_comment(const char *text, uint8_t *action)
{
    unsigned length = 0;
    while (length < APRS_BEACON_COMMENT_MAX && text[length]) {
        if ((unsigned char)text[length] < ' ' || (unsigned char)text[length] > '~') {
            *action = 0;
            return 0;
        }
        ++length;
    }
    while (length && text[length-1] == ' ')
        --length;
    for (unsigned i = 0; i < length; ++i)
        saved_comment[i] = text[i];
    saved_comment[length] = 0;
    comment_saved = 1;
    *action = 4;  /* Native ENT commits the value and returns to its parent menu. */
    return 1;
}

unsigned aprs_load_comment_editor(void)
{
    if (page != COMMENT)
        return 0;
    char text[APRS_BEACON_COMMENT_MAX];
    const char *comment = aprs_beacon_comment();
    for (unsigned i = 0; i < sizeof(text); ++i)
        text[i] = *comment ? *comment++ : ' ';
    ((void (*)(unsigned, unsigned, const char *, unsigned, unsigned,
               unsigned (*)(const char *, uint8_t *)))0x20055a0c)(
        62, 0, text, sizeof(text), 2, aprs_save_comment);
    return 1;
}

static void edit_comment(void)
{
    ((void (*)(void))0x200cd828)();
    page = COMMENT;
    ((void (*)(unsigned))0x200f1600)(STOCK_COMMENT_EDITOR);
}

unsigned aprs_after_editor_navigation(void)
{
    unsigned result = ((unsigned (*)(void))0x200ebdf4)();
    unsigned menu = *(volatile const uint16_t *)0x203e84c9;
    if (page == COMMENT && menu != STOCK_COMMENT_EDITOR) {
        page = SETTINGS;
        if (menu == GPS_MENU)
            show_aprs_settings();
    }
    return result;
}

static void use_current(void)
{
    if (offered_hz && current_fm() == offered_hz && selected_hz != offered_hz) {
        selected_hz = offered_hz;
        if (aprs_channel_hz)
            aprs_set_channel(selected_hz);
        aprs_beacon_reschedule();
    }
    aprs_menu_open();
}

static void show_mode(void)
{
    unsigned available = selected_hz || current_fm();
    page = MODE;
    append(aprs_menu_title, "APRS Mode");
    append(aprs_menu_mode, available ? "RX Only" : "RX Only (tune FM first)");
    append(aprs_menu_channel, available ? "RX & TX" : "RX & TX (tune FM first)");
    show_settings(1);
}

unsigned aprs_gps_mode_tap(unsigned row)
{
    const volatile uint16_t *list = (const volatile uint16_t *)0x203804c8;
    if (list[6] != GPS_TX_SETTING)
        return 0;
    if (row + list[9] == 3) {
        show_mode();
        return 1;
    }
    if (aprs_channel_hz) {
        aprs_tx_enabled = 0;
        aprs_set_channel(0);
    }
    return 0;
}

static void apply_mode(void)
{
    if (!selected_hz)
        selected_hz = current_fm();
    if (!selected_hz) {
        show_mode();
        return;
    }
    volatile uint8_t *dv_mode = (volatile uint8_t *)0x203eb172;
    if (*dv_mode) {
        *dv_mode = 0;
        ((void (*)(unsigned))0x200a27a4)(GPS_TX_SETTING);
    }
    if (aprs_tx_enabled != aprs_menu_choice)
        aprs_beacon_reschedule();
    aprs_tx_enabled = aprs_menu_choice;
    aprs_set_channel(selected_hz);
    *(volatile uint16_t *)0x203804d8 = 3;
    ((void (*)(void))0x200cd828)();
}

static void show_path(void)
{
    page = PATH;
    append(aprs_menu_title, aprs_path_title);
    append(aprs_menu_mode, tx_paths[0]);
    append(aprs_menu_channel, tx_paths[1]);
    append(aprs_menu_beacon, tx_paths[2]);
    show_settings(2);
}

static void show_symbol(void)
{
    page = SYMBOL;
    append(aprs_menu_title, aprs_symbol_title);
    append(aprs_menu_mode, "Primary Symbols");
    append(aprs_menu_channel, "Alternate Symbols");
    append(aprs_menu_beacon, "Overlay Symbols");
    show_settings(2);
}

unsigned aprs_catalog(unsigned group,unsigned overlays,unsigned base)
{
    catalog_count = 0;
    if (overlays) {
        for (unsigned i = 0; i < 36; ++i) {
            unsigned ch = i < 10 ? '0' + i : 'A' + i - 10;
            catalog_symbols[catalog_count++] = (ch << 8) | base;
        }
    } else {
        unsigned table = group == 0 ? '/' : '\\';
        for (unsigned ch = '!'; ch <= '~'; ++ch) {
            unsigned icon = (table << 8) | ch;
            if (aprs_symbol_label(icon))
                catalog_symbols[catalog_count++] = icon;
        }
    }
    return catalog_count;
}
unsigned aprs_catalog_icon(unsigned index) { return catalog_symbols[index]; }

static void show_symbol_list(void)
{
    aprs_catalog(symbol_group,page==OVERLAY_LIST,overlay_base);
    *(uint8_t *)(aprs_symbol_descriptor+1) = catalog_count - 1;
    show_selector(APRS_SYMBOL_LIST);
}

static void open_symbol_group(void)
{
    symbol_group = aprs_menu_choice;
    page = symbol_group == 2 ? OVERLAY_BASE : SYMBOL_LIST;
    overlay_base = (uint8_t)aprs_beacon_symbol()[1];
    show_symbol_list();
}

unsigned aprs_symbol_initial_choice(void)
{
    const char *saved = aprs_beacon_symbol();
    unsigned icon = page == OVERLAY_BASE ? ('\\' << 8) | overlay_base :
                    ((uint8_t)saved[0] << 8) | (uint8_t)saved[1];
    for (unsigned i = 0; i < catalog_count; ++i)
        if (catalog_symbols[i] == icon)
            return i;
    return 0;
}

static void apply_symbol(void)
{
    unsigned icon = catalog_symbols[aprs_menu_choice];
    if (page == OVERLAY_BASE) {
        overlay_base = icon & 255;
        page = OVERLAY_LIST;
        show_symbol_list();
        return;
    }
    saved_symbol[0] = icon >> 8;
    saved_symbol[1] = icon;
    show_aprs_settings();
}

unsigned aprs_symbol_list_select(void)
{
    if (aprs_menu_choice >= catalog_count)
        return 0;
    ((void (*)(void (*)(void)))0x200cd7dc)(apply_symbol);
    return 1;
}

unsigned aprs_symbol_catalog_text(unsigned layer, unsigned rect, unsigned format, unsigned font,
                                  unsigned color, const uint16_t *xy, unsigned align, unsigned language)
{
#ifdef APRS_SLOT_UI
    extern unsigned aprs_symbol_page(void);
    if (!aprs_symbol_page() || rect < 1608 || rect > 1611)
#else
    if (*(volatile uint16_t *)0x203e1a28 != APRS_SYMBOL_LIST || rect < 1608 || rect > 1611)
#endif
        return 0;
    unsigned index = REG8(0x203e1a2b) + rect - 1608;
    if (index >= catalog_count)
        return 1;
    unsigned icon = catalog_symbols[index];
    const char *text = aprs_symbol_label(icon);
    char name[9];
    if (!text) {
        unsigned ch = icon >> 8;
        char *end = append(name, ch >= 'A' ? "Letter " : "Number ");
        *end++ = ch;
        *end = 0;
        text = name;
    }
    uint16_t box[8], label_xy[] = {42, xy[1]};
    ((void (*)(uint16_t *, unsigned, unsigned))0x201420b4)(box, 0, rect);
    aprs_draw_icon(icon, box[1]+10, box[2]+19, color == 17 ? 0x5d19 : 0);
    typedef void (*stock_text)(unsigned, unsigned, const char *, unsigned, unsigned, unsigned,
                               unsigned, const uint16_t *, unsigned, unsigned);
    unsigned length = 0;
    while (text[length])
        ++length;
    ((stock_text)0x20142698)(layer, rect, text, length, format, font, color, label_xy, align, language);
    return 1;
}

static void apply_path(void)
{
    aprs_tx_path = aprs_menu_choice;
    show_aprs_settings();
}

static void interval_text(char *out, unsigned index)
{
    unsigned minutes = aprs_beacon_minutes[index];
    if (minutes >= 10)
        *out++ = '0' + minutes / 10;
    *out++ = '0' + minutes % 10;
    append(out, " min");
}

static void show_auto(void)
{
    page = AUTO;
    append(aprs_menu_title, auto_title);
    append(aprs_menu_mode, "OFF");
    append(aprs_menu_channel, "ON");
    show_settings(1);
}

static void show_interval(void)
{
    page = INTERVAL;
    append(aprs_menu_title, interval_title);
    interval_text(aprs_menu_mode, 0);
    interval_text(aprs_menu_channel, 1);
    interval_text(aprs_menu_beacon, 2);
    interval_text(aprs_settings_path, 3);
    interval_text(aprs_settings_symbol, 4);
    show_settings(4);
}

static void apply_beacon_timing(void)
{
    uint8_t *setting = page == AUTO ? &aprs_auto_beacon : &aprs_beacon_interval;
    if (*setting != aprs_menu_choice) {
        *setting = aprs_menu_choice;
        aprs_beacon_reschedule();
    }
    show_aprs_settings();
}

unsigned aprs_menu_initial_choice(void)
{
    if (page == AUTO)
        return aprs_auto_beacon;
    if (page == INTERVAL)
        return aprs_beacon_interval;
    if (page == PATH)
        return aprs_tx_path;
    if (page == SETTINGS)
        return settings_index;
    if (page == SYMBOL) {
        unsigned table = (uint8_t)aprs_beacon_symbol()[0];
        return table == '/' ? 0 : table == '\\' ? 1 : 2;
    }
    return page == MODE && aprs_channel_hz ? aprs_tx_enabled : 0;
}

unsigned aprs_back_from_mode(void)
{
    unsigned selector = *(volatile const uint16_t *)0x203e1a28;
    if (selector == APRS_SYMBOL_LIST) {
        if (page == OVERLAY_LIST) {
            page = OVERLAY_BASE;
            show_symbol_list();
        } else
            show_symbol();
        return 1;
    }
    if (selector != APRS_SSID_MENU &&
        (selector != APRS_RX_MENU || (page != PATH && page != SYMBOL && page != AUTO && page != INTERVAL)))
        return 0;
    show_aprs_settings();
    return 1;
}

unsigned aprs_menu_select(void)
{
    static void (*const actions[])(void) = {
        use_current, aprs_ssid_open, edit_comment, show_path, show_symbol, show_auto, show_interval
    };
    void (*action)(void);
    if (page == SETTINGS && aprs_menu_choice < sizeof(actions)/sizeof(actions[0])) {
        settings_index = aprs_menu_choice;
        action = actions[aprs_menu_choice];
    } else if (page == MODE && aprs_menu_choice < 2)
        action = apply_mode;
    else if (page == PATH && aprs_menu_choice < 3)
        action = apply_path;
    else if (page == SYMBOL && aprs_menu_choice < 3)
        action = open_symbol_group;
    else if ((page == AUTO && aprs_menu_choice < 2) || (page == INTERVAL && aprs_menu_choice < 5))
        action = apply_beacon_timing;
    else
        return 0;
    ((void (*)(void (*)(void)))0x200cd7dc)(action);
    return 1;
}

static void show_aprs_settings(void)
{
    page = SETTINGS;
    append(aprs_menu_title, aprs_gps_mode_name);
    offered_hz = current_fm();
    char *channel = append(aprs_menu_mode, "FM Channel  ");
    if (selected_hz)
        frequency_text(channel, selected_hz);
    else
        append(channel, offered_hz ? "Use current FM" : "Tune FM first");
    char *ssid = append(aprs_menu_channel, "Beacon SSID  ");
    unsigned number = aprs_beacon_ssid;
    if (number >= 10) {
        *ssid++ = '1';
        number -= 10;
    }
    *ssid++ = '0' + number;
    *ssid = 0;
    append(aprs_menu_beacon, aprs_comment_title);
    append(append(aprs_settings_path, "TX Path  "), tx_paths[aprs_tx_path]);
    append(aprs_settings_symbol, aprs_symbol_title);
    append(append(aprs_settings_auto, "Auto Beacon  "), aprs_auto_beacon ? "ON" : "OFF");
    interval_text(append(aprs_settings_interval, "Beacon Interval  "), aprs_beacon_interval);
    show_settings(6);
}

void aprs_menu_open(void)
{
    settings_index = 0;
    show_aprs_settings();
}

void aprs_ssid_open(void)
{
    show_selector(APRS_SSID_MENU);
}

unsigned aprs_ssid_initial(void)
{
    return aprs_beacon_ssid;
}

static void apply_ssid(void)
{
    if (aprs_ssid_choice < 16)
        aprs_beacon_ssid = aprs_ssid_choice;
    show_aprs_settings();
}

unsigned aprs_ssid_select(void)
{
    ((void (*)(void (*)(void)))0x200cd7dc)(apply_ssid);
    return 1;
}

static void send_beacon(void)
{
    ((void (*)(void))0x200cd828)();
    const char *notice = aprs_beacon_start();
    if (!notice)
        return;
    page = NOTICE;
    append(aprs_menu_title, "APRS Beacon");
    append(aprs_menu_mode, notice);
    show_settings(0);
}

unsigned aprs_quick_beacon(unsigned *result)
{
    *result = 1;
    ((void (*)(void (*)(void)))0x200cd7dc)(send_beacon);
    return 1;
}
