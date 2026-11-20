/* Bench-only DMA producer. The decoded application performs capture itself. */
#include <stdint.h>
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
        ((void (*)(void))0x200ffc70)();
        ((void (*)(void))0x2010fe04)();
    }
}
