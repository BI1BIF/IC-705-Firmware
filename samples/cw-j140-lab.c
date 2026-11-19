// Emulator-only session. These addresses are tied to the verified Japanese 1.40 image.
#define CW_SESSION
#include "cw-arm.c"
#include "cw-audio-spectrum.h"

#define U8(a) (*(volatile const uint8_t *)(a))
#define U16(a) (*(volatile const uint16_t *)(a))
#define U32(a) (*(volatile const uint32_t *)(a))

enum { SCOPE = 80, SCOPE_SAMPLES = 64, TEXT = 128, QUEUE = 64, TITLE_TOP = 149, BODY_BOTTOM = 238, PANEL_BOTTOM = 272,
       SPEED_X = 331, SET_Y = 241, KEY_STEP = 96, KEY_W = 93, KEY_H = 29, HOLD_X = 98,
       SCOPE_X = 291, SCOPE_Y = 176, SCOPE_W = 184, SCOPE_H = 60, WAVE_W = 88,
       FFT_X = 387-SCOPE_X, FFT_W = 87, FFT_H = 27, HISTORY = SCOPE_H-FFT_H,
       PICK_X = 12, PICK_W = 86, PICK_Y = 217, PICK_H = 21, MULTI_LEFT = 361,
       AF_RIGHT = 118, AF_TOP = 157,
       TWIN_LEFT = 130, TWIN_TOP = 153, TWIN_RIGHT = 350, TWIN_BOTTOM = 239,
       SCOPE_INTERVAL_MS = 80 };
enum { AUTO, LOCK, MANUAL };
enum { TOUCH_IDLE, TOUCH_OTHER, TOUCH_HOLD, TOUCH_STOCK };
enum { SETUP_NONE, SETUP_FILTER, SETUP_THRESH, INITIAL_HZ = 600, MIN_LEVEL = 350, LEVEL_STEP = 250,
       MAX_LEVEL = 9850 };
enum { FILTER_WIDE, FILTER_AUTO, FILTER_FIX, TRACK_DELAY = 4 };
enum { COLOR_FFT, COLOR_WAVE, COLOR_RX, COLOR_COUNT };
static const uint32_t color_default[COLOR_COUNT] = {0x5ae7ffff, 0x00ff00ff, 0x00dc00ff};
typedef struct { int16_t low, high; } WaveRange;
typedef struct { uint32_t generation, fed, hz, wave, fft, live; } ScopeStamp;
typedef struct {
    uint32_t active, blocked, fed, pending, scope_next, text_length;
    WaveRange scope[SCOPE];
    char text[TEXT];
    Decoder decoder;
    int16_t pcm[80];
    uint32_t separate, generation, worker_generation, read, write, drops, scope_count;
    int16_t queue[QUEUE][6];
    uint32_t auto_dot, locked_dot, touch, speed_picker, speed_mode;
    uint32_t held, held_length, hold_started;
    char held_text[TEXT];
    uint32_t menu_two;
    uint32_t adjust, setup, fix_hz, threshold, manual_threshold;
    uint32_t filter_mode, tracked_hz;
    uint32_t scope_pending;
    WaveRange scope_partial;
    uint32_t color_open, color_item, color_channel, colors[COLOR_COUNT];
#ifdef CW_RTX
    uint32_t audio_refresh;
#endif
    uint32_t blank_touch_polls;
    uint32_t frame_at;
    ScopeStamp scope_stamp;
    uint32_t scope_at;
} Session;

#ifdef CW_STOCK_STATE
extern const uintptr_t cw_state_anchor;
#define STATE_BASE cw_state_anchor
#else
#define STATE_BASE 0x21001000u
#endif
#define session ((Session *)STATE_BASE)
typedef struct {
    uint32_t next, count;
    uint8_t row[HISTORY][CW_SPECTRUM_BINS];
    CwAudioSpectrum work;
    int16_t delay[TRACK_DELAY][80];
    unsigned head, pitch, strength, candidate, quiet;
} Spectrum;
#define spectrum ((Spectrum *)(STATE_BASE+0x780))
#define rx_filter ((FixedFilter *)(STATE_BASE+0xe00))

// Additional display history follows the unchanged 4 KiB capture/decoder ABI.
// The one startup allocation owns it for the whole session; no UI-owned frees.
enum { RX_TEXT = 384, RX_ROWS = 4, RX_WIDTH = (287-8-2)*64, RX_MAGIC = 0x43575235 };
typedef struct {
    uint32_t length, rows;
    uint16_t start[RX_ROWS], length_at[RX_ROWS];
    char text[RX_TEXT];
} RxPage;
typedef struct { uint32_t magic, revision; RxPage live, held; } RxText;
#define rx_text ((RxText *)(STATE_BASE+0x1000))
_Static_assert(sizeof(RxText) <= 1024 && 4*(RX_WIDTH/215)+16 < RX_TEXT,
               "four narrow-glyph rows and decoder output fit the extra state KiB");
static unsigned receive_advance(unsigned char ch);
typedef uint16_t ScopeCanvas[SCOPE_H][SCOPE_W];
#ifdef CW_STOCK_CANVAS
#define canvas (**(ScopeCanvas **)(STATE_BASE+0x714))
#define canvas_allocation (*(void **)(STATE_BASE+0x718))
enum { SCOPE_ALIGN_EXTRA = 24 };
_Static_assert((SCOPE_W*sizeof(uint16_t)) % 16 == 0 &&
               ((SCOPE_H-1)*SCOPE_W*sizeof(uint16_t)) % 32 == 16,
               "RGB565 pitch and last-row alignment");
#else
#define canvas (*(ScopeCanvas *)0x2100d000)
#endif
_Static_assert(offsetof(Session, decoder) == 472 && offsetof(Session, auto_dot) == 1516 &&
               offsetof(Session, adjust) == 1680 && offsetof(Session, scope_pending) == 1708 &&
               offsetof(Session, colors) == 1728 && sizeof(Session) <= 0x700,
               "replay ABI");
_Static_assert(sizeof(Spectrum) <= 0x680 && sizeof(FixedFilter) <= 0x200, "separate capture buffers");

// The offline profile runs ARM System mode on a single core. Guard sharing
// against interrupt-driven preemption; never run the detector with IRQ masked.
static inline uint32_t lock(void) {
    uint32_t status;
    __asm__ volatile ("mrs %0,cpsr\n\tcpsid i" : "=r"(status) :: "memory");
    return status;
}

static inline void unlock(uint32_t status) {
    __asm__ volatile ("msr cpsr_c,%0" :: "r"(status) : "memory");
}

static int cw_mode(void) {
    return U8(0x203e2128) >> 5 == 1;  // mode nibble 2 or 3 (CW, CW-R on VFO A)
}

#ifdef CW_RTX
static int stock_popup(void) {
    return U8(0x204bd0f4) != 0;  // Stock compositor's popup flag; M.SCOPE uses a different field.
}

static int live_popup(void) {
    return ((int (*)(void))0x200f0fdc)();
}

static int stock_multi_drawn(void) {
    return U8(0x204bd028) != 0;  // Original committed MULTI side panel on target 4.
}

static int stock_af_drawn(void) {
    return U8(0x204bd19e) && U8(0x204bd19f) == 2;  // Original AF side panel on target 3.
}

static int stock_twin_drawn(void) {
    return U8(0x204bd0bc) && U8(0x204bd0bd) == 1;  // Timed TWIN PBT tip, target 9.
}

static void request_refresh(void) {
    // The normal main-loop display dispatcher consumes this stock dirty bit.
    volatile uint8_t *dirty = (volatile uint8_t *)0x203806f7;
    uint32_t status = lock();
    *dirty |= 0x40;
    unlock(status);
}
#else
static inline void request_refresh(void) {}
#endif

static void clear(void *ptr, size_t len) {
    for (uint8_t *p = ptr; len; --len)
        *p++ = 0;
}

enum { RX_CLEAR, RX_MODE, RX_UI, RX_PTT, RX_REQ, RX_WAIT, RX_DSP, RX_KEY };

