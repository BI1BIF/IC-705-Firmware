#include "dmr-ui.h"

#define BYTE(a) (*(volatile uint8_t *)(a))
#define TICKS (*(volatile uint32_t *)0x20381e08)

/* Resolved to the installed v1.4.0 callbacks for the selected region. */
extern unsigned ft_touch(void);
extern void ft_frame(void), ft_input(void), previous_prepare(void);
extern void mode_close(void), mode_select(unsigned action, unsigned key);
extern void data_toggle(void), beep(unsigned);
extern unsigned stock_mode_text(char *, unsigned, unsigned);
extern unsigned aprs_strip_visible(unsigned);
struct element {
    uint16_t flags, x, y, inner_x, inner_y, width, height;
};
extern void stock_row_prepare(unsigned), stock_row_draw(unsigned,unsigned,unsigned);
extern void element_layout(struct element *,unsigned,unsigned);
extern unsigned text_width(const char *,unsigned,unsigned,unsigned,unsigned);
extern void element_text(unsigned,unsigned,const char *,unsigned,unsigned,unsigned,unsigned,
                         const int16_t *,unsigned,unsigned);
static uint8_t held, notice, wanted, menu_seen, revision;
static char caller[48];
static struct element caller_rect;
static uint32_t last_refresh;
static unsigned retries, retry_hz;

static void refresh(void)
{
    unsigned cpsr;
    __asm__ volatile("mrs %0,cpsr\n cpsid i" : "=r"(cpsr) :: "memory");
    BYTE(0x203806f7) |= 0x40;
    __asm__ volatile("msr cpsr_c,%0" :: "r"(cpsr) : "memory");
}

static int mode_menu(void)
{
    return BYTE(0x204bab5d)==1 && BYTE(0x203e84c9)==2 &&
           !BYTE(0x203e84ca) && !BYTE(0x203807dd);
}

static int status_area(void)
{
    return BYTE(0x204bab5d)==1 && !BYTE(0x203e84c9) && !BYTE(0x203e84ca) &&
           !BYTE(0x203807dd) && !BYTE(0x204bd0f4) && !BYTE(0x20380721) && !BYTE(0x2038072a) &&
           !(BYTE(0x204bd0bc) && BYTE(0x204bd0bd)==1) &&
           !(BYTE(0x204bd19e) && BYTE(0x204bd19f)==2);
}

static int plain_fm(void)
{
    return BYTE(0x203e2128)>>4==7 && !(BYTE(0x203e2129)&1);
}

static int active(void)
{
    const volatile struct dmr_ui_status *s=dmr_ui_get_status();
    return s && s->enabled;
}

/* Give the factory frequency compositor the same height it uses with a DV caller. */
unsigned digital_strip_visible(unsigned slot)
{
    if (!slot && (notice || active())) return 1;
    return aprs_strip_visible(slot);
}

/* The factory badge uses a counted byte string and centers it in its own button. */
unsigned dmr_mode_text(char *dst, unsigned mode, unsigned data)
{
    if (mode==7 && !data && active()) {
        unsigned m=dmr_ui_get_status()->enabled;
        const char *text=m==3 ? "P25" : m==2 ? "YSF" : "DMR";
        unsigned n=0;
        while(text[n]) { dst[n]=text[n]; ++n; }
        return n;
    }
    return stock_mode_text(dst,mode,data);
}

static void stop(void)
{
    if (!notice) dmr_rx_set_enabled(0);
    retries=0;
    notice=0;
    refresh();
}

static void try_start(void)
{
    notice=0;
    if (!plain_fm()) notice=DMR_MODE_PENDING;
    else if (!dmr_rx_set_enabled(wanted)) {
        const volatile struct dmr_ui_status *s=dmr_ui_get_status();
        notice=s && s->phase>=DMR_SD_ERROR && s->phase<=DMR_NO_THREAD ?
               s->phase : DMR_RESOURCE_ERROR;
    }
    if (notice!=DMR_MODE_PENDING && notice!=DMR_APRS_BUSY && notice!=DMR_RETIRING) retries=0;
    /* DV changes the factory audio mode first. Cue the completed selection
       once, after any pending mode transition and SD/worker startup. */
    if (!retries) beep(1);
    last_refresh=TICKS;
    refresh();
}

