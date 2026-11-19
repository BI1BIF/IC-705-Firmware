/* J140 emulator experiment. Raw audio arrives in six-sample stock blocks. */
#include <stdint.h>
#include "sstv_cosine.h"

enum { WIDTH = 320, HEIGHT = 240, QUEUE = 32, SCAN = 1128, M1_SCAN = 3530, HISTORY = 1024 };
enum { ROBOT36 = 8, MARTIN_M1 = 44 };
enum { WAIT_VIS, RECEIVING, COMPLETE, LOST };
#define MENU_BYTES ((volatile uint8_t *)(uintptr_t)0x203e84c9)
#define PAGE ((volatile uint8_t *)(uintptr_t)0x204bab5c)

struct Counters {
    unsigned active, offered, dropped, processed, peak, locks, rows, samples, phase, mode;
};
volatile struct Counters counts;
typedef uint16_t Canvas[HEIGHT][WIDTH];
#ifdef SSTV_DEVICE
static Canvas *pixels;
static void *canvas_owner;
static unsigned in_worker, unavailable;
#ifdef SSTV_LATE_JOIN
static volatile unsigned gallery_loading;
static unsigned gallery_slot, gallery_result;
#endif
#ifdef SSTV_RX_DIAG
static unsigned block_peak;
static volatile unsigned displayed_peak, vis_status;
#ifdef SSTV_ROBOT_SYNC
static volatile unsigned robot_loss;
#endif
static unsigned last_peak, last_status;
static char peak_text[10], vis_text[10];
static const char *number(char *buf, unsigned pos, unsigned n) {
    char digits[5];
    unsigned used=0;
    do { digits[used++]='0'+n%10; n/=10; } while(n);
    while (used) buf[pos++]=digits[--used];
    buf[pos]=0;
    return buf;
}
#endif
#define image (*pixels)
#else
static Canvas image __attribute__((aligned(32)));
#endif
static int16_t queue[QUEUE][6];
static uint8_t gap_before[QUEUE];
static unsigned gap_pending;
static unsigned read_at, write_at, painted, generation, worker_generation, painted_mode;
unsigned sstv_thread;
void sstv_worker(void);
static struct {
#ifdef SSTV_TX_STUDY
    unsigned vis_run, hold_period;
#endif
    int a, b, numerator, energy, products[4], squares[4];
    unsigned slot, clock, run, last_sync, scan_at, avg, rows, phase, locks;
    unsigned mode, period, fraction, sync_hits, sync_sum;
#ifdef SSTV_ROBOT_SYNC
    unsigned missed_separator, loss;
#endif
#ifdef SSTV_LATE_JOIN
    unsigned edge, candidate, streak, live, span, robot_period, skips, silence;
    int separator;
#endif
    uint16_t history[HISTORY], scan[M1_SCAN];
    uint8_t previous_y[WIDTH], previous_cr[WIDTH/2];
#ifdef SSTV_RX_DIAG
    unsigned vis_result, level_blocks, level_peak, input_shift;
#endif
} rx;

static unsigned lock(void) {
    unsigned old;
    __asm__ volatile("mrs %0,cpsr\n cpsid i" : "=r"(old) :: "memory");
    return old;
}
static void unlock(unsigned old) {
    __asm__ volatile("msr cpsr_c,%0" :: "r"(old) : "memory");
}
enum { PICTURE = 21, RX_PICTURE = 274 };
static unsigned current_menu(void) { return MENU_BYTES[0] | ((unsigned)MENU_BYTES[1] << 8); }
static int viewing(void) {
    /* Native navigation stores its root menu at MENU+21 and depth at MENU+63.
       This keeps reception alive in Picture's child views and modal dialogs. */
    return counts.active && (current_menu() == PICTURE ||
        (MENU_BYTES[53] && MENU_BYTES[11] == PICTURE && MENU_BYTES[12] == 0));
}
static void zero(void *dst, unsigned size) {
    unsigned char *p = dst;
    while (size--) *p++ = 0;
}

static void clear_image(void) {
    uint16_t *target = &image[0][0];
    unsigned chunks = sizeof(image)/16;
    __asm__ volatile(
        "mov r1,#0\n mov r2,#0\n mov r3,#0\n mov r12,#0\n"
        "1: stmia %0!,{r1-r3,r12}\n subs %1,%1,#1\n bne 1b"
        : "+&r"(target), "+&r"(chunks)
        : : "r1","r2","r3","r12","cc","memory");
}