#ifdef CW_RX_DIAGNOSTICS
enum { DIAG_RAW_SIGNAL = 1, DIAG_TAP_SIGNAL = 2, DIAG_DROP = 4, DIAG_MS = 500 };
typedef struct { unsigned raw, tap, queued, processed, flags, guard; } RxWindow;
typedef struct { RxWindow live, shown; uint32_t since; } RxDiagnostics;
#define rx_diag ((RxDiagnostics *)(STATE_BASE+0x71c))
_Static_assert(sizeof(RxDiagnostics) <= 0x780-0x71c, "diagnostics must not overlap the FFT workspace");

static unsigned has_signal(const int16_t *samples, unsigned count) {
    while (count--)
        if (*samples++)
            return 1;
    return 0;
}

void cw_diag_raw(const int16_t *raw) {
    if (!session->active)
        return;
    unsigned signal = has_signal(raw, 36);
    uint32_t status = lock();
    if (session->active) {
        ++rx_diag->live.raw;
        rx_diag->live.flags |= signal ? DIAG_RAW_SIGNAL : 0;
    }
    unlock(status);
}

static int diag_tick(void) {
    uint32_t status = lock();
    uint32_t now = U32(0x20381e08);
    int changed = 0;
    if (now - rx_diag->since >= DIAG_MS) {
        const RxWindow *a = &rx_diag->live, *b = &rx_diag->shown;
        changed = a->raw != b->raw || a->tap != b->tap || a->queued != b->queued ||
                  a->processed != b->processed || a->flags != b->flags || a->guard != b->guard;
        rx_diag->shown = *a;
        clear(&rx_diag->live, sizeof rx_diag->live);
        rx_diag->since = now;
    }
    unlock(status);
    return changed;
}
#endif

static void rx_page_copy(RxPage *to, const RxPage *from) {
    to->length = from->length;
    to->rows = from->rows;
    for (unsigned i = 0; i < RX_ROWS; ++i) {
        to->start[i] = from->start[i];
        to->length_at[i] = from->length_at[i];
    }
    for (unsigned i = 0; i < from->length; ++i)
        to->text[i] = from->text[i];
}

// Caller holds the lock. Invalidate an in-flight worker snapshot after CLR/EXIT.
static void rx_text_reset(void) {
    ++rx_text->revision;
    rx_text->magic = RX_MAGIC;
    rx_text->live.length = rx_text->live.rows = 0;
    rx_text->held.length = rx_text->held.rows = 0;
}

// Use the same proportional advances and word breaks as the stock text painter.
// This pure layout work is called outside the capture/worker critical sections.
__attribute__((noinline))
static void rx_page_layout(RxPage *p) {
    for (;;) {
        unsigned start = 0, row = 0, first_next = 0;
        for (unsigned i = 0; i < RX_ROWS; ++i)
            p->start[i] = p->length_at[i] = 0;
        while (start < p->length && row < RX_ROWS) {
            unsigned remaining = p->length-start, n = 0, width = 0;
            while (n < remaining) {
                width += receive_advance(p->text[start+n]);
                if (width > RX_WIDTH)
                    break;
                ++n;
            }
            if (remaining > n && p->text[start+n] != ' ') {
                unsigned split = n;
                while (split && p->text[start+split] != ' ')
                    --split;
                if (split)
                    n = split;
            }
            // All supported glyphs are narrower than a row; still ensure progress.
            if (!n)
                n = 1;
            p->start[row] = start;
            p->length_at[row++] = n;
            start += n;
            if (start < p->length && p->text[start] == ' ')
                ++start;
            if (row == 1)
                first_next = start;
        }
        p->rows = row;
        if (start == p->length)
            return;
        // The fifth line starts a new bottom row: discard a whole first row.
        for (unsigned i = first_next; i < p->length; ++i)
            p->text[i-first_next] = p->text[i];
        p->length -= first_next;
    }
}

__attribute__((noinline))
static void rx_page_append(RxPage *p, char ch) {
    // Layout keeps at most 328 narrowest supported glyphs in four rows.
    if (p->length < RX_TEXT)
        p->text[p->length++] = ch;
    rx_page_layout(p);
}

// Caller holds the lock. Preserve the old 128-byte view for earlier probes.
static void rx_legacy_text(Session *s, const RxPage *p) {
    unsigned begin = p->length > TEXT ? p->length-TEXT : 0;
    s->text_length = p->length-begin;
    for (unsigned i = 0; i < s->text_length; ++i)
        s->text[i] = p->text[begin+i];
}

// Caller holds the lock. Logical reset is constant time even with a full queue.
static void discontinuity(Session *s) {
    ++s->generation;
    s->read = s->write;
    s->scope_count = s->scope_next = s->scope_pending = 0;
    spectrum->next = spectrum->count = 0;
    s->tracked_hz = 0;
    s->auto_dot = 0;
    s->separate = s->text_length != 0;
}

// Original KEY SPEED is a read-only input here. Use the stock WPM getter;
// the decoder uses its own 10 ms ticks and never changes KEYER timing.
static unsigned key_half_ms(void) {
    unsigned half = U16(0x2038024a);
    return half >= 50 && half <= 400 ? half : 0;
}

// Original OSTM0 IRQ 134 adds one to the RTX tick each 32,000 P0 clocks (1 ms).
static uint32_t hold_now(void) {
    return U32(0x20381e08);
}

static int hold_elapsed(uint32_t start) {
    return hold_now() - start >= 1000u;
}

static void end_hold_touch(Session *s, int clear_text) {
    uint32_t status = lock();
    if (clear_text) {
        s->text_length = s->held = s->held_length = s->separate = 0;
        rx_text_reset();
    } else if ((s->held ^= 1)) {
        s->held_length = s->text_length;
        for (unsigned i = 0; i < s->held_length; ++i)
            s->held_text[i] = s->text[i];
        if (rx_text->magic == RX_MAGIC)
            rx_page_copy(&rx_text->held, &rx_text->live);
    }
    unlock(status);
    request_refresh();
}

static void decoder_setting(Session *s, unsigned mode, unsigned hz, unsigned threshold, unsigned manual) {
    uint32_t status = lock();
    if (mode != s->filter_mode || hz != s->fix_hz ||
        (mode != FILTER_WIDE && (threshold != s->threshold || manual != s->manual_threshold))) {
        // Do not publish buffered marks identified using a previous channel or floor.
        ++s->generation;
        s->read = s->write;
        s->auto_dot = 0;
        s->tracked_hz = 0;
        s->separate = s->text_length != 0;
    }
    s->fix_hz = hz;
    s->filter_mode = mode;
    s->threshold = threshold;
    s->manual_threshold = manual;
    unlock(status);
}

static unsigned display_color(const Session *s, unsigned item) {
    return s->colors[item] ? s->colors[item] : color_default[item];
}

static int color_touch(Session *s, unsigned col, unsigned x, unsigned y) {
    if (col == 4) {
        s->color_open = 0;
    } else if (col == 3) {
        s->colors[s->color_item] = 0;
    } else if (col < 3) {
        s->color_channel = col;
    } else if (x >= 8 && x < 280 && y >= 165 && y < 213) {
        s->color_item = (y-165)/16;
    } else if (x >= 14 && x <= 269 && y >= 214 && y < 236) {
        unsigned shift = 24-8*s->color_channel;
        unsigned rgb = display_color(s, s->color_item);
        s->colors[s->color_item] = (rgb & ~(255u << shift)) | ((x-14) << shift);
    } else {
        return 0;
    }
    return 1;
}

