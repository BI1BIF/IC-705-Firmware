#ifndef J140_FTX_TX_H
#define J140_FTX_TX_H
#include "device_memory.h"
/* The compact scope frame starts two scanlines above the FT controls. */
enum { FT_PANEL_TOP = 84 };
/* Top edge of the AF panel actually committed by the HOME compositor. */
static inline unsigned ft_af_top(void) {
    unsigned af = *(const volatile unsigned short *)0x204bd19e;
    if (af & 0xff) {
        unsigned kind = af >> 8;
        if (kind == 2) return 157; /* AF/RF/SQL press */
        if (kind == 1 && !*(const volatile unsigned char *)0x204bd68d)
            return 214; /* momentary level display on rotation */
    }
    return 272;
}
enum { FT_LIST, FT_QSO, FT_SETUP, FT_CALL, FT_GRID, FT_MENU, FT_AUTO, FT_TIME, FT_LOG, FT_INFO };
extern unsigned ft_page, ftx_ft4;
int ft_data_ready(void);
void ft_station_open(void);
void ft_station_close(void);
extern unsigned ft_auto_armed;
extern int ft_selected;
int ft_row_eligible(const struct DisplayRow *r);
unsigned ft_list_button(unsigned key);
void ft_return_live(void);
void ft_set_time(unsigned rtc);
void ft_exit(void);
unsigned ft_place_id(const struct DisplayRow *r);
void ft_place_label(unsigned flag, unsigned x, unsigned y);
void ft_history_action(unsigned action);
int ft_history_enabled(unsigned action);
int ft_is_history(void);
int ft_is_cq_only(void);
int ft_choose_row(unsigned y);
const struct DisplayRow *ft_choice_row(void);
int ft_worked(const char *sender);
int ft_panel_touch(unsigned x, unsigned y);
void ft_panel_draw(unsigned full);
void ft_receive_row(const struct DisplayRow *row, int selected);
const struct DisplayRow *ft_row_at(unsigned y);
void ft_label(const char *s, unsigned x, unsigned y, unsigned size, unsigned color);
void ft_key(const char *s, unsigned x, unsigned y, unsigned w, unsigned h);
void ft_blank(unsigned y);
void ft_header(void);
void ft_slot_bar(unsigned slot,unsigned ms);
void view_invalidate(void);
int ft_local_grid(char grid[5]);
int ft_clock(unsigned *slot, unsigned *ms);
unsigned ft_listen(void);
#endif
