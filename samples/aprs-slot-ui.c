/* APRS pages borrow native picker records only while their selector is on screen. */
#include "aprs-j140-popup.h"
#ifdef APRS_SLOT_UI
#pragma GCC optimize ("Os")
#define U8(a) (*(volatile uint8_t *)(a))
#define U16(a) (*(volatile uint16_t *)(a))
enum { QUICK=1, FIRST=170, HISTORY=FIRST, SETTINGS=FIRST+1, CHILD=FIRST+2,
       OTHER_SETTINGS=CHILD+16, LAST=OTHER_SETTINGS };
enum page { ROOT, EVENTS, STYLE, SSID, REVIEW, NOTICE, PATH, AUTOMATIC, INTERVAL, GROUP, ICON, OVERLAY_ICON, MESSAGES, OUTBOX, SENT_DETAIL, MSG_TOOLS, PHRASE_BANK, PHRASES, ANSWER, ANSWER_ENABLE, ANSWER_DELAY, INBOX_ACTION, STATIONS, STATION_FILTER, FUNCTION_MODE };
static void (*set_function_mode)(unsigned);
extern volatile uint32_t aprs_channel_hz;
typedef struct { uint32_t w[18]; } row;
static row *const menu=(row *)APRS_NATIVE_MENU;
extern void aprs_native_open(unsigned, unsigned);
extern uint8_t aprs_history_last, aprs_history_choice, aprs_history_detail, aprs_popup_owned, aprs_tx_enabled;
extern uint8_t aprs_beacon_ssid;
extern unsigned aprs_history_initial(void),aprs_history_select(void);
extern void aprs_history_open(void);
extern const char *aprs_beacon_start(void);
static row saved[LAST-FIRST+1], quick_saved;
static uint16_t ids[94];
static unsigned leased, quick, pending, editing, accepted, held, from_history;
static unsigned page, choice, event, root_row;
static unsigned settings_id=OTHER_SETTINGS;
static const char *const ssids[]={"0","1","2","3","4","5","6","7","8","9","10","11","12","13","14","15"};
static char root_labels[4][32], out_labels[4][32];
static unsigned group,base_icon,out_index,compose_new,notice_parent;
enum editor { BODY=1, CALL, COMMENT, PHRASE_EDIT, ANSWER_TEXT, ANSWER_CALL };
static unsigned phrase_group,phrase_slot,phrase_use,review_send,editing_review;
static const char *const delays[]={"0 s","10 s","20 s","30 s","60 s"};
static char phrase_labels[10][6];
static const char *const paths[]={"Direct","WIDE2-1","WIDE1-1,WIDE2-1"};
static const char *const times[]={"1 min","3 min","5 min","10 min","30 min","SmartBeaconing"};
static const char *const enabled[]={"OFF","ON"};
static const char *const groups[]={"Primary Symbols","Alternate Symbols","Overlay Symbols"};
static const char *const states[]={"Empty","Queued","Awaiting ACK","Delivered","Rejected","Timed out","Canceled"};
static void edit(unsigned field);
static char recipient[10], recipient_label[14], draft[68], preview[3][25];
static const char *notice;
static const char *const events[]={"Position Beacon","Weather","My Beacon Relayed","Message to Me","Message ACK / REJ","Status","Other Packets"};
static const char *const styles[]={"List Only","Silent Popup","Short Tone","Double Short","Short + Long"};

static void copy_text(char *dest,const char *source,unsigned size)
{
    while (--size && *source)
        *dest++=*source++;
    *dest=0;
}

void aprs_ui_restore(void)
{
    if (!leased)
        return;
    for (unsigned i=FIRST;i<=LAST;++i)
        menu[i]=saved[i-FIRST];
    if (quick)
        menu[QUICK]=quick_saved;
    leased=quick=0;
}

static void borrow(void)
{
    aprs_ui_restore();
    for (unsigned i=FIRST;i<=LAST;++i)
        saved[i-FIRST]=menu[i];
    leased=1;
}

void aprs_ui_deferred(unsigned on) { pending=on; }

