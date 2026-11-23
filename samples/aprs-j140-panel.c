/* APRS data and ownership for the native J140 FM notification and position window. */
#include "aprs-j140-popup.h"

#pragma GCC optimize ("Os")

#define REG8(a) (*(volatile uint8_t *)(a))
#define REG16(a) (*(volatile uint16_t *)(a))

enum { PAGE = 0x204bab5d, LIVE_WINDOW = 0x203807dd, STOCK_ALERT = 0x20392fe0,
       STOCK_SELECTOR = 0x203e1a28, POSITION_WINDOW = 13 };

uint8_t aprs_strip[202], aprs_window_state[80], aprs_popup_owned;
static uint8_t auto_pending;
static enum aprs_fix previous_fix;
static uint32_t previous_frequency;
static uint32_t position_frequency;
static struct popup_packet latest_position;
uint8_t aprs_history_detail;
uint32_t aprs_active_frequency(void);
extern volatile uint32_t aprs_channel_hz;

/* The audio consumer and the stock panel task share one pending popup. */
static unsigned lock_popup(void)
{
    unsigned flags;
    __asm__ volatile("mrs %0,cpsr\ncpsid i":"=r"(flags)::"memory");
    return flags;
}

static void unlock_popup(unsigned flags)
{
    __asm__ volatile("msr cpsr_c,%0"::"r"(flags):"memory");
}

unsigned aprs_call_text(char *out, const uint8_t *address)
{
    unsigned n = 0;
    for (; n < 6 && address[n] != (' ' << 1); ++n) {
        unsigned ch = address[n] >> 1;
        out[n] = (ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'Z') ? ch : '?';
    }
    unsigned ssid = address[6] >> 1 & 15;
    if (ssid) {
        out[n++] = '-';
        if (ssid >= 10) {
            out[n++] = '1';
            ssid -= 10;
        }
        out[n++] = '0' + ssid;
    }
    return n;
}

static const uint16_t ambiguity_span[] = {0, 10, 100, 1000, 6000};

static unsigned coordinate(const uint8_t *text, unsigned width, unsigned limit, char a, char b,
                           unsigned shared_precision, int *centre)
{
    if (text[width+2] != '.' || (text[width+5] != a && text[width+5] != b))
        return 0;
    unsigned degree = 0, minutes = 0, ambiguity = 0;
    for (unsigned i = 0; i < width + 5; ++i) {
        if (i == width + 2)
            continue;
        unsigned d = (unsigned)text[i] - '0';
        if (i >= width && text[i] == ' ') {
            d = 0;
            ++ambiguity;
        } else if (d > 9 || ambiguity)
            return 0;
        if (i < width)
            degree = degree * 10 + d;
        else
            minutes = minutes * 10 + d;
    }
    if (shared_precision && ambiguity >= shared_precision)
        return 0;
    if (shared_precision > 1) {
        ambiguity = shared_precision-1;
        minutes -= minutes % ambiguity_span[ambiguity];
    }
    minutes += ambiguity_span[ambiguity]/2;
    if (minutes >= 6000 || degree > limit || (degree == limit && minutes))
        return 0;
    int value = degree * 6000 + minutes;
    *centre = text[width+5] == b ? -value : value;
    return ambiguity + 1;
}

static unsigned printable(uint8_t c)
{
    return c >= ' ' && c <= '~';
}

static int digits(const uint8_t *text, unsigned width)
{
    int result = 0;
    for (unsigned n = 0; n < width; ++n) {
        if (text[n] < '0' || text[n] > '9')
            return NO_READING;
        result = result * 10 + text[n] - '0';
    }
    return result;
}

