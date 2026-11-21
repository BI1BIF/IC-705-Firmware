/* J140 receive display. A completed slot stays immutable while the foreground
   paints it; the audio worker can publish again between any two UI calls. */
#include "live_rx.h"
#include "device_memory.h"
#include <stdatomic.h>
#include <string.h>

const char *row_text(int);
int row_hz(int);
int row_sender(int);
unsigned row_assisted(int);
int row_snr(int);

#ifdef FTX_DEVICE
#define batches (ftx_memory->batches)
#else
enum { FT_PANEL_TOP = 86 };
static struct DisplayBatch batches[3];
#endif
static unsigned front, back, first, ft4_mode;
static _Atomic unsigned middle;
enum { READY = 4 };
#ifdef FTX_DEVICE
static unsigned cq_only, visible_count;
static uint8_t visible_rows[48];
static unsigned delays[3], serial[3], newest, browsing, cached;
static unsigned flag_keys[16];
static uint16_t row_grids[3][48];
static struct { char call[12]; uint16_t grid; } heard[48];
static unsigned next_heard;
void view_invalidate(void) { cached=0; }
#endif

void view_reset(unsigned ft4)
{
    front=0; back=1; first=0; ft4_mode=ft4;
    batches[front].count=0;
    atomic_store(&middle,2);
#ifdef FTX_DEVICE
    cq_only=visible_count=0; newest=0; serial[0]=0; browsing=0; view_invalidate();
    memset(flag_keys,0,sizeof(flag_keys));
    memset(heard,0,sizeof(heard));next_heard=0;
#endif
}

#ifdef FTX_DEVICE
#include "atlas_tag.h"
#include "ft_panel_words.h"
#include "qth.h"
#include "j140_rx_distance.h"
#include "j140_tx.h"
static void index_rows(void)
{
    visible_count=0;
    if(ftx_memory) {
        const struct DisplayBatch *b=&batches[front];
        for(unsigned i=0;i<b->count;i++)
            if(!cq_only || !strncmp(b->rows[i].text,"CQ ",3)) visible_rows[visible_count++]=i;
    }
}
int ft_is_history(void){return browsing;}
int ft_is_cq_only(void){return cq_only;}
static unsigned auto_serial;
__attribute__((section(".ft_panel_code"),noinline)) void ft_return_live(void){auto_serial=serial[front];browsing=0; first=visible_count>10?visible_count-10:0; ft_selected=-1; view_invalidate();}
__attribute__((section(".ftx_controls"),noinline)) int ft_history_enabled(unsigned action){
    return ftx_memory && (action==0?first>0:action==1?first+10<visible_count:1);
}
void ft_history_action(unsigned action){
    ft_selected=-1;
    if(action==2){cq_only=!cq_only; index_rows();ft_return_live();return;}
    if(action==1 && first+20>=visible_count){ft_return_live();return;}
    first=action==1?first+10:first>10?first-10:0;
    browsing=1;view_invalidate();
}
int ft_local_grid(char grid[5]) {
    grid[0]=0;
    if(!ftx_position()) return 0;
    unsigned x=(here_lon+108000000)/1200000, y=(here_lat+54000000)/600000;
    if(x>179) x=179;
    if(y>179) y=179;
    grid[0]='A'+x/10;grid[1]='A'+y/10;grid[2]='0'+x%10;grid[3]='0'+y%10;grid[4]=0;
    return 1;
}
__attribute__((section(".ftx_controls"),noinline)) const struct DisplayRow *ft_row_at(unsigned y) {
    unsigned i=first+(y-102)/17;
    return ftx_memory && y>=102 && y<272 && i<visible_count?&batches[front].rows[visible_rows[i]]:NULL;
}
int ft_can_page(unsigned next) {
    return ftx_memory && (next?first+10<batches[front].count:first!=0);
}

/* The factory stores its resource banks 0x5f0000 bytes apart. The version
   tag binds the index and pictures to the exact atlas in this build. */
