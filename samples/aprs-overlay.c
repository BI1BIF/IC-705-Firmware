/* The mode task owns module allocation. Audio callbacks pin it until they return. */
#include <stdint.h>
#include "aprs-overlay-layout.h"

extern void *radio_alloc(unsigned size);
extern void radio_free(void *p);
static uint8_t *allocation;
uint8_t *loaded;
static uint8_t saved[KEEP_BYTES];
static unsigned have_saved;

static void copy(uint8_t *to, const uint8_t *from, unsigned n)
{
    while (n--)
        *to++ = *from++;
}

/* The installer supplies one image for this region, linked on a 32-byte boundary.
   All absolute data references and external ARM branches are fixed up before use. */
#ifdef APRS_SLOT_IMAGE
uint32_t bound_hz;
static uint32_t retry_at;
static unsigned retry_pending;
static uint8_t *history_tail, *history_last;
static void release_new_history(void)
{
    if (have_saved)
        return;
    if (history_last)
        radio_free(history_last);
    radio_free(history_tail);
    history_last = history_tail = 0;
}
const char aprs_name[] = "APRS", aprs_paused[] = "APRS (Paused)";
unsigned mode_choice;
static unsigned tx_enabled, mount_seen, mode_dirty;
static unsigned audio_users;
enum { ROW_BYTES=72 };
static unsigned mode_open;
extern void aprs_native_open(unsigned id,unsigned parent);

static unsigned irq_lock(void)
{
    unsigned flags;
    __asm__ volatile("mrs %0,cpsr\ncpsid i" : "=r"(flags) :: "memory");
    return flags;
}
static void irq_restore(unsigned flags)
{
    __asm__ volatile("msr cpsr_c,%0" :: "r"(flags) : "memory");
}

static uint8_t *pin_audio(unsigned drain)
{
    unsigned flags = irq_lock();
    uint8_t *base = loaded;
    if (base && (drain || (bound_hz && bound_hz == *(volatile uint32_t *)0x20380714)))
        ++audio_users;
    else
        base = 0;
    irq_restore(flags);
    return base;
}

static void unpin_audio(void)
{
    unsigned flags = irq_lock();
    --audio_users;
    irq_restore(flags);
}

void aprs_slot_note(void)
{
    uint8_t *base = pin_audio(0);
    if (base) {
        ((void (*)(void))(base + NOTE_DMA))();
        unpin_audio();
    }
}

void aprs_slot_copy(int16_t *pcm)
{
    uint8_t *base = pin_audio(0);
    if (!base) {
        ((void (*)(int16_t *))NATIVE_COPY)(pcm);
        return;
    }
    ((void (*)(int16_t *))(base + COPY_PCM))(pcm);
    unpin_audio();
}

void aprs_slot_drain(void)
{
    uint8_t *base = pin_audio(1);
    if (base) {
        ((void (*)(void))(base + RECORD_RX))();
        unpin_audio();
    }
}

static unsigned plain_fm(void)
{
    return (*(volatile uint8_t *)0x203e2128 >> 4) == 7 &&
           !(*(volatile uint8_t *)0x203e2129 & 1) &&
           !(*(volatile uint8_t *)0x203809a1 & 0x10) &&
           !*(volatile unsigned *)FT_STATE && !*(volatile unsigned *)FT_STAGE &&
           !*(volatile unsigned *)SSTV_STAGE && !((unsigned (*)(void))SSTV_RX)();
}

unsigned aprs_mode_initial(void) { return tx_enabled; }

/* GPS and the FUNCTION shortcut share one binding and one transmit permission. */
void aprs_set_mode(unsigned mode)
{
    if (mode && !bound_hz && (!plain_fm() || !*(volatile uint32_t *)0x20380714))
        return;
    if (!mode)
        bound_hz=0;
    else if (!bound_hz)
        bound_hz = *(volatile uint32_t *)0x20380714;
    if (mode && *(volatile uint8_t *)0x203eb172) {
        *(volatile uint8_t *)0x203eb172 = 0;
        ((void (*)(unsigned))APPLY_DV)(478);
    }
    mode_dirty=1;
    tx_enabled = mode==2;
    if (loaded) {
        if (loaded[TX_ENABLED]!=tx_enabled) ((void (*)(void))(loaded+TIMER_RESET))();
        loaded[TX_ENABLED] = tx_enabled;
        if (!tx_enabled) ((void (*)(void))(loaded+MSG_DISARM))();
        ((void (*)(uint32_t))(loaded+SET_CHANNEL))(bound_hz);
    }
    retry_pending = 0;
}

