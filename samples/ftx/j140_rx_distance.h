/* J140 HOME uses the same factory coordinate readers for Internal and Manual.
   Position validity is independent of the FT audio clock. */
#include <math.h>
static int here_lat, here_lon;
static struct { uint16_t grid, km; } ranges[16];
#define FT_DISTANCE __attribute__((section(".ftx_controls"),noinline))

static FT_DISTANCE int coordinate(const char *s,unsigned width)
{
    int degrees=0,minutes=0;
    for(unsigned i=0;i<width+6;++i) {
        unsigned digit=(unsigned)(s[i]-'0');
        if(digit>9) return INT32_MAX;
        if(i<width) degrees=10*degrees+digit;
        else minutes=10*minutes+digit;
    }
    char hemisphere=s[width+6];
    int limit=width==2?90:180;
    if(minutes>=600000 || degrees>limit || (degrees==limit && minutes)) return INT32_MAX;
    int value=degrees*600000+minutes;
    if(hemisphere==(width==2?'N':'E')) return value;
    return hemisphere==(width==2?'S':'W')?-value:INT32_MAX;
}

static FT_DISTANCE unsigned ftx_position(void)
{
    unsigned mode=*(volatile uint8_t *)0x203eb16c;
    if((mode!=1 && mode!=2) || (mode==1 && !((unsigned (*)(void))0x20074650)())) return 0;
    char latitude[12],longitude[12];
    ((void (*)(char *,unsigned))0x20073b70)(latitude,mode==2);
    ((void (*)(char *,unsigned))0x20073b58)(longitude,mode==2);
    int lat=coordinate(latitude,2),lon=coordinate(longitude,3);
    if(lat==INT32_MAX || lon==INT32_MAX) return 0;
    if(lat!=here_lat || lon!=here_lon) {
        memset(ranges,0,sizeof(ranges));
        here_lat=lat; here_lon=lon;
    }
    return mode;
}

/* Resolve at publication, so browsing later cannot change the grid of an older report. */
static FT_DISTANCE unsigned sender_grid(const struct DisplayRow *r)
{
    unsigned pos=r->assisted>>1, grid=0;
    if(pos && pos+3<=sizeof(r->text)){
        const char *g=r->text+pos-1;
        unsigned x=10*(g[0]-'A')+g[2]-'0', y=10*(g[1]-'A')+g[3]-'0';
        if(x<180 && y<180)grid=1+180*x+y;
    }
    if(!r->flag)return grid;
    const char *sender=r->text+r->flag-1;
    size_t n=strcspn(sender," ");
    if(!n || n>=sizeof(heard[0].call) || *sender=='<')return grid;
    for(unsigned i=0;i<48;i++)
        if(!strncmp(heard[i].call,sender,n) && !heard[i].call[n]){
            if(grid)heard[i].grid=grid;
            return heard[i].grid;
        }
    if(grid){
        unsigned i=next_heard;
        next_heard=(i+1)%48;
        memcpy(heard[i].call,sender,n);heard[i].call[n]=0;heard[i].grid=grid;
    }
    return grid;
}

static FT_DISTANCE int ftx_km(unsigned key)
{
    if(!key)return -1;
    unsigned x=(key-1)/180,y=(key-1)%180,index=key%16;
    if(ranges[index].grid!=key) {
        const float rad=.01745329252f;
        float lat=(here_lat/600000.f)*rad, remote=((float)y-89.5f)*rad;
        float dlat=sinf(.5f*(remote-lat));
        float dlon=sinf(.5f*((2.f*x-179.f-here_lon/600000.f)*rad));
        float h=dlat*dlat + cosf(lat)*cosf(remote)*dlon*dlon;
        /* Binary search the central half-angle. No large inverse-trig table
           is needed and the final angular interval is under 0.4 km. */
        float a=0,b=1.570796327f;
        for(unsigned j=0;j<16;++j) {
            float mid=.5f*(a+b), s=sinf(mid);
            if(s*s<h) a=mid; else b=mid;
        }
        ranges[index].km=(uint16_t)((a+b)*6371.009f+.5f);
        ranges[index].grid=key;
    }
    return ranges[index].km;
}
