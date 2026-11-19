/* Microsecond scan schedules, measured from the end of the line sync.
   Scottie starts with green and synchronizes between blue and red. */
enum Layout { GBR, SCOTTIE, RGB, YCRCB, PD, MONO };
struct Mode {
    unsigned vis, height, sync, channels, period, edge;
    enum Layout layout;
    const char *name, *size;
    unsigned start[4], length[4];
};
#define MARTIN(v,h,d,n,size) {v,h,4862,3,4862+2288+3*d,0,GBR,n,size,{572,1144+d,1716+2*d},{d,d,d}}
#define SCOT(v,d,n) {v,256,9000,3,13500+3*d,12000+2*d,SCOTTIE,n,"320 x 256",{1500,3000+d,13500+2*d},{d,d,d}}
#define PDM(v,h,d,n,size) {v,h,20000,4,22080+4*d,0,PD,n,size,{2080,2080+d,2080+2*d,2080+3*d},{d,d,d,d}}
#define BW(v,h,d,n,size) {v,h,7000,1,7000+d,0,MONO,n,size,{0},{d}}
#define PAS(v,s,g,d,n) {v,496,s,3,s+4*g+3*d,0,RGB,n,"640 x 496",{g,2*g+d,3*g+2*d},{d,d,d}}
static const struct Mode basic_modes[]={
    MARTIN(40,256,73216,"Martin M2","320 x 256"),
    MARTIN(36,128,146432,"Martin M3","320 x 128"),
    MARTIN(32,128,73216,"Martin M4","320 x 128"),
    SCOT(60,138240,"Scottie S1"), SCOT(56,88064,"Scottie S2"), SCOT(76,345600,"Scottie DX"),
    {12,240,9000,3,300000,0,YCRCB,"Robot 72","320 x 240",{3000,147000,222000},{138000,69000,69000}},
    {55,256,5523,3,711023,0,RGB,"SC2-180","320 x 256",{500,235500,470500},{235000,235000,235000}},
    PDM(93,256,91520,"PD50","320 x 256"), PDM(99,256,170240,"PD90","320 x 256"),
    PDM(95,496,121600,"PD120","640 x 496"), PDM(98,400,195584,"PD160","512 x 400"),
    PDM(96,496,183040,"PD180","640 x 496"), PDM(97,496,244480,"PD240","640 x 496"),
    PDM(94,616,228800,"PD290","800 x 616"),
    BW(2,120,59900,"BW 8","160 x 120"), BW(6,120,93000,"BW 12","160 x 120"),
    BW(10,240,93000,"BW 24","320 x 240"),
    PAS(113,5208,1042,133333,"Pasokon P3"), PAS(114,7813,1563,200000,"Pasokon P5"),
    PAS(115,10417,2083,266667,"Pasokon P7")
};
static const struct Mode *lookup(unsigned code) {
    for (unsigned i=0;i<sizeof(basic_modes)/sizeof(*basic_modes);i++)
        if (basic_modes[i].vis==code) return basic_modes+i;
    return 0;
}
static struct {
    const struct Mode *m;
    unsigned time,channel,col,next,hits,aligned,y,remainder;
    uint8_t planes[4][WIDTH];
} stream;
static void start_channel(unsigned ch) {
    stream.channel=ch; stream.col=0;
    if (ch<stream.m->channels)
        stream.next=640*stream.m->start[ch]+stream.m->length[ch];
}
static void start_stream(const struct Mode *m) {
    stream.m=m;
    stream.time=stream.hits=stream.aligned=stream.y=stream.remainder=0;
    start_channel(0);
}
static void stream_row(unsigned luma) {
    const struct Mode *m=stream.m;
    stream.remainder+=HEIGHT;
    while (stream.remainder>=m->height) {
        uint16_t *dst=image[stream.y++];
        for (unsigned x=0;x<WIDTH;x++) {
            unsigned a=stream.planes[0][x], b=stream.planes[1][x], c=stream.planes[2][x];
            if (m->layout==PD || m->layout==YCRCB)
                dst[x]=rgb565(stream.planes[luma][x],(int)b-128,(int)c-128);
            else {
                unsigned r=a,g=b,blue=c;
                if (m->layout==GBR || m->layout==SCOTTIE) { r=c; g=a; blue=b; }
                if (m->layout==MONO) { g=a; blue=a; }
                dst[x]=((r>>3)<<11)|((g>>2)<<5)|(blue>>3);
            }
        }
        stream.remainder-=m->height;
    }
    rx.rows++;
}
static void stream_sample(unsigned f) {
    const struct Mode *m=stream.m;
    unsigned t=stream.time, edge=m->edge ? m->edge : m->period;
    if (!stream.aligned && t+ m->sync+1800>=edge) {
        if (f>=1060 && f<=1340 && t<=edge+2000) stream.hits++;
        if (t+1800>=edge && f>=1380 && stream.hits*250>=m->sync) {
            if (m->edge) { t=edge; stream.aligned=1; }
            else { t=0; start_channel(0); }
            stream.hits=0;
        } else if (t>edge+3000) {
            rx.loss=1;
#ifdef SSTV_LATE_JOIN
            rx.phase=rx.live && rx.rows && !f ? COMPLETE : LOST;
#else
            rx.phase=LOST;
#endif
            return;
        }
    }
    if (m->edge && t>=m->period && stream.aligned) {
        t-=m->period; stream.aligned=0; start_channel(0);
    }
    unsigned ch=stream.channel;
    if (ch<m->channels && t*640>=stream.next) {
        unsigned v=clip(((int)f-1500)*255/800);
        do {
            stream.planes[ch][stream.col++]=v;
            stream.next+=2*m->length[ch];
        } while (stream.col<WIDTH && t*640>=stream.next);
        if (stream.col==WIDTH) {
            start_channel(ch+1);
            if (ch+1==m->channels) {
                stream_row(0);
                if (m->layout==PD) stream_row(3);
                if (rx.rows==m->height) rx.phase=COMPLETE;
            }
        }
    }
    stream.time=t+125;
}