/* Older IRQ traffic can finish in the private buffer. The worker publishes only
   the generation it dequeued, and clears that buffer before a new generation. */
static void thread_entry(void) {
    for (;;) {
        unsigned event = ((unsigned (*)(unsigned, unsigned))0x202d488c)(1, ~0u);
        if (event == 8) {
            do { sstv_worker(); } while (viewing() && read_at != write_at);
        }
    }
}

void sstv_begin(void) {
    static const uintptr_t descriptor[] = {(uintptr_t)thread_entry, 0xe8, 1, 4096};
    if (!sstv_thread && *(volatile uintptr_t *)0x20381e90)
        sstv_thread = ((unsigned (*)(const uintptr_t *, unsigned))0x202d48c1)(descriptor, 0);
#ifdef SSTV_DEVICE
    /* A worker finishing the prior generation still owns its pointer. A new
       UI entry can retain it. Claim it before the idle-frame cleanup runs. */
    unsigned old=lock();
    void *held=canvas_owner;
    if (!held && sstv_thread) {
        unlock(old);
        held=((void *(*)(unsigned))0x20127a28)(sizeof(Canvas)+31);
        old=lock();
        canvas_owner=held;
    }
    unavailable=!sstv_thread || !canvas_owner;
    if (unavailable) { unlock(old); return; }
    pixels=(Canvas *)(((uintptr_t)canvas_owner+31)&~(uintptr_t)31);
#else
    unsigned old = lock();
#endif
    zero((void *)&counts, sizeof(counts));
#ifdef SSTV_RX_DIAG
    block_peak=displayed_peak=vis_status=last_peak=last_status=0;
#ifdef SSTV_ROBOT_SYNC
    robot_loss=0;
#endif
#endif
    read_at = write_at = painted = painted_mode = gap_pending = 0;
#ifdef SSTV_LATE_JOIN
    gallery_slot=gallery_loading=gallery_result=0;
#endif
    generation++;
    counts.active = 1;
    unlock(old);
}

/* Invoked by the SSTV row only. Native DV RX can also use menu 274. */
void sstv_open(void) {
    ((void (*)(void))0x200cd828)();
    ((void (*)(unsigned))0x200801e4)(PICTURE);
    sstv_begin();
}

void sstv_capture(const int16_t *src) {
    if (!viewing()) return;
#ifdef SSTV_TX_STUDY
    /* TX monitor samples must not become a received picture. */
    if (*(volatile uint8_t *)0x203809a1 & 0x10) {
        gap_pending=1;
        return;
    }
#endif
#ifdef SSTV_LATE_JOIN
    if (gallery_loading) return;
#endif
    unsigned old = lock();
    counts.offered++;
    unsigned pending = write_at - read_at;
    if (pending == QUEUE) {
        counts.dropped++;
        gap_pending=1;
    } else {
        gap_before[write_at % QUEUE]=gap_pending;
        gap_pending=0;
        int16_t *dst = queue[write_at % QUEUE];
        for (int n = 0; n < 6; ++n) dst[n] = src[n];
        write_at++;
        if (pending+1 > counts.peak) counts.peak = pending+1;
    }
    unlock(old);
    if (!pending && sstv_thread)
        ((unsigned (*)(unsigned,unsigned))0x202d4851)(sstv_thread,1);
}

/* Four-sample fit of x[n-1]+x[n+1] = 2*cos(w)*x[n]. Lookup in 10 Hz bins. */
static unsigned frequency(int sample) {
    int c = sample >> 8;
    int p = rx.b*(rx.a+c), e = rx.b*rx.b;
    unsigned i = rx.slot;
    rx.numerator += p-rx.products[i];
    rx.energy += e-rx.squares[i];
    rx.products[i] = p;
    rx.squares[i] = e;
    rx.slot = (i+1)&3;
    rx.a = rx.b;
    rx.b = c;
    if (rx.energy < 16) return 0;
    unsigned low = 0, high = 255;
    int target = rx.numerator*8192;
    while (low < high) {
        unsigned mid = (low+high)/2;
        if (target < cosine_threshold[mid]*rx.energy) low = mid+1;
        else high = mid;
    }
    return 850+10*low;
}

/* Check stable interiors of tones in the last ~1 s of 1 ms frequency averages.
   Times are relative to the first row's sync onset. */