extern unsigned aprs_stations_active(void),aprs_station_filter;
extern void aprs_stations_open(unsigned sort);
static const char *const filters[]={"All","With Distance","Weather","Objects / Items"};
static unsigned selected(void);
static unsigned initial(void)
{
    if (page==FUNCTION_MODE) return aprs_channel_hz ? 1+aprs_tx_enabled : 0;
    if (page==ROOT)
        return root_row;
    if (page==STATION_FILTER) return aprs_station_filter;
    if (page==SSID)
        return aprs_beacon_ssid;
    if (page==AUTOMATIC) return aprs_auto_beacon;
    if (page==INTERVAL) return aprs_beacon_interval;
    if (page==PATH) return aprs_tx_path;
    if (page==ANSWER_ENABLE) return aprs_answer_on;
    if (page==ANSWER_DELAY) return aprs_answer_delay;
    if (page==ICON || page==OVERLAY_ICON) {
        const char *symbol=aprs_beacon_symbol();
        unsigned icon=((uint8_t)symbol[0]<<8)|(uint8_t)symbol[1];
        for (unsigned i=0;i<=((uint8_t *)&menu[settings_id])[1];++i)
            if (aprs_catalog_icon(i)==icon) return i;
    }
    if (page==EVENTS)
        return event;
    if (page==STYLE)
        return aprs_alert_styles[event];
    return 0;
}

static unsigned always_visible(unsigned index)
{
    (void)index;
    return 0;
}

static void set_child(unsigned id,const char *title, unsigned (*action)(unsigned *))
{
    menu[id]=menu[93];
    menu[id].w[2]=(uintptr_t)action;
    menu[id].w[13]=menu[id].w[15]=(uintptr_t)title;
}

static void picker(unsigned id,const char *title,unsigned count)
{
    row *r=&menu[id];
    *r=menu[12];
    ((uint8_t *)r)[1]=count-1;
    r->w[7]|=1;
    r->w[1]=(uintptr_t)(id==HISTORY ? aprs_history_initial : initial);
    r->w[3]=(uintptr_t)(id==HISTORY ? aprs_history_select : selected);
    r->w[5]=(uintptr_t)always_visible;
    r->w[6]=0;
    r->w[8]=id==HISTORY ? (uintptr_t)&aprs_history_choice : (uintptr_t)&choice;
    r->w[9]=0;
    r->w[12]=r->w[14]=(uintptr_t)title;
    r->w[17]=(uintptr_t)ids;
    U16(0x203e1b1a)=0x0202;
    aprs_native_open(id,0xffff);
}

void aprs_slot_history_open(void)
{
    borrow();
    set_child(CHILD,"",0);
    for (unsigned i=0;i<64;++i)
        ids[i]=CHILD;
    extern unsigned aprs_inbox_active(void);
    picker(HISTORY,aprs_inbox_active() ? "Inbox" : aprs_stations_active() ? "APRS Stations" : "APRS RX List",aprs_history_last+1);
}