struct Atlas { uint32_t tag, exact, prefixes, pool, pixels, index[]; };
static const struct Atlas *flag_atlas(void)
{
    const struct Atlas *a=*(volatile uint8_t *)0x2038089d ?
        (const struct Atlas *)0x18241000 : (const struct Atlas *)0x18831000;
    return a->tag==ATLAS_TAG?a:NULL;
}
/* The normal compiler's constant tables are data only. Keeping them in a
   read-only firmware resource leaves space for the native panel logic. */
int ft_data_ready(void)
{
    extern uint8_t __ft_data[], __ft_data_end[];
    static unsigned ready;
    if(!ready) {
        const struct Atlas *a=flag_atlas();
        if(!a) return 0;
        memcpy(__ft_data,(const uint8_t *)a-FT_DATA_DISTANCE,(uintptr_t)__ft_data_end-(uintptr_t)__ft_data);
        extern uint8_t __log_begin[],__log_end[];
        memset(__log_begin,0,(uintptr_t)__log_end-(uintptr_t)__log_begin);
        ready=1;
    }
    return 1;
}
static FT_DISTANCE unsigned lookup(const struct Atlas *a,const char *key,unsigned lo,unsigned hi)
{
    while(lo<hi) {
        unsigned mid=lo+(hi-lo)/2, entry=a->index[mid];
        const char *s=(const char *)a+a->pool+(entry&0xffffff);
        int cmp=strcmp(key,s);
        if(!cmp) return entry>>24;
        if(cmp<0) hi=mid; else lo=mid+1;
    }
    return 0;
}
static unsigned sender_flag(const struct Atlas *a,const char *call)
{
    char key[FTX_MAX_MESSAGE_LENGTH];
    size_t len=strcspn(call," ");
    if(!a || !len || len>=sizeof(key) || *call=='<') return 0;
    memcpy(key,call,len);key[len]=0;
    unsigned id=lookup(a,key,0,a->exact);
    if(id) return id;
    char *part=key,*slash=strchr(key,'/');
    if(slash) {
        *slash++=0;
        if(strchr(slash,'/') || !strcmp(slash,"MM") || !strcmp(slash,"AM")) return 0;
        if(strcmp(slash,"P") && strcmp(slash,"M") && strcmp(slash,"QRP") &&
           strspn(slash,"0123456789")!=strlen(slash)) {
            if(strlen(key)==strlen(slash)) return 0;
            if(strlen(key)>strlen(slash)) part=slash;
        }
    }
    for(len=strlen(part);len && !id;part[--len]=0)
        id=lookup(a,part,a->exact,a->exact+a->prefixes);
    return id;
}
#endif

#ifdef FTX_DEVICE
__attribute__((section(".ft_panel_code"),noinline)) unsigned ft_place_id(const struct DisplayRow *r){
    const struct Atlas *a=flag_atlas();
    if(!a || !r || !r->flag) return 0;
    const char *sender=r->text+r->flag-1;
    return qth_id(sender_flag(a,sender),sender);
}
#endif
void view_publish(unsigned slot, unsigned count)
{
    struct DisplayBatch *batch=&batches[back];
#ifdef FTX_DEVICE
    /* Only the producer writes back. Its previous publication may also be
       the front frame, but both consumers only read that bank. */
    const struct DisplayBatch *prev=&batches[newest];
    unsigned skip=count && prev->count==48;
    batch->count=prev->count-skip;
    memcpy(batch->rows,prev->rows+skip,batch->count*sizeof(batch->rows[0]));
    memmove(row_grids[back],row_grids[newest]+skip,batch->count*sizeof(uint16_t));
    batch->slot=slot;
    serial[back]=serial[newest]+(count!=0);
    delays[back]=count?rx_first_delay:delays[newest];
    if(count) {
        unsigned i=count-1;
        struct DisplayRow *r=&batch->rows[batch->count++];
        memcpy(r->text,row_text(i),sizeof(r->text));
        r->hz=row_hz(i); r->db=row_snr(i); r->slot=slot;
        r->flag=row_sender(i)+1; r->assisted=row_assisted(i);
        row_grids[back][batch->count-1]=sender_grid(r);
    }
    newest=back;
#else
    batch->count=count; batch->slot=slot;
    for(unsigned i=0;i<count;++i) {
        struct DisplayRow r={.hz=row_hz(i),.db=row_snr(i),.slot=slot};
        strncpy(r.text,row_text(i),sizeof(r.text)-1);
        unsigned j=i;
        while(j && batch->rows[j-1].hz>r.hz) {batch->rows[j]=batch->rows[j-1];--j;}
        batch->rows[j]=r;
    }
#endif
    back=atomic_exchange(&middle,back|READY)&3;
}