static int tone(unsigned base, int start_ms, int end_ms, int hz) {
    unsigned good = 0;
    for (int t = start_ms; t < end_ms; ++t) {
        int v = rx.history[(base+t) & (HISTORY-1)];
        if (v >= hz-55 && v <= hz+55) good++;
    }
    return 3*good >= 2*(unsigned)(end_ms-start_ms);
}
#ifdef SSTV_BASIC
struct Mode;
static const struct Mode *lookup(unsigned);
#endif
static unsigned read_vis(unsigned stop_run) {
    /* The 30 ms VIS stop tone merges with the first line sync. */
    unsigned base = (rx.clock-stop_run+240) >> 3;
    if (!tone(base,-890,-650,1900) || !tone(base,-608,-602,1200) || !tone(base,-570,-330,1900) ||
        !tone(base,-295,-275,1200) || !tone(base,-26,-4,1200)) return 0;
    unsigned value=0, parity=0;
    for (int bit=0; bit<8; bit++) {
        int start = -270+30*bit;
        if (tone(base,start+6,start+24,1100)) {
            value |= 1u << bit;
            parity ^= 1;
        } else if (!tone(base,start+6,start+24,1300)) return 0;
    }
#ifdef SSTV_RX_DIAG
    unsigned code=value&127;
    unsigned known=code==ROBOT36 || code==MARTIN_M1;
#ifdef SSTV_BASIC
    known |= lookup(code)!=0;
#endif
    rx.vis_result=parity ? 129 : (known ? 0 : code+1);
#endif
    return parity ? 0 : value & 127;
}
static unsigned clip(int v) { return v<0 ? 0 : v>255 ? 255 : (unsigned)v; }
static unsigned component(unsigned start, unsigned len, unsigned x, unsigned width) {
    unsigned at=start+((2*x+1)*len)/(2*width);
#ifdef SSTV_LATE_JOIN
    if (rx.mode==ROBOT36 && rx.span)
        at=(at*rx.span+600)/1200;
#endif
    int hz = rx.scan[at];
#ifdef SSTV_TX_STUDY
    if (rx.mode==ROBOT36 && !hz && start==776) return 128;
#endif
#ifdef SSTV_LATE_JOIN
    if (rx.mode==ROBOT36 && rx.span) hz=(hz*rx.span+600)/1200;
#endif
    return clip(((hz-1500)*255+400)/800);
}
static uint16_t rgb565(int y, int cr, int cb) {
    unsigned r=clip(y+((359*cr+128)>>8)), g=clip(y-((183*cr+88*cb+128)>>8));
    unsigned b=clip(y+((454*cb+128)>>8));
    return ((r>>3)<<11) | ((g>>2)<<5) | (b>>3);
}
#ifdef SSTV_BASIC
#include "sstv-basic-modes.h"
#endif
static void end_line(void) {
    unsigned row = rx.rows, odd = row&1;
    unsigned good=0, expected=odd ? 2300 : 1500;
    for (unsigned i=736; i<752; ++i) {
        unsigned at=i;
#ifdef SSTV_LATE_JOIN
        if (rx.span) at=(i*rx.span+600)/1200;
#endif
        if (rx.scan[at]+140 >= expected && rx.scan[at]<=expected+140) good++;
    }
#ifdef SSTV_ROBOT_SYNC
    /* Row parity is known from VIS and the 150 ms line clock. One damaged
       separator is recoverable. A clear reversal or two missing separators
       no longer provides trustworthy colour pairing. */
    if (good<9) {
        unsigned opposite=odd ? 1500 : 2300, reversed=0;
        for (unsigned i=736;i<752;i++) {
            unsigned at=i;
#ifdef SSTV_LATE_JOIN
            if (rx.span) at=(i*rx.span+600)/1200;
#endif
            if (rx.scan[at]+140>=opposite && rx.scan[at]<=opposite+140) reversed++;
        }
#ifdef SSTV_TX_STUDY
        /* The tracked line clock fixes parity even when the separator fades.
           Require consecutive opposite markers before abandoning that clock. */
        rx.missed_separator=reversed>=9 ? rx.missed_separator+1 : 0;
        if (rx.live && rx.missed_separator>=3) { rx.loss=2; rx.phase=LOST; return; }
#else
        if (reversed>=9 || rx.missed_separator) { rx.loss=2; rx.phase=LOST; return; }
        rx.missed_separator=1;
#endif
    } else rx.missed_separator=0;
#else
    if (good < 9) { rx.phase=LOST; return; }
#endif
    for (unsigned i=0; i<WIDTH/2; ++i) {
        unsigned chroma=component(776,352,i,WIDTH/2);
        if (!odd) rx.previous_cr[i]=chroma;
        for (unsigned x=2*i; x<2*i+2; ++x) {
            unsigned y=component(24,704,x,WIDTH);
            if (!odd) rx.previous_y[x]=y;
            else {
                int cr=(int)rx.previous_cr[i]-128, cb=(int)chroma-128;
                image[row-1][x]=rgb565(rx.previous_y[x],cr,cb);
                image[row][x]=rgb565(y,cr,cb);
            }
        }
    }
    rx.rows++;
    if (rx.rows == HEIGHT) rx.phase=COMPLETE;
}

