/* TX pane overlay uses the display surface, never the modulator's pixels. */
#include <stdint.h>
typedef uint8_t u8;
typedef uint16_t u16;
extern volatile u8 display_config[], menu_id[], previous_page[], current_page[];
extern volatile unsigned active, tx_state, tx_fields[], displayed_line;
extern const u16 caption_fields[], caption_items[];
extern void clear_box(unsigned,unsigned,unsigned), frame_box(unsigned,unsigned);
extern void photo(unsigned,unsigned,unsigned,unsigned), placeholder(unsigned,unsigned,unsigned);
extern void grid(unsigned,unsigned,unsigned,unsigned,unsigned);
extern void marker(unsigned,unsigned,unsigned,unsigned,const u8 *);
extern void clear_block(unsigned,unsigned), update_block(unsigned,unsigned,unsigned);
extern void caption(unsigned,unsigned,unsigned,unsigned *), icon(unsigned,unsigned,unsigned);
extern void lookup(u16 *,unsigned,unsigned), fill(unsigned,const u16 *,unsigned);
static unsigned layer(void) { return display_config[5]==1 ? 14 : 12; }

struct TxCursor { unsigned canvas, source_y, error, mode, header, row, segment, x; };
extern volatile struct TxCursor cursor;
static unsigned line(void) {
    if (tx_state!=2 || !cursor.canvas || cursor.header<13 ||
        !(cursor.row || cursor.segment || cursor.x)) return 0;
    unsigned y=cursor.source_y/2;
    return (y<120 ? y : 119)+1;
}

/* Invalidate only the cached TX thumbnail, once per visible row. */
void scan_refresh(void) {
    unsigned next=line();
    if (next!=displayed_line) {
        displayed_line=next;
        if (current_page[1]) previous_page[1]=0;
    }
}

void tx_pane(const u8 *p,const u8 *old,unsigned variant,unsigned incremental) {
    unsigned status=0;
    unsigned sstv=active && menu_id[0]==21 && !menu_id[1];
    if (!incremental) {
        clear_box(layer(),733,12);
        frame_box(layer(),733);
    }
    if (!p[1]) placeholder(layer(),734,p[2]);
    else {
        if (!incremental || sstv) photo(layer(),734,0,1);
        if (sstv) {
            unsigned y=displayed_line;
            if (y && y<=120) {
                u16 box[8], rect[4];
                lookup(box,0,734);
                rect[0]=box[3]; rect[1]=box[4]+y-1; rect[2]=160; rect[3]=1;
                fill(layer(),rect,0xffffffffu);
                rect[1]+=y==120 ? -1 : 1;
                fill(layer(),rect,0x000000ffu);
            }
        } else {
            if (!incremental) grid(layer(),734,1,p[3],p[24]);
            else {
                clear_block(p[25],p[26]); clear_block(old[25],old[26]);
                update_block(old[25],old[26],p[24]);
            }
            marker(layer(),734,p[3],p[3]==0 ? 2 : p[3]==1, p+25);
        }
    }
    caption(layer(),caption_fields[variant],caption_items[variant*2+1],&status);
    if (p[86]==2) icon(layer(),733,243);
}