static unsigned data_extension(struct popup_packet *out, const uint8_t *text, unsigned length,
                               int uncompressed)
{
    out->course = out->speed = out->temperature = out->humidity = out->pressure = NO_READING;
    unsigned start = 0;
    if (uncompressed && length >= 7 && text[3] == '/') {
        int direction = digits(text, 3), speed = digits(text+4, 3);
        int weather = out->kind == WEATHER;
        int ordinary = direction >= 0 && direction <= 360 && speed >= 0;
        if (direction <= 360 && ((weather && direction >= 0) || (ordinary && direction > 0)))
            out->course = direction;
        if (speed != NO_READING && (weather || (ordinary && (direction > 0 || speed > 0))))
            out->speed = weather ? (speed * 1609 + 500) / 1000 : (speed * 1852 + 500) / 1000;
        if (weather || ordinary)
            start = 7;
    }
    if (out->kind != WEATHER)
        return start;

    while (start < length) {
        unsigned width;
        switch (text[start]) {
        case 'h': width = 2; break;
        case 'b': width = 5; break;
        case 'g': case 't': case 'r': case 'p': case 'P': case 'L': case 'l': case 's':
            width = 3; break;
        default: return length;
        }
        if (length - start <= width)
            break;
        const uint8_t *field = text + start + 1;
        int value = digits(field, width);
        if (text[start] == 't' && field[0] == '-' && digits(field+1, 2) != NO_READING)
            value = -digits(field+1, 2);
        if (value != NO_READING) {
            switch (text[start]) {
            case 't': {
                int c = (value - 32) * 5;
                out->temperature = (c + (c < 0 ? -4 : 4)) / 9;
                break;
            }
            case 'h': out->humidity = value ? value : 100; break;
            case 'b': if (value > 0) out->pressure = (value + 5) / 10; break;
            }
        }
        start += 1 + width;
    }
    return length;
}

static int position_symbol(struct popup_packet *out, unsigned table, unsigned code)
{
    if ((table != '/' && table != '\\' && (table < 'A' || table > 'Z') && (table < '0' || table > '9')) ||
        code <= ' ' || code > '~')
        return 0;
    out->symbol[0] = table;
    out->symbol[1] = code;
    out->symbol[2] = 0;
    out->ambiguous = 0;
    out->kind = code == '_' ? WEATHER :
                code == '&' && (table == 'R' || table == 'T' || table == 'I' || table == '2' || table == 'L') ? IGATE :
                code == '[' && table == '/' ? PERSONAL : BEACON;
    return 1;
}

static void position_comment(struct popup_packet *out, const uint8_t *text, unsigned length)
{
    while (length && (text[length-1] == '\r' || text[length-1] == '\n'))
        --length;
    for (unsigned i = 0; i < length; ++i)
        out->comment[i] = printable(text[i]) ? text[i] : '?';
    out->comment[length] = 0;
}

static void write_coordinate(char *text, int centiminutes, unsigned width, char plus, char minus)
{
    text[width+5] = centiminutes < 0 ? minus : plus;
    text[width+6] = 0;
    unsigned magnitude = centiminutes < 0 ? -centiminutes : centiminutes;
    unsigned minutes = magnitude % 6000, degrees = magnitude / 6000;
    text[width] = '0' + minutes / 1000;
    text[width+1] = '0' + minutes / 100 % 10;
    text[width+2] = '.';
    text[width+3] = '0' + minutes / 10 % 10;
    text[width+4] = '0' + minutes % 10;
    while (width) {
        text[--width] = '0' + degrees % 10;
        degrees /= 10;
    }
}

static unsigned compressed_axis(const uint8_t *text, unsigned scale)
{
    unsigned value = 0;
    for (unsigned i = 0; i < 4; ++i) {
        unsigned digit = text[i] - '!';
        if (digit >= 91)
            return (unsigned)-1;
        value = value * 91 + digit;
    }
    return value / scale * 6000 + (value % scale * 6000 + scale/2) / scale;
}

