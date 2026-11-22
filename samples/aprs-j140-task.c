/* J140 FM receive records serviced by the original audio task. */
#include "aprs-j140-popup.h"

uint16_t aprs_offer_frame(const struct output_frame *record, uint16_t *distance);
void aprs_history_begin_record(unsigned sequence);
void aprs_history_commit_record(unsigned sequence, unsigned icon);

enum { PCM_FRAMES = 36, PCM_SLOTS = 8 };

#define REG8(a) (*(volatile const uint8_t *)(a))
#define REG32(a) (*(volatile const uint32_t *)(a))

struct pcm_tag {
    uint32_t sequence;
    uint32_t frequency;
    uint32_t selection;
};

volatile uint32_t aprs_channel_hz APRS_KEEP;
uint32_t aprs_record_count APRS_KEEP, aprs_lost_pcm_blocks, aprs_uncertain_pcm_blocks;
struct output_frame *aprs_records APRS_KEEP;
#ifdef APRS_LAST_BANK_SLOTS
struct output_frame *aprs_history_last_bank APRS_KEEP;
#endif

static volatile struct pcm_tag tags[PCM_SLOTS];
static uint32_t producer_sequence, consumed_sequence;
static uint32_t reception_hz;
static volatile uint32_t channel_selection;

void aprs_set_channel(uint32_t hz)
{
    if (hz == aprs_channel_hz)
        return;
    uint32_t cpsr;
    __asm__ volatile("mrs %0, cpsr\n\tcpsid i" : "=r"(cpsr) :: "memory");
    aprs_channel_hz = hz;
    ++channel_selection;
    __asm__ volatile("msr cpsr_c, %0" :: "r"(cpsr) : "memory");
    aprs_rx_gap();
    reception_hz = 0;
}

uint32_t aprs_active_frequency(void)
{
    uint32_t hz = aprs_channel_hz;
    if (!hz || REG32(0x20380714) != hz || (REG8(0x203e2128) >> 4) != 7 ||
        (REG8(0x203809a1) & 0x10))
        return 0;
#ifdef APRS_COMBINED
    if (!aprs_plain_fm())
        return 0;
#endif
    return hz;
}

void aprs_note_dma(void)
{
    /* The first-slot producer has just published its next write index. */
    unsigned slot = (REG8(0x204016e2) - 1u) & (PCM_SLOTS - 1);
    tags[slot].frequency = aprs_active_frequency();
    tags[slot].selection = channel_selection;
    tags[slot].sequence = ++producer_sequence;
}

void aprs_copy_pcm(int16_t *pcm)
{
    unsigned slot = REG8(0x204016e3);
    unsigned available = REG8(0x204016e2) != slot;
    struct pcm_tag tag = tags[slot];
    ((void (*)(int16_t *))0x200ff810)(pcm);

    uint32_t hz = aprs_active_frequency();
    if (!hz || !available || REG8(0x204016e3) == slot || tag.frequency != hz || tag.selection != channel_selection ||
        tag.sequence != tags[slot].sequence) {
        if (hz && available && tag.frequency == hz && tag.selection == channel_selection)
            ++aprs_uncertain_pcm_blocks;
        aprs_rx_gap();
        reception_hz = 0;
        return;
    }

    uint32_t delta = tag.sequence - consumed_sequence;
    if (reception_hz != hz || delta != 1) {
        if (reception_hz == hz && delta > 1)
            aprs_lost_pcm_blocks += delta - 1;
        aprs_rx_gap();
    }
    consumed_sequence = tag.sequence;
    reception_hz = hz;
    aprs_rx_feed(pcm, PCM_FRAMES);
}

void aprs_record_receive(void)
{
#ifdef APRS_COMBINED
    extern volatile unsigned ft_session_state, ft_tx_stage;
    if (ft_session_state || ft_tx_stage) {
        aprs_rx_read=aprs_rx_written;
        return;
    }
#endif
#ifndef APRS_LAST_BANK_SLOTS
    if (aprs_rx_read != aprs_rx_written && !aprs_records)
        aprs_records = ((void *(*)(unsigned))0x20127a28)((RECORD_SLOTS - HISTORY_PREFIX_SLOTS) * sizeof(*aprs_records));
#endif
    while (aprs_rx_read != aprs_rx_written) {
        const struct output_frame *frame = &aprs_rx_frames[aprs_rx_read % OUT_SLOTS];
        if (!aprs_records) {
            aprs_offer_frame(frame, 0);
            ++aprs_rx_read;
            continue;
        }
        struct output_frame *record = aprs_record_slot(aprs_record_count % RECORD_SLOTS);
        aprs_history_begin_record(aprs_record_count);
        record->end_sample = frame->end_sample;
        record->length = frame->length;
        for (uint32_t n = 0; n < frame->length; ++n)
            record->bytes[n] = frame->bytes[n];
        unsigned icon = aprs_offer_frame(record, &record->distance);
        aprs_history_commit_record(aprs_record_count, icon);
        __atomic_store_n(&aprs_record_count, aprs_record_count + 1, __ATOMIC_RELEASE);
        ++aprs_rx_read;
    }
    if (aprs_active_frequency() != reception_hz) {
        aprs_rx_gap();
        reception_hz = 0;
    }
}
