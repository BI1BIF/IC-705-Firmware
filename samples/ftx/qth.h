/* IDs 1..FT_REGIONS are the original flag IDs. The additional IDs are names
   only. Keep their order in sync with QTH_NAMES in the panel asset builder. */
static unsigned qth_id(unsigned flag, const char *call)
{
    if (flag != FT_CHINA || !call) return flag;
    unsigned n = 0;
    while (call[n] && call[n] != ' ') ++n;
    /* Keep explicit operating prefixes, skip a domestic portable district:
       the home suffix does not identify a province in that district. */
    unsigned slash = 0;
    while (slash < n && call[slash] != '/') ++slash;
    if (slash < n) {
        unsigned tail = n - slash - 1;
        const char *end = call + slash + 1;
        if ((tail == 1 && (*end == 'P' || *end == 'M')) ||
            (tail == 3 && end[0]=='Q' && end[1]=='R' && end[2]=='P')) n = slash;
        else if (slash < tail) n = slash;
        else { call = end; n = tail; }
    }
    if (n < 2 || call[0] != 'B') return flag;
    switch (call[1]) {
    case 'M': case 'N': case 'O': case 'P': case 'Q': case 'U': case 'V': case 'W': case 'X':
        if (n == 2 || (call[2] >= '0' && call[2] <= '9')) {
            if (n >= 4 && call[2]=='9' && call[3]=='P') return flag; /* BV9P, Pratas */
            return FT_REGIONS + 1;
        }
        return flag;
    }
    if (n != 5 && n != 6) return flag;
    if (call[1]<'A' || call[1]>'Y' ||
        !(FT_PROVINCE_SERIES & (1u << (call[1]-'A')))) return flag;
    if (call[2]<'0' || call[2]>'9') return flag;
    for (unsigned i=3;i<n;i++) if (call[i]<'A' || call[i]>'Z') return flag;
    if (n==6 && ((call[3]=='Q' && call[4]>='O' && call[4]<='U') ||
        (call[3]=='S' && call[4]=='O' && call[5]=='S') ||
        ((call[3]=='X' || call[3]=='T') && call[4]==call[3] && call[5]==call[3]))) return flag;
    /* MIIT attachment 2. Rows 0, 3, 8 and 9 use groups of six, the
       other multi-province districts use eight. Hainan has Y and Z. */
    unsigned district=call[2]-'0', letter=call[3]-'A';
    static const unsigned char first[]={2,4,5,8,12,15,18,21,25,29};
    if ((district==0 && letter>=12) || (district!=7 && letter>=24)) return flag;
    unsigned group=0;
    if (district!=1)
        group = (district==0 || district==3 || district>=8) ? letter/6 : letter/8;
    return FT_REGIONS + first[district] + group;
}
