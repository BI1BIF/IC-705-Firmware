/* Bench-only DMA producer. The decoded application performs capture itself. */
#include <stdint.h>
#ifdef IC705_E140
#define DMA_COMPLETE 0x200ffd54
#define AUDIO_CONSUME 0x2010fee8
#else
#define DMA_COMPLETE 0x200ffc70
#define AUDIO_CONSUME 0x2010fe04
#endif
static unsigned bank;
void feed_banks(const int16_t *six,unsigned count) {
    while(count--) {
        volatile uint32_t *dma=(volatile uint32_t *)(0x20400800u+bank*288);
        for(unsigned i=0;i<36;i++) {
            dma[2*i]=(uint32_t)(uint16_t)six[i/6]<<16;
            dma[2*i+1]=0;
        }
        six+=6;
        *(volatile uint32_t *)0xe82000e4=bank?0x41:0xc1;
        bank^=1;
        ((void (*)(void))DMA_COMPLETE)();
        ((void (*)(void))AUDIO_CONSUME)();
    }
}
