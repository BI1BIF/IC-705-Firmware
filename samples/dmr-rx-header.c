/* Isolated DMR group voice header receiver, linked with the dsd-neo FEC implementation. */
#include <dsd-neo/fec/block_codes.h>
#include <dsd-neo/fec/bptc.h>
#include <dsd-neo/fec/rs_12_9.h>
#include <string.h>

unsigned char bits[264], identity[7];

static int group_link_control(unsigned kind) {
    unsigned char slot[20], coded[196], matrix[196], lc[96], reserved[3];
    uint32_t distance;
    rs_12_9_codeword_t word = {0};
    rs_12_9_poly_t syndrome;
    memcpy(slot, bits + 98, 10);
    memcpy(slot + 10, bits + 156, 10);
    if (!Golay_20_8_decode(slot)) return 0;
    unsigned slot_type = 0;
    for (int i = 0; i < 8; ++i) slot_type = (slot_type << 1) | slot[i];
    if ((slot_type & 15) != kind) return 0;
    memcpy(coded, bits, 98);
    memcpy(coded + 98, bits + 166, 98);
    BPTCDeInterleaveDMRData(coded, matrix);
    if (!BPTC_196x96_Decode_Codeword(matrix, lc, reserved, &distance) ||
        distance > DSD_BPTC_196x96_UNIQUE_RADIUS) return 0;
    for (int i = 0; i < 96; ++i)
        word.data[i/8] = (word.data[i/8] << 1) | lc[i];
    for (int i = 9; i < 12; ++i) word.data[i] ^= kind == 1 ? 0x96 : 0x99;
    rs_12_9_calc_syndrome(&word, &syndrome);
    if (rs_12_9_check_syndrome(&syndrome) || (word.data[0] & 63) != 0) return 0;
    identity[0] = slot_type >> 4;
    memcpy(identity+1, word.data+3, 6);
    return 1;
}

int group_header(void) { return group_link_control(1); }
int group_end(void) { return group_link_control(2); }

int embedded_signalling(void) {
    unsigned char word[16];
    memcpy(word, bits + 108, 8);
    memcpy(word + 8, bits + 148, 8);
    if (!QR_16_7_6_decode(word)) return -1;
    int info = 0;
    for (int i = 0; i < 7; ++i) info = (info << 1) | word[i];
    return info;
}