static unsigned drawing;
#ifdef FTX_DEVICE
static unsigned dim_key;
#endif
/* Surface 18 aliases the native waterfall and HOME layers. Surface 7 is
   384x272 and separate from the HOME, AF, MULTI and TWIN render targets.
   Keep the left 360 columns at their normal y. Fold the right 120 columns
   into three tiles in the unused rows above the panel. */
__attribute__((section(".ftx_controls"),noinline)) static unsigned first_break(void){
#ifdef FTX_DEVICE
    return ft_page>=FT_MENU?159:153;
#else
    return 153;
#endif
}
__attribute__((section(".ftx_controls"),noinline)) static unsigned second_break(void){return first_break()==159?231:221;}
__attribute__((section(".ftx_controls"),noinline)) static void origin(int x,int y,int *dx,int *dy)
{
    *dx=0; *dy=0;
    if(drawing==7 && x>=360) {
        *dx=y<(int)first_break()?-360:y<(int)second_break()?-240:-120;
        *dy=y<(int)first_break()?-FT_PANEL_TOP:y<(int)second_break()?-(int)first_break():-(int)second_break();
    }
}
static void text(const char *s,unsigned x,unsigned y,unsigned size,unsigned color)
{
    typedef void (*Painter)(unsigned,unsigned,const char *,unsigned,unsigned,unsigned,unsigned,
                            const uint16_t *,unsigned,unsigned);
    int dx,dy; origin(x,y,&dx,&dy);
    const uint16_t point[2]={x+dx,y+dy+10};
    ((Painter)0x20142698)(drawing,0,s,strlen(s),1,size,color,point,0,0);
}

__attribute__((noinline,section(".ft_extra"))) static void number(int value,unsigned x,unsigned y)
{
    char buf[12],*p=buf+sizeof(buf);
    *--p=0;
    unsigned n=value<0?(unsigned)-value:(unsigned)value;
    do { *--p='0'+n%10;n/=10; } while(n);
    if(value<0) *--p='-';
    text(p,x,y,12,15);
}

static void rectangle(const float rgba[4],int x,int y,int w,int h)
{
    int dx,dy; origin(x,y,&dx,&dy);
    ((void (*)(unsigned,unsigned,const float *))0x202631f3)(0x1121,4,rgba);
    ((void (*)(int,int,int,int))0x2026362f)(x+dx,272-y-dy-h,w,h);
}

__attribute__((noinline,section(".ftx_controls"))) static void list_band(const float color[4], unsigned y, unsigned height)
{
    rectangle(color,0,y,360,height);
    rectangle(color,360,y,35,height);
}

#ifdef FTX_DEVICE
/* Coverage palettes match the solid list backgrounds and the individual
   scanlines of the OEM-style key face, including disabled keys. */
#include "ft_key_shades.h"
static unsigned key_height;

#include "qth_bar.h"
__attribute__((section(".ft_extra"),noinline))
void ft_slot_bar(unsigned slot,unsigned ms) {
    paint_slot_bar(slot,ms,ft_page==FT_LIST?100:132);
}
void ft_header(void)
{
    static const float bar[]={.09f,.14f,.16f,1};
    list_band(bar,86,16);
    text(ftx_ft4?"FT4":"FT8",4,88,13,15);
}