/* M1 sends Green, Blue, Red with 146.432 ms per channel. The native
   viewport has 240 rows. Map the full 256-row field, including row 255. */
static void martin_sample(unsigned f) {
    unsigned elapsed=rx.clock-rx.last_sync;
    if (elapsed < M1_SCAN) {
        rx.scan[elapsed]=f;
        if (elapsed+1 != M1_SCAN) return;
        unsigned y=rx.rows*HEIGHT/256;
        for (unsigned x=0; x<WIDTH; ++x) {
            unsigned g=component(5,1171,x,WIDTH), b=component(1181,1171,x,WIDTH);
            unsigned r=component(2357,1171,x,WIDTH);
            image[y][x]=((r>>3)<<11)|((g>>2)<<5)|(b>>3);
        }
        if (++rx.rows==256) rx.phase=COMPLETE;
        return;
    }
    /* Measure the next sync within its expected window. Noisy recordings
       can split the 4.862 ms pulse into several shorter runs. */
    if (elapsed+45>=rx.period && f>=1030 && f<=1370) {
        rx.sync_hits++;
        rx.sync_sum+=elapsed;
    }
    if (elapsed<rx.period) return;
    if (rx.sync_hits<12) {
#ifdef SSTV_LATE_JOIN
        rx.phase=rx.live && rx.rows && !f ? COMPLETE : LOST;
#else
        rx.phase=LOST;
#endif
        return;
    }
    int hits=(int)rx.sync_hits;
    int error=(int)rx.sync_sum-(int)(rx.period-20)*hits;
    int correction=(error>hits)+(error>2*hits)-(error < -hits)-(error < -2*hits);
    rx.last_sync=rx.clock;
    rx.fraction+=568;
    rx.period=3571+(rx.fraction>=1000)+correction;
    rx.fraction%=1000;
    rx.sync_hits=rx.sync_sum=0;
}
#ifdef SSTV_LATE_JOIN
#include "sstv-late-join.h"
#endif
static void sample8k(int value) {
    unsigned f=frequency(value);
    rx.clock++;
    rx.avg+=f;
    if (!(rx.clock&7)) {
        rx.history[(rx.clock>>3)&(HISTORY-1)] = (rx.avg+4)>>3;
        rx.avg=0;
    }
#ifdef SSTV_TX_STUDY
    if (rx.phase==RECEIVING && rx.mode==ROBOT36 && !rx.live) {
        unsigned prev=rx.vis_run;
        rx.vis_run=f>=1140 && f<=1260 ? prev+1 : 0;
        if (!rx.vis_run && prev>=216 && prev<=432 && read_vis(prev)) {
            rx.phase=WAIT_VIS;
            rx.run=prev;
        }
    }
#endif
    if (rx.phase==RECEIVING) {
#ifdef SSTV_LATE_JOIN
        if (rx.live) {
            rx.silence=f ? 0 : rx.silence+1;
            if (rx.silence>=640) {
                rx.phase=rx.rows ? COMPLETE : LOST;
                return;
            }
        }
#endif
#ifdef SSTV_BASIC
        if (stream.m) { stream_sample(f); return; }
#endif
        if (rx.mode==MARTIN_M1) { martin_sample(f); return; }
#ifdef SSTV_LATE_JOIN
        if (rx.mode==ROBOT36) { tracked_robot(f); return; }
#endif
        unsigned elapsed=rx.clock-rx.last_sync;
        if (elapsed>1216) {
#ifdef SSTV_ROBOT_SYNC
            rx.loss=1;
#endif
            rx.phase=LOST; return;
        }
#ifdef SSTV_ROBOT_SYNC
        if (elapsed>=1128 && f>=1100 && f<=1300) rx.sync_hits++;
        /* At the expected edge a split pulse can have enough total evidence
           but no long final run. Keep the previous line clock for this edge;
           subsequent intact pulses still align to their measured ends. */
        if (elapsed==1200 && rx.scan_at==SCAN && rx.sync_hits>=44 && rx.run<53) {
            rx.scan[0]=f;
            rx.scan_at=1;
            rx.last_sync=rx.clock;
            rx.run=rx.sync_hits=0;
            return;
        }
#endif
        if (rx.scan_at<SCAN) {
            rx.scan[rx.scan_at++]=f;
            if (rx.scan_at==SCAN) end_line();
        }
    }
    if (f>=1140 && f<=1260) { rx.run++; return; }
    unsigned run=rx.run;
    rx.run=0;
    if (rx.phase!=RECEIVING) {
#ifdef SSTV_LATE_JOIN
        unsigned mode=run>=216 && run<=432 ? read_vis(run) : 0;
        unsigned measured=0;
        if (!mode && run>=23 && run<=185)
            mode=observe_line(run,&measured);
        if (!mode) return;
#else
#ifdef SSTV_BASIC
        if (run<216 || run>432) return;
#else
        if (run<251 || run>352) return;
#endif
        unsigned mode=read_vis(run);
#endif
#ifdef SSTV_BASIC
        const struct Mode *m=lookup(mode);
        if (mode!=ROBOT36 && mode!=MARTIN_M1 && !m) return;
        stream.m=m;
        if (m) start_stream(m);
#else
        if (mode!=ROBOT36 && mode!=MARTIN_M1) return;
#endif
        clear_image();
        rx.mode=mode;
        rx.rows=rx.sync_hits=rx.sync_sum=rx.fraction=0;
#ifdef SSTV_LATE_JOIN
        rx.span=0;
        rx.robot_period=mode==ROBOT36 ? measured : 0;
#ifdef SSTV_TX_STUDY
        rx.hold_period=rx.vis_run=0;
#endif
        rx.skips=rx.silence=0;
        rx.live=measured!=0;
        if (rx.live && mode==ROBOT36) rx.skips=rx.separator==1;
        if (rx.live && m && m->edge) {
            stream.time=m->edge+125;
            stream.aligned=1;
            start_channel(m->channels); /* Red only; start with the next complete RGB row. */
        }
        if (rx.live && m && !m->edge) stream.time=125;
        rx.edge=rx.candidate=rx.streak=0;
#endif
#ifdef SSTV_ROBOT_SYNC
        rx.missed_separator=rx.loss=0;
#endif
        rx.period=3572;
        rx.phase=RECEIVING;
        rx.locks++;
    } else {
        if (rx.scan_at!=SCAN || rx.clock-rx.last_sync<1184) return;
#ifdef SSTV_ROBOT_SYNC
        if (run>=56 && run<=88) rx.sync_hits=0;
#endif
        if (run<56 || run>88) return;
    }
    rx.scan[0]=f;
    rx.scan_at=1;
    rx.last_sync=rx.clock;
}