static unsigned compressed_position(struct popup_packet *out, const uint8_t *info, unsigned length)
{
    if (length < 14)
        return 0;
    unsigned table = info[1];
    if (table >= 'a' && table <= 'j')
        table += '0' - 'a';
    else if (table >= '0' && table <= '9')
        return 0;
    unsigned latitude = compressed_axis(info+2, 380926);
    unsigned longitude = compressed_axis(info+6, 190463);
    if (latitude > 180*6000 || longitude > 360*6000 || !position_symbol(out, table, info[10]))
        return 0;
    write_coordinate(out->latitude, 90*6000 - (int)latitude, 2, 'N', 'S');
    write_coordinate(out->longitude, (int)longitude - 180*6000, 3, 'E', 'W');
    unsigned start = data_extension(out, info+14, length-14, 0);
    unsigned course = info[11] - '!', speed = info[12] - '!', type = info[13] - '!';
    if (course < 90 && speed < 91 && type < 64 && (type & 0x18) != 0x10) {
        /* round(1.852 * (1.08^s - 1)) km/h for each base-91 speed value. */
        static const uint16_t kmh[] = {
            0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
            3, 3, 4, 4, 4, 5, 6, 6, 7, 7, 8, 9,
            10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 24, 26,
            28, 30, 33, 35, 38, 42, 45, 49, 53, 57, 62, 67,
            73, 79, 85, 92, 99, 108, 116, 126, 136, 147, 159, 172,
            186, 201, 217, 234, 253, 274, 296, 320, 345, 373, 403, 435,
            470, 508, 549, 593, 641, 692, 748, 807, 872, 942, 1018, 1099,
            1187, 1282, 1385, 1496, 1616, 1745, 1885
        };
        out->course = course * 4;
        out->speed = kmh[speed];
    }
    position_comment(out, info+14+start, length-14-start);
    return 1;
}

static unsigned mice_position(struct popup_packet *out, const uint8_t *info, unsigned length,
                              const uint8_t *destination)
{
    if (length < 9)
        return 0;
    unsigned latitude = 0, ambiguity = 0;
    for (unsigned i = 0; i < 6; ++i) {
        unsigned ch = destination[i] >> 1;
        unsigned digit = ch >= 'P' ? ch - 'P' : ch >= 'A' ? ch - 'A' : ch - '0';
        if (ch == 'K' || ch == 'L' || ch == 'Z') {
            if (i < 2 || (i >= 3 && ch == 'K'))
                return 0;
            ++ambiguity;
            digit = 0;
        } else if (digit > 9 || ambiguity || (i >= 3 && ch >= 'A' && ch < 'P'))
            return 0;
        latitude = latitude * 10 + digit;
    }
    if (info[1] < 38 || info[1] > 127 || info[2] < 38 || info[2] > 97)
        return 0;
    for (unsigned i = 3; i < 7; ++i)
        if (info[i] < 28 || info[i] > 127)
            return 0;
    unsigned longitude = info[1] - 28;
    if ((destination[4] >> 1) >= 'P') {
        longitude += 100;
        if (longitude >= 180)
            longitude -= longitude < 190 ? 80 : 190;
    }
    unsigned minutes = info[2] - (info[2] >= 88 ? 88 : 28);
    longitude = longitude * 6000 + minutes * 100 + info[3] - 28;
    if (latitude % 10000 >= 6000)
        return 0;
    latitude = latitude / 10000 * 6000 + latitude % 10000;
    if (ambiguity) {
        unsigned span = ambiguity_span[ambiguity];
        latitude += span/2;
        longitude = longitude / span * span + span/2;
    }
    unsigned speed = (info[4]-28)*10 + (info[5]-28)/10;
    unsigned course = (info[5]-28)%10*100 + info[6]-28;
    if (course >= 400)
        course -= 400;
    if (speed >= 800)
        speed -= 800;
    if (latitude > 90*6000 || longitude > 180*6000 || course > 360 || speed >= 800 ||
        !position_symbol(out, info[8], info[7]))
        return 0;
    unsigned start = data_extension(out, info+9, length-9, 0);
    out->ambiguous = ambiguity != 0;
    out->speed = (speed*1852 + 500) / 1000;
    out->course = course ? (int)(course % 360) : NO_READING;
    write_coordinate(out->latitude, (destination[3] >> 1) >= 'P' ? (int)latitude : -(int)latitude, 2, 'N', 'S');
    write_coordinate(out->longitude, (destination[5] >> 1) >= 'P' ? -(int)longitude : (int)longitude, 3, 'E', 'W');
    position_comment(out, info+9+start, length-9-start);
    return 1;
}

