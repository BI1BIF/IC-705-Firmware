/* FUNCTION page 2 reuses the two factory empty tiles beside MAX TX PWR. */
#include <stdint.h>
#include "aprs-overlay-layout.h"

#define U8(a) (*(volatile uint8_t *)(a))
#define U16(a) (*(volatile uint16_t *)(a))
#define U32(a) (*(volatile uint32_t *)(a))
extern unsigned plain_fm(void), tx_enabled, bound_hz;
extern uintptr_t aprs_overlay_load(void);
extern uint8_t *pin_audio(unsigned);
extern void unpin_audio(void), aprs_set_mode(unsigned);
extern void stock_top(unsigned), stock_icon19(unsigned), stock_clear(unsigned,unsigned,unsigned);
extern void stock_clear_span(unsigned,const uint16_t *,unsigned);
extern void stock_bezel(unsigned,unsigned,unsigned,unsigned,unsigned);
extern void stock_focus(unsigned,unsigned,unsigned);
extern unsigned stock_action(unsigned);
extern void stock_text(unsigned,unsigned,const char *,unsigned,unsigned,unsigned,unsigned,const uint16_t *,unsigned,unsigned);

static void text(unsigned layer,unsigned rect,const char *s,unsigned x,unsigned y,unsigned size,unsigned color,unsigned align)
{
    uint16_t xy[2]={x,y};
    unsigned n=0;
    while (s[n]) ++n;
    stock_text(layer,rect,s,n,1,size,color,xy,align,0);
}

unsigned function_action(unsigned action)
{
    unsigned key=U16(0x204021b8);
    if (action!=39 || U8(0x20380431)!=24 || U8(0x204bab5d)!=3 ||
        U8(0x203e8500)!=1 || U16(0x203e1a28) || (key!=0x1c0 && key!=0x1c1) || !plain_fm())
        return stock_action(action);
    if (key==0x1c1 && !tx_enabled) return 0;
    if (!aprs_overlay_load()) return 0;
    uint8_t *base=pin_audio(1);
    if (!base) return 0;
    if (key==0x1c0)
        ((void (*)(void (*)(unsigned)))(base+FUNCTION_PICKER))(aprs_set_mode);
    else {
        base[AUTO_ON]=!base[AUTO_ON];
        base[CONFIG_DIRTY]=1;
        ((void (*)(void))(base+TIMER_RESET))();
    }
    unpin_audio();
    return 1;
}

static void tile(unsigned rect,const char *title,const char *value,unsigned active,unsigned enabled,unsigned focused)
{
    unsigned art=enabled ? (active ? 435 : 432) : 429;
    stock_clear(18,rect,12);
    stock_bezel(18,rect,art+1,art,art+2);
    text(18,rect,title,45,33,rect==794 ? 14 : 17,enabled ? 15 : 29,1);
    text(18,rect,value,45,68,14,enabled ? (active ? 57 : 27) : 30,1);
    if (focused) stock_focus(18,rect,243);
}

void function_draw(const uint8_t *frame,unsigned full)
{
    static unsigned last=~0u;
    if (frame[53]!=2 || !plain_fm()) {
        if (!full && frame[53]==2 && last!=~0u) {
            for (unsigned rect=793;rect<=794;++rect) {
                stock_clear(18,rect,12);
                stock_bezel(18,rect,433,432,434);
                if (frame[54]==rect-789) stock_focus(18,rect,243);
            }
        }
        last=~0u;
        return;
    }
    unsigned mode=bound_hz ? tx_enabled+1 : 0;
    unsigned paused=mode && bound_hz!=U32(0x20380714);
    unsigned available=mode==2;
    uint8_t *base=pin_audio(1);
    unsigned on=available && base && base[AUTO_ON];
    unsigned interval=on ? base[AUTO_INTERVAL] : 0;
    if (base) unpin_audio();
    unsigned focus=frame[54];
    unsigned state=mode+(available<<2)+(on<<3)+(interval<<4)+(focus<<8)+(paused<<16);
    if (!full && last==state) return;
    last=state;
    static const char *const modes[]={"OFF","RX Only","RX & TX"};
    static const char *const times[]={"ON  1 min","ON  3 min","ON  5 min","ON  10 min","ON  30 min","ON  SMART"};
    tile(793,"APRS",paused ? "Paused" : modes[mode],mode && !paused,1,focus==4);
    tile(794,"AUTO BCN",on ? times[interval] : "OFF",on,available,focus==5);
}

/* The battery ends at x=127. Each 66-pixel run holds both 12-point labels.
   Ownership comes from the same HOME frame the factory icon painters use. */
static unsigned header_x(const volatile uint8_t *frame)
{
    if (!frame[48] && !frame[49]) return 132;
    if (!frame[51] && !frame[52] && !frame[53] && !frame[54]) return 198;
    if (!frame[55] && !frame[56]) return 264;
    if (!frame[41] && !frame[43]) return 44;
    return 0;
}

static unsigned header_layout=~0u, header_dirty=~0u;

static unsigned header_layer(void)
{
    return U8(0x204bab61)==2 ? 15 : 11;
}

void function_top(unsigned full)
{
    const volatile uint8_t *frame=(const volatile uint8_t *)0x204bab5c;
    unsigned state=0, x=0;
    /* HOME and the M.SCOPE mini spectrum share the factory status bar. */
    if ((frame[5]==0 || frame[5]==2) && bound_hz && plain_fm()) {
        uint8_t *base=pin_audio(1);
        if (base) {
            state=1;
            if (tx_enabled && base[AUTO_ON]) {
                state=2;
                if (U32(base+AUTO_WAIT) && ((U32(0x20381e08)/500u)&1u)) state=3;
            }
            if (bound_hz==U32(0x20380714)) x=header_x(frame);
            else if (state>=2) { x=header_x(frame);state|=4; }
            unpin_audio();
        }
    }
    unsigned layout=x ? (x<<3)|state : 0;
    unsigned changed=layout!=header_layout;
    if (!full && changed && header_layout!=~0u && header_layout) {
        unsigned old_x=header_layout>>3;
        const uint16_t rect[]={old_x,0,old_x==44 ? 52 : 66,20};
        stock_clear_span(header_layer(),rect,0xff);
    }
    header_layout=layout;
    header_dirty=full || changed;
    /* An empty native slot can still be repainted as its underlying data changes. */
    if (x && !header_dirty) {
        const volatile uint8_t *previous=(const volatile uint8_t *)0x204bd690;
        for (unsigned i=41;i<=56;++i)
            if (frame[i]!=previous[i]) { header_dirty=1;break; }
    }
    stock_top(full);
}

void function_top_labels(unsigned full)
{
    stock_icon19(full);
    if (!header_dirty || !header_layout) return;
    unsigned x=header_layout>>3;
    unsigned font=x==44 ? 9 : 12;
    unsigned baseline=x==44 ? 13 : 14;
    unsigned layer=header_layer();
    text(layer,1,"APRS",x,baseline,font,header_layout&4 ? 29 : 15,0);
    if ((header_layout&3)==2)
        text(layer,1,"BCN",x+(x==44 ? 29 : 38),baseline,font,14,0);
}
