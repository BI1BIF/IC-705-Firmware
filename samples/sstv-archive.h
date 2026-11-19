/* The SSTV album uses reserved 8.3 names in the existing Picture directory.
   Original SD wrappers own the file handles and all media access. */
enum { ALBUM_SIZE=8 };
static const uint8_t bitmap_header[66]={
    0x42,0x4d,0x42,0x58,0x02,0,0,0,0,0,66,0,0,0,40,0,0,0,
    0x40,1,0,0,0x10,0xff,0xff,0xff,1,0,16,0,3,0,0,0,0,0x58,2,0,
    0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0xf8,0,0,0xe0,7,0,0,0x1f,0,0,0
};
static const char album_path[]="C:\\IC-705\\Picture\\SSTV0000.BMP";
volatile char archive_names[ALBUM_SIZE][16];
volatile unsigned sstv_archive_choice;

#define sd_open ((int (*)(const char *,unsigned,int *))0x2023fec8)
#define sd_close ((int (*)(int))0x2023fee4)
#define sd_read ((int (*)(int,void *,unsigned,unsigned *))0x2023ff00)
#define sd_write ((int (*)(int,const void *,unsigned,unsigned *))0x2023ff18)
#define sd_seek ((int (*)(int,int,unsigned,unsigned *))0x2023ff64)

static void slot_path(char *out,unsigned slot) {
    for (unsigned i=0;i<sizeof(album_path);i++) out[i]=album_path[i];
    out[sizeof(album_path)-6]='0'+slot;
}

static int archive_probe(unsigned slot,int *fd) {
    char path[sizeof(album_path)];
    slot_path(path,slot);
    return sd_open(path,0,fd)==0;
}

static int archive_save(unsigned slot) {
    char path[sizeof(album_path)];
    unsigned bytes;
    int fd;
    slot_path(path,slot);
    /* Open without truncation. A second check protects any existing file
       even when a failed read could not distinguish it from a free slot. */
    if (sd_open(path,0x201,&fd)) return 0;
    int ok=!sd_seek(fd,0,2,&bytes) && bytes==0 &&
        !sd_write(fd,bitmap_header,sizeof(bitmap_header),&bytes) && bytes==sizeof(bitmap_header) &&
        !sd_write(fd,image,sizeof(Canvas),&bytes) && bytes==sizeof(Canvas);
    return sd_close(fd)==0 && ok;
}

static int archive_load(unsigned slot) {
    int fd;
    unsigned bytes;
    uint8_t header[sizeof(bitmap_header)];
    if (!archive_probe(slot,&fd)) return 0;
    int ok=!sd_read(fd,header,sizeof(header),&bytes) && bytes==sizeof(header);
    for (unsigned i=0;i<sizeof(header) && ok;i++) ok=header[i]==bitmap_header[i];
    if (ok && (!sd_seek(fd,0,2,&bytes) && bytes==sizeof(header)+sizeof(Canvas)) &&
        !sd_seek(fd,sizeof(header),0,&bytes)) {
        void *temp=((void *(*)(unsigned))0x20127a28)(sizeof(Canvas));
        ok=temp && !sd_read(fd,temp,sizeof(Canvas),&bytes) && bytes==sizeof(Canvas);
        if (sd_close(fd)) ok=0;
        if (ok) {
            uint16_t *dst=&image[0][0];
            unsigned chunks=sizeof(Canvas)/16;
            __asm__ volatile(
                "1: ldmia %1!,{r1-r3,r12}\n stmia %0!,{r1-r3,r12}\n subs %2,%2,#1\n bne 1b"
                : "+&r"(dst),"+&r"(temp),"+&r"(chunks)
                : : "r1","r2","r3","r12","cc","memory");
            temp=(uint8_t *)temp-sizeof(Canvas);
        }
        if (temp) ((void (*)(void *))0x20127a78)(temp);
        return ok;
    } else ok=0;
    return sd_close(fd)==0 && ok;
}

static void archive_action(void) {
    ((void (*)(void))0x200cd828)();
    unsigned slot=sstv_archive_choice;
    unsigned old=lock();
    if (in_worker || counts.phase==RECEIVING) {
        gallery_result=2;
        unlock(old);
        return;
    }
    gallery_loading=1;
    read_at=write_at;
    unlock(old);
    gallery_result=3;
    if (!slot && (counts.rows || gallery_slot)) {
        gallery_result=4;
        int fd;
        for (unsigned i=1;i<=ALBUM_SIZE;i++) {
            if (archive_probe(i,&fd)) { sd_close(fd); continue; }
            gallery_result=archive_save(i) ? 1 : 3;
            break;
        }
    } else if (slot && slot<=ALBUM_SIZE && archive_load(slot)) {
        gallery_slot=slot;
        gallery_result=0;
    }
    if (!gallery_slot) gallery_loading=0;
    *(volatile uint8_t *)0x20380c98 |= 1;
}

unsigned sstv_archive_select(void) {
    ((void (*)(void (*)(void)))0x200cd7dc)(archive_action);
    return 2;
}

unsigned sstv_archive_open(void) {
    if (!viewing() || current_menu()!=RX_PICTURE) return 0;
    if (((unsigned (*)(void))0x200c490c)() || ((unsigned (*)(void))0x200c27e8)()) {
        gallery_result=3;
        *(volatile uint8_t *)0x20380c98 |= 1;
        return 1;
    }
    for (unsigned i=0;i<ALBUM_SIZE;i++) {
        int fd;
        int exists=archive_probe(i+1,&fd);
        if (exists) sd_close(fd);
        volatile char *label=archive_names[i];
        const char *text=exists ? "SSTV  " : "Empty ";
        for (unsigned k=0;k<6;k++) label[k]=text[k];
        label[6]='1'+i;
        label[7]=0;
    }
    ((void (*)(unsigned,unsigned))0x200cd628)(283,0xffff);
    return 1;
}

const char *sstv_gallery_text(unsigned field) {
    if (current_menu()!=RX_PICTURE) return 0;
    if (field==0x56f) return "SAVE/HIST";
    if (field==0x568 && gallery_slot) return "Saved SSTV";
    if (field==0x56c && gallery_slot) return "320 x 240";
    if (field==0x56d && gallery_slot) return "SSTV BMP";
    if (field==0x56a && gallery_result) {
        static const char *const states[]={0,"Saved","RX busy","SD error","Album full"};
        return states[gallery_result];
    }
    return 0;
}