static unsigned position_payload(struct popup_packet *out, const uint8_t *info, unsigned length)
{
    if (length >= 14 && (info[1] < '0' || info[1] > '9'))
        return compressed_position(out, info, length);
    if (length < 20)
        return 0;
    int lat, lon;
    unsigned precision = coordinate(info+1, 2, 90, 'N', 'S', 0, &lat);
    if (!precision || !coordinate(info+10, 3, 180, 'E', 'W', precision, &lon) ||
        !position_symbol(out, info[9], info[19]))
        return 0;
    if (precision > 1) {
        out->ambiguous = 1;
        write_coordinate(out->latitude, lat, 2, 'N', 'S');
        write_coordinate(out->longitude, lon, 3, 'E', 'W');
    } else {
        for (unsigned i = 0; i < 8; ++i)
            out->latitude[i] = info[1+i];
        out->latitude[8] = 0;
        for (unsigned i = 0; i < 9; ++i)
            out->longitude[i] = info[10+i];
        out->longitude[9] = 0;
    }
    unsigned start = data_extension(out, info+20, length-20, 1);
    position_comment(out, info+20+start, length-20-start);
    return 1;
}

static unsigned position_text(struct popup_packet *out,const uint8_t *info,unsigned length,const uint8_t *dest)
{
    if (!length) return 0;
    if (*info=='`' || *info=='\'') return mice_position(out,info,length,dest);
    int timed=*info=='/' || *info=='@';
#ifdef APRS_SLOT_UI
    unsigned name=0;
    const uint8_t *begin=info;
    if (*info==';' || *info==')') {
        int item=*info==')';
        while (name<9 && name+1<length && printable(info[name+1]) &&
               !(item && (info[name+1]=='!' || info[name+1]=='_'))) ++name;
        if (name+1>=length || (item ? name<3 : name!=9)) return 0;
        unsigned marker=name+1;
        if (info[marker]!='_' && info[marker]!=(item ? '!' : '*')) return 0;
        if (!item) while (name && info[name]==' ') --name;
        if (!name) return 0;
        info+=marker;length-=marker;timed=!item;
    } else
#endif
    if (!timed && *info!='!' && *info!='=') return 0;
    if (timed) {
        if (length<21) return 0;
        unsigned suffix=info[7];
        int ts=digits(info+1,6);
        unsigned first=(unsigned)ts/10000, second=(unsigned)ts/100%100;
        if (ts<0 || ts%100>=60 || (suffix=='h' ? first>23 || second>=60 :
            (suffix!='z' && suffix!='/') || !first || first>31 || second>23)) return 0;
        info+=7;length-=7;
    }
    if (!position_payload(out,info,length)) return 0;
#ifdef APRS_SLOT_UI
    if (name) {
        for (unsigned i=0;i<name;++i) out->entity[i]=begin[1+i];
        out->entity[name]=0;out->item=*begin==')';out->removed=*(info-(timed ? 7 : 0))=='_';
    }
#endif
    return 1;
}

static unsigned address_bytes(const uint8_t *frame)
{
    unsigned addresses = 14;
    while (!(frame[addresses-1] & 1))
        addresses += 7;  /* Decoder already validated the AX.25 address field. */
    return addresses;
}

static void route_text(struct popup_packet *out, const uint8_t *frame, unsigned addresses)
{
    unsigned n = aprs_call_text(out->route, frame+7);
    for (unsigned i = 0; i < n; ++i)
        out->station[i] = out->route[i];
    out->station[n] = 0;
    out->route[n++] = '>';
    n += aprs_call_text(out->route+n, frame);
    unsigned last_repeated = 0;
    for (unsigned i = 14; i < addresses; i += 7)
        if (frame[i+6] & 0x80)
            last_repeated = i;
    for (unsigned i = 14; i < addresses; i += 7) {
        out->route[n++] = ',';
        n += aprs_call_text(out->route+n, frame+i);
        if (i == last_repeated)
            out->route[n++] = '*';
    }
    out->route[n] = 0;
}

