/* FTLOG.ADI has fixed-size records so a partial final write can be retried in
   place. It is ordinary length-tagged ASCII ADIF; trailing spaces are padding. */
#define LOG_BYTES 320
#define LOG_QUEUE 4
#define LOG_CACHE 32
#define LOG_FN __attribute__((section(".ft_logcode"),noinline))
static const char log_path[]="C:\\IC-705\\FTLOG.ADI";
static const char log_header[]="IC-705 FT log\r\n<ADIF_VER:5>3.1.6 <EOH>\r\n";
#define l_open ((int (*)(const char *,unsigned,int *))0x2023fec8)
#define l_close ((int (*)(int))0x2023fee4)
#define l_read ((int (*)(int,void *,unsigned,unsigned *))0x2023ff00)
#define l_write ((int (*)(int,const void *,unsigned,unsigned *))0x2023ff18)
#define l_seek ((int (*)(int,int,unsigned,unsigned *))0x2023ff64)
struct Contact {
    char own[7],dx[7],grid[5],mygrid[5],sent[4],rcvd[4],on[15],off[15];
    unsigned freq,mode,band;
};
struct Query {char call[7]; signed char worked;};
static struct Journal {
    struct Contact pending[LOG_QUEUE],current;
    struct Query cache[LOG_CACHE],query[LOG_CACHE];
    char line[LOG_BYTES+1],detail[LOG_BYTES+1],operator[7];
    unsigned head,count,total,offset,nquery,cache_next,band,mode,epoch,job_epoch;
    unsigned saved,load_view,misses,error,was_card,next_poll,reset;
    _Atomic unsigned io;
} journal __attribute__((section(".ft_logram")));
static const char *const bands[]={"","160m","80m","60m","40m","30m","20m","17m","15m","12m","10m","6m","2m","70cm"};
static LOG_FN unsigned log_band(unsigned hz){
    static const unsigned upper[]={0,2000000,4000000,5500000,7300000,10150000,14350000,18168000,21450000,24990000,29700000,54000000,148000000,450000000};
    for(unsigned i=1;i<sizeof(upper)/sizeof(*upper);i++)if(hz<=upper[i])return i;
    return 0;
}
static void number2(char *p,unsigned v){p[0]='0'+v/10;p[1]='0'+v%10;}
static unsigned month_days(unsigned y,unsigned m){
    static const uint8_t days[]={31,28,31,30,31,30,31,31,30,31,30,31};
    return days[m-1]+(m==2 && y%4==0);
}
static LOG_FN int utc_stamp(char *out){
    unsigned v[6], y,m,d,h,min,sec;
    if(!ftx_rtc){
        char date[8]={0},time[8]={0};
        if(!((unsigned (*)(void))0x2021300c)())return 0;
        ((void (*)(char *))0x20212b64)(time);((void (*)(char *))0x20212b80)(date);
        for(unsigned i=0;i<6;i++){const char *p=(i<3?date:time)+2*(i%3);
            if((unsigned)(p[0]-'0')>9||(unsigned)(p[1]-'0')>9)return 0;
            v[i]=(p[0]-'0')*10+p[1]-'0';}
        y=v[2];m=v[1];d=v[0]; h=v[3];min=v[4];sec=v[5];
    }else{
        for(unsigned i=0;i<6;i++){unsigned b=U8(0x2038079a+i+(i>=3));
            if((b>>4)>9||(b&15)>9)return 0;
            v[i]=(b>>4)*10+(b&15);}
        y=v[0];m=v[1];d=v[2];h=v[3];min=v[4];sec=v[5];
    }
    if(m<1||m>12||d<1||d>month_days(y,m)||h>=24||min>=60||sec>=60)return 0;
    int t=h*60+min-(ftx_rtc?pref.utc_q*15:0);
    if(t<0){t+=1440;if(--d==0){if(--m==0){m=12;y=(y+99)%100;}d=month_days(y,m);}}
    if(t>=1440){t-=1440;if(++d>month_days(y,m)){d=1;if(++m==13){m=1;y=(y+1)%100;}}}
    memcpy(out,"20",2);number2(out+2,y);number2(out+4,m);number2(out+6,d);
    number2(out+8,t/60);number2(out+10,t%60);number2(out+12,sec);out[14]=0;return 1;
}
static char *tag(char *p,const char *name,const char *v,unsigned n){
    if(!n)return p;
    *p++='<';p=copy(p,name);*p++=':';p=digits(p,n);*p++='>';memcpy(p,v,n);p+=n;*p++=' ';return p;
}
static LOG_FN void format_contact(char *dst,const struct Contact *q){
    char *p=dst, mhz[14],*f=digits(mhz,q->freq/1000000);*f++='.';
    unsigned v=q->freq%1000000;for(int i=5;i>=0;i--){f[i]='0'+v%10;v/=10;}f[6]=0;
#define FIELD(name,value) p=tag(p,name,value,strlen(value))
    FIELD("CALL",q->dx);FIELD("STATION_CALLSIGN",q->own);
    FIELD("BAND",bands[q->band]);FIELD("MODE",q->mode?"MFSK":"FT8");
    if(q->mode){FIELD("SUBMODE","FT4");}
    p=tag(p,"QSO_DATE",q->on,8);p=tag(p,"TIME_ON",q->on+8,6);
    p=tag(p,"QSO_DATE_OFF",q->off,8);p=tag(p,"TIME_OFF",q->off+8,6);
    FIELD("FREQ",mhz);FIELD("RST_SENT",q->sent);FIELD("RST_RCVD",q->rcvd);
    FIELD("MY_GRIDSQUARE",q->mygrid);FIELD("GRIDSQUARE",q->grid);
#undef FIELD
    memset(p,' ',dst+LOG_BYTES-7-p);memcpy(dst+LOG_BYTES-7,"<EOR>\r\n",7);dst[LOG_BYTES]=0;
}
static LOG_FN int field_get(const char *record,const char *name,char *out,unsigned cap){
    const char *p=strstr(record,name);out[0]=0;if(!p)return 0;
    p+=strlen(name);unsigned n=0;
    while(*p>='0'&&*p<='9'){n=n*10+*p++-'0';if(n>=cap)return 0;}
    if(*p++!='>'||p+n>record+LOG_BYTES)return 0;
    memcpy(out,p,n);out[n]=0;return 1;
}
static int read_at(int fd,unsigned pos,char *dest,unsigned bytes){
    unsigned n;return !l_seek(fd,pos,0,&n)&&n==pos&&!l_read(fd,dest,bytes,&n)&&n==bytes;
}
/* This task owns the file handle. The UI snapshots queries before launch,
   then consumes the published result on its next input tick. */
