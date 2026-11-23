#include <stdint.h>
#include "dmr-ui.h"
#include "dmr-layout.h"

#define BYTE(a) (*(volatile uint8_t *)(a))
#define WORD(a) (*(volatile uint32_t *)(a))
extern int sd_open(const char *,unsigned,int *), sd_close(int), sd_read(int,void *,unsigned,unsigned *);
extern void *radio_alloc(unsigned);
extern void radio_free(void *);
extern int dmr_resource_matches(const uint8_t *);
extern unsigned aprs_overlay_unload(void), factory_fm_available(void);
extern unsigned make_thread(const uintptr_t *,unsigned), signal_thread(unsigned,unsigned);
extern unsigned wait_signal(unsigned,unsigned), native_playback_queued(void);
extern void native_playback_read(int16_t *), aprs_slot_copy(int16_t *), aprs_slot_note(void);
extern unsigned stock_playback_page(unsigned page);

volatile uint8_t dmr_guard_active, dmr_owns_fm;
static unsigned thread_id, seq, tags[8], tune_tags[8];
static volatile unsigned tune_anchor, tune_generation;
static volatile unsigned users, starting, switching;
static uint8_t *image;
static void *allocation;
static volatile struct dmr_ui_status status;

/* Only the RX monitor decision uses the file player's listening behavior.
   The original squelch detection and recorder input still run. */
unsigned dmr_monitor_page(unsigned page) {
    return dmr_guard_active || stock_playback_page(page);
}

static unsigned lock(void) {
    unsigned flags;
    __asm__ volatile("mrs %0,cpsr\n cpsid i":"=r"(flags)::"memory");
    return flags;
}
static void unlock(unsigned flags) { __asm__ volatile("msr cpsr_c,%0"::"r"(flags):"memory"); }
static int transmitting(void) {
    return (BYTE(0x203806f4)&0xa0) || (BYTE(0x203809a1)&16) ||
        WORD(0x203809ac) || WORD(0x203809b0);
}
/* Keep symbol timing through small VFO corrections. Anchor this window to
   one frequency, so a series of fine steps cannot walk into another channel. */
static int same_channel(unsigned hz) {
    return hz-tune_anchor+500u<=1000u;
}
#ifdef DMR_RX_LAMP
static volatile unsigned voice_tune, voice_tick;
#define TICKS WORD(0x20381e08)
/* The stock caller has already checked RX LED and selected its receive path.
   Preserve its other indicator bits and leave the squelch sample untouched. */
