#ifdef APRS_SLOT_UI
.syntax unified
.arm
.global aprs_native_open
aprs_native_open:
    push {r4-r6,lr}
    ldr pc,=0x200cd62c
.macro intercept name,callback,displaced,resume
.global \name
\name:
    push {r0-r3,ip,lr}
    bl \callback
    cmp r0,#0
    pop {r0-r3,ip,lr}
    movne r0,#4
    bxne lr
    .word \displaced
    ldr pc,=\resume
.endm
intercept aprs_reply_touch,aprs_ui_touch,0xe92d4070,0x2007f108
intercept aprs_reply_keyboard,aprs_ui_keyboard,0xe92d401c,0x20052fb4
intercept aprs_reply_back,aprs_ui_back,0xe92d4010,0x200cd82c
#endif
