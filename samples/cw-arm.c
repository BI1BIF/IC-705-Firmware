#include <stdint.h>
#include <stddef.h>

// One call per 80 samples of mono, signed 8 kHz PCM. Caller zeros state on entry.
typedef struct {
    uint32_t dot, age, pattern, signal;
    uint8_t trained, reacquiring, confirmed, reserved;
    uint32_t count;
    uint8_t started, gap_count;
    uint16_t gap_level;
    uint32_t spacing, dropped;
    uint16_t training[16];
    uint32_t size;
    char output[16];
} Decoder;

_Static_assert(sizeof(Decoder) == 88 && offsetof(Decoder, output) == 72, "test harness ABI");

enum { FIT_INITIAL, LIVE, FIT_WORD, LOCKED };
enum { REFIT_GAP = 1, KEEP_SPACE = 2, SKIP_SPACE = 4, LIMIT_GAP_LEARN = 8, GAP_SHIFT = 4 };

static const char alphabet[128] = {
    [63] = '0', [47] = '1', [39] = '2', [35] = '3', [33] = '4', [32] = '5', [48] = '6',
        [56] = '7', [60] = '8', [62] = '9', [5] = 'A', [24] = 'B', [26] = 'C', [12] = 'D',
        [2] = 'E', [18] = 'F', [14] = 'G', [16] = 'H', [4] = 'I', [23] = 'J', [13] = 'K',
        [20] = 'L', [7] = 'M', [6] = 'N', [15] = 'O', [22] = 'P', [29] = 'Q', [10] = 'R',
        [8] = 'S', [3] = 'T', [9] = 'U', [17] = 'V', [11] = 'W', [25] = 'X', [27] = 'Y',
        [28] = 'Z', [85] = '.', [115] = ',', [76] = '?', [50] = '/', [49] = '=', [97] = '-',
        [94] = '\'', [120] = ':', [82] = '"'
};

static void emit(Decoder *d, char ch) {
    if (d->size < sizeof d->output)
        d->output[d->size++] = ch;
    else
        ++d->dropped;
}

static void word_space(Decoder *d) {
    uint32_t gap = d->spacing >> GAP_SHIFT;
    unsigned refit_word = d->spacing & KEEP_SPACE;
    uint32_t cutoff = 80 * d->dot;
    if (d->gap_count < 3 && d->gap_level >= 16 * d->dot)
        cutoff = 96 * d->dot;
    uint32_t learned = (uint32_t)d->gap_level * 19 / 4;
    if (d->gap_count == 3 && d->gap_level >= 23 * d->dot && learned > cutoff)
        cutoff = learned;
    if (d->dot <= 6) {
        // Keep the normal word gap unless the sender takes that long between letters.
        if (d->gap_level >= 28 * d->dot)
            cutoff = learned > cutoff ? learned : cutoff;
        else if (cutoff > 112 * d->dot)
            cutoff = 112 * d->dot;
    }
    if (refit_word || (!(d->spacing & SKIP_SPACE) && gap * 16 >= cutoff))
        emit(d, ' ');

    // Learn from complete letter gaps; a long break starts a fresh cadence.
    if (gap > 48 * d->dot) {
        d->gap_count = d->gap_level = 0;
    } else if (gap >= 2 * d->dot && gap <= 32 * d->dot) {
        if ((d->spacing & LIMIT_GAP_LEARN) && gap > 7 * d->dot)
            gap = 7 * d->dot;
        // Do not let a normal long word gap dominate the letter-gap estimate.
        if (d->gap_count && gap * 4 > 2u * d->gap_level)
            gap = d->gap_level / 2u;
        d->gap_level = d->gap_count ? (d->gap_level + 4 * gap) / 2 : 4 * gap;
        if (d->gap_count != 3)
            ++d->gap_count;
    }
}

