#include "live_rx.h"

static int pair(const char *p)
{
    return 10 * (p[0] - '0') + p[1] - '0';
}

int live_open_gps(unsigned ft4, unsigned edge_second_of_day, uint32_t edge_sample, uint32_t first_sample)
{
    typedef unsigned (*Valid)(void);
    typedef void (*ReadTime)(char *);
    Valid utc_valid = (Valid)0x2021300c;
    ReadTime read_time = (ReadTime)0x20212b64;
    char time[8] = {0};
    unsigned elapsed = first_sample - edge_sample;
    live_close();
    if (ft4 > 1 || elapsed >= 8000 || !utc_valid()) return 0;

    read_time(time);
    if (!utc_valid()) return 0;
    for (unsigned i = 0; i < 6; ++i) {
        if (time[i] < '0' || time[i] > '9') return 0;
    }
    unsigned hour = pair(time), minute = pair(time + 2), second = pair(time + 4);
    if (hour > 23 || minute > 59 || second > 59) return 0;
    unsigned seconds = hour * 3600 + minute * 60 + second;
    if (seconds != edge_second_of_day) return 0;

    unsigned sample_of_day = seconds * 8000 + elapsed;
    unsigned length = ft4 ? 60000 : 120000;
    live_open(ft4, first_sample, sample_of_day / length, sample_of_day % length);
    return 1;
}