static unsigned text_kind(const uint8_t *info, unsigned length)
{
    if (length && info[0] == '>')
        return STATUS;
    if (length >= 11 && info[0] == ':' && info[10] == ':')
        return MESSAGE;
    return PACKET;
}

static void packet_content(struct popup_packet *out, const uint8_t *info, unsigned length,
                           const uint8_t *destination)
{
    out->alert_event = ALERT_COUNT;
    if (position_text(out, info, length, destination))
        return;
    out->symbol[0] = out->symbol[1] = 0;
    out->kind = text_kind(info, length);
    out->message_id[0] = 0;
    if (out->kind == MESSAGE) {
        unsigned n = 9;
        while (n && info[n] == ' ')
            --n;
        for (unsigned i = 0; i < n; ++i)
            out->longitude[i] = printable(info[i+1]) ? info[i+1] : '?';
        out->longitude[n] = 0;
        info += 11;
        length -= 11;
    } else if (out->kind == STATUS) {
        ++info;
        --length;
    }
    while (length && (info[length-1] == '\r' || info[length-1] == '\n'))
        --length;
    if (out->kind == MESSAGE) {
        unsigned first = length;
        while (first && length-first < 5) {
            unsigned ch = info[first-1];
            if (!((ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z')))
                break;
            --first;
        }
        if (first && first < length && info[first-1] == '{') {
            for (unsigned i = first; i < length; ++i)
                out->message_id[i-first] = info[i];
            out->message_id[length-first] = 0;
            length = first-1;
        }
    }
    for (unsigned i = 0; i < length; ++i)
        out->comment[i] = printable(info[i]) ? info[i] : '?';
    out->comment[length] = 0;
}

#ifdef APRS_SLOT_UI
/* Decode the inner addresses separately; Mic-E stores latitude in destination. */
static unsigned text_address(const uint8_t *s,unsigned n,uint8_t *ax)
{
    unsigned k=0,ssid=0;
    while (k<n && s[k]!='-') {
        if (k==6 || !((s[k]>='A' && s[k]<='Z') || (s[k]>='0' && s[k]<='9'))) return 0;
        ax[k]=s[k]<<1;++k;
    }
    if (!k) return 0;
    for (unsigned i=k;i<6;++i) ax[i]=' '<<1;
    if (k<n) {
        if (++k==n || n-k>2) return 0;
        while (k<n) {
            if (s[k]<'0' || s[k]>'9') return 0;
            ssid=10*ssid+s[k++]-'0';
        }
        if (ssid>15) return 0;
    }
    ax[6]=0x60+2*ssid;return 1;
}

static unsigned unwrap(struct popup_packet *out,const uint8_t *s,unsigned len,uint8_t *dest)
{
    unsigned first=0,last=0,end=0,hops=0;int sep=0;
    uint8_t src[7];
    while (end<len && end<100 && s[end]!=':') {
        if (s[end]=='>' || s[end]==',') {
            if (end==last || (first && sep && s[end]!=sep)) return 0;
            if (!first) {
                if (s[end]!='>' || !text_address(s,end-(s[end-1]=='*'),src)) return 0;
                first=end+1;
            } else {
                if (++hops>8) return 0;
                sep=s[end];
            }
            last=end+1;
        } else if (s[end]<33 || s[end]>126) return 0;
        ++end;
    }
    if (!first || end+1>=len || s[end]!=':' || last==end || s[end+1]=='}') return 0;
    if (s[first-2]=='*' && sep==',') return 0;
    last=first;
    while (last<end) {
        unsigned next=last;
        while (next<end && s[next]!='>' && s[next]!=',') ++next;
        unsigned n=next-last-(s[next-1]=='*');
        unsigned is_dest=sep=='>' ? next==end : last==first;
        if (!n || n>9) return 0;
        if (is_dest) {
            if (n!=next-last || !text_address(s+last,n,dest)) return 0;
        } else {
            /* APRS-IS path components may contain mixed-case q constructs. */
            for (unsigned i=0;i<n;++i) {
                unsigned c=s[last+i];
                if (!((c>='A' && c<='Z')||(c>='a' && c<='z')||(c>='0' && c<='9')||c=='-')) return 0;
            }
        }
        last=next+1;
    }
    unsigned n=0;
    while (out->station[n]) { out->route[n]=out->station[n];++n; }
    out->route[n++]=' ';out->route[n++]='|';out->route[n++]=' ';
    for (unsigned i=0;i<end && n+1<sizeof(out->route);++i) out->route[n++]=s[i];
    out->route[n]=0;
    out->station[aprs_call_text(out->station,src)]=0;
    return end+2;
}
#endif

static void parse(struct popup_packet *out,const uint8_t *frame,unsigned addresses,unsigned length)
{
    const uint8_t *info=frame+addresses+2,*dest=frame;
    route_text(out,frame,addresses);
#ifdef APRS_SLOT_UI
    out->entity[0]=0;out->item=out->removed=0;
    uint8_t inner[7];
    if (length && *info=='}') {
        unsigned consumed=unwrap(out,info+1,length-1,inner);
        if (consumed) { info+=consumed;length-=consumed;dest=inner; }
    }
#endif
    packet_content(out,info,length,dest);
}
void aprs_parse_packet(struct popup_packet *out, const struct output_frame *record)
{
    unsigned addresses=address_bytes(record->bytes);
    parse(out,record->bytes,addresses,record->length-addresses-4);
}

uint16_t aprs_offer_frame(const struct output_frame *record, struct output_frame *history)
{
    const uint8_t *frame = record->bytes;
    unsigned addresses = address_bytes(frame);
    unsigned length = record->length-addresses-4;
    unsigned icon;
    if (history) {
        history->distance=APRS_NO_DISTANCE;
#ifdef APRS_SLOT_UI
        history->history_direction=0;
#endif
    }
    static struct popup_packet packet; /* Only the record consumer writes the parse workspace. */
    parse(&packet,frame,addresses,length);
    if (packet.kind <= PERSONAL) {
        if (history) {
#ifdef APRS_SLOT_UI
            history->distance=aprs_packet_distance(&packet,&history->history_direction);
#else
            history->distance=aprs_packet_distance(&packet,0);
#endif
        }
        icon = (packet.symbol[0] << 8) | (uint8_t)packet.symbol[1];
    } else
        icon = packet.kind;
    unsigned event = aprs_alert_class(&packet,frame,addresses,length);
    packet.alert_event = event;
    unsigned style = event < ALERT_COUNT ? aprs_alert_styles[event] : LIST_ONLY;
#ifdef APRS_SLOT_UI
    if (icon==MESSAGE && event!=ALERT_MESSAGE) icon=0xfffe; /* Raw history only. */
    if (style == LIST_ONLY)
        return icon;
#endif
    if (style != LIST_ONLY) {
        unsigned flags = lock_popup();
        /* Keep a waiting addressed message ahead of background position traffic. */
        if (!auto_pending || packet.kind == MESSAGE || latest_position.kind != MESSAGE) {
            latest_position = packet;
            position_frequency = aprs_channel_hz;
            auto_pending = style;
        }
        unlock_popup(flags);
    }
    const char *name=packet.station;
    unsigned n=0;while (name[n]) ++n;
    for (unsigned i = 0; i < 13; ++i)
        aprs_strip[10+i] = i < n ? name[i] : ' ';
    aprs_strip[23] = n;
    aprs_strip[2] = 1;
    aprs_strip[3] = 2;
    aprs_strip[6] = position_frequency == aprs_channel_hz ? 4 : 0;
    REG8(0x203806f7) |= 0x40;  /* Original screen refresh flag. */
    return icon;
}

static unsigned window(void)
{
    return REG8(LIVE_WINDOW) | (REG8(LIVE_WINDOW+1) << 8);
}

unsigned aprs_open_history_detail(void)
{
    if (window() || REG8(LIVE_WINDOW+2) || REG16(STOCK_ALERT) || REG8(PAGE) != 1)
        return 0;
    REG16(0x203808fa) = 0;
    aprs_popup_owned = aprs_history_detail = 1;
    ((void (*)(unsigned))0x20048510)(2);
    if (window() == POSITION_WINDOW)
        return 1;
    aprs_popup_owned = aprs_history_detail = 0;
    return 0;
}

unsigned aprs_standby_ready(void)
{
    return !window() && !REG8(LIVE_WINDOW+2) && !REG16(STOCK_ALERT) && !REG16(STOCK_SELECTOR) && REG8(PAGE) == 1;
}

static unsigned select_position(unsigned automatic)
{
    if (!aprs_standby_ready() || !aprs_active_frequency() || position_frequency != aprs_channel_hz)
        return 0;
    unsigned flags = lock_popup();
    unsigned style = automatic ? auto_pending : SILENT_POPUP;
    if (!style) {
        unlock_popup(flags);
        return 0;
    }
    if (automatic)
        auto_pending = 0;
    const char *source = (const char *)&latest_position;
    char *out = (char *)&aprs_popup_packet;
    for (unsigned i = 0; i < sizeof(aprs_popup_packet); ++i)
        out[i] = source[i];
    unlock_popup(flags);
    REG16(0x203808fa) = 0;  /* Stock window age, including manual reopen. */
    aprs_popup_owned = 1;
    return style;
}

unsigned aprs_allow_position_touch(void)
{
    if (!aprs_channel_hz || (REG8(0x203e2128) >> 4) != 7)
        return 1;
    return select_position(0);
}

unsigned aprs_strip_visible(unsigned slot)
{
    unsigned valid = ((unsigned (*)(unsigned))0x2004a8fc)(slot);
    return valid ? valid : !slot && aprs_active_frequency() && (aprs_strip[6] & 4);
}

unsigned aprs_icon_without_call(void)
{
    return !aprs_strip[2] && (aprs_strip[6] & 4) && aprs_active_frequency();
}

void aprs_update_panel(void)
{
    uint32_t listening = aprs_active_frequency();
    if (aprs_popup_owned && window() == POSITION_WINDOW) {
        enum aprs_fix fix = aprs_gps_fix();
        if (fix != previous_fix) {
            previous_fix = fix;
            REG8(0x203806f7) |= 0x40;
        }
        if (!listening && !aprs_history_detail)
            ((void (*)(unsigned))0x200efe64)(1);
        else if (aprs_window_state[79] == 3 && !REG16(STOCK_ALERT))
            ((void (*)(unsigned))0x2004859c)(1);
    }
    if (window() != POSITION_WINDOW) {
        aprs_popup_owned = 0;
        if (aprs_history_detail) {
            aprs_history_detail = 0;
            if (!window() && !REG8(LIVE_WINDOW+2) && !REG16(STOCK_ALERT) &&
                !REG16(STOCK_SELECTOR) && REG8(PAGE) == 1)
                aprs_history_resume();
        }
    }
    if (listening != previous_frequency) {
        if (!listening || previous_frequency)
            aprs_strip[2] = 0;
        previous_frequency = listening;
        REG8(0x203806f7) |= 0x40;
    }
    uint8_t icon = listening && position_frequency == listening ? 4 : 0;
    if (aprs_strip[6] != icon) {
        aprs_strip[6] = icon;
        REG8(0x203806f7) |= 0x40;
    }
#ifdef APRS_SLOT_UI
    extern unsigned aprs_preview_open(void);
    aprs_alert_tick(listening || (aprs_plain_fm() && aprs_preview_open()));
#else
    aprs_alert_tick(listening);
#endif
    unsigned style = 0;
    if (auto_pending) {
        if (listening && aprs_standby_ready())
            style = select_position(1);
        else
            auto_pending = 0; /* Stock menu/alerts keep the foreground. */
    }
    if (style) {
        ((void (*)(unsigned))0x20048510)(3);
        if (window() == POSITION_WINDOW)
            aprs_alert_sound(style);
    }
#ifdef APRS_SLOT_UI
    aprs_messages_poll();
#endif
    aprs_beacon_poll();
}
