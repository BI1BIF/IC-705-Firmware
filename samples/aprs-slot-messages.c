/* Numbered messages retain their ID on every retry. ACK packets never request an ACK. */
#include "aprs-j140-popup.h"
#define NOW (*(volatile uint32_t *)0x20381e08)
extern volatile uint32_t aprs_channel_hz;
extern void *memcpy(void *,const void *,__SIZE_TYPE__);
enum { CAPACITY=4, MAX_SENDS=5, RETRY_MS=30000, ACK_TAG=5 };
struct sent_message aprs_outbox[CAPACITY] APRS_KEEP;
unsigned aprs_sent_count APRS_KEEP;
static unsigned serial APRS_KEEP;
struct ack_request {
    char station[10],id[6];
    uint8_t ssid;
    uint32_t hz,received;
};
static struct ack_request ack[CAPACITY];
static unsigned ack_cursor;
static char *append(char *dest,const char *source)
{
    while (*source) *dest++=*source++;
    *dest=0;
    return dest;
}
static int same(const char *a,const char *b)
{
    while (*a && *a==*b) { ++a;++b; }
    return *a==*b;
}
int aprs_valid_recipient(const char *s)
{
    unsigned n=0,letters=0,digits=0;
    while (s[n] && s[n]!='-') {
        if (s[n]>='A' && s[n]<='Z') ++letters;
        else if (s[n]>='0' && s[n]<='9') ++digits;
        else return 0;
        if (++n>6) return 0;
    }
    if (!letters && !digits) return 0;
    if (!s[n]) return 1;
    s+=n+1;
    if (*s<'1' || *s>'9') return 0;
    return !s[1] || (*s=='1' && s[1]>='0' && s[1]<='5' && !s[2]);
}
static void addressee(char *buf,const char *name)
{
    buf[0]=':';
    for (unsigned i=1;i<=9;++i) buf[i]=*name ? *name++ : ' ';
    buf[10]=':';
}
static const char *send_slot(unsigned slot)
{
    struct sent_message *m=&aprs_outbox[slot];
    char info[11+67+1+3+1];
    addressee(info,m->station);
    char *end=append(info+11,m->text);
    *end++='{';append(end,m->id);
    return aprs_start_message(info,slot+1);
}
const char *aprs_send_reply(const char *name,const char *body)
{
    if (!aprs_valid_recipient(name)) return "Check recipient";
    unsigned n=0;
    for (;body[n];++n) {
        unsigned c=(uint8_t)body[n];
        if (n>=67 || c<32 || c>126 || c=='{' || c=='}' || c=='~' || c=='|')
            return "Check message text";
    }
    if (!n) return "Enter message text";
    if (aprs_message_active()) return "Radio TX busy";
    unsigned slot=aprs_sent_count%CAPACITY;
    struct sent_message *m=&aprs_outbox[slot];
    if (m->state==MSG_WAIT || m->state==MSG_QUEUED) return "Outbox full";
    struct sent_message previous=*m;
    unsigned id=(serial+1)%1000;
    append(m->station,name);append(m->text,body);
    m->id[0]='0'+id/100;m->id[1]='0'+id/10%10;m->id[2]='0'+id%10;m->id[3]=0;
    m->ssid=aprs_beacon_ssid;m->hz=aprs_channel_hz;
    m->attempts=0;m->state=MSG_QUEUED;m->created=NOW;m->due=NOW+RETRY_MS;
    const char *error=send_slot(slot);
    if (error) { *m=previous;return error; }
    ++aprs_sent_count;serial=id;
    aprs_cancel_answer(name);
    return 0;
}
void aprs_message_finished(unsigned tag)
{
    if (tag>=ACK_TAG && tag<ACK_TAG+CAPACITY) {
        ack[tag-ACK_TAG].hz=0;return;
    }
    if (!tag || tag>CAPACITY) return;
    struct sent_message *m=&aprs_outbox[tag-1];
    if (m->state==MSG_QUEUED || m->state==MSG_WAIT) {
        ++m->attempts;m->due=NOW+RETRY_MS;m->state=MSG_WAIT;
    }
}
void aprs_message_cancel(unsigned slot)
{
    struct sent_message *m=&aprs_outbox[slot];
    if (m->state==MSG_QUEUED || m->state==MSG_WAIT) m->state=MSG_CANCEL;
}
int aprs_match_result(const char *name,const char *response)
{
    for (unsigned i=0;i<CAPACITY;++i) {
        struct sent_message *m=&aprs_outbox[i];
        if ((m->state==MSG_WAIT || m->state==MSG_QUEUED) && m->attempts &&
            m->hz==aprs_channel_hz && m->ssid==aprs_beacon_ssid &&
            same(m->station,name) && same(m->id,response+3)) {
            m->state=response[0]=='a' ? MSG_ACK : MSG_REJECT;
            return 1;
        }
    }
    return 0;
}
void aprs_message_ack(const struct popup_packet *p)
{
    if (!aprs_tx_enabled || !aprs_channel_hz || !aprs_plain_fm() ||
        !aprs_valid_recipient(p->station)) return;
    for (unsigned i=0;i<CAPACITY;++i)
        if (ack[i].hz==aprs_channel_hz && same(ack[i].station,p->station) &&
            same(ack[i].id,p->message_id)) return;
    for (unsigned i=0;i<CAPACITY;++i) {
        struct ack_request *a=&ack[(ack_cursor+i)%CAPACITY];
        if (a->hz && (aprs_message_active() || NOW-a->received<30000)) continue;
        append(a->station,p->station);append(a->id,p->message_id);
        a->received=NOW;a->ssid=aprs_beacon_ssid;a->hz=aprs_channel_hz;
        return;
    }
}
uint8_t aprs_answer_on APRS_KEEP,aprs_answer_delay APRS_KEEP=1;
char aprs_answer_text[65] APRS_KEEP,aprs_answer_call[10] APRS_KEEP;
const uint8_t aprs_delays[5]={0,10,20,30,60};
static struct ack_request answer;
static uint32_t answered_at;
static char answered_station[10];
void aprs_cancel_answer(const char *station)
{
    if (same(station,answer.station)) answer.hz=0;
}
void aprs_schedule_answer(const struct popup_packet *p)
{
    if (!aprs_answer_on || !aprs_tx_enabled || !aprs_answer_text[0] ||
        !aprs_valid_recipient(p->station) || same(p->station,p->longitude) ||
        (aprs_answer_call[0] && !same(aprs_answer_call,p->station)) ||
        (p->comment[0]=='A' && p->comment[1]=='A' && p->comment[2]==':') ||
        (same(answered_station,p->station) && NOW-answered_at<60000)) return;
    if (answer.hz && !same(answer.station,p->station) && NOW-answer.received<90000) return;
    append(answer.station,p->station);answer.ssid=aprs_beacon_ssid;
    answer.received=NOW;answer.hz=aprs_channel_hz;
}
void aprs_messages_disarm(void)
{
    answer.hz=0;
    for (unsigned i=0;i<CAPACITY;++i) {
        ack[i].hz=0;aprs_message_cancel(i);
    }
}
void aprs_messages_poll(void)
{
    if (aprs_return_hz || !aprs_tx_enabled || !aprs_plain_fm() || !aprs_channel_hz ||
        *(volatile uint32_t *)0x20380714!=aprs_channel_hz || aprs_message_active()) return;
    uint32_t now=NOW;
    for (unsigned i=0;i<CAPACITY;++i) {
        unsigned slot=(ack_cursor+i)%CAPACITY;
        struct ack_request *a=&ack[slot];
        if (!a->hz) continue;
        if (a->hz!=aprs_channel_hz || a->ssid!=aprs_beacon_ssid || now-a->received>=30000) {
            a->hz=0;continue;
        }
        if (now-a->received<1500) continue;
        char info[20];
        addressee(info,a->station);append(append(info+11,"ack"),a->id);
        if (!aprs_start_message(info,ACK_TAG+slot)) ack_cursor=(slot+1)%CAPACITY;
        return;
    }
    if (answer.hz) {
        unsigned age=now-answer.received;
        if (!aprs_answer_on || answer.ssid!=aprs_beacon_ssid || answer.hz!=aprs_channel_hz ||
            age>90000) answer.hz=0;
        else if (age>=1500+1000u*aprs_delays[aprs_answer_delay] && aprs_answer_text[0]) {
            char body[68];
            append(append(body,"AA:"),aprs_answer_text);
            if (!aprs_send_reply(answer.station,body)) {
                append(answered_station,answer.station);answered_at=now;return;
            }
        }
    }
    for (unsigned i=0;i<CAPACITY;++i) {
        struct sent_message *m=&aprs_outbox[i];
        if (m->state!=MSG_QUEUED && m->state!=MSG_WAIT) continue;
        if (m->ssid!=aprs_beacon_ssid || m->hz!=aprs_channel_hz) { m->state=MSG_CANCEL;continue; }
        if ((int32_t)(now-m->due)<0) continue;
        if (m->attempts>=MAX_SENDS || now-m->created>300000) { m->state=MSG_TIMEOUT;continue; }
        if (aprs_standby_ready() && !send_slot(i)) m->due=now+RETRY_MS;
    }
}
