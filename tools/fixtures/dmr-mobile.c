/* Compile the upstream generator's burst constructors unchanged for isolated receive tests. */
#define main upstream_cli
#include "dmr_synth.c"
#undef main
void _fini(void) {}

uint8_t input_voice[27];
int fixture_symbols[144];
static uint8_t embedded_lc[128];
static unsigned opcode;

void fixture_init(unsigned cc, unsigned src, unsigned tg, unsigned flco) {
    InitAllFecFunction();
    cfg.ms = 1;
    cfg.cc = cc;
    cfg.src = src;
    cfg.tg = tg;
    cfg.alg = ALG_NONE;
    uint8_t lc[9], bits72[72];
    full_lc_bytes(0,lc);
    opcode=flco; lc[0]=(uint8_t)opcode; lc[2]|=opcode>>8;
    bytes_to_bits(lc,9,bits72);
    bptc128_encode(bits72,embedded_lc);
}

void fixture_lc(unsigned kind) {
    uint8_t payload[96];
    lc_burst_payload(0,kind == 1 ? 0x969696 : 0x999999,payload);
    if(opcode) {
        uint8_t cw[12];
        full_lc_bytes(0,cw); cw[0]=(uint8_t)opcode; cw[2]|=opcode>>8;
        dmr_test_encode_rs_12_9(cw,cw+9);
        for(int i=9;i<12;++i) cw[i]^=kind==1 ? 0x96 : 0x99;
        bytes_to_bits(cw,12,payload);
    }
    build_data_burst(0,cfg.cc,kind,payload,fixture_symbols);
}

void fixture_voice(unsigned vc) {
    char planes[3][4][24] = {0};
    for (int f = 0; f < 3; ++f) {
        for (int i = 0; i < 36; ++i) {
            unsigned dibit = (input_voice[9*f+i/4] >> (6-2*(i%4))) & 3;
            const dsd_ambe_2450_dibit_map_entry *map = &dsd_ambe_2450_dibit_map[i];
            planes[f][map->high_row][map->high_col] = dibit >> 1;
            planes[f][map->low_row][map->low_col] = dibit & 1;
        }
    }
    const uint8_t *frag = vc >= 2 && vc <= 5 ? embedded_lc+32*(vc-2) : NULL;
    build_voice_burst(0,vc,cfg.cc,planes,frag,fixture_symbols);
}
