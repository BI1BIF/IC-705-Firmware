/* Field bundle adapter. The regular source build calls qth_id directly. */
#include "ft_panel_words.h"
#include "qth.h"

extern unsigned sender_flag(const void *, const char *);
extern unsigned panel_word(unsigned, unsigned, unsigned, unsigned, int);
extern unsigned ftx_ft4;
extern void text(const char *,unsigned,unsigned,unsigned,unsigned);
extern void rectangle(const float *,int,int,int,int);
#include "qth_bar.h"

void qth_rx_bar(unsigned slot,unsigned ms) { if(ms!=~0u) paint_slot_bar(slot,ms,100); }

unsigned qth_detail(const void *atlas,const char *sender)
{
    return qth_id(sender_flag(atlas,sender),sender);
}

void qth_row(unsigned flag,const char *row,unsigned y,int selected)
{
    mark_long_message(row,y,selected);
    if (!flag) return;
    const char *sender=row+(unsigned char)row[43]-1;
    panel_word(FT_LIST_NAMES+qth_id(flag,sender),199,y,64,selected?3:2);
}