static void step(Decoder *d, uint32_t mark, uint32_t ticks, unsigned complete) {
    // An overfull pattern cannot become a valid letter. At the next pause,
    // let AUTO re-estimate rather than merging more letters at the stale rate.
    if (!mark && d->pattern == 128 && d->trained == LIVE && d->dot >= 7 &&
            ticks >= 8 && ticks >= d->dot) {
        if (d->started)
            word_space(d);
        emit(d, '~');
        d->started = 1;
        d->pattern = 0;
        d->spacing = REFIT_GAP;
    }
    if (mark) {
        if (ticks * 2 < d->dot || ticks > 5 * d->dot)
            return;
        uint32_t dash = ticks > 2 * d->dot;
        if (d->trained != LOCKED) {
            uint32_t unit = dash ? (ticks + 1) / 3 : ticks;
            // An ambiguous long dot inside a letter should not slow the next gap test.
            if (!dash && d->pattern && unit >= d->dot + 4)
                unit = d->dot + 3;
            d->dot = (7 * d->dot + unit + 4) / 8;
        }
        d->pattern = d->pattern >= 64 ? 128 : (d->pattern ? d->pattern : 1) * 2 + dash;
    } else if (5 * ticks >= 9 * d->dot && d->pattern) {
        // Allow shortened hand-key letter gaps while leaving typical intra-letter gaps intact.
        char ch = d->pattern < sizeof alphabet ? alphabet[d->pattern] : 0;
        if (d->started)
            word_space(d);
        emit(d, ch ? ch : '~');
        d->started = 1;
        d->pattern = d->spacing = 0;
    }
    if (!mark && d->started) {
        if (ticks >= 5 * d->dot)
            d->spacing |= REFIT_GAP;
        // A brief rejected burst can split a word gap; retain the longest part.
        if (complete && 5 * ticks >= 9 * d->dot && ticks > (d->spacing >> GAP_SHIFT))
            d->spacing = (ticks << GAP_SHIFT) | (d->spacing & ((1u << GAP_SHIFT) - 1));
    }
}

static void replay_training(Decoder *d) {
    for (uint32_t i = 0; i < d->count; ++i)
        step(d, !(i & 1), d->training[i], 1);
    d->count = 0;
}

static void train(Decoder *d, unsigned confirm_track) {
    // A single noise burst or two isolated marks cannot establish an AUTO station.
    // Keep the original marks for replay once there are three complete marks.
    if (confirm_track && d->count < 5)
        return;
    uint32_t shortest = 0;
    for (uint32_t i = 0; i < d->count; i += 2)
        if (!shortest || d->training[i] < shortest)
            shortest = d->training[i];
    uint32_t sum = 0, n = 0;
    for (uint32_t i = 0; i < d->count; i += 2)
        if (d->training[i] * 2 <= shortest * 3) {
            sum += d->training[i];
            ++n;
        }
    if (n == 0 || shortest < 2)
        return;
    // n is at most eight; avoid a runtime division helper on ARMv7-A.
    d->dot = 0;
    for (sum += n / 2; sum >= n; sum -= n)
        ++d->dot;
    // Five similar marks with four short gaps can be 0 rather than a slow 5.
    if (d->count == 9 && n == 5 && d->dot >= 9 && d->dot <= 45) {
        unsigned short_gaps = 0;
        for (uint32_t i = 1; i < d->count; i += 2) {
            uint32_t gap = d->training[i];
            short_gaps += 5 * gap >= d->dot && 2 * gap < d->dot;
        }
        if (short_gaps == 4)
            d->dot = (d->dot + 1) / 3;
    }
    d->trained = LIVE;
    replay_training(d);
}

// A word gap is a safe boundary to reconsider speed: no partial letter has
// to be reinterpreted. Fit both short/long marks and their intervening gaps.
static uint32_t distance(uint32_t a, uint32_t b) {
    return a > b ? a - b : b - a;
}

static uint32_t timing_loss(const Decoder *d, uint32_t dot, uint32_t *classes) {
    uint32_t loss = 0;
    *classes = 0;
    // The first mark after a pause can be a merged burst. Do not let one
    // mark that the previous speed would reject set the rate of the whole word.
    uint32_t start = d->count >= 7 && d->training[0] > 5 * d->dot ? 1 : 0;
    for (uint32_t i = start; i < d->count; ++i) {
        uint32_t ticks = d->training[i];
        uint32_t short_error = distance(ticks, dot);
        uint32_t long_error = distance(ticks, 3 * dot);
        if ((i & 1) == 0) {
            // A speed change needs credible examples of both marks. An almost
            // uniform series of dots must not also count as dashes at twice the speed.
            if (3 * ticks <= 4 * dot && 2 * ticks >= dot)
                *classes |= 1;
            if (3 * ticks >= 7 * dot && ticks <= 5 * dot)
                *classes |= 2;
            loss += 2 * (short_error < long_error ? short_error : long_error);
        } else {
            uint32_t error = short_error < long_error ? short_error : long_error;
            uint32_t word_error = distance(ticks, 7 * dot);
            loss += error < word_error ? error : word_error;
        }
    }
    return loss;
}