unsigned aprs_symbol_page(void)
{
    return leased && U16(0x203e1a28)==settings_id && (page==ICON || page==OVERLAY_ICON);
}
static char *joined(char *buf,const char *first,const char *second)
{
    char *end=buf;
    while (*first && end-buf<29) *end++=*first++;
    *end++=' ';*end++=' ';
    copy_text(end,second,32-(end-buf));
    return buf;
}
static void show(unsigned next)
{
    const char *items[16], *title;
    unsigned count;
    borrow();
    /* The stock differential renderer identifies a picker by its numeric ID. */
    settings_id=settings_id==SETTINGS ? OTHER_SETTINGS : SETTINGS;
    page=next;
    if (page==FUNCTION_MODE) {
        title="APRS Mode"; items[0]="OFF"; items[1]="RX Only"; items[2]="RX & TX"; count=3;
    } else if (page==ROOT) {
        title="APRS";
        items[0]="RX Alert";
        items[1]=joined(root_labels[0],"Beacon SSID",ssids[aprs_beacon_ssid]);
        items[2]=joined(root_labels[1],"Auto Beacon",enabled[aprs_auto_beacon]);
        items[3]=joined(root_labels[2],"Beacon Interval",
                        aprs_beacon_interval==SMART_INTERVAL ? "Smart" : times[aprs_beacon_interval]);
        items[4]=joined(root_labels[3],"TX Path",paths[aprs_tx_path]);
        items[5]="Beacon Symbol";items[6]="Beacon Comment";
        count=7;
    } else if (page==AUTOMATIC || page==INTERVAL || page==PATH || page==GROUP) {
        const char *const *labels;
        if (page==AUTOMATIC) { title="Auto Beacon";labels=enabled;count=2; }
        else if (page==INTERVAL) { title="Beacon Interval";labels=times;count=sizeof(times)/sizeof(*times); }
        else if (page==PATH) { title="TX Path";labels=paths;count=3; }
        else { title="Beacon Symbol";labels=groups;count=3; }
        for (unsigned i=0;i<count;++i) items[i]=labels[i];
    } else if (page==ICON || page==OVERLAY_ICON) {
        count=aprs_catalog(group,page==OVERLAY_ICON,base_icon);
        set_child(CHILD,"Symbol",0);
        for (unsigned i=0;i<count;++i) ids[i]=CHILD;
        picker(settings_id,page==OVERLAY_ICON ? "Overlay" : groups[group],count);
        return;
    } else if (page==STATIONS) {
        title="APRS Stations";count=4;items[0]="Last Heard";items[1]="Callsign";items[2]="Distance";
        items[3]=joined(root_labels[0],"Filter",filters[aprs_station_filter]);
    } else if (page==STATION_FILTER) {
        title="Station Filter";count=4;
        for (unsigned i=0;i<count;++i) items[i]=filters[i];
    } else if (page==MESSAGES) {
        title="APRS Messages";count=0;
        if (aprs_tx_enabled) items[count++]="New Message";
        items[count++]="Inbox";items[count++]="Outbox";items[count++]="Message Tools";
    } else if (page==MSG_TOOLS) {
        title="Message Tools";items[0]="Edit Quick Text";items[1]="Auto Reply";count=2;
        if (aprs_tx_enabled) items[count++]="New from Quick Text";
    } else if (page==ANSWER) {
        title="Auto Reply";items[0]=joined(root_labels[0],"Auto Reply",enabled[aprs_answer_on]);
        items[1]="Reply Text";items[2]=joined(root_labels[1],"Reply To",aprs_answer_call[0] ? aprs_answer_call : "All");
        items[3]=joined(root_labels[2],"Delay",delays[aprs_answer_delay]);count=4;
    } else if (page==ANSWER_ENABLE || page==ANSWER_DELAY) {
        title=page==ANSWER_ENABLE ? "Auto Reply" : "Reply Delay";
        count=page==ANSWER_ENABLE ? 2 : 5;
        for (unsigned i=0;i<count;++i) items[i]=page==ANSWER_ENABLE ? enabled[i] : delays[i];
    } else if (page==PHRASE_BANK) {
        title="Quick Text";count=2;items[0]="1 - 10";items[1]="11 - 20";
    } else if (page==PHRASES) {
        title="Quick Text";count=10;
        for (unsigned i=0;i<count;++i) {
            unsigned n=phrase_group*10+i+1;
            char *label=phrase_labels[i];label[0]='#';label[1]='0'+n/10;label[2]='0'+n%10;label[3]=0;
            items[i]=aprs_phrases[n-1][0] ? aprs_phrases[n-1] : label;
        }
    } else if (page==INBOX_ACTION) {
        title="Inbox";count=2;items[0]="Read";items[1]="Mark Unread";
    } else if (page==OUTBOX) {
        title="Outbox";count=aprs_sent_count<4 ? aprs_sent_count : 4;
        for (unsigned i=0;i<count;++i) {
            struct sent_message *m=&aprs_outbox[(aprs_sent_count-1-i)%4];
            items[i]=joined(out_labels[i],m->station,states[m->state]);
        }
        if (!count) { items[0]="Empty";count=1; }
    } else if (page==SENT_DETAIL) {
        struct sent_message *m=&aprs_outbox[out_index];
        title=m->station;items[0]=states[m->state];items[1]=m->id;
        count=2;
        for (unsigned offset=0;m->text[offset] && count<5;) {
            copy_text(preview[count-2],m->text+offset,sizeof(preview[0]));
            items[count]=preview[count-2];
            for (unsigned i=0;items[count][i];++i) ++offset;
            ++count;
        }
        if (m->state==MSG_QUEUED || m->state==MSG_WAIT) items[count++]="Cancel retries";
        else if (aprs_tx_enabled) items[count++]="Re-send";
    } else if (page==SSID) {
        title="Beacon SSID";
        count=16;
        for (unsigned i=0;i<count;++i)
            items[i]=ssids[i];
    } else if (page==EVENTS || page==STYLE) {
        title=page==EVENTS ? "RX Alert" : events[event];
        count=page==EVENTS ? ALERT_COUNT : SHORT_LONG+1;
        for (unsigned i=0;i<count;++i)
            items[i]=page==EVENTS ? events[i] : styles[i];
    } else if (page==REVIEW) {
        title=compose_new ? "APRS Message" : "APRS Reply";
        copy_text(recipient_label,"To  ",sizeof(recipient_label));
        copy_text(recipient_label+4,recipient,sizeof(recipient));
        items[0]=recipient_label;
        count=1;
        for (unsigned offset=0;draft[offset] && count<=3;) {
            copy_text(preview[count-1],draft+offset,sizeof(preview[0]));
            items[count]=preview[count-1];
            for (unsigned i=0;preview[count-1][i];++i)
                ++offset;
            ++count;
        }
        review_send=count;items[count++]="Send";items[count++]="Edit";items[count++]="Use Quick Text";
    } else {
        title="APRS";items[0]=notice;count=1;
    }
    for (unsigned i=0;i<count;++i) {
        ids[i]=CHILD+i;
        set_child(ids[i],items[i],0);
    }
    picker(settings_id,title,count);
}