unsigned cw_lab_touch(void) {
    Session *s = session;
#ifdef CW_RTX
    if (live_popup() || U8(0x203807dd) != 0)
        return 0;
#endif
    if (!s->active) {
        s->touch = TOUCH_IDLE;
        s->blank_touch_polls = 0;
        return 0;
    }
    // Snapshot the mailbox together, as the stock touch reader does.
    uint32_t saved = lock();
    unsigned up = U8(0x203e1f23);
    unsigned x = U8(0x203e1f24) * 256u + U8(0x203e1f25);
    unsigned y = U8(0x203e1f26) * 256u + U8(0x203e1f27);
    unlock(saved);
    int no_position = x == 9999 && y == 9999;  // Stock panel's released coordinates.
    if (up || no_position || !(x | y)) {
        // One missing report during a press is not necessarily a release.
        int blank = !up && !no_position;
        if (blank && s->touch != TOUCH_IDLE && ++s->blank_touch_polls < 2)
            return 1;
        if (s->touch == TOUCH_HOLD)
            end_hold_touch(s, hold_elapsed(s->hold_started));
        s->touch = TOUCH_IDLE;
        s->blank_touch_polls = 0;
        return blank;  // Let the stock reader see its own release, never the raw (0,0) report.
    }
    if (x >= 480 || y >= 272)
        return 1;
    s->blank_touch_polls = 0;
#ifdef CW_RTX
    // Stock input wakes the display before dispatching a button; consume that gesture.
    if (s->touch == TOUCH_IDLE &&
        (((int (*)(void))0x20090630)() || ((int (*)(unsigned))0x20090a80)(0) || U8(0x20380721))) {
        s->touch = TOUCH_OTHER;
        return 1;
    }
#endif
    int stock_touch = y < TITLE_TOP;
#ifdef CW_RTX
    unsigned side = U8(0x20380569);  // Stock side-panel ID, before the next LCD frame.
    stock_touch |= side == 18 ? x < AF_RIGHT && y >= AF_TOP : side && x >= MULTI_LEFT;
    stock_touch |= U8(0x203804a6) && U8(0x203804a7) == 1 && x >= TWIN_LEFT && x < TWIN_RIGHT &&
                   y >= TWIN_TOP && y < TWIN_BOTTOM;
#endif
    // A gesture starting in the stock UI stays there until release.
    if (s->touch == TOUCH_STOCK || (s->touch == TOUCH_IDLE && stock_touch)) {
        s->touch = TOUCH_STOCK;
        return 0;
    }
    int hold_key = x >= HOLD_X && x < HOLD_X+KEY_W && y >= SET_Y && y < SET_Y+KEY_H;
    if (s->touch == TOUCH_HOLD) {
        if (!hold_key) {
            s->touch = TOUCH_OTHER;
        } else if (hold_elapsed(s->hold_started)) {
            end_hold_touch(s, 1);
            s->touch = TOUCH_OTHER;
        }
    } else if (s->touch == TOUCH_IDLE) {
        s->touch = TOUCH_OTHER;
        int accepted = 1;
        int bottom = y >= SET_Y && y < SET_Y+KEY_H;
        unsigned col = 5;
        if (bottom)
            for (unsigned k = 0; k < 5; ++k)
                if (x >= 2+k*KEY_STEP && x < 2+k*KEY_STEP+KEY_W)
                    col = k;
        if (s->color_open) {
            accepted = color_touch(s, col, x, y);
        } else if (!s->adjust && col == 4) {
            s->color_open = 1;
            s->setup = SETUP_NONE;
            s->speed_picker = 0;
        } else if ((x >= SPEED_X && x < 480 && y >= TITLE_TOP && y < TITLE_TOP+16) || (s->adjust && col == 2)) {
            s->speed_picker ^= 1;
            s->setup = SETUP_NONE;
        } else if ((s->menu_two || s->adjust) && col == 3) {
            s->adjust ^= 1;
            s->setup = SETUP_NONE;
            s->speed_picker = 0;
        } else if (!s->adjust && col == 0) {
            s->menu_two ^= 1;
            s->setup = SETUP_NONE;
            s->speed_picker = 0;
        } else if ((s->adjust && col < 2) || (!s->speed_picker && y >= SCOPE_Y && y < SCOPE_Y+SCOPE_H &&
                    ((x >= SCOPE_X && x < SCOPE_X+WAVE_W) || (x >= SCOPE_X+FFT_X && x < SCOPE_X+FFT_X+FFT_W)))) {
            unsigned next = (s->adjust && col < 2 ? col == 1 : x >= SCOPE_X+FFT_X) ? SETUP_FILTER : SETUP_THRESH;
            if (s->setup == SETUP_FILTER && next == SETUP_FILTER && !bottom && s->fix_hz) {
                unsigned hz = 300 + ((x-(SCOPE_X+FFT_X))*95 + (FFT_W-1)/2)/(FFT_W-1)*10;
                decoder_setting(s, FILTER_FIX, hz, s->threshold, s->manual_threshold);
            } else {
                s->setup = s->setup == next ? SETUP_NONE : next;
                s->speed_picker = 0;
            }
        } else if (s->speed_picker) {
            if (x >= PICK_X && x < PICK_X+3*PICK_W && y >= PICK_Y && y < PICK_Y+PICK_H) {
                unsigned mode = x < PICK_X+PICK_W ? AUTO : x < PICK_X+2*PICK_W ? LOCK : MANUAL;
                uint32_t status = lock();
                if (mode == AUTO || (mode == LOCK && (s->speed_mode == LOCK || s->auto_dot)) ||
                    (mode == MANUAL && key_half_ms())) {
                    if (mode == LOCK && s->speed_mode != LOCK)
                        s->locked_dot = s->auto_dot;
                    s->speed_mode = mode;
                }
                unlock(status);
            }
            s->speed_picker = 0;
        } else if (s->setup && x >= PICK_X && x < PICK_X+3*PICK_W && y >= PICK_Y && y < PICK_Y+PICK_H) {
            unsigned choice = (x-PICK_X)/PICK_W;
            if (s->setup == SETUP_FILTER) {
                unsigned mode = choice == 0 ? FILTER_AUTO : choice == 1 ? FILTER_FIX : FILTER_WIDE;
                unsigned hz = mode == FILTER_FIX ? (s->fix_hz ? s->fix_hz : INITIAL_HZ) : 0;
                decoder_setting(s, mode, hz, s->threshold, s->manual_threshold);
            } else if (s->filter_mode != FILTER_WIDE) {
                unsigned level = s->threshold;
                if (choice == 1 && level > MIN_LEVEL)
                    level -= LEVEL_STEP;
                if (choice == 2 && level < MAX_LEVEL)
                    level += LEVEL_STEP;
                decoder_setting(s, s->filter_mode, s->fix_hz, level,
                                choice == 0 ? !s->manual_threshold : s->manual_threshold);
            }
        } else if (s->setup) {
            s->setup = SETUP_NONE;
        } else if (hold_key && !s->menu_two) {
            s->hold_started = hold_now();
            s->touch = TOUCH_HOLD;
        } else {
            accepted = 0;
        }
        if (accepted) {
#ifdef CW_RTX
            // Same confirmation tone as a stock MENU tile; respects Beep and level settings.
            ((void (*)(unsigned))0x2007d478)(1);
#endif
            request_refresh();
        }
    }
    return 1;
}