static void reacquire(Decoder *d) {
    uint32_t prior = d->dot;
    uint32_t classes, best_loss = timing_loss(d, prior, &classes);
    uint32_t best = prior;
    // 10 ms ticks; keep the previous speed if the new window lacks both mark lengths.
    for (uint32_t dot = 3; dot <= 15; ++dot) {
        uint32_t loss = timing_loss(d, dot, &classes) + 3;
        if (classes == 3 && loss < best_loss) {
            best = dot;
            best_loss = loss;
        }
    }
    if (best != prior && distance(best, prior) * 4 >= prior) {
        if (d->spacing & REFIT_GAP) {
            uint32_t gap = d->spacing >> GAP_SHIFT;
            // A pause close to this sender's letter spacing does not become a word gap on refit.
            if (d->gap_count >= 2 && d->gap_level >= 16 * prior &&
                    gap * 16 < (uint32_t)d->gap_level * 19 / 4) {
                d->spacing |= SKIP_SPACE;
            } else {
                d->spacing |= KEEP_SPACE;
                // A normal word pause at the old speed is not evidence of stretched letters at the new speed.
                if (d->gap_level < 16 * prior)
                    d->spacing |= LIMIT_GAP_LEARN;
            }
        }
        d->gap_count = d->gap_level = 0;
    }
    d->dot = best;
    d->trained = LIVE;
    replay_training(d);
}

static uint32_t tone_present(const int16_t *pcm) {
    static const int32_t coeff[] = {7686, 7568, 7440, 7299, 7147, 6985, 6811, 6627, 6433};
    uint32_t energy = 0;
    for (uint32_t i = 0; i < 80; ++i) {
        int32_t x = pcm[i] >> 6;
        energy += x * x;
    }
    if (energy < 18000)
        return 0;
    for (uint32_t bin = 0; bin < sizeof coeff / sizeof *coeff; ++bin) {
        int32_t a = 0, b = 0;
        for (uint32_t i = 0; i < 80; ++i) {
            int32_t next = (pcm[i] >> 6) + ((coeff[bin] * a) >> 12) - b;
            b = a;
            a = next;
        }
        int64_t power = (int64_t)a*a + (int64_t)b*b - (((int64_t)a*b*coeff[bin]) >> 12);
        if (power > 15 * (int64_t)energy)
            return 1;
    }
    return 0;
}

static uint32_t cw_mark(Decoder *d, uint32_t mark, uint32_t fixed_dot, unsigned confirm_track) {
    d->size = 0;
    if (fixed_dot && d->trained != LOCKED) {
        d->dot = fixed_dot;
        d->trained = LOCKED;
        // Replay here so letters finished by buffered silence are delivered with this block.
        replay_training(d);
    } else if (!fixed_dot && d->trained == LOCKED) {
        d->trained = LIVE;
    } else if (fixed_dot) {
        d->dot = fixed_dot;
    }
    if (!d->signal && !d->count && d->trained == FIT_INITIAL && !d->age) {
        d->signal = mark;
        d->age = mark;
        return 0;
    }
    if (mark != d->signal) {
        if (d->trained == LIVE || d->trained == LOCKED) {
            step(d, d->signal, d->age, 1);
            if (d->trained == LIVE && mark && (d->spacing & REFIT_GAP))
                d->trained = FIT_WORD;
        } else {
            d->training[d->count++] = d->age;
            if (d->trained == FIT_WORD && d->count == 8)
                reacquire(d);
            else if (d->count == 16)
                train(d, confirm_track);
            if (d->trained == FIT_INITIAL && d->count == 16) {
                d->count = d->age = 0;
                d->signal = 0;
                return 0;
            }
        }
        d->signal = mark;
        d->age = 1;
    } else if (d->age < 1000) {
        ++d->age;
    }
    if (!mark) {
        if (d->trained == FIT_INITIAL && d->count > 0) {
            if (d->age == 40)
                train(d, confirm_track);
            // An unconfirmed E or T can still be the start of a real transmission.
            // Keep it through an ordinary pause, but drop it after 1.2 s of quiet.
            if (d->trained == FIT_INITIAL && d->age >= (confirm_track ? 120u : 40u))
                d->count = d->age = 0;
        }
        if (d->trained == FIT_WORD && d->count > 0 && d->age == 40)
            reacquire(d);
        if (d->trained == LIVE || d->trained == LOCKED)
            step(d, 0, d->age, 0);
    }
    return d->size;
}