/* One bounded worker turn. Producer can preempt decoding, never the dequeue. */
void sstv_worker(void) {
    for (unsigned n=0; n<QUEUE && viewing(); n++) {
        int16_t pcm[6];
        unsigned old=lock();
        unsigned epoch=generation;
        if (!counts.active || read_at==write_at) { unlock(old); break; }
#ifdef SSTV_LATE_JOIN
        if (gallery_loading) { unlock(old); break; }
#endif
#ifdef SSTV_DEVICE
        in_worker=1;
#endif
        unsigned gap=gap_before[read_at%QUEUE];
        for (int i=0;i<6;i++) pcm[i]=queue[read_at%QUEUE][i];
        read_at++;
        unlock(old);
        if (worker_generation!=epoch) {
            zero(&rx,sizeof(rx));
            worker_generation=epoch;
        }
        if (gap) {
            rx.phase=LOST;
            rx.run=0;
            zero(rx.history,sizeof(rx.history));
        }
#ifdef SSTV_RX_DIAG
        /* The estimator discards eight low bits. Set its input scale from a
           48 ms peak during the leader, then hold the scale through the image.
           A sudden loud block immediately restores unity to prevent clipping. */
        unsigned raw_peak=0;
        for (unsigned i=0;i<6;i++) {
            unsigned mag=pcm[i]<0 ? -(int)pcm[i] : pcm[i];
            if (mag>raw_peak) raw_peak=mag;
        }
        if (rx.phase!=RECEIVING) {
            if (raw_peak>rx.level_peak) rx.level_peak=raw_peak;
            if (++rx.level_blocks==64) {
                rx.input_shift=rx.level_peak && rx.level_peak<=512 ? 5 :
                               rx.level_peak && rx.level_peak<=2048 ? 3 : 0;
                rx.level_blocks=rx.level_peak=0;
            }
        }
        if (raw_peak>(32767u>>rx.input_shift)) rx.input_shift=0;
        int gain=1<<rx.input_shift;
        for (int i=0;i<6;i++) sample8k(pcm[i]*gain);
#else
        for (int i=0;i<6;i++) sample8k(pcm[i]);
#endif
        old=lock();
#ifdef SSTV_DEVICE
        in_worker=0;
#endif
        if (generation==epoch && counts.active) {
            /* Report a gap at the tail even before another sample arrives.
               gap_pending also resets VIS history on the next admitted block. */
            if (read_at==write_at && gap_pending) rx.phase=LOST;
            counts.rows=rx.rows;
            counts.phase=rx.phase;
            counts.locks=rx.locks;
            counts.mode=rx.mode;
            counts.samples+=6;
            counts.processed++;
#ifdef SSTV_RX_DIAG
            vis_status=rx.vis_result;
#ifdef SSTV_ROBOT_SYNC
            robot_loss=rx.loss;
#endif
            if (raw_peak>block_peak) block_peak=raw_peak;
            if (counts.processed==1 || !(counts.processed&511)) {
                displayed_peak=block_peak;
                block_peak=0;
            }
#endif
        }
        unlock(old);
    }
}