void aprs_function_picker(void (*set_mode)(unsigned))
{
    set_function_mode=set_mode;
    show(FUNCTION_MODE);
}

void aprs_slot_settings(void)
{
    root_row=event=0;
    show(ROOT);
}

static void back_to_rx(void)
{
    ((void (*)(void))0x200cd828)();
    aprs_ui_restore();
    if (from_history)
        aprs_history_resume();
    from_history=0;
}

static void phrases(unsigned use)
{
    phrase_use=use;
    if (aprs_phrases_load()) show(PHRASE_BANK);
    else { notice="Insert SD card";notice_parent=use==1 ? REVIEW : MSG_TOOLS;show(NOTICE); }
}
extern void aprs_inbox_mark(unsigned unread);
extern void aprs_inbox_read(void);
void aprs_inbox_actions(void) { pending=0;show(INBOX_ACTION); }
static void apply(void)
{
    pending=0;
    if (page==FUNCTION_MODE) {
        set_function_mode(choice);
        ((void (*)(void))0x200cd828)();
    } else if (page==ROOT) {
        root_row=choice;
        static const uint8_t children[]={EVENTS,SSID,AUTOMATIC,INTERVAL,PATH,GROUP};
        if (choice<6) show(children[choice]);
        else edit(COMMENT);
    } else if (page==SSID && choice<16) {
        aprs_beacon_ssid=choice;aprs_settings_dirty=1;
        show(ROOT);
    } else if (page==EVENTS && choice<ALERT_COUNT) {
        event=choice;
        show(STYLE);
    } else if (page==STYLE && choice<=SHORT_LONG) {
        aprs_alert_styles[event]=choice;aprs_settings_dirty=1;
        aprs_alert_sound(choice);
        show(EVENTS);
    } else if (page==AUTOMATIC || page==INTERVAL || page==PATH) {
        if (page==AUTOMATIC) aprs_auto_beacon=choice;
        else if (page==INTERVAL) aprs_beacon_interval=choice;
        else aprs_tx_path=choice;
        aprs_settings_dirty=1;aprs_beacon_reschedule();show(ROOT);
    } else if (page==GROUP) {
        group=choice;show(ICON);
    } else if (page==ICON || page==OVERLAY_ICON) {
        unsigned icon=aprs_catalog_icon(choice);
        if (page==ICON && group==2) { base_icon=icon&255;show(OVERLAY_ICON); }
        else { saved_symbol[0]=icon>>8;saved_symbol[1]=icon;aprs_settings_dirty=1;show(ROOT); }
    } else if (page==STATIONS) {
        if (choice==3) show(STATION_FILTER);else aprs_stations_open(choice);
    } else if (page==STATION_FILTER) {
        aprs_station_filter=choice;show(STATIONS);
    } else if (page==MESSAGES) {
        if (aprs_tx_enabled && choice==0) {
            compose_new=1;from_history=editing_review=0;recipient[0]=draft[0]=0;edit(CALL);
        } else if (choice==(unsigned)aprs_tx_enabled) {
            extern void aprs_inbox_open(void);
            aprs_inbox_open();
        } else if (choice==1u+aprs_tx_enabled) show(OUTBOX);
        else show(MSG_TOOLS);
    } else if (page==MSG_TOOLS) {
        if (choice==1) show(ANSWER);
        else phrases(choice==2 ? 2 : 0);
    } else if (page==ANSWER) {
        if (choice==0) show(ANSWER_ENABLE);
        else if (choice==3) show(ANSWER_DELAY);
        else edit(choice==1 ? ANSWER_TEXT : ANSWER_CALL);
    } else if (page==ANSWER_ENABLE || page==ANSWER_DELAY) {
        if (page==ANSWER_ENABLE) {
            if (choice && !aprs_answer_text[0]) {
                notice="Set Reply Text first";notice_parent=ANSWER;show(NOTICE);return;
            }
            aprs_answer_on=choice;
        } else aprs_answer_delay=choice;
        aprs_settings_dirty=1;show(ANSWER);
    } else if (page==PHRASE_BANK) {
        phrase_group=choice;show(PHRASES);
    } else if (page==PHRASES) {
        phrase_slot=phrase_group*10+choice;
        if (!phrase_use) edit(PHRASE_EDIT);
        else if (aprs_phrases[phrase_slot][0]) {
            copy_text(draft,aprs_phrases[phrase_slot],sizeof(draft));
            if (phrase_use==1) show(REVIEW);
            else { recipient[0]=0;compose_new=1;from_history=0;editing_review=1;edit(CALL); }
        }
    } else if (page==INBOX_ACTION) {
        if (choice==0) {
            page=ROOT;((void (*)(void))0x200cd828)();aprs_inbox_read();
        }
        else { aprs_inbox_mark(1);aprs_history_resume(); }

    } else if (page==OUTBOX && aprs_sent_count) {
        out_index=(aprs_sent_count-1-choice)%4;show(SENT_DETAIL);
    } else if (page==SENT_DETAIL) {
        struct sent_message *m=&aprs_outbox[out_index];
        if (choice!=((uint8_t *)&menu[settings_id])[1]) return;
        if (m->state==MSG_WAIT || m->state==MSG_QUEUED) { aprs_message_cancel(out_index);show(OUTBOX); }
        else if (aprs_tx_enabled) {
            copy_text(recipient,m->station,sizeof(recipient));copy_text(draft,m->text,sizeof(draft));
            compose_new=1;show(REVIEW);
        }
    } else if (page==REVIEW) {
        if (choice==review_send+1) { editing_review=1;edit(BODY);return; }
        if (choice==review_send+2) { phrases(1);return; }
        notice_parent=compose_new ? OUTBOX : 0;
        const char *error=aprs_send_reply(recipient,draft);
        notice=error ? error : compose_new ? "Message queued" : "Reply queued";
        if (error) notice_parent=REVIEW;
        show(NOTICE);
    }
}

