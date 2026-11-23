/* APRS body painted inside the original J140 position window. */
#include "aprs-j140-popup.h"

#pragma GCC optimize ("Os")

struct popup_packet aprs_popup_packet;

enum { HEIGHT = 272, POPUP_RECT = 1518, UI_LAYER = 7, ICON_SIZE = 24, SYMBOL_CROP = 42 };
enum { WHITE = 15, MUTED = 57 };
enum { DETAIL_TOP = 109, DETAIL_STEP = 19, DETAIL_LAST = 205 };
struct point { uint16_t x, y; };

static const char *const directions[] = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"};

static const char *direction(unsigned bearing)
{
    return directions[((bearing + 22) / 45) & 7];
}

static unsigned length(const char *text)
{
    unsigned n = 0;
    while (text[n])
        ++n;
    return n;
}

__attribute__((noinline)) static void label_span(const char *text, unsigned n, unsigned x, unsigned y,
                       unsigned font, unsigned color, unsigned align)
{
    typedef void (*stock_text)(unsigned, unsigned, const char *, unsigned, unsigned, unsigned,
                               unsigned, const struct point *, unsigned, unsigned);
    if (n) {
        const struct point xy = {x, y};
        ((stock_text)0x20142698)(7, 1518, text, n, 1, font, color, &xy, align, 0);
    }
}

__attribute__((noinline)) static void label(const char *text, unsigned x, unsigned y,
                                            unsigned font, unsigned color, unsigned align)
{
    label_span(text, length(text), x, y, font, color, align);
}

static unsigned fit(const char *text, unsigned n, unsigned font, unsigned width)
{
    typedef unsigned (*stock_fit)(const char *, unsigned, unsigned, unsigned, unsigned, unsigned);
    return ((stock_fit)0x20141fc8)(text, n, 1, font, 0, width);
}

static void fitted(const char *text, unsigned x, unsigned y, unsigned font, unsigned color, unsigned width)
{
    unsigned n = length(text);
    if (fit(text, n, font, width) == n) {
        label_span(text, n, x, y, font, color, 0);
    } else {
        char row[108];
        unsigned tail = fit(text, n, font, width - 24);
        if (tail > sizeof(row) - 4)
            tail = sizeof(row) - 4;
        for (unsigned i = 0; i < tail; ++i)
            row[i] = text[i];
        row[tail++] = '.';
        row[tail++] = '.';
        row[tail++] = '.';
        row[tail] = 0;
        label(row, x, y, font, color, 0);
    }
}

static void wrapped_text(const char *text, unsigned x, unsigned left, unsigned y, unsigned last, const char *heading)
{
    enum { RIGHT = 361 };
    while (*text == ' ')
        ++text;
    if (!*text)
        return;
    if (heading)
        label(heading, left, y, 14, MUTED, 0);
    while (*text && y + DETAIL_STEP <= last) {
        unsigned n = length(text);
        unsigned count = fit(text, n, 16, RIGHT - x);
        unsigned end = count;
        if (count < n && text[count] != ' ') {
            while (end && text[end-1] != ' ')
                --end;
            if (!end)
                end = count;
        }
        unsigned visible = end;
        while (visible && text[visible-1] == ' ')
            --visible;
        label_span(text, visible, x, y, 16, WHITE, 0);
        text += end;
        while (*text == ' ')
            ++text;
        x = left;
        y += DETAIL_STEP;
    }
    if (*text)
        fitted(text, x, y, 16, WHITE, RIGHT - x);
}

static void raw_route(const char *text, unsigned reply)
{
    /* The controls own their whole pixel rectangle, including the bevel. */
    for (unsigned y=reply ? 204 : 218;*text && y<=260;y+=13) {
        unsigned width=y==204 ? 350 : reply && y>=230 ? 168 : 253;
        unsigned count=fit(text,length(text),11,width);
        if (!count) break;
        label_span(text,count,14,y,11,MUTED,0);
        text+=count;
    }
}

static void clear_color(const float *rgba)
{
    ((void (*)(unsigned, unsigned, const float *))0x202631f3)(0x1121, 4, rgba);
}

