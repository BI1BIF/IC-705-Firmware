#include <stddef.h>
#include <stdint.h>

/* Linked into the standalone codec image; newlib owns this arena, including
 * its cached FFT plan and emulated TLS objects. It never uses host firmware RAM
 * outside this image. Keep the whole image resident until the worker is idle. */
static uint8_t arena[16*1024] __attribute__((aligned(64)));
static unsigned taken;
unsigned dmr_audio_heap_peak;
void *_sbrk(ptrdiff_t bytes) {
    if (bytes < -(ptrdiff_t)taken || bytes > (ptrdiff_t)(sizeof arena - taken))
        return (void *)-1;
    void *p = arena+taken;
    taken += bytes;
    if (taken > dmr_audio_heap_peak)
        dmr_audio_heap_peak = taken;
    return p;
}