unsigned dmr_rx_lamp(unsigned indicators,unsigned carrier) {
    if (dmr_guard_active && status.enabled==1) {
        carrier=!switching && status.phase==DMR_GROUP && voice_tune &&
            voice_tune==tune_generation && same_channel(WORD(0x20380714)) &&
            TICKS-voice_tick<=240;
    }
    return (indicators&~1u)|(carrier&1u);
}
#endif
static int load_resource(uint8_t *base) {
    int fd;
    unsigned n=0;
    if (sd_open("C:\\IC-705\\DMRRX.BIN",0,&fd)) return 0;
    int bad=sd_read(fd,base,RESOURCE_BYTES,&n);
    if (sd_close(fd) || bad || n!=RESOURCE_BYTES || !dmr_resource_matches(base)) return 0;
    const uint16_t *rel=(const uint16_t *)(base+IMAGE_BYTES);
    for (unsigned i=0;i<RELOC_COUNT;++i)
        ((uint32_t *)base)[rel[i]]+=(uintptr_t)base-LINK_BASE;
    for (unsigned i=IMAGE_BYTES;i<MEM_BYTES;++i) base[i]=0;
    for (unsigned i=0;i<IMAGE_BYTES;i+=32)
        __asm__ volatile("mcr p15,0,%0,c7,c11,1"::"r"(base+i):"memory");
    __asm__ volatile("dsb sy":::"memory");
    for (unsigned i=0;i<IMAGE_BYTES;i+=32)
        __asm__ volatile("mcr p15,0,%0,c7,c5,1"::"r"(base+i):"memory");
    __asm__ volatile("dsb sy\n isb":::"memory");
    return 1;
}
static void worker(void) {
    for (;;) {
        wait_signal(1,2);
        if (!dmr_guard_active) {
            if (!users && !starting) break;
            continue;
        }
        if (switching) {
            unsigned mode=status.enabled;
            ((void(*)(unsigned))(image+CORE_SWITCH))(mode);
            unsigned flags=lock();
            if (dmr_guard_active && status.enabled==mode) switching=0;
            unlock(flags);
            continue;
        }
        ((void(*)(void))(image+CORE_WORK))();
        ((void(*)(volatile struct dmr_ui_status *))(image+CORE_STATUS))(&status);
#ifdef DMR_RX_LAMP
        if (status.phase!=DMR_GROUP) voice_tune=0;
        else if (status.decoded_samples!=WORD(image+AUDIO_PRODUCED)) {
            voice_tick=TICKS;
            voice_tune=WORD(image+CORE_TUNE);
        }
#endif
        status.decoded_samples=WORD(image+AUDIO_PRODUCED);
    }
    void *old=allocation;
    image=0;
    radio_free(old);
    unsigned flags=lock();
    allocation=0;
    thread_id=0;
    dmr_owns_fm=0;
    unlock(flags);
}
const volatile struct dmr_ui_status *dmr_ui_get_status(void) { return &status; }
int dmr_rx_set_enabled(unsigned enable) {
    if (!enable) {
        unsigned flags=lock();
        dmr_guard_active=0;
        status.enabled=0;
        status.phase=0;
        unsigned id=thread_id;
        unlock(flags);
        if (id) signal_thread(id,1);
        return 0;
    }
    if (dmr_guard_active) {
        unsigned flags=lock();
        if (status.enabled!=enable) {
            switching=1;
            status.enabled=enable; status.phase=DMR_SEARCH; status.row[0]=0;
        }
        unlock(flags);
        return 1;
    }
    if (dmr_owns_fm) { status.phase=DMR_RETIRING; return 0; }
    if (transmitting()) { status.phase=DMR_TX_BUSY; return 0; }
    if (!factory_fm_available()) { status.phase=DMR_OTHER_RX; return 0; }
    dmr_owns_fm=1;
    if (!aprs_overlay_unload()) { status.phase=DMR_APRS_BUSY; dmr_owns_fm=0; return 0; }
    allocation=radio_alloc(MEM_BYTES+63);
    if (!allocation) { status.phase=DMR_NO_RAM; dmr_owns_fm=0; return 0; }
    uint8_t *base=(uint8_t *)(((uintptr_t)allocation+63)&~63u);
    if (!load_resource(base)) { status.phase=DMR_SD_ERROR; goto fail; }
    unsigned flags=lock();
    if (transmitting()) { status.phase=DMR_TX_BUSY; unlock(flags); goto fail; }
    starting=1;
    image=base;
    WORD(base+CORE_MODE)=enable;
    unlock(flags);
    /* Only the small-stack card image passes load_resource's digest check. */
    static const uintptr_t task[]={(uintptr_t)worker,0xe8,1,16384};
    unsigned created=make_thread(task,0);
    flags=lock();
    thread_id=created;
    starting=0;
    int ready=created && !transmitting();
    if (ready) {
        status.enabled=enable;
        status.row[0]=0;
        status.phase=DMR_SEARCH;
        status.color_code=status.source_id=status.talkgroup=~0u;
        status.sample_blocks=status.varying_blocks=0;
        status.decoded_samples=status.playback_samples=0;
        tune_anchor=0; tune_generation=0;
#ifdef DMR_RX_LAMP
        voice_tune=0;
#endif
        switching=0; dmr_guard_active=1;
    } else status.phase=created ? DMR_TX_BUSY : DMR_NO_THREAD;
    unlock(flags);
    /* Once created, only the worker releases its image, even if TX intervened. */
    if (created) return ready;
fail:
    radio_free(allocation);
    image=0; allocation=0; dmr_owns_fm=0;
    return 0;
}

void dmr_note(void) {
    aprs_slot_note();
    if (dmr_guard_active) {
        unsigned i=(BYTE(0x204016e2)-1u)&7;
        unsigned hz=WORD(0x20380714);
        if (!tune_generation || !same_channel(hz)) {
            tune_anchor=hz;
            ++tune_generation;
        }
        tags[i]=++seq;
        tune_tags[i]=tune_generation;
    }
}
void dmr_input(int16_t *pcm) {
    if (!dmr_guard_active) { aprs_slot_copy(pcm); return; }
    unsigned slot=BYTE(0x204016e3)&7, tag=tags[slot], tune=tune_tags[slot];
    aprs_slot_copy(pcm);
    unsigned flags=lock();
    if (!dmr_guard_active || slot==BYTE(0x204016e3) || tags[slot]!=tag ||
        !tune || tune!=tune_generation || !same_channel(WORD(0x20380714)) ||
        transmitting()) { unlock(flags); return; }
    ++users;
    uint8_t *base=image;
    unlock(flags);
    ((void(*)(const int16_t *,unsigned,unsigned))(base+CORE_INPUT))(pcm,tune,tag);
    ++status.sample_blocks;
    for (unsigned i=1;i<36;++i)
        if (pcm[i]!=pcm[0]) { ++status.varying_blocks; break; }
    flags=lock(); --users; unlock(flags);
}
void dmr_play(int16_t *pcm) {
    if (!dmr_guard_active) { native_playback_read(pcm); return; }
    unsigned queued=native_playback_queued();
    native_playback_read(pcm);
    /* Called from the SSIF0 DMA interrupt. Leave native sound and TX alone. */
    if (!queued && !switching && tune_generation && same_channel(WORD(0x20380714)) &&
        WORD(image+CORE_TUNE)==tune_generation && !transmitting()) {
        unsigned count=((unsigned(*)(int16_t *))(image+AUDIO_PULL))(pcm);
        for (unsigned i=0;i<count;++i) {
            int sample=pcm[i];
            /* Double ordinary speech. Compress strong peaks above 75% output. */
            if (sample>12288) pcm[i]=24576+(sample-12288)/4;
            else if (sample< -12288) pcm[i]=-24576-(-sample-12288)/4;
            else pcm[i]=sample*2;
        }
        status.playback_samples+=count;
    }
}