void cw_lab_input(void) {
    unsigned page = U8(0x203807dd);
    int submenu = U8(0x203e84c9) | U8(0x203e84ca);
#ifndef CW_MERGED_ENTRY
    unsigned up = U8(0x203e1f23);
    unsigned x = U8(0x203e1f24) * 256u + U8(0x203e1f25);
    unsigned y = U8(0x203e1f26) * 256u + U8(0x203e1f27);
    int empty_touch = !up && U8(0x204021b6) == 0x60 && !U16(0x204021b8);
#endif
    if (session->active) {
        unsigned key = U8(0x20380431);
        // The stock scanner has already dispatched the navigation key.
        int exit = key == 9;
#ifdef CW_RTX
        // The last composed state identifies the stock side panel that received EXIT.
        exit &= !stock_multi_drawn() && !stock_af_drawn();
#endif
        int leave = exit || (page != 0 && page != 5) || submenu || !cw_mode();
#ifdef CW_RTX
        // Use the stock live query that feeds the compositor. Its previous frame
        // can still show KEYER/DECODE after the selection callback has closed it.
        leave |= key == 5 || key == 6 || key == 8 || live_popup();
        if (!leave && !page) {
#ifdef CW_RX_DIAGNOSTICS
            int diag_refresh = diag_tick();
#else
            int diag_refresh = 0;
#endif
            uint32_t now = hold_now();
            // Keep new PCM at full rate; coalesce only unsolicited LCD redraws.
            // Physical controls still request an immediate original UI update.
            if (diag_refresh || (session->fed - session->audio_refresh >= 8 &&
                                 now - session->frame_at >= SCOPE_INTERVAL_MS)) {
                session->audio_refresh = session->fed;
                session->frame_at = now;
                request_refresh();
            }
        }
#endif
        if (leave) {
            uint32_t status = lock();
            session->active = session->blocked = session->fed = session->text_length = session->drops = 0;
            session->locked_dot = session->touch = session->speed_picker = session->speed_mode = 0;
            session->blank_touch_polls = 0;
            session->held = session->held_length = session->menu_two = 0;
            session->adjust = session->setup = session->fix_hz = session->threshold = session->manual_threshold = 0;
            session->filter_mode = FILTER_WIDE;
            session->color_open = session->color_item = session->color_channel = 0;
            clear(session->colors, sizeof session->colors);
#ifdef CW_RTX
            session->audio_refresh = 0;
            session->frame_at = 0;
#endif
            discontinuity(session);
            rx_text_reset();
            unlock(status);
#ifdef CW_RTX
            // EXIT at HOME can change only the overlay, not the stock page ID.
            if (!page)
                request_refresh();
#endif
        }
        return;
    }
#ifndef CW_MERGED_ENTRY
    if (page != 5 || submenu || !cw_mode() || U8(0x204bab5d) != 2 || U8(0x204bd24b) != 1 ||
        !empty_touch)
        return;
    if (x >= 9 && x <= 149 && y >= 229 && y <= 265) {
        uint32_t status = lock();
        // Do not let the opening press also hit the first softkey.
        session->touch = TOUCH_OTHER;
        session->blocked = 1;
        session->threshold = MIN_LEVEL;
        session->active = 1;
        unlock(status);
#ifdef CW_RTX
        // Close the grid like the stock RTTY overlay; leave the VFO backing frame live.
        ((void (*)(unsigned))0x200efe64)(0);
#endif
    }
#endif
}

#ifdef CW_MERGED_ENTRY
extern volatile uint8_t cw_picker_choice;

static void cw_picker_to_keyer(void) {
    ((void (*)(void))0x200cd828)();  // Original selector close.
    if (cw_mode())
        ((void (*)(unsigned))0x200801e4)(13);
}

static void cw_picker_to_decode(void) {
    ((void (*)(void))0x200cd828)();
    if (!cw_mode() || !STATE_BASE)
        return;
    // Close the original lower-screen application through its own teardown.
    ((void (*)(void))0x200f192c)();
    uint32_t status = lock();
    session->touch = TOUCH_OTHER;
    session->blocked = 1;
    session->threshold = MIN_LEVEL;
#ifdef CW_RX_DIAGNOSTICS
    clear(rx_diag, sizeof *rx_diag);
    rx_diag->since = hold_now();
#endif
    session->active = 1;
    unlock(status);
    ((void (*)(unsigned))0x200efe64)(0);
}

int cw_picker_select(void) {
    ((void (*)(void (*)(void)))0x200cd7dc)(cw_picker_choice ? cw_picker_to_decode : cw_picker_to_keyer);
    return 2;
}

void cw_picker_open(void) {
    if (!cw_mode() || !STATE_BASE) {
        ((void (*)(unsigned))0x200801e4)(13);
        return;
    }
    ((void (*)(unsigned))0x200efe64)(0);
    // IDs above 47 do not have their close policy copied by the stock opener.
    *(volatile uint16_t *)0x203e1b1a = 0x0202;
    ((void (*)(unsigned, unsigned))0x200cd628)(277, 0xffff);
}
#endif

// Caller holds the lock. Both capture and the worker see a TX request even
// if the other task has not yet reached the next audio callback.
static int receiving(Session *s) {
    if (!s->active)
        return 0;
    // DSP TX feedback is the same upstream bit used to draw the solid TX icon.
    // Stock requests and key activity can precede it. Raw PTT can stay asserted
    // while stock is still receiving (D1 field trace); it isn't a TX request.
    unsigned guard = !cw_mode() ? RX_MODE : (U8(0x203806f4) & 0xa0) ? RX_UI :
                     U32(0x203809ac) ? RX_REQ :
                     U32(0x203809b0) ? RX_WAIT : (U8(0x203809a1) & 0x10) ? RX_DSP :
                     U8(0x203e1e68) ? RX_KEY : RX_CLEAR;
    if (guard) {
#ifdef CW_RX_DIAGNOSTICS
        rx_diag->live.guard = guard;
#endif
        if (!s->blocked) {
            discontinuity(s);
            s->blocked = 1;
        }
        return 0;
    }
    // Use the same ungated PCM source as stock AUDIO SCOPE. The recording
    // gate is not a TX indication; the real TX checks above still apply.
    s->blocked = 0;
    return 1;
}

static void append_received(Session *s, const char *out, unsigned count, unsigned epoch,
                            unsigned revision) {
    RxPage page;
    uint32_t status = lock();
    if (!receiving(s) || s->generation != epoch || rx_text->revision != revision) {
        unlock(status);
        return;
    }
    unsigned separate = s->separate;
    if (rx_text->magic == RX_MAGIC) {
        rx_page_copy(&page, &rx_text->live);
    } else {
        // Offline fixtures may seed the original 128-byte fields directly.
        page.length = s->text_length;
        page.rows = 0;
        for (unsigned i = 0; i < page.length; ++i)
            page.text[i] = s->text[i];
    }
    unlock(status);
    rx_page_layout(&page);
    if (count && separate && page.length)
        rx_page_append(&page, ' ');
    for (unsigned i = 0; i < count; ++i)
        if (page.length || out[i] != ' ')
            rx_page_append(&page, out[i]);
    status = lock();
    if (receiving(s) && s->generation == epoch && rx_text->revision == revision) {
        rx_text->magic = RX_MAGIC;
        rx_page_copy(&rx_text->live, &page);
        rx_legacy_text(s, &page);
        if (count)
            s->separate = 0;
    }
    unlock(status);
}

#ifndef CW_RTX
void cw_lab_refresh_rx(void) {
    uint32_t status = lock();
    receiving(session);
    unlock(status);
}
#endif

void cw_lab_pcm(const int16_t *block) {
    Session *s = session;
    uint32_t status = lock();
#ifdef CW_RX_DIAGNOSTICS
    if (s->active) {
        ++rx_diag->live.tap;
        if (has_signal(block, 6))
            rx_diag->live.flags |= DIAG_TAP_SIGNAL;
    }
#endif
    if (!receiving(s)) {
        unlock(status);
        return;
    }
    if (s->write - s->read == QUEUE) {
        s->drops += QUEUE;
#ifdef CW_RX_DIAGNOSTICS
        rx_diag->live.flags |= DIAG_DROP;
#endif
        discontinuity(s);
    }
#ifdef CW_RTX
    int wake = s->read == s->write;
#endif
    int16_t *slot = s->queue[s->write & (QUEUE-1)];
    for (unsigned i = 0; i < 6; ++i)
        slot[i] = block[i];
    ++s->write;
#ifdef CW_RX_DIAGNOSTICS
    ++rx_diag->live.queued;
#endif
    unlock(status);
#ifdef CW_RTX
    // Only notify on empty -> nonempty, and never issue an SVC in the critical section.
    if (wake) {
        const unsigned thread = U32(STATE_BASE+0x700);
        if (thread)
            ((unsigned (*)(unsigned, unsigned))0x202d4851)(thread, 1);
    }
#endif
}

static unsigned peak_pitch(const uint8_t *levels, unsigned bin) {
    unsigned center = 300 + 50*bin;
    if (!bin || bin+1 == CW_SPECTRUM_BINS)
        return center;
    int left = levels[bin-1], right = levels[bin+1];
    int slope = right-left, curve = 2*levels[bin]-left-right;
    // Round the three-bin parabolic estimate to 10 Hz without a division helper.
    int magnitude = slope < 0 ? -slope : slope;
    unsigned step = 5*magnitude > 3*curve ? 20 : 5*magnitude > curve ? 10 : 0;
    return slope < 0 ? center-step : center+step;
}