static unsigned selected(void)
{
    if (page==NOTICE || (page==REVIEW && choice<review_send))
        return 0;
    pending=1;
    ((void (*)(void (*)(void)))0x200cd7dc)(apply);
    return 1;
}

unsigned aprs_ui_back(void)
{
    extern unsigned aprs_inbox_active(void);
    if (pending) return 0;
    if (leased && U16(0x203e1a28)==HISTORY && aprs_stations_active()) { show(STATIONS);return 1; }
    if (leased && U16(0x203e1a28)==HISTORY && aprs_inbox_active()) { show(MESSAGES);return 1; }
    if (!leased || U16(0x203e1a28)!=settings_id)
        return 0;
    if (page==EVENTS || page==SSID || page==AUTOMATIC || page==INTERVAL || page==PATH || page==GROUP)
        show(ROOT);
    else if (page==STATION_FILTER) show(STATIONS);
    else if (page==ICON) show(GROUP);
    else if (page==OVERLAY_ICON) show(ICON);
    else if (page==OUTBOX || page==MSG_TOOLS) show(MESSAGES);
    else if (page==ANSWER) show(MSG_TOOLS);
    else if (page==ANSWER_ENABLE || page==ANSWER_DELAY) show(ANSWER);
    else if (page==PHRASE_BANK) show(phrase_use==1 ? REVIEW : MSG_TOOLS);
    else if (page==PHRASES) show(PHRASE_BANK);
    else if (page==INBOX_ACTION) aprs_history_resume();
    else if (page==SENT_DETAIL) show(OUTBOX);
    else if (page==STYLE) show(EVENTS);
    else if (page==NOTICE && notice_parent) show(notice_parent);
    else if (page==REVIEW && compose_new) show(MESSAGES);
    else if (page==NOTICE || page==REVIEW) {
        page=ROOT;
        back_to_rx();
    } else
        return 0;
    return 1;
}

