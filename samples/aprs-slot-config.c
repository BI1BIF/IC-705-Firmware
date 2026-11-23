/* APRS preferences have their own pair of SD records. Do not persist TX queues. */
#include "aprs-j140-popup.h"
struct settings_record {
    uint32_t magic, sequence, frequency;
    uint8_t enabled, ssid, path, automatic, interval, styles[ALERT_COUNT];
    char symbol[2], comment[APRS_BEACON_COMMENT_MAX+1];
    uint8_t edited, answer_on,delay;
    char answer[65],caller[10];
    uint32_t sum;
};
void *memset(void *dest,int value,__SIZE_TYPE__ n)
{
    uint8_t *p=dest;
    while (n--) *p++=value;
    return dest;
}
static uint32_t sequence APRS_KEEP, retry_after APRS_KEEP;
uint8_t aprs_settings_dirty APRS_KEEP;
uint32_t aprs_card_checksum(const void *r,unsigned bytes)
{
    const uint8_t *p=(const uint8_t *)r;
    uint32_t sum=2166136261u;
    for (unsigned i=0;i<bytes;++i)
        sum=(sum^p[i])*16777619u;
    return sum;
}
static int transfer(void *r,unsigned bytes,unsigned bank,int write,int phrases)
{
    char path[]="C:\\IC-705\\APRS0.CFG";
    if (phrases) path[13]='T';
    path[14]='0'+bank;
    int fd;
    if (((int (*)(const char *,unsigned,int *))0x2023fec8)(path,write ? 0x201 : 0,&fd))
        return 0;
    uintptr_t op=write ? 0x2023ff18 : 0x2023ff00;
    unsigned count=0;
    int rc=((int (*)(int,void *,unsigned,unsigned *))op)(fd,r,bytes,&count);
    return !((int (*)(int))0x2023fee4)(fd) && !rc && count==bytes;
}
static int valid(const struct settings_record *r)
{
    if (r->magic!=0x31525041 || r->sum!=aprs_card_checksum(r,__builtin_offsetof(struct settings_record,sum)) || r->enabled>1 ||
        r->ssid>15 || r->path>2 || r->automatic>1 || r->interval>SMART_INTERVAL ||
        r->answer_on>1 || r->delay>=5 || r->answer[64] || r->caller[9] || r->edited>1 || r->comment[APRS_BEACON_COMMENT_MAX]) return 0;
    for (unsigned i=0;i<ALERT_COUNT;++i)
        if (r->styles[i]>SHORT_LONG) return 0;
    return 1;
}
static void settings_fields(struct settings_record *r,int restore)
{
#define FIELD(local,field) do { if (restore) local=r->field; else r->field=local; } while (0)
    FIELD(aprs_beacon_ssid,ssid); FIELD(aprs_tx_path,path);
    FIELD(aprs_auto_beacon,automatic); FIELD(aprs_beacon_interval,interval);
    FIELD(comment_saved,edited); FIELD(aprs_answer_on,answer_on);FIELD(aprs_answer_delay,delay);
    for (unsigned i=0;i<sizeof(r->answer);++i) FIELD(aprs_answer_text[i],answer[i]);
    for (unsigned i=0;i<sizeof(r->caller);++i) FIELD(aprs_answer_call[i],caller[i]);
    for (unsigned i=0;i<sizeof(saved_comment);++i) FIELD(saved_comment[i],comment[i]);
    for (unsigned i=0;i<2;++i) FIELD(saved_symbol[i],symbol[i]);
    for (unsigned i=0;i<ALERT_COUNT;++i) FIELD(aprs_alert_styles[i],styles[i]);
#undef FIELD
}
/* Called by the mode task. 'mount' is true once per ready card; operator changes
   made while the card was away take priority over that card's old settings. */
void aprs_config_poll(uint32_t *hz,unsigned *tx,unsigned mount,unsigned changed)
{
    aprs_history_card_poll(mount);
    if (!mount && !aprs_settings_dirty && !changed) return;
    struct settings_record record={0}, newest;
    if (changed) aprs_settings_dirty=1;
    if (mount) {
        int found=0;
        for (unsigned i=0;i<2;++i)
            if (transfer(&record,sizeof(record),i,0,0) && valid(&record) &&
                (!found || (int32_t)(record.sequence-newest.sequence)>0)) {
                newest=record;found=1;
            }
        sequence=found ? newest.sequence : 0;
        if (found && !aprs_settings_dirty) {
            settings_fields(&newest,1);
            if (!*(volatile uint8_t *)0x203eb172) {
                *hz=newest.frequency;
                *tx=newest.frequency && newest.enabled;
            }
            aprs_beacon_reschedule();
        }
        retry_after=0;
    }
    if (!aprs_settings_dirty) return;
    uint32_t now=*(volatile uint32_t *)0x20381e08;
    if (retry_after && (int32_t)(now-retry_after)<0) return;
    record=(struct settings_record){.magic=0x31525041,.sequence=sequence+1,
                                    .frequency=*hz,.enabled=*tx};
    settings_fields(&record,0);
    record.sum=aprs_card_checksum(&record,__builtin_offsetof(struct settings_record,sum));
    if (transfer(&record,sizeof(record),record.sequence&1,1,0)) {
        sequence=record.sequence;aprs_settings_dirty=0;retry_after=0;
    } else retry_after=now+5000;
}

/* Quick texts are card-resident. Keep the last complete bank on any write error. */
char aprs_phrases[20][33];
static struct phrase_file {
    uint32_t magic,sequence;
    char text[20][33];
    uint32_t sum;
} phrase_work;
static uint32_t phrase_seq;
static int card_ready(void)
{
    uint8_t card=*(volatile uint8_t *)0x20380172;
    return card==3 || card==4;
}
int aprs_phrases_load(void)
{
    if (!card_ready()) return 0;
    int found=0;
    phrase_seq=0;
    memset(aprs_phrases,0,sizeof(aprs_phrases));
    for (unsigned i=0;i<2;++i) {
        if (!transfer(&phrase_work,sizeof(phrase_work),i,0,1) || phrase_work.magic!=0x31545841 ||
            phrase_work.sum!=aprs_card_checksum(&phrase_work,__builtin_offsetof(struct phrase_file,sum)) ||
            (found && (int32_t)(phrase_work.sequence-phrase_seq)<=0)) continue;
        unsigned j=0;
        while (j<20 && !phrase_work.text[j][32]) ++j;
        if (j!=20) continue;
        __builtin_memcpy(aprs_phrases,phrase_work.text,sizeof(aprs_phrases));
        phrase_seq=phrase_work.sequence;found=1;
    }
    return 1;
}
int aprs_phrase_save(unsigned index,const char *text)
{
    if (!aprs_phrases_load()) return 0;
    phrase_work.magic=0x31545841;phrase_work.sequence=phrase_seq+1;
    __builtin_memcpy(phrase_work.text,aprs_phrases,sizeof(aprs_phrases));
    unsigned i=0;
    for (;i<32 && text[i];++i) phrase_work.text[index][i]=text[i];
    phrase_work.text[index][i]=0;
    phrase_work.sum=aprs_card_checksum(&phrase_work,__builtin_offsetof(struct phrase_file,sum));
    if (!transfer(&phrase_work,sizeof(phrase_work),phrase_work.sequence&1,1,1)) return 0;
    __builtin_memcpy(aprs_phrases[index],phrase_work.text[index],33);
    return 1;
}