#ifdef CW_SESSION
uint32_t cw_feed(Decoder *d, const int16_t *pcm, uint32_t fixed_dot) {
    return cw_mark(d, tone_present(pcm), fixed_dot, 0);
}
#else
uint32_t cw_feed(Decoder *d, const int16_t *pcm) {
    return cw_mark(d, tone_present(pcm), 0, 0);
}
#endif

#if defined(CW_FILTER_TRIAL) || defined(CW_SESSION)
enum { FIXED_PITCH_MASK = 2047, FIXED_AUTO_TRACK = 1u << 14, FIXED_AUTO_LEVEL = 1u << 15 };
typedef struct {
    int16_t previous[2][80];
    uint64_t peak;
    uint32_t next, noise, marks;
} FixedFilter;

_Static_assert(sizeof(FixedFilter) == 344, "filter trial ABI");

static int32_t fixed_coeff(unsigned hz) {
    // Include guard bands beyond the selectable 300–1250 Hz range.
    static const uint16_t coeffs[] = {
        8091,8035,7966,7884,7791,7686,7568,7440,7299,7147,6985,6811,6627,6433,6229,6016,5793,5561,
        5320,5072,4815,4551,4280,4003
    };
    unsigned bin = (hz-200u) / 50u, rem = (hz-200u) % 50u;
    return rem ? coeffs[bin] - ((coeffs[bin]-coeffs[bin+1])*rem+25u) / 50u : coeffs[bin];
}

static uint64_t filter_power(int32_t a, int32_t b, int32_t coeff) {
    int64_t power = (int64_t)a*a + (int64_t)b*b - (((int64_t)a*b*coeff) >> 12);
    return power > 0 ? (uint64_t)power : 0;
}

static inline __attribute__((always_inline)) uint32_t fixed_mark_mode(const int16_t *pcm, FixedFilter *f,
                                                                      uint32_t setting, unsigned auto_threshold,
                                                                      unsigned acquiring) {
    // Specialize the hot loop so manual threshold does not pay for local noise estimates.
    // 30 ms symmetric Hann window, updated every 10 ms. Threshold in input peak PCM units.
    static const uint16_t hann[120] = {
        0,0,0,0,1,1,2,2,3,4,4,5,6,7,9,10,11,13,14,16,
        17,19,21,23,25,27,29,31,33,35,38,40,43,45,48,50,53,56,59,62,
        64,67,70,73,77,80,83,86,89,92,96,99,102,105,109,112,115,119,122,125,
        129,132,136,139,142,146,149,152,156,159,162,165,169,172,175,178,181,184,187,190,
        193,196,199,201,204,207,209,212,215,217,219,222,224,226,228,230,232,234,236,238,
        240,241,243,244,246,247,248,249,250,251,252,253,254,254,255,255,255,256,256,256
    };
    unsigned hz = setting & FIXED_PITCH_MASK, threshold = setting >> 16;
    if (hz < 300 || hz > 1250 || !threshold)
        return 0;
    int32_t coeff = fixed_coeff(hz);
    unsigned tracking = setting & FIXED_AUTO_TRACK;
    unsigned edge = tracking && (hz < 380 || hz > 1170);
    int32_t side[2] = {0};
    if (auto_threshold) {
        side[0] = fixed_coeff(edge || hz >= 380 ? hz-80 : hz+160);
        side[1] = fixed_coeff(edge || hz <= 1170 ? hz+80 : hz-160);
    }
    int32_t a = 0, b = 0, sa[2] = {0}, sb[2] = {0};
    unsigned at = 0;
    for (unsigned part = 0; part < 3; ++part) {
        const int16_t *input = part == 2 ? pcm : f->previous[f->next ^ part];
        for (unsigned i = 0; i < 80; ++i, ++at) {
            int32_t weighted = (input[i] * hann[at < 120 ? at : 239-at]) >> 13;
            if (auto_threshold) {
                for (unsigned j = 0; j < 2; ++j) {
                    int32_t next = weighted + (int32_t)(((int64_t)side[j]*sa[j]) >> 12) - sb[j];
                    sb[j] = sa[j];
                    sa[j] = next;
                }
            }
            int32_t next = weighted + (int32_t)(((int64_t)coeff*a) >> 12) - b;
            b = a;
            a = next;
        }
    }
    for (unsigned i = 0; i < 80; ++i)
        f->previous[f->next][i] = pcm[i];
    f->next ^= 1;
    // Coherent gain is about 60/32. A different floor can be tested without changing Morse timing.
    uint64_t minimum = threshold*15/8;
    minimum *= minimum;
    uint64_t level = filter_power(a, b, coeff);
    unsigned weak = 0;
    if (auto_threshold) {
        // At an AUTO band edge a broad signal outside the search range can look like a peak.
        uint64_t left = filter_power(sa[0], sb[0], side[0]), right = filter_power(sa[1], sb[1], side[1]);
        uint64_t local = left < right ? left : right;
        if (edge)
            local = left > right ? left : right;
        uint32_t background = local > UINT32_MAX ? UINT32_MAX : (uint32_t)local;
        unsigned strict = tracking && acquiring;
        if (background > f->noise)
            f->noise += (background - f->noise) >> (strict ? 2 : 4);
        else
            f->noise -= (f->noise - background) >> 6;
        uint64_t floor = (uint64_t)f->noise * 8u;
        // A noise burst can outrun the average. Check the current window too;
        // relax this check after timing is established to keep weak marks.
        if (tracking) {
            uint64_t instant = local * (strict ? 12u : 9u);
            weak = !edge && level >= minimum && level >= (f->peak >> 4) &&
                   local * 4u <= level && (uint64_t)f->noise * 3u <= level;
            if (instant > floor)
                floor = instant;
        }
        if (floor > minimum)
            minimum = floor;
        f->peak -= f->peak >> 6;
        if (level >= minimum && level > f->peak)
            f->peak = level;
        if ((f->peak >> 4) > minimum)
            minimum = f->peak >> 4;
    }
    return level >= minimum ? 1 : weak ? 2 : 0;
}

