/* The MODE shortcut runs a receive application on the normal USB-D VFO. */
#include "live_rx.h"
#include "device_memory.h"
#include "j140_tx.h"
#include <stdatomic.h>

#define BYTE(a) (*(volatile uint8_t *)(a))
#define WORD(a) (*(volatile uint32_t *)(a))
enum { OFF, STARTING, LISTENING, STOPPING, NO_MEMORY, NO_THREAD, MODE_FAILED };
static _Atomic unsigned state, thread, painting, shared_worker;
extern uintptr_t cw_state_anchor;
extern unsigned cw_lab_work(unsigned budget);
static unsigned restore_scope, held, last_second, anchor_second, anchor_adc, last_hz, redraw, wake_blocks;
static const char *memory_error;
static unsigned painted_outputs;
static unsigned anchor_tick;
static _Atomic unsigned audio_tick;
static unsigned display_suspended;
static int display_dark(void) {
    return BYTE(0x20380721) || BYTE(0x2038072a);
}
int ft_can_page(unsigned);
void ft_station_tick(void);
unsigned ft_listen(void){return atomic_load(&state)==LISTENING;}
void view_invalidate(void);
static _Atomic unsigned adc, clock_ready, generation;
static _Atomic unsigned consumed, tuning_blocked;
unsigned ftx_ft4, ftx_choice, ftx_rtc;
__attribute__((section(".ft_menu"))) const char ftx_menu_title[]="Digital", ftx_label8[]="FT8", ftx_label4[]="FT4";
__attribute__((section(".ft_menu"))) const uint16_t ftx_items[]={318,319};
void view_button(const char *,int,int,int,int);

static unsigned lock(void) {
    unsigned old;
    __asm__ volatile("mrs %0,cpsr\n cpsid i" : "=r"(old) :: "memory");
    return old;
}
static void unlock(unsigned old) {
    __asm__ volatile("msr cpsr_c,%0" :: "r"(old) : "memory");
}
static void refresh(void) {
    unsigned old=lock();
    BYTE(0x203806f7)|=0x40;
    unlock(old);
}
static void wake(void) {
    unsigned id=atomic_load(&thread);
    if(id) ((unsigned (*)(unsigned,unsigned))0x202d4851)(id,1);
}
static int mode_page(void) {
    return BYTE(0x203e84c9)==2 && BYTE(0x203e84ca)==0 && BYTE(0x203807dd)==0;
}
/* CI-V 27 10 01 opens the native scope page, including on remote reconnect.
   Keep the FT panel above this one page; menus and dialogs still own input. */
static int other_panel_open(void) {
    unsigned page=BYTE(0x203e84c9);
    return (page && page!=9) || BYTE(0x203e84ca) || BYTE(0x203807dd);
}
void ft_exit(void) {
    unsigned s=atomic_load(&state);
    if(s==OFF || s==STOPPING) return;
    display_suspended=0;
    ft_station_close();
    atomic_store(&state,atomic_load(&thread)?STOPPING:OFF);
    wake();
    if(restore_scope) {
        restore_scope=0;
        ((void (*)(unsigned))0x200f1f04)(0);
    }
    refresh();
}
static unsigned audio_age(void) {
    unsigned last=atomic_load(&audio_tick);
    return WORD(0x20381e08)-last;
}
const char *ftx_status(void) {
    switch(atomic_load(&state)) {
    case NO_MEMORY: return memory_error;
    case NO_THREAD: return "No CW or FT worker";
    case MODE_FAILED: return "Select USB-D and retry";
    case STARTING: return "Starting receiver";
    case LISTENING:
        if(audio_age()>=2000)return "No RX audio";
        if(tuning_blocked)return "RX paused";
        /* fall through */
    default: return live_enabled() && atomic_load(&clock_ready)?0:(ftx_rtc?"Waiting for RTC tick":"Waiting for GPS UTC");
    }
}
static int clock_second(void) {
    if(ftx_rtc) {
        /* Factory RIIC1 clock cache YY MM DD weekday HH MM SS (BCD).
           The FT periods both divide a minute, also in local display time. */
        unsigned value=0;
        for(unsigned i=0;i<3;++i) {
            unsigned raw=BYTE(0x2038079eu + i), tens=raw>>4, units=raw&15;
            unsigned field=tens*10+units;
            if(units>9 || field>=(i?60u:24u)) return -1;
            value=value*60+field;
        }
        return value;
    }
    if(!((unsigned (*)(void))0x2021300c)()) return -1;
    char stamp[8]={0};
    ((void (*)(char *))0x20212b64)(stamp);
    unsigned pairs[3];
    for(unsigned i=0;i<3;++i) {
        unsigned a=(unsigned)(stamp[2*i]-'0'), b=(unsigned)(stamp[2*i+1]-'0');
        if(a>9 || b>9) return -1;
        pairs[i]=10*a+b;
    }
    return pairs[0]<24 && pairs[1]<60 && pairs[2]<60 ?
        (int)((pairs[0]*60+pairs[1])*60+pairs[2]) : -1;
}
/* Anchor on the first observed change of a fresh GPS second. Serial latency
   relative to RF time is a field measurement. Recheck drift and expiry. */