static unsigned save_reply(const char *text,uint8_t *action)
{
    if (editing==COMMENT) {
        unsigned result=aprs_save_comment(text,action);
        if (result) aprs_settings_dirty=1;
        return result;
    }
    unsigned n=0;
    unsigned max=editing==CALL || editing==ANSWER_CALL ? 9 : editing==ANSWER_TEXT ? 64 :
                 editing==PHRASE_EDIT ? 32 : 67;
    while (n<max && text[n]) ++n;
    while (n && text[n-1]==' ') --n;
    if (editing==CALL || editing==ANSWER_CALL) {
        char name[10];
        for (unsigned i=0;i<n;++i) name[i]=text[i]>='a' && text[i]<='z' ? text[i]-32 : text[i];
        name[n]=0;
        if (!(editing==ANSWER_CALL && !n) && !aprs_valid_recipient(name)) { *action=0;return 0; }
        copy_text(editing==CALL ? recipient : aprs_answer_call,name,10);
        if (editing==ANSWER_CALL) aprs_settings_dirty=1;
    } else {
        if (!n && editing!=PHRASE_EDIT) { *action=0;return 0; }
        char value[68];
        for (unsigned i=0;i<n;++i) {
            unsigned c=(uint8_t)text[i];
            if (c<32 || c>126 || c=='{' || c=='}' || c=='~' || c=='|') { *action=0;return 0; }
            value[i]=c;
        }
        value[n]=0;
        if (editing==PHRASE_EDIT) {
            if (!aprs_phrase_save(phrase_slot,value)) { accepted=2;*action=4;return 1; }
        } else if (editing==ANSWER_TEXT) {
            copy_text(aprs_answer_text,value,sizeof(aprs_answer_text));aprs_settings_dirty=1;
        } else copy_text(draft,value,sizeof(draft));
    }
    accepted=1;
    *action=4;
    return 1;
}

unsigned aprs_ui_keyboard(void)
{
    if (!editing)
        return 0;
    char text[67];
    unsigned length=editing==CALL || editing==ANSWER_CALL ? 9 : editing==COMMENT ? APRS_BEACON_COMMENT_MAX :
                    editing==ANSWER_TEXT ? 64 : editing==PHRASE_EDIT ? 32 : 67;
    const char *initial=editing==COMMENT ? aprs_beacon_comment() : editing==CALL ? recipient : editing==ANSWER_CALL ? aprs_answer_call :
                        editing==ANSWER_TEXT ? aprs_answer_text : editing==PHRASE_EDIT ? aprs_phrases[phrase_slot] : draft;
    for (unsigned i=0;i<length;++i) text[i]=*initial ? *initial++ : ' ';
    ((void (*)(unsigned,unsigned,const char *,unsigned,unsigned,
               unsigned (*)(const char *,uint8_t *)))0x20055a0c)(62,0,text,length,2,save_reply);
    return 1;
}

static void edit(unsigned field)
{
    unsigned previous=page;page=ROOT;
    ((void (*)(void))0x200cd828)();
    page=previous;editing=field;accepted=0;
    ((void (*)(unsigned))0x200f1600)(349);
}
unsigned aprs_ui_touch(void)
{
    volatile uint8_t *s=(volatile uint8_t *)0x203e1f23;
    if (s[0] || (s[1]==0 && s[2]==0 && s[3]==0 && s[4]==0)) {
        held=0;
        return 0;
    }
    if (held)
        return 1;
    unsigned x=(s[1]<<8)|s[2], y=(s[3]<<8)|s[4];
    if (!aprs_popup_owned || U8(0x203807dd)!=13 || x<241 || x>322 || y<222 || y>264 ||
        !aprs_can_reply(&aprs_popup_packet))
        return 0;
    copy_text(recipient,aprs_popup_packet.station,sizeof(recipient));
    held=editing=BODY;accepted=compose_new=editing_review=0;draft[0]=0;
    from_history=aprs_history_detail;
    aprs_history_detail=0;
    ((void (*)(unsigned))0x200efe64)(1);
    ((void (*)(unsigned))0x2007d478)(1);
    ((void (*)(unsigned))0x200f1600)(349);
    return 1;
}