unsigned dmr_ui_touch(void)
{
    unsigned x=BYTE(0x203e1f24)*256u+BYTE(0x203e1f25);
    unsigned y=BYTE(0x203e1f26)*256u+BYTE(0x203e1f27);
    if (BYTE(0x203e1f23) || x==9999 || !(x|y)) {
        if (held) { held=0; return 1; }
        return ft_touch();
    }
    if (held) return 1;
    if (mode_menu() && x>=104 && x<188 && y>=220 && y<263) {
        unsigned current=dmr_ui_get_status()->enabled;
        if (current==3 || (!current && BYTE(0x203e2128)>>4!=9)) {
            if (active() || notice) stop();
            return ft_touch();
        }
        held=1;
        wanted=current+1;
        mode_close();
        if(!current) {
            mode_select(2,4);
            if (BYTE(0x203e2128)>>4==7 && (BYTE(0x203e2129)&1)) data_toggle();
        }
        retry_hz=*(volatile unsigned *)0x20380714;
        retries=8;
        try_start();
        return 1;
    }
    if (notice || active()) {
        if (notice && status_area() && x>=caller_rect.x && x<caller_rect.x+caller_rect.width &&
            y>=caller_rect.y && y<caller_rect.y+caller_rect.height) {
            held=1; beep(1); stop(); return 1;
        }
        /* Native FM is also the digital discriminator. Its explicit MODE key
           is the only ordinary selection that leaves the backend mode equal. */
        if (mode_menu() && x>=10 && x<94 && y>=220 && y<263) {
            stop();
        }
    }
    return ft_touch();
}

void dmr_ui_input(void)
{
    ft_input();
    if (!mode_menu()) {
        if (BYTE(0x20380431)!=9) menu_seen=0;
    } else menu_seen=1;
    if (!notice && !active()) return;
    if ((notice && TICKS-last_refresh>=6000) || (!notice && !plain_fm()) ||
        (notice && status_area() && !menu_seen && BYTE(0x20380431)==9 &&
        !BYTE(0x204bd028) && !BYTE(0x204bd19e))) stop();
    else if (retries) {
        if (!status_area() || retry_hz!=*(volatile unsigned *)0x20380714 ||
            (BYTE(0x203e2128)>>4!=9 && BYTE(0x203e2128)>>4!=7)) stop();
        else if (TICKS-last_refresh>=125) {
            --retries;
            try_start();
        }
    }
    else if (!notice && TICKS-last_refresh>=250) {
        last_refresh=TICKS;
        refresh();
    }
}

void dmr_ui_frame(void)
{
    ft_frame();
    if (mode_menu()) menu_seen=1;
}

/* Publish changes to the stock 43-byte caller model. Its per-bank comparison
   schedules both erasure and redraw, including on the spectrum page. */
void digital_row_prepare(unsigned slot)
{
    static const char *const reasons[]={
        "Check SD card", "Start failed", "FM mode not ready", "Starting",
        "TX request active", "Other RX active", "APRS busy", "DMR memory full", "Worker unavailable"
    };
    if (!notice && !active()) {
        stock_row_prepare(slot);
        return;
    }
    const volatile char *src=notice ? reasons[notice-DMR_SD_ERROR] : dmr_ui_get_status()->row;
    unsigned n=0, changed=0;
    while(n<sizeof(caller)-1 && src[n]) {
        char ch=src[n];
        changed|=ch!=caller[n];
        caller[n++]=ch;
    }
    changed|=caller[n]!=0;
    caller[n]=0;
    if(changed) ++revision;
    volatile uint8_t *model=(volatile uint8_t *)0x204bac6c;
    for(unsigned i=1;i<43;++i) model[i]=0;
    model[4]=revision;
}

void digital_row_draw(unsigned element,unsigned color,unsigned frame)
{
    if (!notice && !active()) {
        stock_row_draw(element,color,frame);
        return;
    }
    element_layout(&caller_rect,0,element);
    unsigned n=0;
    while(caller[n]) ++n;
    if(!n || !caller_rect.width) return;
    unsigned style=BYTE(0x204bab61);
    unsigned size=16, width=text_width(caller,n,1,size,0);
    while(width>caller_rect.width && size>9) width=text_width(caller,n,1,--size,0);
    if (width>caller_rect.width) return;
    /* Native caller text uses a 17 px baseline offset, 16 in compact headers. */
    int16_t offset[2]={style ? 0 : (caller_rect.width-width)/2,style ? 16 : 17};
    element_text(style==2 ? 15 : style==1 ? 13 : 11,element,caller,n,1,size,color,offset,0,0);
}