#ifdef SSTV_TX_STUDY
#include "sstv-j140-tx.h"
#endif

void sstv_prepare_frame(void) {
#ifdef SSTV_TX_STUDY
    tx_frame();
#endif
#ifdef SSTV_DEVICE
    unsigned old=lock();
    if (!viewing()) {
        counts.active=0;
        void *retired=in_worker ? 0 : canvas_owner;
        if (retired) { pixels=0; canvas_owner=0; }
        unlock(old);
        if (retired) ((void (*)(void *))0x20127a78)(retired);
        if (current_menu()!=PICTURE && current_menu()!=RX_PICTURE) unavailable=0;
        return;
    }
#ifdef SSTV_LATE_JOIN
    if (gallery_slot && current_menu()==PICTURE) {
        gallery_slot=gallery_loading=0;
        read_at=write_at;
        generation++;
        counts.rows=counts.mode=counts.phase=0;
    }
#endif
    unlock(old);
#endif
    if (!counts.active) return;
    if (!viewing()) {
        counts.active=0;
        return;
    }
    unsigned complete_rows=counts.mode==ROBOT36 ? counts.rows & ~1u : counts.rows;
    unsigned label_mode=counts.phase==LOST ? 0 : counts.mode;
    if (current_menu() == RX_PICTURE) {
        PAGE[348+3]=complete_rows != 0;
#ifdef SSTV_LATE_JOIN
        if (gallery_slot) PAGE[348+3]=1;
#endif
        PAGE[348+53]=PAGE[348+57]=0;
    }
#ifdef SSTV_RX_DIAG
    unsigned status=(!counts.offered ? 1 : !counts.processed ? 2 : 3)
        | ((counts.dropped!=0)<<2) | ((counts.phase==LOST)<<3) | (vis_status<<4);
    if (current_menu()==PICTURE && (last_peak!=displayed_peak || last_status!=status)) {
        *(volatile uint8_t *)0x20380c98 |= 1;
        last_peak=displayed_peak;
        last_status=status;
    }
#endif
    if (painted!=complete_rows || painted_mode!=label_mode) {
        *(volatile uint8_t *)0x20380c98 |= 1;
        painted=complete_rows;
        painted_mode=label_mode;
    }
}

unsigned sstv_thumbnail_ready(unsigned native) {
    return viewing() && current_menu() == PICTURE ? counts.rows >= (counts.mode==ROBOT36 ? 2u : 1u) : native;
}