static void apply_mode(void)
{
    aprs_set_mode(1+(mode_choice!=0));
    *(volatile uint16_t *)0x203804d8 = 3;
    ((void (*)(void))CLOSE_MODE)();
}

unsigned aprs_mode_choose(void)
{
    if (!bound_hz && (!plain_fm() || !*(volatile uint32_t *)0x20380714))
        return 0;
    ((void (*)(void (*)(void)))DEFER)(apply_mode);
    return 1;
}

unsigned aprs_mode_closed(void)
{
    if (mode_open) {
        unsigned flags = irq_lock();
        for (unsigned i=0;i<3;++i)
            copy((uint8_t *)MODE_ROWS+i*ROW_BYTES,(uint8_t *)MODE_ROWS-ROW_BYTES,ROW_BYTES);
        mode_open = 0;
        irq_restore(flags);
    }
    return 4;
}

unsigned aprs_mode_row(unsigned row)
{
    volatile uint16_t *list = (volatile uint16_t *)0x203804c8;
    if (list[6] != 478)
        return 0;
    if (row + list[9] == 3) {
        if (mode_open)
            return 1;
        unsigned flags = irq_lock();
        copy((uint8_t *)MODE_ROWS,(uint8_t *)MODE_TEMPLATE,3*ROW_BYTES);
        mode_open = 1;
        irq_restore(flags);
        *(volatile uint16_t *)0x203e1b1a = 0x0202;
        aprs_native_open(MODE_PICKER,0xffff);
        return 1;
    }
    if (bound_hz) aprs_set_mode(0);
    return 0;
}

const char *aprs_mode_label(void)
{
    if (!bound_hz)
        return 0;
    return plain_fm() && *(volatile uint32_t *)0x20380714 == bound_hz ? aprs_name : aprs_paused;
}

/* The factory resource-bank byte is also used by FT's country atlas. */
static const uint8_t *resource(unsigned offset)
{
    return (const uint8_t *)(*(volatile uint8_t *)0x2038089d ? 0x18000000u : 0x185f0000u) + offset;
}

static uint32_t fingerprint(const uint8_t *p, unsigned length, uint32_t hash)
{
    while (length--)
        hash = (hash ^ *p++) * 16777619u;
    return hash;
}