__attribute__((section(".ftx_controls"),noinline))
static void draw_glyph(const uint8_t *mask,const uint16_t *pal,unsigned x,unsigned y,unsigned w,unsigned paint)
{
    static uint16_t pixels[15][16] __attribute__((aligned(32)));
    unsigned height=paint?15:12; /* Flags use their own palette and twelve source rows. */
    for(unsigned row=0;row<height;row++){
        unsigned index=!paint?0:paint>=2?2*(paint-2):key_shades[key_height][row]+33*dim_key;
        const uint16_t *colors=pal+16*index;
        for(unsigned col=0;col<w;col++){
            unsigned byte=mask[8*row+col/2];
            pixels[row][col]=colors[(byte>>(4*(col&1)))&15];
        }
    }
    /* Publish complete cache lines to the graphics engine before it reads them. */
    for(unsigned row=0;row<height;row++)
        __asm__ volatile("mcr p15,0,%0,c7,c10,1"::"r"(pixels[row]):"memory");
    __asm__ volatile("dsb sy":::"memory");
    int dx,dy;origin(x,y,&dx,&dy);
    ((void (*)(const uint16_t *,int,unsigned,int,int,int,int))0x20263b13)(
        pixels[height-1],-32,3,x+dx,272-y-dy-height,w,height);
    ((void (*)(void))0x20263191)(); /* source reusable after vgFinish */
}

__attribute__((section(".ft_panel_code"),noinline))
static unsigned panel_word(unsigned id, unsigned x, unsigned y, unsigned limit, int paint)
{
    const struct Atlas *atlas=flag_atlas();
    if(!atlas || !id)return 0;
    const uint16_t *header=(const uint16_t *)((const uint8_t *)atlas+PANEL_OFFSET);
    const uint8_t *data=(const uint8_t *)(header+4);
    const uint16_t *offset=(const uint16_t *)data;
    const uint16_t *word=(const uint16_t *)(data+header[0]+offset[id-1]);
    unsigned width=0;
    for(const uint16_t *p=word;*p;p++)width+=*p<=header[2]?8:16;
    if(!paint || width>limit)return width;
    const uint8_t *masks=(const uint8_t *)atlas-FT_GLYPH_DISTANCE;
    for(;*word;word++){
        unsigned w=*word<=header[2]?8:16;
        draw_glyph(masks+120*(*word-1),(const uint16_t *)(data+header[1]),x,y,w,paint);
        x+=w;
    }
    return width;
}
/* The factory outline painter allocates glyph paths for each unfamiliar run.
   Decoded messages use immutable ROM pixels even when the FT worker holds RAM. */
static unsigned draw_message(const char *s,unsigned y,unsigned selected)
{
    static const char chars[]=FT_RX_CHARS;
    const uint8_t *atlas=(const uint8_t *)flag_atlas();
    unsigned n=0;
    for(;atlas && n<20 && s[n];n++){
        const char *found=strchr(chars,s[n]);
        unsigned i=found?(unsigned)(found-chars):(unsigned)(strchr(chars,'?')-chars);
        const uint8_t *tile=atlas+(i<FT_RX_SPLIT?FT_RX_FIRST:FT_RX_SECOND)+448*i+224*selected;
        ((void (*)(const void *,int,unsigned,int,int,int,int))0x20263b13)(
            tile+208,-16,3,35+8*n,272-y-14,8,14);
    }
    return n*8;
}
static unsigned label_width(const char *s)
{
    return *s==127?panel_word((unsigned char)s[1],0,0,0,0)+7*strlen(s+2):7*strlen(s);
}
#endif

#ifdef FTX_DEVICE
__attribute__((section(".ft_panel_code"),noinline)) void ft_place_label(unsigned flag,unsigned x,unsigned y){
    if(flag)panel_word((unsigned char)Z_again[1]+flag,x,y,390-x,1);
}
#endif
void view_page(unsigned next)
{
#ifdef FTX_DEVICE
    unsigned last=batches[front].count>10?batches[front].count-10:0;
    if(next) first=first+10<last?first+10:last;
    else first=first>10?first-10:0;
    browsing=first!=last;
#else
    if(next && first+10<batches[front].count) first+=10;
    if(!next && first>=10) first-=10;
#endif
}