static void observe_clock(unsigned n) {
    unsigned sec=(unsigned)clock_second();
    if(sec!=last_second) {
        if(sec<86400 && last_second<86400 && (last_second+1)%86400==sec) {
            unsigned delta=n-anchor_adc;
            if(!atomic_load(&clock_ready) || delta<6000 || delta>10000)
                atomic_fetch_add(&generation,1);
            anchor_adc=n;
            anchor_second=sec;
            anchor_tick=WORD(0x20381e08);
            atomic_store(&clock_ready,1);
        } else if(atomic_exchange(&clock_ready,0)) atomic_fetch_add(&generation,1);
        last_second=sec;
    }
    if((sec>=86400 || n-anchor_adc>20000) && atomic_exchange(&clock_ready,0))
        atomic_fetch_add(&generation,1);
}
int ft_clock(unsigned *slot,unsigned *ms) {
    unsigned irq=lock();
    unsigned age=WORD(0x20381e08)-anchor_tick,period=ftx_ft4?7500:15000;
    unsigned day=(anchor_second*1000+age)%86400000;
    int valid=atomic_load(&clock_ready) && age<1800;
    unlock(irq);
    *slot=day/period; *ms=day%period;
    return valid;
}
static void synchronize(void) {
    unsigned old=lock();
    if(atomic_load(&generation)!=consumed || !atomic_load(&clock_ready) || tuning_blocked) {
        live_close();
        consumed=atomic_load(&generation);
    }
    if(!live_enabled() && atomic_load(&clock_ready) && !tuning_blocked) {
        unsigned n=atomic_load(&adc),length=ftx_ft4?60000:120000;
        unsigned t=anchor_second*8000+(n-anchor_adc);
        live_open(ftx_ft4,n,t/length,t%length);
    }
    unlock(old);
}
__attribute__((noinline)) int ftx_step(void) {
    unsigned s=atomic_load(&state);
    if(s==STOPPING && !atomic_load(&painting)) {
        live_close();
        ftx_release();
        atomic_store(&shared_worker,0);
        atomic_store(&thread,0);
        atomic_store(&state,OFF);
        return 0;
    } else if(s==STARTING) {
        memory_error=ftx_allocate(ftx_ft4);
        atomic_store(&audio_tick,WORD(0x20381e08));
        if(!memory_error) view_reset(ftx_ft4);
        unsigned expected=STARTING;
        last_second=~0u;
        atomic_store(&clock_ready,0);
        wake_blocks=0;
        tuning_blocked=0;
        last_hz=WORD(0x20380714);
        atomic_compare_exchange_strong(&state,&expected,memory_error?NO_MEMORY:LISTENING);
        refresh();
    } else if(s==LISTENING) {
        synchronize();
        while(atomic_load(&state)==LISTENING && live_pending() && !rx_hold_input()) live_poll();
        if(live_enabled()) rx_decode_work(8);
    }
    return 1;
}
/* CW and FT keep separate sessions. The D6 worker still services CW on each wake. */
unsigned ftx_cw_work(unsigned budget) {
    if(atomic_load(&shared_worker)) ftx_step();
    return cw_lab_work(budget);
}
static void worker(void) {
    for(;;) {
        ((unsigned (*)(unsigned,unsigned))0x202d488c)(1,~0u);
        if(!ftx_step()) return; /* RTX reclaims this task and its stack. */
    }
}
__attribute__((section(".ftx_controls"))) static void start(void) {
    ((void (*)(void))0x200cd828)();
    ((void (*)(void))0x200f192c)();
    if(atomic_load(&state)!=OFF) return;
    if(!ft_data_ready()) return;
    ftx_ft4=ftx_choice==1;
    ft_station_open();
    view_invalidate(); /* Also cover a second startup error after visiting MODE. */
    restore_scope=!((unsigned (*)(void))0x200f1e48)();
    if(restore_scope) ((void (*)(unsigned))0x200f1f04)(1);
    /* Same SSB selection and DATA action as the factory MODE buttons. */
    if(BYTE(0x203e2128)>>4!=1) ((void (*)(unsigned,unsigned))0x20080a34)(2,0);
    if(BYTE(0x203e2128)>>4==0) ((void (*)(unsigned,unsigned))0x20080a34)(0,0);
    if(BYTE(0x203e2128)>>4==1 && !(BYTE(0x203e2129)&1))
        ((void (*)(void))0x20080e50)();
    if(BYTE(0x203e2128)>>4!=1 || !(BYTE(0x203e2129)&1)) {
        atomic_store(&state,MODE_FAILED);
    } else {
        static const uintptr_t task[]={(uintptr_t)worker,0xe8,1,4096};
        uintptr_t cw_state=cw_state_anchor;
        unsigned id=cw_state ? WORD(cw_state+0x700) : 0;
        atomic_store(&shared_worker,id!=0);
        if(!id) id=((unsigned (*)(const uintptr_t *,unsigned))0x202d48c1)(task,0);
        atomic_store(&thread,id);
        atomic_store(&state,atomic_load(&thread)?STARTING:NO_THREAD);
        wake();
    }
    refresh();
}
unsigned ftx_select(void) {
    ((void (*)(void (*)(void)))0x200cd7dc)(start);
    return 2;
}
void ftx_audio(const int16_t *pcm) {
    if(atomic_load(&state)!=LISTENING) return;
    unsigned n=atomic_load(&adc);
    atomic_store(&adc,n+6);
    unsigned hz=WORD(0x20380714);
    unsigned blocked=(BYTE(0x203e2128)>>4)!=1 || !(BYTE(0x203e2129)&1) ||
        (BYTE(0x203809a1)&0x10) || WORD(0x203809ac) || WORD(0x203809b0);
    if(hz!=last_hz || blocked!=tuning_blocked) {
        last_hz=hz;
        tuning_blocked=blocked;
        atomic_fetch_add(&generation,1);
    }
    if(!wake_blocks){atomic_store(&audio_tick,WORD(0x20381e08));observe_clock(n);}
    if(!blocked && consumed==atomic_load(&generation) && atomic_load(&clock_ready))
        live_capture(pcm,n);
    if(++wake_blocks==24) { wake_blocks=0; wake(); }
}
unsigned ftx_sample_count(void) { return atomic_load(&adc); }
void ftx_input(void) {
    unsigned s=atomic_load(&state);
    if(s==OFF || s==STOPPING) return;
    if(display_dark()) {
        display_suspended=1;
        view_invalidate();
        return;
    }
    if(display_suspended) {
        if(BYTE(0x204bab5d)!=1 || other_panel_open())return;
        display_suspended=0;
        view_invalidate();
        refresh();
    }
    if(BYTE(0x204bab5d)!=1){if(s!=STARTING)ft_exit();return;}
    ft_station_tick();
    unsigned side_exit=BYTE(0x204bd028) || (BYTE(0x204bd19e) && BYTE(0x204bd19f)==2);
    if((BYTE(0x20380431)==9 && !side_exit) || other_panel_open()) {
        ft_exit();
        return;
    }
    unsigned n=atomic_load(&adc);
    static unsigned panel_tick;
    unsigned now=WORD(0x20381e08);
    static unsigned missing_audio;
    unsigned stalled=s==LISTENING && audio_age()>=2000;
    if(n-redraw>=2000 || missing_audio!=stalled || ((ft_page==FT_QSO || ft_page==FT_SETUP) && now-panel_tick>=250)) {
        missing_audio=stalled;redraw=n;panel_tick=now;refresh();
    }
}
unsigned ftx_touch(void) {
    unsigned up=BYTE(0x203e1f23);
    unsigned x=256u*BYTE(0x203e1f24)+BYTE(0x203e1f25);
    unsigned y=256u*BYTE(0x203e1f26)+BYTE(0x203e1f27);
    if(up || x==9999 || !(x|y)) { unsigned was=held; held=0; return was==1; }
    if(held) return held==1;
    unsigned s=atomic_load(&state);
    if(s!=OFF && s!=STOPPING && display_dark())display_suspended=1;
    if(s!=OFF && s!=STOPPING && x<480 && y<272 &&
       (((int (*)(void))0x20090630)() || ((int (*)(unsigned))0x20090a80)(0) || display_dark() || display_suspended)) {
        held=1;
        return 1;
    }
    if(BYTE(0x204bab5d)!=1)return 0;
    if(s==OFF && mode_page() && x>=393 && x<470 && y>=171 && y<214) {
        held=1;
        ((void (*)(unsigned))0x2007d478)(1);
        ((void (*)(void))0x200f192c)();
        *(volatile uint16_t *)0x203e1b1a=0x0202;
        ((void (*)(unsigned,unsigned))0x200cd628)(317,0xffff);
        return 1;
    }
    if(s==OFF || s==STOPPING) return 0;
    /* Route a gesture by the OEM layer actually composited over the FT keys. */
    if(y<FT_PANEL_TOP || (BYTE(0x204bd028) && x>=361) ||
       (BYTE(0x204bd19e) && BYTE(0x204bd19f)==2 && x<118 && y>=157) ||
       (BYTE(0x204bd0bc) && BYTE(0x204bd0bd)==1 && x>=130 && x<350 && y>=153 && y<239) ||
       BYTE(0x204bd0f4) || other_panel_open()) {
        held=2;
        return 0;
    }
    held=1;
    if(!ft_panel_touch(x,y)) return 1;
    view_invalidate();
    refresh();
    ((void (*)(unsigned))0x2007d478)(1);
    return 1;
}
void ft_set_time(unsigned rtc) {
    unsigned old=lock();
    ftx_rtc=rtc;
    last_second=~0u;
    atomic_store(&clock_ready,0);
    atomic_fetch_add(&generation,1);
    unlock(old);
    wake(); refresh();
}
void ftx_frame(void) {
    unsigned s=atomic_load(&state);
    if(s==OFF) {
        if(BYTE(0x204bab5d)==1 && mode_page() && ft_data_ready()) view_button("FT8/4",393,171,77,43);
        return;
    }
    if(display_dark())display_suspended=1;
    if(display_suspended || BYTE(0x204bab5d)!=1 || s==STOPPING || other_panel_open() || BYTE(0x204bd0f4)) {
        view_invalidate();
        return;
    }
    atomic_store(&painting,1);
    if(atomic_load(&state)!=STOPPING && atomic_load(&state)!=OFF) {
        unsigned length=ftx_ft4?60000:120000;
        unsigned t=anchor_second*8000+(atomic_load(&adc)-anchor_adc);
        painted_outputs |= 1u<<(BYTE(0x20380cbc)&1);
        view_draw(t/length,live_enabled()?t%length:~0u);
    }
    atomic_store(&painting,0);
    if(atomic_load(&state)==STOPPING) wake();
}
/* On return from a custom page HOME may otherwise take its incremental path.
   Invalidate each output that actually received FT pixels before stock draw. */
void ftx_prepare_frame(void) {
    unsigned s=atomic_load(&state);
    if((s==OFF || s==STOPPING || BYTE(0x204bab5d)!=1) && painted_outputs) {
        BYTE(0x20380c98)|=1;
        painted_outputs &= ~(1u<<(BYTE(0x20380cbc)&1));
        if(painted_outputs) refresh();
    }
}
