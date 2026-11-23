/* Authenticate the exact card image, including fixups, before executing it. */
#include <stdint.h>
#include "dmr-layout.h"

static uint32_t rotr(uint32_t x,unsigned n) { return (x>>n)|(x<<(32-n)); }

int dmr_resource_matches(const uint8_t *p)
{
    static const uint32_t k[64]=DMR_SHA_CONSTANTS;
    static const uint32_t expected[8]=DMR_SHA_EXPECTED;
    const unsigned length=RESOURCE_BYTES;
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                   0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    unsigned padded=(length+9+63)&~63;
    for (unsigned pos=0;pos<padded;pos+=64) {
        uint32_t w[16];
        for (unsigned i=0;i<64;i+=4) {
            uint32_t word=0;
            for (unsigned j=0;j<4;++j) {
                unsigned index=pos+i+j;
                unsigned b=index<length ? p[index] : index==length ? 128 : 0;
                if (index>=padded-4) b=(length*8u)>>((padded-1-index)*8);
                word=(word<<8)|(b&255);
            }
            w[i/4]=word;
        }
        uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],last=h[7];
        for (unsigned i=0;i<64;++i) {
            if (i>=16) {
                uint32_t x=w[(i+1)&15],y=w[(i+14)&15];
                w[i&15]+=(rotr(x,7)^rotr(x,18)^(x>>3))+w[(i+9)&15]+(rotr(y,17)^rotr(y,19)^(y>>10));
            }
            uint32_t t=last+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+k[i]+w[i&15];
            last=g;g=f;f=e;e=d+t;d=c;c=b;b=a;
            a=t+(rotr(b,2)^rotr(b,13)^rotr(b,22))+((b&c)^(b&d)^(c&d));
        }
        h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=last;
    }
    for (unsigned i=0;i<8;++i) if (h[i]!=expected[i]) return 0;
    return 1;
}