typedef unsigned (*Select)(unsigned,unsigned);
struct Paint { unsigned offscreen, display; float saved[4]; };
static int begin(struct Paint *p,unsigned target)
{
    p->offscreen=((unsigned (*)(void))0x20195188)();
    p->display=((unsigned (*)(void))0x20194c10)();
    if(!((Select)0x201951ac)(p->offscreen,target)) return 0;
    drawing=target;
    ((void (*)(unsigned,unsigned,float *))0x202632a1)(0x1121,4,p->saved);
    return 1;
}
static void copy_piece(const uint16_t *target,int x,int y,int right,int bottom)
{
    typedef void (*Blit)(const uint16_t *,int,unsigned,int,int,int,int);
    int dx,dy; origin(x,y,&dx,&dy);
    int stride=drawing==7?384:480;
    ((Blit)0x20263b13)(target+(bottom+dy-1)*stride+x+dx,-2*stride,3,x,272-bottom,right-x,bottom-y);
}
#ifdef FTX_DEVICE
static FT_DISTANCE void copy_rect(const uint16_t *target,int x,int y,int right,int bottom)
{
    if(x<360) copy_piece(target,x,y,right<360?right:360,bottom);
    if(right<=360) return;
    if(x<360) x=360;
    while(y<bottom) {
        int end=y<(int)first_break()?first_break():y<(int)second_break()?second_break():272;
        if(end>bottom) end=bottom;
        copy_piece(target,x,y,right,end);
        y=end;
    }
}
#endif
static void finish(struct Paint *p,int x,int y,int w,int h)
{
    ((void (*)(unsigned,unsigned,const float *))0x202631f3)(0x1121,4,p->saved);
    ((void (*)(void))0x20263191)();
    if(((Select)0x20194c18)(p->display,*(volatile uint8_t *)0x20380cbc)) {
        const uint16_t *target=*(const uint16_t **)((unsigned (*)(unsigned))0x20195190)(drawing);
#ifdef FTX_DEVICE
        if(y==FT_PANEL_TOP) {
            /* The CW panel uses the same committed MULTI, AF and TWIN layers. */
            int right=*(volatile uint8_t *)0x204bd028?361:480;
            unsigned af_top=ft_af_top();
            int left=af_top<272?118:0;
            if(left) copy_rect(target,0,FT_PANEL_TOP,left,af_top);
            if(*(volatile uint8_t *)0x204bd0bc && *(volatile uint8_t *)0x204bd0bd==1) {
                copy_rect(target,left,FT_PANEL_TOP,right,153);
                copy_rect(target,left,153,130,239);
                copy_rect(target,350,153,right,239);
                copy_rect(target,left,239,right,272);
            } else copy_rect(target,left,FT_PANEL_TOP,right,272);
        } else
#endif
        copy_piece(target,x,y,x+w,y+h);
        ((void (*)(void))0x20263191)();
    }
    ((Select)0x201951ac)(p->offscreen,18);
}

#ifdef FTX_DEVICE
void view_button(const char *label, int x, int y, int w, int h)
{
    struct Paint p;
    if(!begin(&p,18)) return;
    /* Resources and stretch parameters of the J140 MODE keys. */
    typedef void (*Slice)(unsigned,unsigned,const uint16_t *,unsigned,unsigned);
    typedef void (*Repeat)(unsigned,unsigned,const uint16_t *,unsigned,unsigned,unsigned);
    uint16_t point[4]={x+10,y,w,h};
    ((Repeat)0x20148430)(18,209,point,19,3,43);
    point[0]=x;
    ((Slice)0x20148238)(18,210,point,10,43);
    point[0]=x+w-10;
    ((Slice)0x20148238)(18,208,point,10,43);
    text(label,x+15,y+16,17,15);
    finish(&p,x,y,w,h);
}
#endif

