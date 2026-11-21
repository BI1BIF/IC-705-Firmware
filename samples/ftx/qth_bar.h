static void paint_slot_bar(unsigned slot,unsigned ms,unsigned x) {
    static const float edge[]={.43f,.56f,.62f,1},rail[]={.055f,.09f,.12f,1},fill[]={.22f,.70f,.90f,1};
    unsigned period=ftx_ft4?7500:15000;
    static const float bar[]={.09f,.14f,.16f,1};
    rectangle(bar,x,86,15,16);
    rectangle(edge,x+15,90,72,8);
    rectangle(rail,x+16,91,70,6);
    if(ms>=period)return;
    text(slot&1?"B":"A",x+1,88-(slot&1),12,15);
    unsigned w=70*ms/period;
    if(w)rectangle(fill,x+16,91,w,6);
}

/* Keep the full message in the detail and reply views. */
static void mark_long_message(const char *s,unsigned y,int selected)
{
    for (unsigned i=0;i<=20;i++) if (!s[i]) return;
    static const float bg[]={.035f,.055f,.065f,1}, active[]={.15f,.43f,.38f,1};
    static const float ink[]={.93f,.96f,.95f,1};
    rectangle(selected?active:bg,187,y+1,8,14);
    for (unsigned x=187;x<=193;x+=3) rectangle(ink,x,y+12,1,2);
}