static void rect(unsigned x, unsigned y, unsigned w, unsigned h)
{
    ((void (*)(int, int, int, int))0x2026362f)(x, HEIGHT-y-h, w, h);
}

static void clean_pixels(const void *pixels, unsigned bytes)
{
    uintptr_t end = (uintptr_t)pixels + bytes;
    for (uintptr_t line = (uintptr_t)pixels & ~(uintptr_t)31; line < end; line += 32)
        __asm__ volatile("mcr p15, 0, %0, c7, c10, 1" :: "r"(line) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
}

static void blit(const uint16_t *pixels, unsigned x, unsigned y, unsigned w, unsigned h)
{
    typedef void (*write_pixels)(const uint16_t *, int, unsigned, int, int, int, int);
    clean_pixels(pixels, w*h*sizeof(*pixels));
    ((write_pixels)0x20263b13)(pixels + (h-1)*w, -2*(int)w, 3, x, HEIGHT-y-h, w, h);
}

void aprs_draw_direction(unsigned direction,unsigned left,unsigned top,uint16_t background)
{
    static const int8_t axis[8][2]={{0,-2},{1,-1},{2,0},{1,1},{0,2},{-1,1},{-2,0},{-1,-1}};
    const int8_t *v=axis[direction-1];
    uint16_t pixels[14*14] __attribute__((aligned(8)));
    for (int y=0;y<14;++y) {
        for (int x=0;x<14;++x) {
            int a=(x-6)*v[0]+(y-6)*v[1], b=(x-6)*v[1]-(y-6)*v[0];
            if (v[0] && v[1]) { a=a*3/2;b=b*3/2; }
            int edge=__builtin_abs(b);
            pixels[y*14+x]=a+edge>=-2 && a+2*edge<=12 ? (b<0 ? 0xf904 : 0xc103) : background;
        }
    }
    blit(pixels,left,top,14,14);
}

static void fix_badge(enum aprs_fix fix)
{
    enum { X = 294, Y = 29, WIDTH = 68, HEIGHT_BADGE = 20, RADIUS = 5 };
    /* Coverage of a one-pixel stroke around a five-pixel corner. */
    static const uint8_t corner[RADIUS][RADIUS] = {
        {0, 0, 1, 3, 4},
        {0, 2, 3, 1, 0},
        {1, 3, 0, 0, 0},
        {3, 1, 0, 0, 0},
        {4, 0, 0, 0, 0},
    };
    static const uint16_t edge[5] = {0, 0x18c4, 0x2987, 0x426a, 0x5b2e};
    uint16_t band[4*WIDTH] __attribute__((aligned(8)));
    for (unsigned top = 0; top < HEIGHT_BADGE; top += 4) {
        for (unsigned row = 0; row < 4; ++row) {
            unsigned y = top + row;
            unsigned dy = y < HEIGHT_BADGE/2 ? y : HEIGHT_BADGE-1-y;
            for (unsigned x = 0; x < WIDTH; ++x) {
                unsigned dx = x < WIDTH/2 ? x : WIDTH-1-x;
                unsigned coverage = dx < RADIUS && dy < RADIUS ? corner[dy][dx] : (dx == 0 || dy == 0) * 4;
                band[row*WIDTH+x] = edge[coverage];
            }
        }
        blit(band, X, Y+top, WIDTH, 4);
    }
    const char *text = fix == LIVE_FIX ? "GPS" : fix == LAST_FIX ? "LAST FIX" :
                       fix == MANUAL_FIX ? "MANUAL" : "NO FIX";
    label(text, X+WIDTH/2, 42, 12, fix == LIVE_FIX || fix == MANUAL_FIX ? WHITE : MUTED, 1);
}

enum { ARROW_MASK = 91, ARROW_STRIDE = 92, ARROW_PAD = 12 };

struct filter_span {
    uint8_t first, weight[3];
};

static unsigned filtered_row(const uint8_t *row, const struct filter_span *span)
{
    row += span->first;
    return row[0]*span->weight[0] + row[1]*span->weight[1] + row[2]*span->weight[2];
}

__attribute__((optimize("Os")))
void aprs_upload_filtered_arrow(unsigned image, const uint8_t *mask, unsigned stride,
                               unsigned format, unsigned x, unsigned y, unsigned width, unsigned height)
{
    typedef void (*upload)(unsigned, const uint8_t *, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);
    upload original = (upload)0x202639eb;
    if (format != 11 || width != ARROW_MASK || height != ARROW_MASK || stride < ARROW_MASK) {
        original(image, mask, stride, format, x, y, width, height);
        return;
    }
    void *storage = ((void *(*)(unsigned))0x20127a28)(ARROW_STRIDE*ARROW_MASK+31);
    if (!storage) {
        original(image, mask, stride, format, x, y, width, height);
        return;
    }
    uint8_t *filtered = (uint8_t *)(((uintptr_t)storage+31) & ~(uintptr_t)31);
    struct filter_span spans[ARROW_MASK - 2*ARROW_PAD];
    /* A 75% pixel covers 8/6 source pixels. Preserve edge coverage at 1:1 display size.
       The stock masks have transparent borders, so partial outer bins are empty. */
    unsigned source_pixel = 0, fraction = 8*ARROW_PAD - ARROW_MASK;
    for (unsigned i = 0; i < sizeof(spans)/sizeof(*spans); ++i) {
        unsigned first = 6 - fraction;
        unsigned middle = 8 - first < 6 ? 8 - first : 6;
        spans[i] = (struct filter_span){source_pixel, {first, middle, 8-first-middle}};
        unsigned advance = fraction >= 4 ? 2 : 1;
        source_pixel += advance;
        fraction += 8 - 6*advance;
    }
    for (unsigned i = 0; i < ARROW_MASK*ARROW_STRIDE; ++i)
        filtered[i] = 0;
    for (unsigned row = 0; row < sizeof(spans)/sizeof(*spans); ++row) {
        const struct filter_span *vertical = &spans[row];
        const uint8_t *src = mask + vertical->first*stride;
        uint8_t *dest = filtered + (row+ARROW_PAD)*ARROW_STRIDE + ARROW_PAD;
        for (unsigned col = 0; col < sizeof(spans)/sizeof(*spans); ++col) {
            unsigned sum = filtered_row(src, &spans[col])*vertical->weight[0] +
                           filtered_row(src+stride, &spans[col])*vertical->weight[1] +
                           filtered_row(src+2*stride, &spans[col])*vertical->weight[2];
            dest[col] = (sum+32) >> 6;
        }
    }
    clean_pixels(filtered, ARROW_STRIDE*ARROW_MASK);
    original(image, filtered, ARROW_STRIDE, format, x, y, width, height);
    ((void (*)(void *))0x20127a78)(storage);
}

static void dial_face(int bearing)
{
    typedef void (*mask_draw)(unsigned, unsigned, unsigned, unsigned, const struct point *, unsigned);
    typedef void (*image_draw)(unsigned, unsigned, unsigned, const struct point *);
    static const struct point marks[] = {{54, 63}, {92, 101}, {54, 138}, {16, 101}};
    static const uint16_t labels[] = {573, 572, 574, 575};
    const struct point origin = {16, 60};
    /* Stock D-PRS drawing with the dial held north-up for APRS bearings. */
    ((mask_draw)0x201422f0)(UI_LAYER, POPUP_RECT, 8, 0xffffffff, &origin, 0);
    for (unsigned i = 0; i < 4; ++i)
        ((image_draw)0x20142104)(UI_LAYER, POPUP_RECT, labels[i], &marks[i]);
    if (bearing >= 0) {
        unsigned step = ((unsigned)(bearing * 16 + 180) / 360) & 15;
        /* The stock mask painter ignores alpha. Reserve FE for the filtered APRS arrow. */
        ((mask_draw)0x201422f0)(UI_LAYER, POPUP_RECT, 4 + (step & 3), 0xff0000fe, &origin, step >> 2);
    }
}

static unsigned stock_symbol(uint16_t icon)
{
    unsigned symbol = (icon & 255) - 33;
    if (symbol >= 94)
        return 3;  /* Generic station marker. */
    const uint8_t *const *tables = (const uint8_t *const *)0x2017a404;
    const uint8_t *entry = tables[(icon >> 8) != '/'] + 2*symbol;
    return entry[0] ? entry[1] : 3;
}

struct base_symbol { const char *name; uint16_t art, alias; };
struct overlay_symbol { const char *name; uint16_t icon; };
#include "aprs-symbol-art.inc"

static const struct base_symbol *symbol_base(uint16_t icon)
{
    unsigned index = (icon & 255) - '!';
    return index >= 94 ? 0 : base_symbols + ((icon >> 8) == '/' ? 0 : 94) + index;
}

const char *aprs_symbol_label(uint16_t icon)
{
    unsigned table = icon >> 8;
    if (table != '/' && table != '\\') {
        for (unsigned i = 0; i < sizeof(overlay_symbols) / sizeof(*overlay_symbols); ++i)
            if (overlay_symbols[i].icon == icon)
                return overlay_symbols[i].name;
        return 0;
    }
    const struct base_symbol *base = symbol_base(icon);
    return base ? base->name : 0;
}

static void draw_overlay(uint16_t *pixels, unsigned ch)
{
    static const uint8_t glyphs[36][5] = {
        {14,19,21,25,14}, {4,12,4,4,14}, {14,17,2,4,31}, {30,1,14,1,30},
        {2,6,10,31,2}, {31,16,30,1,30}, {7,8,30,17,14}, {31,1,2,4,8},
        {14,17,14,17,14}, {14,17,15,1,14}, {14,17,31,17,17}, {30,17,30,17,30},
        {15,16,16,16,15}, {30,17,17,17,30}, {31,16,30,16,31}, {31,16,30,16,16},
        {15,16,19,17,15}, {17,17,31,17,17}, {14,4,4,4,14}, {7,2,2,18,12},
        {17,18,28,18,17}, {16,16,16,16,31}, {17,27,21,17,17}, {17,25,21,19,17},
        {14,17,17,17,14}, {30,17,30,16,16}, {14,17,17,19,15}, {30,17,30,18,17},
        {15,16,14,1,30}, {31,4,4,4,4}, {17,17,17,17,14}, {17,17,10,10,4},
        {17,17,21,27,17}, {17,10,4,10,17}, {17,10,4,4,4}, {31,2,4,8,31}
    };
    unsigned index = ch >= 'A' && ch <= 'Z' ? ch - 'A' + 10 : ch - '0';
    if (index >= 36 || (ch > '9' && ch < 'A'))
        return;
    for (unsigned y = 0; y < 7; ++y)
        for (unsigned x = 0; x < 7; ++x)
            pixels[(y+16)*ICON_SIZE+x+16] = y && y < 6 && x && x < 6 &&
                (glyphs[index][y-1] & (32u >> x)) ? 0xffff : 0x1083;
}

static uint32_t text_symbol(unsigned icon, int x, int y, uint32_t bg)
{
    if (icon == MESSAGE) {
        int side = x < 24 ? x : 47-x;
        int depth = y < 24 ? y : 47-y;
        if (side < 4 || depth < 10 || side+depth < 17)
            return bg;
        return y >= side+1 && y <= side+3 ? 0xeaf5ff : 0x298cda;
    }
    if (x < 12 || x > 35 || y < 4 || y > 43 || (y < 13 && x-y > 22))
        return bg;
    if (x < 16 || x > 31 || y < 8 || y > 39 || (y < 15 && x-y > 17))
        return 0x52bddd;
    return (y >= 20 && y <= 22) || (y >= 29 && y <= 31) ? 0x52bddd : bg;
}

static unsigned averaged565(const uint32_t colors[4])
{
    unsigned rb = 0, g = 0;
    for (unsigned i = 0; i < 4; ++i) {
        rb += colors[i] & 0xff00ff;
        g += colors[i] & 0xff00;
    }
    return ((rb >> 10) & 0xf800) | ((g >> 7) & 0x07e0) | ((rb >> 5) & 0x001f);
}

static int raster_icon(uint16_t *pixels,uint16_t icon,uint16_t background)
{
    typedef void (*resource_info)(unsigned, const uint8_t **, const uint32_t **,
                                  unsigned *, unsigned *, unsigned *);
    const uint8_t *source = 0;
    const uint32_t *palette = 0;
    unsigned width, height, stride = 0;
    unsigned table = icon >> 8;
    const struct base_symbol *base = symbol_base(icon);
    unsigned stock = icon;
    if (base && base->alias) {
        stock = base->alias;
        base = symbol_base(stock);
    }
    if (base && base->art) {
        const uint8_t *data = extra_pixels + base->art;
        for (unsigned i = 0; i < ICON_SIZE*ICON_SIZE;) {
            unsigned run = *data++, color = run & 15;
            unsigned end = i + (run >> 4) + 1;
            while (i < end)
                pixels[i++] = color ? extra_palette[color] : background;
        }
        goto present;
    }
    if (icon != MESSAGE && icon != STATUS) {
        ((resource_info)0x20148710)(stock_symbol(stock), &source, &palette, &width, &height, &stride);
        if (width < SYMBOL_CROP || height < SYMBOL_CROP)
            return 0;
        source += ((height - SYMBOL_CROP) / 2) * stride + (width - SYMBOL_CROP) / 2;
    }
    unsigned bg = ((unsigned)(background & 0xf800) << 8) | ((background & 0x07e0) << 5) |
                  ((background & 31) << 3);
    for (unsigned y = 0; y < ICON_SIZE; ++y) {
        for (unsigned x = 0; x < ICON_SIZE; ++x) {
            uint32_t colors[4];
            for (unsigned i = 0; i < 4; ++i) {
                if (source) {
                    /* Map the central 42×42 of the stock palette artwork to 24×24. */
                    unsigned sx = x*7/4 + (i & 1), sy = y*7/4 + (i >> 1);
                    unsigned index = source[sy*stride+sx];
                    colors[i] = index ? palette[index] : bg;
                } else {
                    colors[i] = text_symbol(icon, x*2 + (i & 1), y*2 + (i >> 1), bg);
                }
            }
            pixels[y*ICON_SIZE+x] = averaged565(colors);
        }
    }
present:
    if (table && table != '/' && table != '\\')
        draw_overlay(pixels, table);
    return 1;
}

void aprs_draw_icon(uint16_t icon,unsigned left,unsigned top,uint16_t background)
{
#ifdef APRS_SLOT_UI
    /* The stock panel redraws four rows on a highlight change. Keep both
       backgrounds for the visible symbols in disposable display memory. */
    static struct cached_icon {
        uint16_t pixels[ICON_SIZE*ICON_SIZE] __attribute__((aligned(8)));
        uint16_t icon,bg;
    } cache[8];
    static unsigned used,next;
    unsigned i=0;
    while (i<used && (cache[i].icon!=icon || cache[i].bg!=background)) ++i;
    if (i==used) {
        i=next;
        if (!raster_icon(cache[i].pixels,icon,background)) return;
        cache[i].icon=icon;cache[i].bg=background;
        if (used<8) ++used;
        next=(i+1)%8;
    }
    blit(cache[i].pixels,left,top,ICON_SIZE,ICON_SIZE);
#else
    uint16_t pixels[ICON_SIZE*ICON_SIZE] __attribute__((aligned(8)));
    if (raster_icon(pixels,icon,background)) blit(pixels,left,top,ICON_SIZE,ICON_SIZE);
#endif
}

enum aprs_fix aprs_gps_fix(void)
{
    unsigned source = *(volatile const uint8_t *)0x203eb16c;  /* Stock GPS Select. */
    if (source == 2)
        return MANUAL_FIX;
    if (source != 1 || !((unsigned (*)(void))0x20074650)())
        return NO_FIX;
    /* Position publication reloads 120; the stock timer counts down until expiry. */
    unsigned remaining = *(volatile const uint8_t *)0x2038130e;
    return !remaining ? NO_FIX : remaining > 115 ? LIVE_FIX : LAST_FIX;
}

enum aprs_fix aprs_local_position(char lat[9], char lon[10])
{
    typedef void (*get_coord)(char *, unsigned);
    unsigned cpsr;
    __asm__ volatile("mrs %0, cpsr\n\tcpsid i" : "=r"(cpsr) :: "memory");
    enum aprs_fix fix = aprs_gps_fix();
    if (fix != NO_FIX) {
        /* The original GPS Position page uses these same source-aware getters. */
        ((get_coord)0x20073b70)(lat, fix == MANUAL_FIX);
        ((get_coord)0x20073b58)(lon, fix == MANUAL_FIX);
    }
    __asm__ volatile("msr cpsr_c, %0" :: "r"(cpsr) : "memory");
    return fix;
}

int aprs_geometry(const char *coords[4], unsigned packet, unsigned *metres, int *bearing)
{
    typedef void (*geometry)(double *, const double *, const double *, unsigned);
    double decimal[4];
    for (unsigned i = 0; i < 4; ++i) {
        unsigned short_coord = packet && i < 2;
        unsigned width = 2 + (i & 1), fraction = short_coord ? 2 : 4;
        const char *c = coords[i];
        unsigned degrees = 0, minutes = 0;
        for (unsigned n = 0; n < width + 2 + fraction; ++n) {
            if (short_coord && n == width+2)
                ++c;  /* Skip the APRS decimal separator. */
            unsigned digit = (unsigned)c[n] - '0';
            if (digit > 9)
                return NO_FIX;
            if (n < width)
                degrees = degrees * 10 + digit;
            else
                minutes = minutes * 10 + digit;
        }
        char hemisphere = c[width+2+fraction];
        unsigned limit = (i & 1) ? 180 : 90;
        if (degrees > limit || (degrees == limit && minutes) || minutes >= (short_coord ? 6000u : 600000u) ||
            ((i & 1) ? hemisphere != 'E' && hemisphere != 'W' : hemisphere != 'N' && hemisphere != 'S'))
            return NO_FIX;
        decimal[i] = degrees + minutes / (short_coord ? 6000.0 : 600000.0);
        if (hemisphere == 'S' || hemisphere == 'W')
            decimal[i] = -decimal[i];
        if ((i & 1) && decimal[i] < 0)
            decimal[i] += 360.0;
        decimal[i] *= 60.0;  /* The stock geometry core takes arcminutes. */
    }
    double result[2];
    ((geometry)0x201276cc)(result, decimal, decimal+2, 0);
    if (!(result[0] >= 0.0 && result[0] <= 20100.0))
        return NO_FIX;
    *metres = (unsigned)(result[0]*1000.0 + 0.5);
    if (result[1] >= 0.0 && result[1] <= 360.0)
        *bearing = (unsigned)(result[1] + 0.5) % 360;
    return 1;
}

static enum aprs_fix gps_position(const struct popup_packet *p, unsigned *metres, int *bearing)
{
    char lat[9], lon[10];
    enum aprs_fix fix = aprs_local_position(lat, lon);
    const char *coords[4] = {p->latitude, p->longitude, lat, lon};
    return fix && aprs_geometry(coords, 1, metres, bearing) ? fix : NO_FIX;
}

static char *append(char *out, const char *text)
{
    while (*text)
        *out++ = *text++;
    *out = 0;
    return out;
}

static char *number(char *out, int n, unsigned width)
{
    char reversed[10];
    unsigned i = 0;
    if (n < 0) {
        *out++ = '-';
        n = -n;
    }
    do {
        reversed[i++] = '0' + n % 10;
        n /= 10;
    } while (n || i < width);
    while (i)
        *out++ = reversed[--i];
    *out = 0;
    return out;
}

/* Quantize at the same precision as the distance on the popup. */
static uint16_t encode_distance(unsigned metres, unsigned ambiguous)
{
    unsigned value = metres < 10000 ? (metres+5)/10 :
                     metres < 100000 ? 900+(metres+50)/100 : 1800+(metres+500)/1000;
    return value | (ambiguous ? 0x8000 : 0);
}

uint16_t aprs_packet_distance(const struct popup_packet *p,uint32_t *direction)
{
    unsigned metres;
    int bearing=-1;
    enum aprs_fix fix = gps_position(p, &metres, &bearing);
    if (direction && bearing>=0 && metres)
        *direction=1+(((bearing+22)/45)&7);
    return fix == NO_FIX ? APRS_NO_DISTANCE : encode_distance(metres, p->ambiguous || fix == LAST_FIX);
}

void aprs_distance_text(char *out, uint16_t distance)
{
    if (distance == APRS_NO_DISTANCE) {
        append(out, "-- km");
        return;
    }
    if (distance & 0x8000)
        *out++ = '~';
    unsigned value = distance & 0x7fff;
    unsigned scale = value < 1000 ? 100 : value < 1900 ? 10 : 1;
    unsigned rounded = value - (scale == 100 ? 0 : scale == 10 ? 900 : 1800);
    out = number(out, rounded / scale, 1);
    if (scale != 1) {
        *out++ = '.';
        out = number(out, rounded % scale, scale == 100 ? 2 : 1);
    }
    append(out, " km");
}

static void row(const char *name, const char *value, unsigned y)
{
    label(name, 133, y, 14, MUTED, 0);
    fitted(value, 225, y, 16, WHITE, 131);
}

static void reading(const char *name, int n, unsigned width, const char *unit, unsigned y)
{
    char value[30];
    if (n != NO_READING)
        append(number(value, n, width), unit);
    else
        append(value, "--");
    row(name, value, y);
}

static void motion_line(const struct popup_packet *p, unsigned y)
{
    char value[16];
    label("SPEED", 133, y, 12, MUTED, 0);
    if (p->speed == NO_READING)
        append(value, "--");
    else
        append(number(value, p->speed, 1), " km/h");
    label(value, 183, y, 14, WHITE, 0);
    label("COURSE", 264, y, 12, MUTED, 0);
    if (p->course == NO_READING)
        append(value, "--");
    else
        append(number(value, p->course, 3), "\xdf");
    label(value, 361, y, 15, WHITE, 2);
}

static void coord_row(const char *name, const char *raw, unsigned width, unsigned y, unsigned ambiguous)
{
    char value[14], *out = value;
    if (ambiguous)
        *out++ = '~';
    for (unsigned n = 0; n < width; ++n)
        *out++ = raw[n];
    *out++ = '\xdf';  /* Stock single-byte degree glyph. */
    for (unsigned n = width; n < width+5; ++n)
        *out++ = raw[n];
    *out++ = '\'';
    append(out, raw+width+5);
    row(name, value, y);
}

void aprs_draw_popup(void)
{
    static const char *const titles[] = {"POSITION BEACON", "WEATHER STATION", "APRS IGATE", "PERSONAL STATION",
                                        "APRS MESSAGE", "APRS STATUS", "APRS PACKET"};
    static const float rule[4] = {.28f, .32f, .37f, 1.f};
    const struct popup_packet *p = &aprs_popup_packet;
    if (p->kind > PACKET)
        return;
    const char *title=titles[p->kind];
#ifdef APRS_SLOT_UI
    if (p->entity[0]) title=p->item ? (p->removed ? "ITEM REMOVED" : "APRS ITEM") :
                                     (p->removed ? "OBJECT REMOVED" : "APRS OBJECT");
#endif
    if (p->alert_event == ALERT_RELAY)
        title="MY BEACON RELAYED";
    else if (p->alert_event == ALERT_ACK)
        title=p->comment[0]=='a' ? "MESSAGE ACK" : "MESSAGE REJECTED";
    else if (p->alert_event == ALERT_WEATHER && p->kind == PACKET)
        title="WEATHER REPORT";
    float saved[4];
    ((void (*)(unsigned, unsigned, float *))0x202632a1)(0x1121, 4, saved);
    clear_color(rule);
    rect(14, 52, 350, 1);
    if (p->kind <= PERSONAL)
        rect(120, 63, 1, 145);
    clear_color(saved);
    label(title, 13, 43, 18, WHITE, 0);
    if (p->kind > PERSONAL) {
        aprs_draw_icon(p->kind, 14, 58, 0);
        label(p->station, 46, 76, 22, WHITE, 0);
        if (p->kind == MESSAGE) {
            label("TO", 14, 112, 14, MUTED, 0);
            label(p->longitude, 46, 112, 16, WHITE, 0);
            if (*p->message_id) {
                label("ID", 265, 112, 14, MUTED, 0);
                label(p->message_id, 293, 112, 16, WHITE, 0);
            }
        }
#ifdef APRS_SLOT_UI
        unsigned reply=aprs_can_reply(p);
#else
        unsigned reply=0;
#endif
        wrapped_text(p->comment, 14, 14, p->kind == MESSAGE ? 133 : 111, reply ? 190 : DETAIL_LAST, 0);
#ifdef APRS_SLOT_UI
        if (reply) {
            uint16_t line[80] __attribute__((aligned(8)));
            for (unsigned y=0; y<42; ++y) {
                unsigned shade=8-y/7;
                uint16_t fill=(shade<<11)|(shade<<6)|shade;
                for (unsigned x=0; x<80; ++x) {
                    unsigned dx=x<40 ? x : 79-x, dy=y<21 ? y : 41-y;
                    line[x]=dx+dy<2 ? 0 : !dx || !dy || dx+dy==2 ? 0x4a49 : fill;
                }
                blit(line,187,222+y,80,1);
            }
            label("Reply", 227, 249, 18, WHITE, 1);
        }
#endif
        raw_route(p->route,reply);
        return;
    }
    unsigned metres;
    int bearing = -1;
    enum aprs_fix fix = gps_position(p, &metres, &bearing);

    fix_badge(fix);
    dial_face(bearing);
    char value[24];
    aprs_distance_text(value, fix == NO_FIX ? APRS_NO_DISTANCE : encode_distance(metres,p->ambiguous));
    unsigned font=fit(value,length(value),22,88)==length(value) ? 22 : 18;
    label(value, 62, 172, font, WHITE, 1);
    if (bearing >= 0)
        append(append(number(value, bearing, 3), "\xdf "), direction(bearing));
    else
        append(value, "--");
    label(value, 62, 196, 15, MUTED, 1);

    aprs_draw_icon((p->symbol[0] << 8) | (uint8_t)p->symbol[1], 133, 64, 0);
#ifdef APRS_SLOT_UI
    label(p->entity[0] ? p->entity : p->station,165,82,22,WHITE,0);
#else
    label(p->station,165,82,22,WHITE,0);
#endif
    if (p->kind == WEATHER) {
        reading("TEMP", p->temperature, 1, "\xdf" "C", DETAIL_TOP);
        reading("HUM", p->humidity, 1, "%", DETAIL_TOP+DETAIL_STEP);
        if (p->speed != NO_READING) {
            char *wind = value;
            if (p->course != NO_READING)
                wind = append(append(wind, direction(p->course)), " ");
            append(number(wind, p->speed, 1), " km/h");
            row("WIND", value, DETAIL_TOP+2*DETAIL_STEP);
        } else {
            row("WIND", "--", DETAIL_TOP+2*DETAIL_STEP);
        }
        reading("PRESS", p->pressure, 1, " hPa", DETAIL_TOP+3*DETAIL_STEP);
    } else {
        unsigned y = DETAIL_TOP;
        if (p->kind == IGATE) {
            row("MODE", p->symbol[0] == 'R' ? "RX ONLY" : p->symbol[0] == 'T' || p->symbol[0] == '2' ?
                "TX IGATE" : p->symbol[0] == 'L' ? "LoRa IGATE" : "IGATE", y);
            y += DETAIL_STEP;
        }
        coord_row("LAT", p->latitude, 2, y, p->ambiguous);
        coord_row("LON", p->longitude, 3, y+DETAIL_STEP, p->ambiguous);
        unsigned comment_y = y+2*DETAIL_STEP;
        if (p->kind == BEACON && (p->course != NO_READING || p->speed != NO_READING)) {
            if (*p->comment) {
                motion_line(p,comment_y);
                comment_y += DETAIL_STEP;
            } else {
                reading("SPEED", p->speed, 1, " km/h", comment_y);
                reading("COURSE", p->course, 3, "\xdf", comment_y+DETAIL_STEP);
            }
        }
        wrapped_text(p->comment, 225, 133, comment_y, DETAIL_LAST, "COMMENT");
    }
    raw_route(p->route,0);
}