#ifdef FTX_DEVICE
static unsigned draw_flag(const struct DisplayRow *row,unsigned sequence,unsigned x,unsigned y)
{
    if(!row->flag) return 0;
    const struct Atlas *a=flag_atlas();
    if(!a) return 0;
    /* Consecutive pages share nine rows. Keep the atlas result even when a
       newly decoded row makes their text move by one line. */
    unsigned key=(sequence+1)<<8, *entry=&flag_keys[sequence%16];
    if((*entry&~255u)!=key || !key)
        *entry=key|sender_flag(a,row->text+row->flag-1);
    unsigned id=*entry&255;
    if(!id) return 0;
    const uint8_t *tile=(const uint8_t *)a+0x3af000+(id-1)*128;
    draw_glyph(tile+32,(const uint16_t *)tile,x,y,16,0);
    return id;
}
__attribute__((section(".ftx_controls"),noinline)) int ft_choose_row(unsigned y){
    if(!ft_row_at(y))return 0;
    int i=(int)(first+(y-102)/17);
    ft_selected=i==ft_selected?-1:i;view_invalidate();return 1;
}
__attribute__((section(".ftx_controls"),noinline)) const struct DisplayRow *ft_choice_row(void){
    return ft_selected>=0 && (unsigned)ft_selected<visible_count?&batches[front].rows[visible_rows[ft_selected]]:NULL;
}
__attribute__((section(".ftx_controls"),noinline)) void ft_label(const char *s,unsigned x,unsigned y,unsigned size,unsigned color){
    if(*s==127) {
        if(y==86)key_height=2;
        x+=panel_word((unsigned char)s[1],x,y,480-x,1);
        if(y==86)key_height=0;
        s+=2;
    }
    if(*s) text(s,x,y,size,color);
}
__attribute__((noinline)) void ft_blank(unsigned y){static const float bg[]={.035f,.055f,.065f,1};rectangle(bg,0,y,y?360:384,272-y);}

void ft_key(const char *s,unsigned x,unsigned y,unsigned w,unsigned h) {
    static const float accent[]={.51f,.79f,.94f,1};
    static const float menu_bg[]={.063f,.122f,.165f,1}, rule[]={.22f,.29f,.33f,1};
    if(w==350 && x==4){
        for(unsigned i=0;i<h;i++){
            const float *color=i==h-1?rule:menu_bg;
            rectangle(color,0,y+i,360,1);
            rectangle(color,360,y+i,35,1);
        }
        key_height=1;
        ft_label(s,8,y+(h-15)/2,12,15);
        key_height=0;
        return;
    }
    dim_key=ft_page==FT_LIST && (ft_auto_armed ? y!=89 : y==161 && !ft_history_enabled(x==439));
    key_height=h;
    const struct Atlas *atlas=flag_atlas();
    if(!atlas)return;
    const uint16_t *pixels=(const uint16_t *)((const uint8_t *)atlas+FT_KEY_OFFSET);
    typedef void (*Blit)(const uint16_t *,int,unsigned,int,int,int,int);
    Blit blit=(Blit)0x20263b13;
    for(unsigned i=0;i<h;){
        int dx,dy;origin(x,y+i,&dx,&dy);
        unsigned first=32*i/(h-1), end=i+1;
        unsigned boundary=x<360?272:y+i<first_break()?first_break():y+i<second_break()?second_break():272;
        while(end<h && y+end<boundary && 32*end/(h-1)==first+end-i)++end;
        const uint16_t *line=pixels+176*(33*dim_key+first+end-i-1);
        blit(line,-352,3,x+dx,272-y-end-dy,w-2,end-i);
        blit(line+170,-352,3,x+dx+w-2,272-y-end-dy,2,end-i);
        i=end;
    }
    if(ft_page==FT_LIST && x==399 && y==89)rectangle(accent,x,y+1,3,h-2);
    unsigned width=label_width(s);
    ft_label(s,x+(w>width?(w-width)/2:2),y+(h-15)/2,12,15);
    key_height=0;
    dim_key=0;
}

#endif

/* Call from the normal frame compositor after the stock mini-scope.
   The caller supplies live UTC slot/phase, independent of the last decode. */