static uintptr_t aprs_overlay_load(void)
#else
uintptr_t aprs_overlay_load(const uint8_t *image)
#endif
{
    if (loaded)
        return (uintptr_t)loaded;
#ifdef APRS_SLOT_IMAGE
    const uint8_t *first = resource(FIRST_OFFSET);
    const uint8_t *tail = resource(TAIL_OFFSET);
    if (*(const uint32_t *)first != SLOT_HASH)
        return 0;
    const uint16_t *absolute = (const uint16_t *)(tail + RELOC_OFFSET);
    const uint16_t *branches = absolute + ABS_COUNT;
    /* Put surviving records before the temporary decoder in the stock heap.
       Otherwise the records can split the free block used for the SSTV canvases. */
    if (!history_tail) {
        history_tail = radio_alloc(HISTORY_TAIL_BYTES);
        if (!history_tail)
            return 0;
        history_last = radio_alloc(HISTORY_LAST_BYTES);
        if (!history_last) {
            radio_free(history_tail);history_tail=0;
            return 0;
        }
    }
#endif
    allocation = radio_alloc(MEMORY_BYTES + 31);
    if (!allocation) {
#ifdef APRS_SLOT_IMAGE
        release_new_history();
#endif
        return 0;
    }
    uint8_t *base = (uint8_t *)(((uintptr_t)allocation + 31) & ~31u);
    uint32_t delta = (uintptr_t)base - LINK_BASE;
#ifdef APRS_SLOT_IMAGE
    if (fingerprint(first+4,FIRST_PACKED,2166136261u)!=FIRST_HASH || fingerprint(tail, PACKED_TAIL, 2166136261u) != TAIL_HASH) {
        radio_free(allocation);
        allocation=0;
        release_new_history();
        return 0;
    }
    ((void (*)(const uint8_t *,uint8_t *))UNPACK)(first+4,base);
    ((void (*)(const uint8_t *,uint8_t *))UNPACK)(tail,base+FIRST_BYTES);
    uint32_t hash = fingerprint(base, IMAGE_BYTES, 2166136261u);
    if (fingerprint((const uint8_t *)absolute, 2*(ABS_COUNT+BRANCH_COUNT), hash) != SLOT_HASH) {
        radio_free(allocation);
        allocation = 0;
        release_new_history();
        return 0;
    }
#else
    copy(base, image, IMAGE_BYTES);
#endif
    for (unsigned i = IMAGE_BYTES; i < MEMORY_BYTES; ++i)
        base[i] = 0;
#ifdef APRS_SLOT_IMAGE
    enum { reloc_unit=4 };
#else
    enum { reloc_unit=1 };
#endif
    for (unsigned i = 0; i < ABS_COUNT; ++i)
        *(uint32_t *)(base + reloc_unit*absolute[i]) += delta;
    for (unsigned i = 0; i < BRANCH_COUNT; ++i) {
        uint32_t *op = (uint32_t *)(base + reloc_unit*branches[i]);
        *op = (*op & 0xff000000) | ((*op - (delta >> 2)) & 0x00ffffff);
    }
    if (have_saved)
        copy(base + KEEP_OFFSET, saved, KEEP_BYTES);
#ifdef APRS_SLOT_IMAGE
    *(uint8_t **)(base + HISTORY_TAIL_PTR) = history_tail;
    *(uint8_t **)(base + HISTORY_LAST_PTR) = history_last;
#endif
    /* Cortex-A9 uses 32-byte cache lines. Publish generated code before calling it. */
    for (uintptr_t p = (uintptr_t)base; p < (uintptr_t)base + IMAGE_BYTES; p += 32)
        __asm__ volatile("mcr p15, 0, %0, c7, c11, 1" :: "r"(p) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
    for (uintptr_t p = (uintptr_t)base; p < (uintptr_t)base + IMAGE_BYTES; p += 32)
        __asm__ volatile("mcr p15, 0, %0, c7, c5, 1" :: "r"(p) : "memory");
    __asm__ volatile("dsb sy\n\tisb" ::: "memory");
    ((void (*)(void))(base + TIMER_RESET))();
    loaded = base;
    return (uintptr_t)loaded;
}

#ifdef APRS_SLOT_IMAGE
void aprs_slot_settings(void)
{
    if (plain_fm() && aprs_overlay_load())
        ((void (*)(void))(loaded+UI_SETTINGS))();
}

void aprs_slot_quick(unsigned id,unsigned parent)
{
    if (id==1 && loaded && bound_hz && bound_hz==*(volatile uint32_t *)0x20380714 && plain_fm())
        ((void (*)(unsigned,unsigned))(loaded+UI_QUICK))(id,parent);
    else
        ((void (*)(unsigned,unsigned))OPEN_MODE)(id,parent);
}

void aprs_slot_restore_ui(void)
{
    if (loaded)
        ((void (*)(void))(loaded+UI_RESTORE))();
}

unsigned aprs_slot_input(unsigned offset, unsigned fallback)
{
    uint8_t *base=pin_audio(1);
    if (!base)
        return ((unsigned (*)(void))fallback)();
    unsigned result=((unsigned (*)(void))(base+offset))();
    unpin_audio();
    return result;
}

void aprs_slot_update(void)
{
    uint8_t *base=pin_audio(1);
    if (base) {
        ((void (*)(void))(base+PANEL_UPDATE))();
        unpin_audio();
    }
}

static unsigned tx_dispatch(unsigned arg,unsigned entry,unsigned original)
{
    uint8_t *base=pin_audio(1);
    if (base) {
        if (*(volatile unsigned *)(base+TX_STAGE)) {
            unsigned result=((unsigned (*)(unsigned))(base+entry))(arg);
            unpin_audio();
            return result;
        }
        unpin_audio();
    }
    return ((unsigned (*)(unsigned))original)(arg);
}
unsigned aprs_slot_source(unsigned arg) { return tx_dispatch(arg,TX_SOURCE,FT_SOURCE); }
unsigned aprs_slot_request(unsigned arg) { return tx_dispatch(arg,TX_REQUEST,FT_REQUEST); }
unsigned aprs_slot_mod(void) { return tx_dispatch(0,TX_MOD,FT_MOD); }
#endif

unsigned aprs_overlay_unload(void)
{
    if (!loaded)
        return 1;
#ifdef APRS_SLOT_IMAGE
    if (((unsigned (*)(void))(loaded+UI_BUSY))())
        return 0;
    unsigned flags = irq_lock();
    if (audio_users) {
        irq_restore(flags);
        return 0;
    }
#endif
    if (*(volatile unsigned *)(loaded + TX_STAGE) || loaded[POPUP_OWNED] ||
        *(volatile unsigned *)(loaded + RX_READ) != *(volatile unsigned *)(loaded + RX_WRITTEN)) {
#ifdef APRS_SLOT_IMAGE
        irq_restore(flags);
#endif
        return 0;
    }
    uint8_t *old = loaded;
    loaded = 0;
#ifdef APRS_SLOT_IMAGE
    irq_restore(flags);
#endif
    copy(saved, old + KEEP_OFFSET, KEEP_BYTES);
#ifdef APRS_SLOT_IMAGE
    if (!bound_hz && !*(uint32_t *)(old+RECORD_COUNT)) {
        radio_free(history_last);radio_free(history_tail);
        history_tail=history_last=0;
    }
#endif
    have_saved = 1;
    radio_free(allocation);
    allocation = 0;
    return 1;
}

#ifdef APRS_SLOT_IMAGE
/* The GPS selector supplies zero for OFF or the selected ordinary FM frequency. */
void aprs_overlay_bind(uint32_t hz)
{
    bound_hz = hz;
    retry_pending = 0;
}

void aprs_overlay_prepare(void)
{
    ((void (*)(void))FT_PREPARE)();
    unsigned card=*(volatile uint8_t *)0x20380172;
    if (card!=3 && card!=4) mount_seen=0;
    else if (*(volatile uint8_t *)0x203eb172<=2 && plain_fm() && (loaded || !mount_seen || mode_dirty)) {
        if (aprs_overlay_load()) {
            ((void (*)(uint32_t *,unsigned *,unsigned,unsigned))(loaded+CONFIG_POLL))(
                &bound_hz,&tx_enabled,!mount_seen,mode_dirty);
            mount_seen=1;mode_dirty=0;
        }
    }
    if (!bound_hz && !loaded)
        return;
    /* Only the armed timer needs the overlay while listening on a different FM VFO. */
    if (!bound_hz || !plain_fm() || (*(volatile uint32_t *)0x20380714 != bound_hz &&
        !(tx_enabled && (loaded ? loaded[AUTO_ENABLE] : saved[AUTO_ENABLE-KEEP_OFFSET])))) {
        retry_pending = 0;
        aprs_overlay_unload();
        return;
    }
    uint32_t now = *(volatile uint32_t *)0x20381e08;
    if (!loaded && (!retry_pending || (int32_t)(now - retry_at) >= 0)) {
        if (!aprs_overlay_load()) {
            retry_pending = 1;
            retry_at = now + 1000;
            return;
        }
        retry_pending = 0;
    }
    if (loaded) {
        if (loaded[TX_ENABLED] != tx_enabled) {
            loaded[TX_ENABLED] = tx_enabled;
            ((void (*)(void))(loaded + TIMER_RESET))();
        }
        ((void (*)(uint32_t))(loaded + SET_CHANNEL))(bound_hz);
    }
}
#endif