static LOG_FN void log_worker(void){
    struct Journal *j=&journal;
    const unsigned header=sizeof(log_header)-1;
    unsigned size=0,n=0,tail,total=0;
    int fd=-1,ok=1;
    int rc=l_open(log_path,j->saved?0x202:0,&fd);
    if(rc){ok=!j->saved && (rc==7||rc==2);goto done;}
    ok=!l_seek(fd,0,2,&size);
    if(ok && size<header && j->saved){
        if(size)ok=read_at(fd,0,j->line,size)&&!memcmp(j->line,log_header,size);
        if(ok)ok=!l_seek(fd,0,0,&n)&&!l_write(fd,log_header,header,&n)&&n==header;
        size=header;
    }
    if(!ok || size<header || !read_at(fd,0,j->line,header)||memcmp(j->line,log_header,header)){ok=0;goto close;}
    total=(size-header)/LOG_BYTES;tail=(size-header)%LOG_BYTES;
    if(total && (!read_at(fd,header+total*LOG_BYTES-7,j->line,7)||memcmp(j->line,"<EOR>\r\n",7))){ok=0;goto close;}
    if(j->saved){
        char record[LOG_BYTES+1];format_contact(record,&j->pending[j->head]);
        int exists=total && read_at(fd,header+(total-1)*LOG_BYTES,j->line,LOG_BYTES) && !memcmp(j->line,record,LOG_BYTES);
        if(!exists){
            unsigned pos=header+total*LOG_BYTES;
            if(tail && (!read_at(fd,pos,j->line,tail)||memcmp(j->line,record,tail))){
                /* Recover only an interrupted record in our identified fixed-record file. */
                if(!read_at(fd,pos,j->line,tail)||memcmp(j->line,"<CALL:",tail<6?tail:6)){ok=0;goto close;}
            }
            ok=!l_seek(fd,pos,0,&n)&&n==pos&&!l_write(fd,record,LOG_BYTES,&n)&&n==LOG_BYTES;
            if(!ok)goto close;
            ++total;
        }
    }
    if(j->load_view && total){
        unsigned back=j->offset<total?j->offset:total-1;
        ok=read_at(fd,header+(total-1-back)*LOG_BYTES,j->detail,LOG_BYTES);j->detail[LOG_BYTES]=0;
    }else if(j->load_view)j->detail[0]=0;
    if(j->nquery){
        for(unsigned i=total;ok && i>0;i--){
            char local[8],remote[8],band[8],mode[8];
            ok=read_at(fd,header+(i-1)*LOG_BYTES,j->line,LOG_BYTES);
            j->line[LOG_BYTES]=0;
            if(!ok || !field_get(j->line,"<STATION_CALLSIGN:",local,8)||strcmp(local,j->operator)||
               !field_get(j->line,"<BAND:",band,8)||strcmp(band,bands[j->band])||
               !field_get(j->line,j->mode?"<SUBMODE:":"<MODE:",mode,8)||strcmp(mode,j->mode?"FT4":"FT8")||
               !field_get(j->line,"<CALL:",remote,8))continue;
            for(unsigned k=0;k<j->nquery;k++)if(!strcmp(j->query[k].call,remote))j->query[k].worked=1;
        }
    }
close:
    if(l_close(fd))ok=0;
done:
    j->total=total;j->error=!ok;atomic_store(&j->io,2);
}
static void reset_query(void){journal.epoch++;memset(journal.cache,0,sizeof(journal.cache));}
static LOG_FN void log_poll(void){
    struct Journal *j=&journal;
    unsigned state=atomic_load(&j->io);
    if(state==1)return;
    if(state==2){
        if(!j->error){
            if(j->saved){if(outcome==LOG_PENDING && receipt_index==j->head)outcome=LOG_SAVED;j->head=(j->head+1)%LOG_QUEUE;j->count--;reset_query();}
            if(j->epoch==j->job_epoch)for(unsigned i=0;i<j->nquery;i++)
                for(unsigned k=0;k<LOG_CACHE;k++)if(!strcmp(j->query[i].call,j->cache[k].call))
                    j->cache[k].worked=j->query[i].worked?1:-1;
            if(j->load_view)j->reset=0;
        }
        atomic_store(&j->io,0);view_invalidate();
    }
    unsigned card=U8(0x20380172)==3;
    unsigned band=log_band(U32(0x20380714));
    if(j->was_card!=card||j->mode!=ftx_ft4||j->band!=band||strcmp(j->operator,pref.call)){
        j->was_card=card;j->mode=ftx_ft4;j->band=band;copy(j->operator,pref.call);
        j->reset=1;j->detail[0]=0;reset_query();
    }
    if(!card || (int)(NOW-j->next_poll)<0)return;
    j->saved=j->count!=0;j->nquery=0;j->load_view=j->reset && ft_page==FT_LOG;
    for(unsigned i=0;i<LOG_CACHE;i++)if(j->cache[i].call[0]&&!j->cache[i].worked)
        j->query[j->nquery++]=j->cache[i];
    if(!j->saved&&!j->nquery&&!j->load_view)return;
    j->job_epoch=j->epoch;j->next_poll=NOW+(j->error?3000:200);
    static const uintptr_t task[]={(uintptr_t)log_worker,0xe9,1,2048};
    atomic_store(&j->io,1);
    if(!((unsigned (*)(const uintptr_t *,unsigned))0x202d48c1)(task,0)){j->error=1;atomic_store(&j->io,0);}
}
LOG_FN int ft_worked(const char *sender){
    if(!pref.call[0])return 0;
    char dx[7];unsigned n=strcspn(sender," ");if(n<3||n>6)return 0;memcpy(dx,sender,n);dx[n]=0;
    unsigned band=log_band(U32(0x20380714));
    for(unsigned i=0;i<journal.count;i++){
        const struct Contact *q=&journal.pending[(journal.head+i)%LOG_QUEUE];
        if(q->band==band && q->mode==ftx_ft4 && !strcmp(q->own,pref.call)&&!strcmp(q->dx,dx))return 1;
    }
    if(U8(0x20380172)!=3)return 0;
    if(journal.band!=band||journal.mode!=ftx_ft4||strcmp(journal.operator,pref.call))return -1;
    for(unsigned i=0;i<LOG_CACHE;i++){
        struct Query *q=&journal.cache[i];
        if(!strcmp(q->call,dx))return q->worked ? q->worked>0 : -1;
    }
    struct Query *q=&journal.cache[journal.cache_next++%LOG_CACHE];copy(q->call,dx);q->worked=0;
    return -1;
}
static LOG_FN int log_touch(unsigned x,unsigned y){
    if(x<399||atomic_load(&journal.io)==1)return 0;
    if(y>=89&&y<122&&journal.offset+1<journal.total)journal.offset++;
    else if(y>=125&&y<158&&journal.offset)journal.offset--;
    else if(y>=197&&y<230){journal.next_poll=NOW;}
    else return 0;
    journal.reset=1;return 1;
}
static LOG_FN void log_draw(void){
    ft_label(Z_log,4,87,14,15);
    char s[24];
    if(atomic_load(&journal.io)!=1 && journal.detail[0]){
        static const char *const fields[]={"<CALL:","<QSO_DATE:","<TIME_ON:","<BAND:","<MODE:","<RST_SENT:","<RST_RCVD:"};
        for(unsigned i=0;i<7;i++){
            field_get(journal.detail,i==4 && strstr(journal.detail,"<SUBMODE:")?"<SUBMODE:":fields[i],s,sizeof(s));
            ft_label(s,8+(i%3)*111,122+(i/3)*31,14,15);
        }
    }else ft_label(journal.count?Z_pending:Z_empty,8,125,14,15);
    if(journal.offset+1<journal.total)ft_key(Z_older,399,89,77,33);
    if(journal.offset)ft_key(Z_newer,399,125,77,33);
    if(journal.count||journal.error)ft_key(Z_again,399,197,77,33);
}
