.syntax unified
.arm
.fpu neon
.text
/* Four J140 application callbacks chain to the existing CW/SSTV handlers. */
.macro save
    push {r0-r3,r12,lr}
    mrs r0,cpsr
    push {r0,r1}
.endm
.macro restore
    pop {r0,r1}
    msr APSR_nzcvqg,r0
    pop {r0-r3,r12,lr}
.endm
.global ftx_pcm_bridge
ftx_pcm_bridge:
    save
    add r0,sp,#40
    bl ftx_audio
    restore
    b previous_pcm
.global ftx_input_bridge
ftx_input_bridge:
    save
    bl ftx_input
    restore
    b previous_input
.global ftx_prepare_bridge
ftx_prepare_bridge:
    save
    bl ftx_prepare_frame
    restore
    b previous_prepare
.global ftx_touch_bridge
ftx_touch_bridge:
    save
    bl ftx_touch
    cmp r0,#0
    beq 1f
    restore
    mov r0,#0
    ldr pc,=0x2007f110
1:  restore
    b previous_touch
.global ftx_frame_bridge
ftx_frame_bridge:
    save
    vpush {d0-d7}
    vpush {d16-d31}
    vmrs r0,fpscr
    push {r0,r1}
    bl ftx_frame
    pop {r0,r1}
    vmsr fpscr,r0
    vpop {d16-d31}
    vpop {d0-d7}
    restore
    b previous_frame

.global ftx_cw_bridge
ftx_cw_bridge:
    b ftx_cw_work


.section .station,"ax"
.macro ft_tail name
.global \name\()_arm
\name\()_arm:
    ldr ip,=\name
    bx ip
.endm
ft_tail ft_tx_source
ft_tail ft_tx_requested
ft_tail ft_tx_mod_block

/* Scatter-load the appended selector rows without needing a stack. A low
   length copies from an earlier restored row, a high length from the stream. */
.section .ft_extra,"ax"
.thumb
.thumb_func
.global ft_restore_modes
ft_restore_modes:
1:  ldrb r3,[r0],#1
    cbz r3,5f
    cmp r3,#128
    bhs 3f
    ldrb ip,[r0],#1
    ldrb r2,[r0],#1
    add.w r2,ip,r2,lsl #8
    sub.w r2,r1,r2
2:  ldrb ip,[r2],#1
    strb ip,[r1],#1
    subs r3,#1
    bne 2b
    b 1b
3:  subs r3,#128
4:  ldrb ip,[r0],#1
    strb ip,[r1],#1
    subs r3,#1
    bne 4b
    b 1b
5:  bx lr