void view_draw(unsigned slot,unsigned phase)
{
#ifdef FTX_DEVICE
    extern const char *ftx_status(void);
    const char *status=ftx_status();
#else
    const char *status=0;
    if(!live_enabled()) return;
#endif
    struct Paint p;
#ifdef FTX_DEVICE
    if(!begin(&p,7)) return;
    const struct DisplayBatch *batch=NULL;
    if(ftx_memory) {
        if(atomic_load(&middle)&READY) {
            unsigned previous=serial[front];
            unsigned old_base=previous-batches[front].count;
            unsigned anchor=first<visible_count?old_base+visible_rows[first]:old_base;
            unsigned chosen=ft_selected>=0?old_base+visible_rows[ft_selected]:0;
            front=atomic_exchange(&middle,front)&3;
            unsigned base=serial[front]-batches[front].count;
            index_rows();
            if(browsing){
                first=0;
                while(first+1<visible_count && (int)(base+visible_rows[first]-anchor)<0)first++;
            }else first=visible_count>10?visible_count-10:0;
            if(ft_selected>=0){
                ft_selected=-1;
                for(unsigned i=first;i<visible_count && i<first+10;i++)
                    if(base+visible_rows[i]==chosen)ft_selected=i;
            }
            unsigned added=serial[front]-previous;
            if(added>batches[front].count) added=batches[front].count;
            if(!ft_auto_armed)for(unsigned i=batches[front].count-added;i<batches[front].count;++i)
                ft_receive_row(&batches[front].rows[i],0);
        }
        batch=&batches[front];
        if(ft_auto_armed){
            unsigned n=serial[front]-auto_serial;
            if(n>batch->count)n=batch->count;
            for(unsigned pass=0;pass<2 && ft_auto_armed;pass++)
                for(unsigned i=batch->count-n;i<batch->count && ft_auto_armed;i++)
                    if((!strncmp(batch->rows[i].text,"CQ ",3))==pass)
                        ft_receive_row(&batch->rows[i],0);
        }
    }
    if(ft_page) {
        unsigned page=ft_page;
        unsigned full=cached!=page+1;
        if(page<=FT_SETUP || full) ft_panel_draw(full);
        cached=page+1;
        finish(&p,0,FT_PANEL_TOP,480,272-FT_PANEL_TOP);
        return;
    }
#else
    if(!begin(&p,18)) return;
    if(!status && (atomic_load(&middle)&READY)) {
        unsigned old_slot=batches[front].slot;
        front=atomic_exchange(&middle,front)&3;
        if(batches[front].slot!=old_slot || first>=batches[front].count) first=0;
    }
    const struct DisplayBatch *batch=status ? NULL : &batches[front];
#endif
    static const float bg[]={.035f,.055f,.065f,1},bar[]={.09f,.14f,.16f,1};
    static const float progress[]={.15f,.43f,.38f,1};
#ifdef FTX_DEVICE
    unsigned position=ftx_position();
    static struct PageKey { unsigned seq, first, position; int lat, lon; const char *status; } prior;
    struct PageKey key={batch?serial[front]:0,first,position,here_lat,here_lon,status};
    unsigned changed=cached!=1 || memcmp(&key,&prior,sizeof(key));
    /* Surface 7 retains the FT list even when HOME repaints underneath it.
       The slot rail is the only changing element of a stable live page. */
    if(!changed && !status){
        ft_slot_bar(slot,phase/8);
        finish(&p,0,FT_PANEL_TOP,480,272-FT_PANEL_TOP);
        return;
    }
    if(changed) { prior=key; cached=1; rectangle(bg,0,0,384,272); }
    ft_header();
#else
    rectangle(bg,0,86,480,186);
    rectangle(bar,0,86,480,16);
#endif
    unsigned length=ft4_mode?60000:120000;
#ifndef FTX_DEVICE
    if(!status && phase<length) {
        unsigned width=65*phase/length;
        if(width) rectangle(progress,78+70*(slot&1),86,width,16);
    }
#endif
#ifdef FTX_DEVICE
    if(!status) ft_slot_bar(slot,phase/8);
    extern unsigned ftx_ft4;
    if (ftx_memory && (ftx_memory->plan.wf.time_osr==1 || ftx_memory->plan.wf.freq_osr==1)) text("ECO",42,88,12,15);
#else
    text(ft4_mode?"FT4":"FT8",4,88,13,15);
#endif
    if(status && batch && batch->count) text(status,78,88,12,15);
#ifndef FTX_DEVICE
    else {text("RX A",80,86,12,15);text("RX B",150,86,12,15);}
#endif
#ifdef FTX_DEVICE
    text("QTH",199,87,12,15);
#endif
    text("dB",269,88,12,15);text("Hz",307,87,12,15);
#ifdef FTX_DEVICE
    text(position==2?"km M":position==1?"km G":"km",362,88,12,15);
    if(!changed) { finish(&p,0,FT_PANEL_TOP,480,272-FT_PANEL_TOP); return; }
#else
    text("RX",434,86,12,15);
#endif
    #ifdef FTX_DEVICE
    unsigned shown=visible_count;
#else
    unsigned shown=batch?batch->count:0;
#endif
    unsigned previous_slot=0;
    for(unsigned n=0;n<10;++n) {
        unsigned y=102+17*n;
        static const float divider[]={.16f,.22f,.27f,1};
        list_band(divider,y+16,1);
        if(!batch || first+n>=shown) continue;
        unsigned i=first+n;
#ifdef FTX_DEVICE
        if((int)i==ft_selected){
            list_band(progress,y,16);
        }
        i=visible_rows[i];
#endif
        const struct DisplayRow *r=&batch->rows[i];
        if(n && r->slot!=previous_slot) {
            static const float slot_blue[]={.19f,.62f,.84f,1};
            list_band(slot_blue,y-1,1);
        }
        previous_slot=r->slot;
        /* Keep the numeric columns clear on long nonstandard messages. */
        text(r->slot&1?((r->assisted&1)?"B*":"B"):((r->assisted&1)?"A*":"A"),4,y+2,12,15);
#ifdef FTX_DEVICE
        unsigned flag=draw_flag(r,serial[front]-batch->count+i,18,y+2);
        draw_message(r->text,y+2,(int)(first+n)==ft_selected);
        mark_long_message(r->text,y+1,(int)(first+n)==ft_selected);
        if(flag)panel_word(FT_LIST_NAMES+qth_id(flag,r->text+r->flag-1),199,y+1,64,
                          (int)(first+n)==ft_selected?3:2);
        int km=position ? ftx_km(row_grids[front][i]) : -1;
        if(km>=0) number(km,362,y+2); else text("--",362,y+2,12,15);
#endif
#ifndef FTX_DEVICE
        text(r->text,35,y,13,15);
#endif
#ifdef FTX_DEVICE
        if(r->flag && ft_worked(r->text+r->flag-1)==1){
            unsigned n=strcspn(r->text+r->flag-1," ");
            unsigned start=r->flag-1;
            if(start+n>20)n=start<20?20-start:0;
            if(n)rectangle(progress,35+8*start,y+9,8*n,1);
        }
#endif
        if(r->db!=-128) number(r->db,269,y+2); else text("--",269,y+2,12,15);
        number(r->hz,307,y+2);
    }
    if(!batch || !batch->count) text(status ? status : "No decodes",6,104,13,15);
#ifdef FTX_DEVICE
    const struct DisplayRow *pick=ft_selected>=0?&batch->rows[visible_rows[ft_selected]]:NULL;
    ft_key(ft_auto_armed?Z_stop:pick?(ft_row_eligible(pick)?Z_reply:Z_info):Z_cq,399,89,77,33);
    ft_key(browsing?Z_live:pick?Z_clear:Z_auto,399,125,77,33);
    ft_key(Z_old,399,161,37,33);
    ft_key(Z_new,439,161,37,33);
    ft_key(cq_only?Z_all:Z_cq_only,399,197,77,33);
    ft_key(Z_menu,399,233,77,33);
#else
    if(batch && first) text("<",435,139,16,15);
    if(batch && first+10<batch->count) text(">",435,174,16,15);
    text("EXIT",425,242,14,15);
#endif
    finish(&p,0,FT_PANEL_TOP,480,272-FT_PANEL_TOP);
}
