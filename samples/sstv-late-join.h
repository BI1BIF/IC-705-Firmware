/* A valid VIS always wins. Late entry requires four consecutive compatible
   intervals and, for Robot 36, alternating Cr/Cb separator tones. */
static unsigned observe_line(unsigned run,unsigned *measured) {
    unsigned dt=rx.clock-rx.edge;
    rx.edge=rx.clock;
    if (dt<480 || dt>8600) { rx.streak=0; return 0; }
    unsigned mode=0, best=55;
    if (dt>=1150 && dt<=1250 && run>=45 && run<=90) {
        unsigned now=rx.clock>>3;
        int mark=tone(now,-58,-54,1500) ? 1 : tone(now,-58,-54,2300) ? 2 : 0;
        if (mark && mark!=rx.separator) mode=ROBOT36;
        rx.separator=mark;
    }
    if (!mode) {
        if (run<=52 && dt>=3517 && dt<=3627) { mode=MARTIN_M1; best=0; }
        for (unsigned i=0;i<sizeof(basic_modes)/sizeof(*basic_modes);i++) {
            const struct Mode *m=basic_modes+i;
            /* M3/M4 share the period with M1/M2. Choose the taller preview.
               BW12 and BW24 likewise share one scan schedule. */
            if (m->vis==36 || m->vis==32 || m->vis==6) continue;
            unsigned want=(m->period+62)/125,pulse=(m->sync+62)/125;
            unsigned err=dt>want ? dt-want : want-dt;
            if (err<best && run*4>=pulse*3 && run*4<=pulse*5) {
                best=err; mode=m->vis;
            }
        }
    }
    if (mode && mode==rx.candidate) rx.streak++;
    else { rx.candidate=mode; rx.streak=mode!=0; }
    if (rx.streak<4) return 0;
    *measured=dt;
    return mode;
}

static void tracked_robot(unsigned hz) {
    unsigned t=rx.clock-rx.last_sync;
    unsigned target=rx.robot_period ? rx.robot_period : 1200;
    int in_sync=hz>=1140 && hz<=1260;
    unsigned run=rx.run;
    rx.run=in_sync ? run+1 : 0;
    /* Normal completion has no following sync on the last transmitted row. */
    if (rx.rows==HEIGHT-1 && t>=(1128*target+600)/1200) {
        rx.span=target>=1198 && target<=1202 ? 0 : target;
        end_line();
        return;
    }
    if (t>1250) {
#ifdef SSTV_TX_STUDY
        if (!rx.live) {
            /* No next edge: advance one row on the measured clock. The scan
               already contains the first samples of the next row. */
            target=rx.hold_period ? (rx.hold_period+8)/16 : target;
            rx.span=target>=1198 && target<=1202 ? 0 : target;
            end_line();
            rx.last_sync+=target;
            for (unsigned i=0;i<t-target;i++) rx.scan[i]=rx.scan[target+i];
            rx.scan[t-target]=hz;
            rx.sync_hits=0;
            return;
        }
#endif
        rx.loss=1;
        rx.phase=rx.live && rx.rows && !hz ? COMPLETE : LOST;
        return;
    }
    if (t+80>=target && hz>=1100 && hz<=1300) rx.sync_hits++;
    int edge=!in_sync && t>=1150 && run>=48 && run<=91;
    int split=t==target && run<48 && rx.sync_hits>=44;
    if (edge || split) {
#ifdef SSTV_TX_STUDY
        if (edge) rx.hold_period=rx.hold_period ? (7*rx.hold_period+16*t+4)/8 : 16*t;
#endif
        rx.robot_period=t;
        rx.span=t>=1198 && t<=1202 ? 0 : t;
        if (rx.skips) rx.skips=0;
        else end_line();
        rx.last_sync=rx.clock;
        rx.sync_hits=rx.run=0;
        rx.scan[0]=hz;
        return;
    }
    rx.scan[t]=hz;
}