static unsigned pitch_bin(unsigned pitch) {
    return (pitch-300+25)/50;
}

static void track_pitch(Spectrum *s, const uint8_t *levels) {
    unsigned best = 0, sum = 0;
    for (unsigned i = 0; i < CW_SPECTRUM_BINS; ++i) {
        if (levels[i] > levels[best])
            best = i;
        sum += levels[i];
    }
    unsigned peak = levels[best];
    if (s->strength > 2)
        s->strength -= 2;
    if (peak < 78 || peak < sum/CW_SPECTRUM_BINS + 42) {
        if (s->quiet < 10)
            ++s->quiet;
        s->candidate = 0;
        return;
    }
    unsigned previous = s->pitch ? pitch_bin(s->pitch) : 0;
    // Hold the incumbent through Morse gaps; do not chase weaker marks between its elements.
    if (!s->pitch || s->quiet == 10 ||
        (peak >= s->strength + 24 && s->candidate == best+1)) {
        s->pitch = peak_pitch(levels, best);
        s->strength = peak;
        s->candidate = 0;
    } else {
        if (levels[previous] > s->strength)
            s->strength = levels[previous];
        s->candidate = peak >= s->strength + 24 ? best+1 : 0;
    }
    s->quiet = 0;
}

// Single, non-reentrant decoder worker. It may be preempted by capture or EXIT.
unsigned cw_lab_work(unsigned budget) {
    Session *s = session;
    unsigned done = 0;
    for (; done < budget; ++done) {
        int16_t samples[6];
        uint32_t status = lock();
        if (!receiving(s) || s->read == s->write) {
            unlock(status);
            break;
        }
        unsigned epoch = s->generation;
        unsigned text_revision = rx_text->revision;
        unsigned half = s->speed_mode == MANUAL ? key_half_ms() : 0;
        unsigned fixed_dot = s->speed_mode == LOCK ? s->locked_dot : half ? (half+10)/20 : 0;
        unsigned filter_mode = s->filter_mode;
        unsigned setting = (s->manual_threshold ? 0 : FIXED_AUTO_LEVEL) | s->threshold << 16;
        unsigned pitch = s->fix_hz;
        const int16_t *slot = s->queue[s->read++ & (QUEUE-1)];
#ifdef CW_RX_DIAGNOSTICS
        ++rx_diag->live.processed;
#endif
        for (unsigned i = 0; i < 6; ++i) {
            int16_t v = samples[i] = slot[i];
            // Keep both signed PCM extremes; skipping samples aliases CW tones on an 88-pixel display.
            if (!s->scope_pending || v < s->scope_partial.low)
                s->scope_partial.low = v;
            if (!s->scope_pending || v > s->scope_partial.high)
                s->scope_partial.high = v;
            if (++s->scope_pending == SCOPE_SAMPLES) {
                s->scope[s->scope_next++] = s->scope_partial;
                if (s->scope_next == SCOPE)
                    s->scope_next = 0;
                if (s->scope_count < SCOPE)
                    ++s->scope_count;
                s->scope_pending = 0;
            }
        }
        unlock(status);
        if (s->worker_generation != epoch) {
            clear(&s->decoder, sizeof s->decoder);
            if (filter_mode != FILTER_WIDE)
                clear(rx_filter, sizeof *rx_filter);
            if (filter_mode == FILTER_AUTO) {
                clear(spectrum->delay, sizeof spectrum->delay);
                spectrum->head = spectrum->pitch = spectrum->strength = spectrum->candidate = spectrum->quiet = 0;
            }
            cw_spectrum_reset(&spectrum->work);
            s->pending = 0;
            s->worker_generation = epoch;
        }
        for (unsigned i = 0; i < 6; ++i) {
            s->pcm[s->pending++] = samples[i];
            if (s->pending == 80) {
                s->pending = 0;
                uint8_t levels[CW_SPECTRUM_BINS];
                int new_row = cw_spectrum_feed(&spectrum->work, s->pcm, levels);
                unsigned n;
                int changed_station = 0;
                if (filter_mode == FILTER_AUTO) {
                    unsigned previous = spectrum->pitch;
                    if (new_row)
                        track_pitch(spectrum, levels);
                    pitch = spectrum->pitch;
                    changed_station = previous && distance(pitch_bin(pitch), pitch_bin(previous)) > 1;
                    if (changed_station) {
                        clear(&s->decoder, sizeof s->decoder);
                        rx_filter->peak = 0;
                        rx_filter->noise = 0;
                        rx_filter->marks = 0;
                    }
                    // Wait for the spectrum before deciding whether the first mark was present.
                    int16_t *delayed = spectrum->delay[spectrum->head];
                    unsigned verify = !fixed_dot && (setting & FIXED_AUTO_LEVEL) ? FIXED_AUTO_TRACK : 0;
                    n = pitch ? cw_feed_fixed(&s->decoder, delayed, rx_filter, setting | pitch | verify, fixed_dot) : 0;
                    for (unsigned j = 0; j < 80; ++j)
                        delayed[j] = s->pcm[j];
                    spectrum->head = (spectrum->head+1) % TRACK_DELAY;
                } else if (pitch) {
                    n = cw_feed_fixed(&s->decoder, s->pcm, rx_filter, setting | pitch, fixed_dot);
                } else {
                    n = cw_feed(&s->decoder, s->pcm, fixed_dot);
                }
                status = lock();
                if (receiving(s) && s->generation == epoch) {
                    s->tracked_hz = filter_mode == FILTER_AUTO ? pitch : 0;
                    if (changed_station && s->text_length)
                        s->separate = 1;
                    if (new_row) {
                        for (unsigned bin = 0; bin < CW_SPECTRUM_BINS; ++bin)
                            spectrum->row[spectrum->next][bin] = levels[bin];
                        if (++spectrum->next == HISTORY)
                            spectrum->next = 0;
                        if (spectrum->count < HISTORY)
                            ++spectrum->count;
                    }
                    ++s->fed;
                    if (!fixed_dot && s->speed_mode == AUTO)
                        s->auto_dot = s->decoder.dot;
                }
                unlock(status);
                if (n)
                    append_received(s, s->decoder.output, n, epoch, text_revision);
            }
        }
    }
    return done;
}

// Reuse the original text painter without touching the RTTY queues or page state.
// The test panel supplies the background on the emulator's LCD surface.
typedef void (*StockText)(unsigned, unsigned, const char *, unsigned, unsigned,
                          unsigned, unsigned, const uint16_t *, unsigned, unsigned);
static const StockText draw_text = (StockText)0x20142698;

static void draw_line_color(const char *text, unsigned length, unsigned x, unsigned y, unsigned size, unsigned color) {
    const uint16_t point[2] = {x, y};
    draw_text(18, 0, text, length, 1, size, color, point, 0, 0);
}

static void draw_line(const char *text, unsigned length, unsigned x, unsigned y, unsigned size) {
    draw_line_color(text, length, x, y, size, 15);
}

static void draw_center(const char *text, unsigned length, unsigned x, unsigned y, unsigned size, unsigned color) {
    const uint16_t point[2] = {x, y};
    draw_text(18, 0, text, length, 1, size, color, point, 1, 0); // Stock text alignment: centered.
}

static void draw_key(const char *text, unsigned length, unsigned column, unsigned color) {
    draw_center(text, length, 48+column*KEY_STEP, SET_Y+20, length > 7 ? 15 : 17, color);
}

__attribute__((noinline))
static void draw_rgb_line(const char *text, unsigned length, unsigned x, unsigned y, unsigned size, unsigned rgb) {
    typedef void (*PaintedText)(unsigned, unsigned, const char *, unsigned, unsigned,
                               unsigned, const uint32_t *, const uint16_t *, unsigned, unsigned);
    const uint16_t point[] = {x, y};
    uint32_t colors[length];
    for (unsigned i = 0; i < length; ++i)
        colors[i] = rgb;
    ((PaintedText)0x2014289c)(18, 0, text, length, 1, size, colors, point, 0, 0);
}

