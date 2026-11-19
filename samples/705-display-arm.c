/* PC emulator only: J140 settings renderer with a resident UTF-16 word table. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define PTR(type, address) ((volatile type *)(address))
#define RUN PTR(u16, 0x204CC1D4)
#define SLOT PTR(u32, 0x204C9FC0)
#define LAB_SLOT PTR(u32, 0x21000000)
#define SLOT_WORDS (0x2214 / 4)
#define STATE ((volatile struct state *)0x21008000)
#define WORDS ((const struct word *)0x2100B004)
#define THIRD_OPTION (*PTR(u32, 0x2100AFF8))
#define DISPLAY_MODE (*PTR(u32, 0x2100AFFC))

struct state {
    u32 applies, restores, span, missing;
    u16 original[32];
    u32 font[SLOT_WORDS];
};

struct word {
    u16 scope, source_len, translated_len;
    u16 source[24], translated[24];
};

_Static_assert(sizeof(struct word) == 102, "word table record size");
_Static_assert(sizeof(struct state) <= 0x2FF8, "guest workspace size");

u32 init_font(u32 bytes)
{
    typedef u32 (*load_font)(u32, u32, u32, u32, u32);
    return ((load_font)0x20197410)(0x21000004, 0x21100000, bytes, 0, 18);
}

u32 has_glyph(u32 codepoint)
{
    typedef u32 (*char_index)(u32, u32);
    u32 wrapper = LAB_SLOT[1];
    u32 face = wrapper ? *PTR(u32, wrapper + 4) : 0;
    return face ? ((char_index)0x2025B668)(face, codepoint) : 0;
}

/* Return zero to keep the stock count and font. A positive return selects the lab face. */
u32 apply(u32 selected, u32 count)
{
    if (!count || count > 32 || STATE->span ||
        (selected != 0x204C9FC0 && selected != 0x204C1770))
        return 0;

    u16 menu = *PTR(u16, 0x203E84C9);
    u16 item = *PTR(u16, 0x204BACB8);
    u16 scope = 0;
    if (menu == 67 && *PTR(u16, 0x203804DA) == 0)
        scope = 1;
    else if (menu == 286 && (item == 0x8E || item == 0x8F || item == 0x90))
        scope = 2;
    else if (menu == 286 && item == 0x8C)
        scope = 4;
    if (menu == 67 || menu == 286)
        scope |= 8; /* Previous display-language label. */
    if ((menu == 67 && *PTR(u16, 0x203804DA) != 0) ||
        (menu == 286 && item >= 0x91 && item <= 0x9F))
        scope |= 16; /* Remaining display lists and their choice pages. */
    if (menu == 68 || (menu == 286 && item >= 0xA0 && item <= 0xA6))
        scope |= 32; /* Display units. */
    if (menu == 286 && item == 0xA7)
        scope |= 64; /* Display language choices; the system language is 0xA8. */
    if (menu == 69 || menu == 70 || (menu == 286 && item == 0xAE))
        scope |= 128; /* Time settings pilot. */
    if (THIRD_OPTION) {
        if (DISPLAY_MODE == 2) {
            if (!menu && *PTR(u8, 0x204BAB5D) == 2)
                scope |= 512;
            if (menu == 22)
                scope |= 1024;
        } else {
            scope = 0;
        }
        if (menu == 67 || (menu == 286 && item == 0xA7))
            scope |= 256; /* Only the display picker and its current value contain the third label. */
    } else if (*PTR(u16, 0x203EAE44) != 0x0101) {
        return 0;
    }
    if (!scope)
        return 0;

    u32 length = count;
    while (length && RUN[length - 1] == ' ')
        --length;
    u32 rows = *PTR(u32, 0x2100B000);
    if (rows > 128)
        return 0;
    for (u32 row = 0; row < rows; ++row) {
        const struct word *entry = &WORDS[row];
        u32 n = entry->translated_len, i;
        if (!(entry->scope & scope) || length != entry->source_len || length > 24 || !n || n > 24)
            continue;
        for (i = 0; i < length && RUN[i] == entry->source[i]; ++i) {}
        if (i != length)
            continue;

        if (THIRD_OPTION) {
            for (i = 0; i < n; ++i) {
                if (!has_glyph(entry->translated[i])) {
                    ++STATE->missing;
                    return 0;
                }
            }
        }
        STATE->span = n > count ? n : count;
        for (i = 0; i < STATE->span; ++i)
            STATE->original[i] = RUN[i];
        for (i = 0; i < n; ++i)
            RUN[i] = entry->translated[i];
        for (i = 0; i < SLOT_WORDS; ++i) {
            STATE->font[i] = SLOT[i];
            SLOT[i] = LAB_SLOT[i];
        }
        ++STATE->applies;
        return n;
    }
    return 0;
}

void restore(void)
{
    u32 span = STATE->span;
    if (!span)
        return;
    for (u32 i = 0; i < SLOT_WORDS; ++i) {
        LAB_SLOT[i] = SLOT[i];
        SLOT[i] = STATE->font[i];
    }
    for (u32 i = 0; i < span; ++i)
        RUN[i] = STATE->original[i];
    STATE->span = 0;
    ++STATE->restores;
}