static uint32_t fixed_mark(const int16_t *pcm, FixedFilter *f, uint32_t setting, unsigned acquiring) {
    return setting & FIXED_AUTO_LEVEL ? fixed_mark_mode(pcm, f, setting, 1, acquiring)
                                      : fixed_mark_mode(pcm, f, setting, 0, 0);
}
#ifdef CW_FILTER_TRIAL
uint32_t cw_filtered(Decoder *d, const int16_t *pcm, FixedFilter *f, uint32_t setting) {
    return cw_mark(d, fixed_mark(pcm, f, setting, 0), 0, 0);
}
#else
__attribute__((noinline)) uint32_t cw_feed_fixed(Decoder *d, const int16_t *pcm, FixedFilter *f,
                                                 uint32_t setting, uint32_t fixed_dot) {
    unsigned hz = setting & FIXED_PITCH_MASK;
    unsigned tracking = setting & FIXED_AUTO_TRACK;
    if (!tracking || fixed_dot) {
        d->reacquiring = d->confirmed = 0;
    } else if (!d->reacquiring && d->trained == LIVE && !d->signal && d->age >= 300) {
        // A long idle needs fresh noise checks, not a lost speed or first letter.
        d->reacquiring = 1;
        d->confirmed = 0;
    }
    unsigned mark = fixed_mark(pcm, f, setting, d->trained == FIT_INITIAL || d->reacquiring);
    if (tracking && hz >= 380 && hz <= 1170) {
        // Decide two blocks late. Only fill weak blocks flanked by confirmed tone.
        f->marks = (f->marks << 2) | mark;
        mark = (f->marks & 0x10u) || (f->marks & 0x64u) == 0x64u ||
               (f->marks & 0x69u) == 0x69u || (f->marks & 0x1a4u) == 0x1a4u;
    } else {
        f->marks = 0;
        mark = mark == 1;
    }
    if (d->reacquiring && d->signal && !mark &&
        ((2*d->age >= d->dot && 2*d->age <= 3*d->dot) ||
         (3*d->age >= 7*d->dot && d->age <= 5*d->dot))) {
        // Relax again after complete marks agree with the retained timing prior.
        if (++d->confirmed == 3)
            d->reacquiring = d->confirmed = 0;
    }
    return cw_mark(d, mark, fixed_dot, tracking);
}
#endif
#endif