void cw_lab_title_strip(void) {
    const uint16_t heading[2] = {2, TITLE_TOP};
    ((void (*)(unsigned, unsigned, const uint16_t *))0x20145454)(18, 0x9a, heading);
}

void cw_lab_softkeys(void) {
    typedef void (*Tile)(unsigned, unsigned, const uint16_t *, unsigned, unsigned);
    typedef void (*Repeat)(unsigned, unsigned, const uint16_t *, unsigned, unsigned, unsigned);
    const Tile tile = (Tile)0x20148238;
    const Repeat repeat = (Repeat)0x20148430;
    // Same three stock RTTY sprites, with full-screen coordinates on target 18.
    for (unsigned x = 0; x < 5*KEY_STEP; x += KEY_STEP) {
        if (x == 2*KEY_STEP && !session->adjust && !session->menu_two && !session->color_open)
            continue;  // Leave the retired page-one key's slot empty.
        uint16_t point[2] = {x+12, SET_Y};
        repeat(18, 0xbd, point, 17, 4, KEY_H);
        point[0] = x+80;
        repeat(18, 0xbd, point, 1, 5, KEY_H);
        point[0] = x+2;
        tile(18, 0xbe, point, 10, KEY_H);
        point[0] = x+85;
        tile(18, 0xbc, point, 10, KEY_H);
    }
}

static void digits(char *end, unsigned number) {
    for (; number; ) {
        unsigned next = number/10;
        *--end = '0'+number-10*next;
        number = next;
    }
}

#ifdef CW_RX_DIAGNOSTICS
static void draw_diagnostics(const RxWindow *d) {
    static const char *const guard[] = {"", "MODE", "UI", "PTT", "REQ", "WAIT", "DSP", "KEY"};
    const char *status = !d->raw && !d->tap ? "D4 RX: NO PCM" :
                         !d->tap || ((d->flags & DIAG_RAW_SIGNAL) && !(d->flags & DIAG_TAP_SIGNAL)) ? "D4 RX: NO TAP SIGNAL" :
                         d->guard && !d->processed ? "D4 RX: TX BLOCK" :
                         d->queued && !d->processed ? "D4 RX: QUEUE STALL" :
                         d->flags & DIAG_DROP ? "D4 RX: QUEUE DROP" :
                         !(d->flags & DIAG_TAP_SIGNAL) ? "D4 RX: PCM ZERO" :
                         d->guard ? "D4 RX: INTERMITTENT" : d->processed ? "D4 RX: AUDIO OK" : "D4 RX: WAITING";
    unsigned n = 0;
    while (status[n]) ++n;
    draw_line(status, n, 8, 220, 11);
    if (d->guard) {
        const char *reason = guard[d->guard];
        for (n = 0; reason[n]; ++n) {}
        draw_line(reason, n, 154, 220, 11);
    }
    char counters[] = "RAW 000 TAP 000 IN 000 OUT 000";
    digits(counters+7, d->raw > 999 ? 999 : d->raw);
    digits(counters+15, d->tap > 999 ? 999 : d->tap);
    digits(counters+22, d->queued > 999 ? 999 : d->queued);
    digits(counters+sizeof counters-1, d->processed > 999 ? 999 : d->processed);
    draw_line(counters, sizeof counters-1, 8, 233, 11);
}
#endif

static unsigned receive_advance(unsigned char ch) {
    // J140's stock size-15 typeface advances in 1/64 pixels, measured at the text renderer.
    static const uint16_t letters[] = {
        800,710,681,808,618,564,804,802,328,431,738,562,1060,826,868,654,868,715,574,619,806,741,1118,743,736,626
    };
    if (ch >= 'A' && ch <= 'Z')
        return letters[ch-'A'];
    if (ch >= '0' && ch <= '9')
        return 629;
    switch (ch) {
    case ' ': return 293;
    case '.': case ',': case ':': return 313;
    case '?': return 596;
    case '/': return 480;
    case '=': return 629;
    case '-': return 319;
    case '\'': return 215;
    case '"': return 380;
    default: return 780;  // ~ (unrecognized pattern)
    }
}

__attribute__((noinline))
static void draw_color_settings(const Session *s) {
    static const char *const labels[] = {"FFT Scope Color", "Signal Wave Color", "RX Font Color"};
    static const uint8_t lengths[] = {15, 17, 13};
    draw_center("CW DECODE SET", 13, 240, TITLE_TOP+12, 14, 15);
    for (unsigned i = 0; i < COLOR_COUNT; ++i) {
        unsigned rgb = display_color(s, i);
        char values[] = "R000 G000 B000";
        digits(values+4, rgb>>24);
        digits(values+9, (rgb>>16)&255);
        digits(values+14, (rgb>>8)&255);
        draw_line_color(i == s->color_item ? ">" : " ", 1, 8, 178+16*i, 12, 15);
        draw_line(labels[i], lengths[i], 19, 178+16*i, 12);
        draw_rgb_line("##", 2, 139, 178+16*i, 12, rgb);
        draw_line(values, sizeof values-1, 169, 178+16*i, 12);
    }
    draw_line("0", 1, 14, 234, 10);
    draw_line("255", 3, 252, 234, 10);
    unsigned level = display_color(s, s->color_item) >> (24-8*s->color_channel) & 255;
    draw_line("|", 1, 12+level, 224, 10);
    for (unsigned i = 0; i < 3; ++i)
        draw_key("RGB"+i, 1, i, i == s->color_channel ? 53 : 15);
    draw_key("DEF", 3, 3, 15);
    draw_key("SET", 3, 4, 15);
    draw_line("AF 640 ms", 9, 292, 176, 10);
    draw_line("300-1250", 8, 387, 176, 10);
}

