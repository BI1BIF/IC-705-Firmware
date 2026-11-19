.syntax unified
.arm
.text
.macro save
    push {r0-r4, lr}
    mrs r4, cpsr
    push {r4, r5}
.endm
.macro restore
    pop {r4, r5}
    msr APSR_nzcvqg, r4
    pop {r0-r4, lr}
.endm

.global sstv_pcm_hook
sstv_pcm_hook:
#ifdef SSTV_DEVICE
    @ Native code overwrites r4 here, and D6 saves it only until that MOV.
    @ Active is exactly 0 or 1. Preserve APSR while taking the short idle path.
    ldr r4, =counts
    ldr r4, [r4]
    add pc, pc, r4, lsl #2
    nop
    ldr pc, =sstv_d6_pcm
#endif
    save
    add r0, sp, #40        @ Native six-sample PCM at entry SP+8.
    push {r12, lr}
    bl sstv_capture
    pop {r12, lr}
    restore
#ifdef SSTV_DEVICE
    ldr pc, =sstv_d6_pcm
#else
    mov r4, #0
    ldr pc, =0x2010feb0
#endif

.global sstv_frame_hook
sstv_frame_hook:
    save
    push {r12, lr}
    bl sstv_prepare_frame
    pop {r12, lr}
    restore
    push {r4-r12, lr}     @ Original STMFD at 0x2013c5e8.
    ldr pc, =0x2013c5ec

.global sstv_image_hook
sstv_image_hook:
    push {r0-r3, r12, lr}
    mrs r0, cpsr
    push {r0, r1}
    ldr r0, [sp, #124]    @ Saved caller LR, entry SP+92.
    bl sstv_source
    mov r4, r0
    pop {r0, r1}
    msr APSR_nzcvqg, r0
    pop {r0-r3, r12, lr}
    ldr pc, =0x2018e83c

.global sstv_thumbnail_hook
sstv_thumbnail_hook:
    push {r1-r3, r5, r12, lr}
    ldrb r0, [r4, #29]    @ Stock half-panel RX image availability.
    bl sstv_thumbnail_ready
    pop {r1-r3, r5, r12, lr}
    ldr pc, =0x2018f81c    @ Stock CMP and thumbnail renderer.

.global sstv_picture_label
sstv_picture_label:
    push {r0-r3, r12, lr}
    mov r0, r1
    bl sstv_picture_text
    cmp r0, #0
    beq 2f
    str r0, [sp, #8]      @ Preserve stock geometry, font, and alignment.
    mov r1, #0
1:  ldrb r2, [r0, r1]
    cmp r2, #0
    addne r1, r1, #1
    bne 1b
    str r1, [sp, #12]
2:  pop {r0-r3, r12, lr}
    ldr pc, =0x20142698

#ifdef SSTV_DEVICE
.macro rx_only_handler name, native_reg, resume
.global \name
\name:
    push {r0-r3, r12, lr}
    bl sstv_rx_only
    cmp r0, #0
    pop {r0-r3, r12, lr}
    movne r0, #2
    bxne lr
    push {\native_reg, lr}
    ldr pc, =\resume
.endm
#ifdef SSTV_TX_STUDY
.global sstv_tx_source_hook
.global sstv_tx_request_hook
sstv_tx_request_hook:
    push {r0-r3,r12,lr}
    bl sstv_tx_requested
    mov r1,r0,lsr #5
    str r1,[sp,#4]
    pop {r0-r3,r12,lr}
    ldr pc,=0x20109678

sstv_tx_source_hook:
    push {r1-r3,r12,lr}
    mrs r2,cpsr
    push {r2}
    bl sstv_tx_source
    pop {r2}
    msr APSR_nzcvq,r2
    pop {r1-r3,r12,lr}
    ldrb r0,[r0,r1]
    ldr pc,=0x20060d2c

rx_only_handler sstv_pict_tx, r4, 0x200c4624
.global sstv_tx_all
sstv_tx_all:
    push {r0-r3, r12, lr}
    bl sstv_tx_toggle
    cmp r0, #0
    pop {r0-r3, r12, lr}
    movne r0, #2
    bxne lr
    push {r3, lr}
    ldr pc, =0x200c46d0
#else
rx_only_handler sstv_pict_tx, r4, 0x200c4624
rx_only_handler sstv_tx_all, r3, 0x200c46d0
#endif
#endif

#ifdef SSTV_TX_STUDY
.global sstv_tx_detail_draw
sstv_tx_detail_draw:
    push {r0-r3, r12, lr}
    bl sstv_tx_detail_active
    cmp r0, #0
    pop {r0-r3, r12, lr}
    ldreq pc, =0x2018e7e8
    @ Continue after the original photo draw and the DV grid and block marker.
    ldr lr, =0x201901c0
    ldr pc, =0x2018e7e8

.global sstv_tx_mode_button
sstv_tx_mode_button:
    push {r0-r3, r12, lr}
    bl sstv_tx_mode_open
    cmp r0, #0
    pop {r0-r3, r12, lr}
    movne r0, #1
    bxne lr
    push {r1-r5, lr}
    ldr pc, =0x200c4d94
#endif

#ifdef SSTV_LATE_JOIN
.global sstv_archive_button
sstv_archive_button:
    push {r0-r3, r12, lr}
    bl sstv_archive_open
    cmp r0, #0
    pop {r0-r3, r12, lr}
    movne r0, #1
    bxne lr
    push {r4, lr}
    ldr pc, =0x200c4940
#endif
