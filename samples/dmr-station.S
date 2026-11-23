.syntax unified
.thumb
.global dmr_restore
.thumb_func
dmr_restore:
    ldr r2,=__work_start
    ldr r3,=__work_end
    mov.w ip,#0
1:  cmp r2,r3
    bhs 2f
    str ip,[r2],#4
    b 1b
2:  ldr ip,=restore_modes
    bx ip

#ifdef DMR_LONG_INIT
/* Both descriptors start at the same address. The longer one continues
   with the next token stream using the decoder's advanced source and dest. */
.global dmr_restore_long
.thumb_func
dmr_restore_long:
    push {r4,lr}
    bl dmr_restore
    pop {r4,lr}
    ldr ip,=restore_modes
    bx ip
#endif

.arm
.global aprs_fm_guard,factory_fm_available
aprs_fm_guard:
    ldr r2,=dmr_owns_fm
    ldrb r2,[r2]
    cmp r2,#0
    movne r0,#0
    bxne lr
factory_fm_available:
    ldr r2,=fm_literal
    ldr pc,=fm_resume