void cw_lab_draw(void) {
    const Session *s = session;
    RxPage page;
    uint32_t status = lock();
    unsigned active = s->active, held = s->held, length = held ? s->held_length : s->text_length;
    const char *src = held ? s->held_text : s->text;
    unsigned mode = s->speed_mode, picker = s->speed_picker, setup = s->setup;
    unsigned adjust = s->adjust, menu_two = s->menu_two, filter_mode = s->filter_mode;
    unsigned hz = filter_mode == FILTER_AUTO ? s->tracked_hz : s->fix_hz;
    unsigned threshold = s->threshold, manual = s->manual_threshold;
    unsigned dot = mode == LOCK ? s->locked_dot : s->auto_dot;
    int extended = rx_text->magic == RX_MAGIC &&
                   !(held && !rx_text->held.length && length);
    if (extended) {
        rx_page_copy(&page, held ? &rx_text->held : &rx_text->live);
    } else {
        page.length = length;
        page.rows = 0;
        for (unsigned i = 0; i < length; ++i)
            page.text[i] = src[i];
    }
    unlock(status);
    if (!active)
        return;
    if (s->color_open) {
        draw_color_settings(s);
        return;
    }
    draw_center("CW DECODE", 9, 240, TITLE_TOP+12, 14, 15);
    const unsigned visible_rows = picker || setup ? 2u : 4u;
    const unsigned first_row = 182, row_step = 16;
    if (!extended)
        rx_page_layout(&page);
    for (unsigned row = 0; row < page.rows && row < visible_rows; ++row) {
        unsigned start = page.start[row], n = page.length_at[row];
        if (s->colors[COLOR_RX])
            draw_rgb_line(page.text+start, n, 8, first_row+row_step*row, 15, s->colors[COLOR_RX]);
        else
            draw_line_color(page.text+start, n, 8, first_row+row_step*row, 15, 53);
    }
    char speed[] = " -- WPM";
    if ((mode == MANUAL && key_half_ms()) || (mode != MANUAL && dot)) {
        // The detector has 10 ms resolution. Avoid a division routine in the lab ELF.
        unsigned wpm;
        if (mode == MANUAL) {
            wpm = ((unsigned (*)(void))0x20060448)();
        } else {
            wpm = 0;
            for (unsigned ticks = 120 + dot/2; ticks >= dot; ticks -= dot)
                ++wpm;
        }
        if (wpm >= 100) {
            speed[0] = '1';
            wpm -= 100;
        }
        speed[1] = wpm >= 10 || speed[0] != ' ' ? '0' : ' ';
        for (; wpm >= 10; wpm -= 10)
            ++speed[1];
        speed[2] = '0' + wpm;
    }
    draw_line("AF 640 ms", 9, 292, 176, 10);
    draw_line("300-1250", 8, 387, 176, 10);
    if (held)
        draw_line("HOLD", 4, 10, 162, 11);
    // Disabled labels preserve the reference positions without implying a function.
    if (adjust) {
        draw_key("THRESH", 6, 0, 15);
        draw_key("FILTER", 6, 1, 15);
        draw_key("SPEED", 5, 2, 15);
        draw_key("ADJ", 3, 3, 15);
    } else if (menu_two) {
        draw_key("< 2 >", 5, 0, 15);
        draw_key("ADJ", 3, 3, 15);
    } else {
        draw_key("< 1 >", 5, 0, 15);
        draw_key("HOLD/CLR", 8, 1, 15);
        draw_key("TX MEM", 6, 3, 6);
    }
    if (!adjust)
        draw_key("SET", 3, 4, 15);
    draw_center(speed + (speed[0] == ' '), speed[0] == ' ' ? 6 : 7, 449, TITLE_TOP+12, 11, 15);
    const char *const modes[] = {"AUTO", "LOCK", "MANUAL"};
    draw_center(modes[mode], mode == MANUAL ? 6 : 4, 392, TITLE_TOP+12, 11, 15);
    if (picker) {
        draw_line("SPEED", 5, PICK_X+7, PICK_Y-4, 11);
        for (unsigned i = 0; i < 3; ++i)
            draw_center(modes[i], i == MANUAL ? 6 : 4, PICK_X+PICK_W/2+i*PICK_W, PICK_Y+14, 11, 15);
    } else if (setup == SETUP_FILTER) {
        if (filter_mode == FILTER_FIX) {
            char label[] = "FILTER FIX      HZ";
            digits(label+15, hz);
            draw_line(label, sizeof label-1, PICK_X+7, PICK_Y-4, 11);
        } else if (filter_mode == FILTER_AUTO) {
            char label[] = "FILTER AUTO     HZ";
            digits(label+15, hz);
            draw_line(hz ? label : "FILTER AUTO", hz ? sizeof label-1 : 11, PICK_X+7, PICK_Y-4, 11);
        } else {
            draw_line("FILTER WIDE", 11, PICK_X+7, PICK_Y-4, 11);
        }
        draw_center("AUTO", 4, PICK_X+PICK_W/2, PICK_Y+14, 11, 15);
        draw_center("FIX", 3, PICK_X+3*PICK_W/2, PICK_Y+14, 11, 15);
        draw_center("WIDE", 4, PICK_X+5*PICK_W/2, PICK_Y+14, 11, 15);
    } else if (setup == SETUP_THRESH) {
        char label[] = "THRESH     ";
        digits(label+11, threshold);
        if (filter_mode != FILTER_WIDE) {
            draw_line(label, sizeof label-1, PICK_X+7, PICK_Y-4, 11);
            draw_line(manual ? "MANUAL" : "AUTO", manual ? 6 : 4, 24, 231, 11);
            draw_line("-", 1, 147, 231, 11);
            draw_line("+", 1, 233, 231, 11);
        } else {
            draw_line("THRESH: AUTO OR FIX", 19, PICK_X+7, PICK_Y-4, 11);
        }
    }
}

#include "cw-scope-pixels.h"

static unsigned power_at(const uint8_t *levels, unsigned scaled) {
    unsigned bin = scaled >> 8, frac = scaled & 255;
    return bin == CW_SPECTRUM_BINS-1 ? levels[bin] :
           (levels[bin]*(256-frac) + levels[bin+1]*frac) >> 8;
}

static uint16_t rgb565(unsigned rgba) {
    return ((rgba >> 16) & 0xf800) | ((rgba >> 13) & 0x7e0) | ((rgba >> 11) & 0x1f);
}