unsigned aprs_ui_navigation(void)
{
    unsigned result=((unsigned (*)(void))0x200ebdf4)();
    if (editing && U16(0x203e84c9)!=349) {
        unsigned field=editing;
        editing=0;
        if (field==COMMENT) show(ROOT);
        else if (field==PHRASE_EDIT) {
            if (accepted==2) { notice="SD write failed";notice_parent=PHRASES;show(NOTICE); }
            else show(PHRASES);
        } else if (field==ANSWER_CALL || field==ANSWER_TEXT) show(ANSWER);
        else if (field==CALL && accepted && editing_review) { editing_review=0;show(REVIEW); }
        else if (field==CALL && accepted) {
            editing=BODY;accepted=0;
            ((void (*)(unsigned))0x200f1600)(349);
        }
        else if (accepted || editing_review) { editing_review=0;show(REVIEW); }
        else if (compose_new) show(MESSAGES);
        else if (from_history)
            aprs_history_resume();
    }
    return result;
}

static void open_history(void)
{
    pending=0;
    aprs_history_open();
}

static unsigned quick_history(unsigned *tone)
{
    *tone=1;pending=1;
    ((void (*)(void (*)(void)))0x200cd7dc)(open_history);
    return 1;
}

static void send_beacon(void)
{
    pending=0;
    ((void (*)(void))0x200cd828)();
    notice_parent=0;notice=aprs_beacon_start();
    if (notice)
        show(NOTICE);
}

static unsigned quick_send(unsigned *tone)
{
    *tone=1;pending=1;
    ((void (*)(void (*)(void)))0x200cd7dc)(send_beacon);
    return 1;
}

static void open_messages(void) { pending=0;from_history=0;show(MESSAGES); }
static unsigned quick_messages(unsigned *tone)
{
    *tone=1;pending=1;
    ((void (*)(void (*)(void)))0x200cd7dc)(open_messages);
    return 1;
}
static void open_stations(void) { pending=0;show(STATIONS); }
static unsigned quick_stations(unsigned *tone)
{
    *tone=1;pending=1;
    ((void (*)(void (*)(void)))0x200cd7dc)(open_stations);
    return 1;
}
static unsigned extra;
static unsigned quick_hide(unsigned index)
{
    if (index<extra)
        return 0;
    return ((unsigned (*)(unsigned))quick_saved.w[5])(index-extra);
}

void aprs_ui_quick(unsigned id,unsigned parent)
{
    borrow();
    quick_saved=menu[QUICK];
    quick=1;
    extra=3+aprs_tx_enabled;
    unsigned count=((uint8_t *)&quick_saved)[1]+1;
    const uint16_t *old=(const uint16_t *)quick_saved.w[17];
    ids[0]=CHILD;
    set_child(CHILD,"APRS RX List",quick_history);
    if (aprs_tx_enabled) {
        ids[1]=CHILD+1;
        set_child(CHILD+1,"Send APRS Beacon",quick_send);
    }
    ids[extra-2]=CHILD+extra-2;
    set_child(ids[extra-2],"APRS Messages",quick_messages);
    ids[extra-1]=CHILD+extra-1;
    set_child(ids[extra-1],"APRS Stations",quick_stations);
    for (unsigned i=0;i<count;++i)
        ids[extra+i]=old[i];
    menu[QUICK].w[5]=(uintptr_t)quick_hide;
    menu[QUICK].w[9]=0;
    menu[QUICK].w[17]=(uintptr_t)ids;
    ((uint8_t *)&menu[QUICK])[1]=count+extra-1;
    aprs_native_open(id,parent);
}

unsigned aprs_preview_open(void)
{
    return leased && U16(0x203e1a28)==settings_id && (page==EVENTS || page==STYLE);
}

unsigned aprs_ui_busy(void)
{
    if (leased && !U16(0x203e1a28) && !pending)
        aprs_ui_restore();
    return leased || editing || pending || aprs_return_hz;
}
#endif