const char *sstv_picture_text(unsigned field) {
#ifdef SSTV_TX_STUDY
    if (tx_half() && field==0x2e4) {
        const char *text=tx_button_text();
        return text ? text : "SEND";
    }
    if (viewing() && current_menu()==276) {
        if (field==0x59f) return "MODE";
        if (field==0x599) return "TX Mode";
        if (field==0x59a) return tx_mode_name();
        if (field==0x59b) return tx_mode>=2 ? basic_modes[tx_mode-2].size : tx_mode ? "320 x 256" : "320 x 240";
        if (field==0x59c) return "";
    }
#endif
#ifdef SSTV_DEVICE
    if (unavailable && field==0x2e1) return "RX unavailable";
#ifdef SSTV_RX_DIAG
    if (viewing() && field==0x2e4) {
        if (!counts.offered) return "NO PCM";
        if (!counts.processed) return "QUEUE";
        peak_text[0]='P'; peak_text[1]=' ';
        return number(peak_text,2,displayed_peak);
    }
    if (viewing() && field==0x2e3) {
        unsigned vis=vis_status;
        if (counts.dropped) return "GAP";
        if (vis==129) return "PARITY";
        if (vis) {
            vis_text[0]='V';vis_text[1]='I';vis_text[2]='S';vis_text[3]=' ';
            return number(vis_text,4,vis-1);
        }
        if (counts.phase==LOST) {
#ifdef SSTV_ROBOT_SYNC
            if (robot_loss==1) return "SYNC";
            if (robot_loss==2) return "COLOR";
#endif
            return "LOST";
        }
#ifdef SSTV_LATE_JOIN
        if (rx.live) return "MID RX";
#endif
    }
#endif
#ifdef SSTV_TX_STUDY
    if (tx_half() && field==0x2e3) return counts.phase==RECEIVING ? "RX IMG" : "RX";
#endif
    if ((viewing() || unavailable) && (field==0x2e3 || field==0x2e4))
        return field==0x2e3 ? "RX ONLY" : "---";
#endif
    if (!viewing()) return 0;
#ifdef SSTV_LATE_JOIN
    extern const char *sstv_gallery_text(unsigned);
    const char *archive_label=sstv_gallery_text(field);
    if (archive_label) return archive_label;
    if (field==0x568 || field==0x56a || field==0x56f) return 0;
#endif
#ifdef SSTV_BASIC
    const struct Mode *m=lookup(counts.mode);
    if (m && (field==0x56c || counts.phase!=LOST
#ifdef SSTV_LATE_JOIN
              || rx.live
#endif
              )) return field==0x56c ? m->size : m->name;
#endif
    if (field==0x56c)
        return counts.mode==MARTIN_M1 ? "320 x 256" : "320 x 240";
#ifdef SSTV_LATE_JOIN
    if (counts.phase==LOST && rx.live && counts.mode)
        return counts.mode==ROBOT36 ? "Robot 36" : "Martin M1";
#endif
    if (counts.phase==LOST && field==0x2e1) return "SSTV AUTO";
    if (counts.mode==MARTIN_M1) return "Martin M1";
    if (counts.mode==ROBOT36) return "Robot 36";
    return "SSTV AUTO";
}

#ifdef SSTV_DEVICE
volatile unsigned sstv_choice;
unsigned sstv_rx_only(void) { return viewing() || unavailable; }
void sstv_picker_open(void) {
    ((void (*)(unsigned))0x200efe64)(0);
    *(volatile uint16_t *)0x203e1b1a=0x0202;
    ((void (*)(unsigned,unsigned))0x200cd628)(280,0xffff);
}
static void sstv_to_dv(void) {
    unavailable=0;
    ((void (*)(void))0x200cd828)();
    ((void (*)(unsigned))0x200801e4)(PICTURE);
}
unsigned sstv_select(void) {
    ((void (*)(void (*)(void)))0x200cd7dc)(sstv_choice ? sstv_open : sstv_to_dv);
    return 2;
}
#endif

/* Only the two stock RX draws use the decoder's pixels. */
uintptr_t sstv_source(unsigned caller) {
    return (caller==0x201909e8 || caller==0x2018f84c) && viewing()
        ? (uintptr_t)image : 0x20625d84;
}
#ifdef SSTV_LATE_JOIN
#include "sstv-archive.h"
#endif