// Same ARM scopes in the isolated panel and on the original redraw thread.
void cw_lab_scope_draw(void) {
    WaveRange points[SCOPE];
    uint8_t rows[HISTORY][CW_SPECTRUM_BINS];
    uint32_t status = lock();
    int live = receiving(session);
    unsigned hz = live ? session->fix_hz | session->tracked_hz : 0;
    unsigned count = live ? session->scope_count : 0;
    unsigned partial = live && session->scope_pending;
    unsigned history = live ? spectrum->count : 0;
    uint16_t wave_color = rgb565(display_color(session, COLOR_WAVE));
    uint16_t fft_color = rgb565(display_color(session, COLOR_FFT));
    ScopeStamp stamp = {session->generation, session->fed, hz, wave_color, fft_color, live ? 2u : 1u};
    const ScopeStamp *old = &session->scope_stamp;
    uint32_t now = hold_now();
    if (stamp.generation == old->generation && stamp.hz == old->hz &&
        stamp.wave == old->wave && stamp.fft == old->fft && stamp.live == old->live) {
        // RF frames also call us. Cap actual raster work, not just dirty requests.
#ifdef CW_RTX
        if (stamp.fed == old->fed || now - session->scope_at < SCOPE_INTERVAL_MS) {
#else
        if (stamp.fed == old->fed) {
#endif
            unlock(status);
            return;
        }
    }
    for (unsigned x = 0; x < SCOPE-partial; ++x) {
        unsigned at = x + count + partial;
        unsigned index = at-SCOPE + (count == SCOPE ? session->scope_next : 0);
        points[x] = at < SCOPE ? (WaveRange){0, 0} : session->scope[index >= SCOPE ? index-SCOPE : index];
    }
    if (partial)
        points[SCOPE-1] = session->scope_partial;
    unsigned at = spectrum->next;
    for (unsigned y = 0; y < history; ++y) {
        at = at ? at-1 : HISTORY-1;
        for (unsigned bin = 0; bin < CW_SPECTRUM_BINS; ++bin)
            rows[y][bin] = spectrum->row[at][bin];
    }
    unlock(status);

    // Both canvas bases are 32-bit aligned. Clear two RGB565 pixels at once;
    // may_alias keeps the halfword/word views explicit to the compiler.
    typedef uint32_t CanvasPair __attribute__((may_alias));
    CanvasPair *pairs = (CanvasPair *)canvas;
    for (unsigned i = 0; i < sizeof(ScopeCanvas)/sizeof(CanvasPair); ++i)
        pairs[i] = 0;
    for (unsigned y = 0; y < SCOPE_H; ++y)
        canvas[y][382-SCOPE_X] = 0x8c51;
    unsigned fft_previous = FFT_H-1;
    for (unsigned x = 0; x < WAVE_W; ++x) {
        WaveRange p = points[(x*SCOPE)/WAVE_W];
        int top = 27 - p.high*26/32768, bottom = 27 - p.low*26/32768;
        for (int y = top; y <= bottom; ++y)
            canvas[y][x] = wave_color;
        if (x >= FFT_W)
            continue;
        unsigned position = fft_positions[x];
        unsigned level = history ? power_at(rows[0], position) : 0;
        unsigned fft_next = FFT_H-1 - ((level*(FFT_H-2)*257 + 257) >> 16);
        if (!x)
            fft_previous = fft_next;
        for (unsigned y = fft_next < fft_previous ? fft_next : fft_previous;
             y <= (fft_next > fft_previous ? fft_next : fft_previous); ++y)
            canvas[y][FFT_X+x] = fft_color;
        fft_previous = fft_next;
        for (unsigned y = 0; y < history; ++y)
            canvas[FFT_H+y][FFT_X+x] = waterfall_palette[power_at(rows[y], position)];
    }
    if (hz) {
        unsigned marker = FFT_X + ((hz-300)*(FFT_W-1)+475)/950;
        for (unsigned y = 6; y < SCOPE_H; y += 4)
            canvas[y][marker] = 0xffff;
    }
#if defined(CW_RTX) && defined(CW_STOCK_CANVAS)
    // Stock 0x20148164 cleans CPU pixels before vgWritePixels consumes them.
    uintptr_t end = (uintptr_t)canvas + sizeof(ScopeCanvas);
    for (uintptr_t line = (uintptr_t)canvas & ~(uintptr_t)31; line < end; line += 32)
        __asm__ volatile ("mcr p15, 0, %0, c7, c10, 1\n\tdmb sy" :: "r"(line) : "memory");
    __asm__ volatile ("dsb sy" ::: "memory");
#endif
    // These keys describe the snapshot, even if the worker advanced while drawing.
    session->scope_stamp = stamp;
    session->scope_at = now;
}

#ifdef CW_RTX
// Only the waveform needs RGB565 scratch; the graphics backend fills the rest.
static void fill_rect(const float *rgba, int x, int y, int w, int h) {
    ((void (*)(unsigned, unsigned, const float *))0x202631f3)(0x1121, 4, rgba);
    ((void (*)(int, int, int, int))0x2026362f)(x, 272-y-h, w, h);
}

static void blit_cw_rect(const uint16_t *target, int left, int top, int right, int bottom) {
    enum { WIDTH = 480 };
    typedef void (*Blit)(const uint16_t *, int, unsigned, int, int, int, int);
    ((Blit)0x20263b13)(target + (bottom-1)*WIDTH + left, -WIDTH*2, 3,
                      left, PANEL_BOTTOM-bottom, right-left, bottom-top);
}

void cw_rtx_draw(void) {
    enum { WIDTH = 480 };
    typedef unsigned (*Select)(unsigned, unsigned);
    typedef void (*Blit)(const uint16_t *, int, unsigned, int, int, int, int);
    const Blit blit = (Blit)0x20263b13;
    const unsigned offscreen = ((unsigned (*)(void))0x20195188)();
    const unsigned display = ((unsigned (*)(void))0x20194c10)();
    if (!offscreen || !display)
        return;
#ifdef CW_STOCK_CANVAS
    ScopeCanvas **scope = (ScopeCanvas **)(STATE_BASE+0x714);
    if (!session->active && *scope) {
        ((void (*)(void *))0x20127a78)(canvas_allocation);
        canvas_allocation = 0;
        *scope = 0;
        session->scope_stamp.live = 0;
    }
#endif
    if (!session->active) {
#ifndef CW_MERGED_ENTRY
        if (!cw_mode() || U8(0x203807dd) != 5 || U8(0x204bab5d) != 2 || U8(0x204bd24b) != 1 ||
            U8(0x203e84c9) || U8(0x203e84ca) || !((Select)0x201951ac)(offscreen, 18))
            return;
        float saved[4];
        const float border[] = {77/255.0f, 77/255.0f, 77/255.0f, 1};
        const float background[] = {26/255.0f, 26/255.0f, 26/255.0f, 1};
        ((void (*)(unsigned, unsigned, float *))0x202632a1)(0x1121, 4, saved);
        fill_rect(border, 9, 229, 141, 37);
        fill_rect(background, 10, 230, 139, 35);
        ((void (*)(unsigned, unsigned, const float *))0x202631f3)(0x1121, 4, saved);
        draw_line("CW DECODE", 9, 32, 252, 15);
        if (((Select)0x20194c18)(display, U8(0x20380cbc))) {
            const uint16_t *target = *(const uint16_t **)((unsigned (*)(unsigned))0x20195190)(18);
            blit(target + 265*WIDTH + 9, -WIDTH*2, 3, 9, 272-266, 141, 37);
        }
#endif
        return;
    }

    // A stock screen can take over before the next input poll closes CW.
    if (U8(0x204bab5d) != 1 || stock_popup())
        return;

#ifdef CW_STOCK_CANVAS
    if (!*scope) {
        void *raw = ((void *(*)(unsigned))0x20127a28)(sizeof(ScopeCanvas) + SCOPE_ALIGN_EXTRA);
        if (raw) {
            canvas_allocation = raw;
            // Heap guarantees 8-byte alignment; the last RGB565 row is the original blitter's source.
            *scope = (ScopeCanvas *)((((uintptr_t)raw + 15u) & ~31u) + 16u);
        }
    }
    if (!*scope)
        return;
#endif
    cw_lab_scope_draw();
    if (!((Select)0x201951ac)(offscreen, 18))
        return;
    float saved[4];
    const float background[] = {0, 0, 0, 1};
    const float title[] = {41/255.0f, 40/255.0f, 41/255.0f, 1};
    const float border[] = {74/255.0f, 73/255.0f, 74/255.0f, 1};
    ((void (*)(unsigned, unsigned, float *))0x202632a1)(0x1121, 4, saved);
    fill_rect(background, 0, TITLE_TOP, WIDTH, 16);
    fill_rect(background, 0, TITLE_TOP+16, WIDTH, PANEL_BOTTOM-TITLE_TOP-16);
    cw_lab_title_strip();  // Stock RTTY title strip.
    const unsigned dividers[] = {2, 287, 382, 478};
    for (unsigned i = 0; i < 4; ++i)
        fill_rect(border, dividers[i], TITLE_TOP+16, 1, BODY_BOTTOM-TITLE_TOP-16);
    fill_rect(border, 2, BODY_BOTTOM-1, WIDTH-3, 1);
    if (session->color_open) {
        fill_rect(border, 14, 220, 256, 1);
    } else if (session->speed_picker || session->setup) {
        unsigned selected = session->speed_picker ? session->speed_mode : session->setup != SETUP_FILTER ? 0 :
                            session->filter_mode == FILTER_WIDE ? 2 : session->filter_mode-1;
        fill_rect(title, PICK_X, PICK_Y-15, 3*PICK_W, 15);
        for (unsigned i = 0; i < 3; ++i) {
            fill_rect(border, PICK_X+i*PICK_W, PICK_Y, PICK_W, PICK_H);
            fill_rect(i == selected ? border : title,
                      PICK_X+i*PICK_W+1, PICK_Y+1, PICK_W-2, PICK_H-2);
        }
    }
    ((void (*)(unsigned, unsigned, const float *))0x202631f3)(0x1121, 4, saved);
    blit(canvas[SCOPE_H-1], -SCOPE_W*2, 3, SCOPE_X, 272-SCOPE_Y-SCOPE_H, SCOPE_W, SCOPE_H);
    cw_lab_softkeys();
    cw_lab_draw();
    // Finish the producer while its offscreen context is current. The display
    // copy must not sample a surface with outstanding GPU writes.
    ((void (*)(void))0x20263191)();
    if (!((Select)0x20194c18)(display, U8(0x20380cbc)))
        return;
    const uint16_t *target = *(const uint16_t **)((unsigned (*)(unsigned))0x20195190)(18);
    int right = stock_multi_drawn() ? MULTI_LEFT : WIDTH;
    int left = stock_af_drawn() ? AF_RIGHT : 0;
    if (stock_twin_drawn()) {
        blit_cw_rect(target, left, TITLE_TOP, right, TWIN_TOP);
        blit_cw_rect(target, left, TWIN_TOP, TWIN_LEFT, TWIN_BOTTOM);
        blit_cw_rect(target, TWIN_RIGHT, TWIN_TOP, right, TWIN_BOTTOM);
        blit_cw_rect(target, left, TWIN_BOTTOM, right, PANEL_BOTTOM);
    } else {
        blit_cw_rect(target, left, TITLE_TOP, right, PANEL_BOTTOM);
    }
    if (left)
        blit_cw_rect(target, 0, TITLE_TOP, left, AF_TOP);
    // Match stock copy/restore ordering; the original final finish precedes VDC submit.
#ifdef CW_MERGED_ENTRY
    // The next original frame creates its text objects in the offscreen context.
    ((Select)0x201951ac)(offscreen, 18);
#endif
}
#endif
