.syntax unified
.arm
.text
.align 2

.macro entry name
.ifdef APRS_SLOT_BUILD
.section .text.\name,"ax"
.align 2
.endif
.global \name
.type \name, %function
\name:
.endm

@ Preserve flags and scratch registers while deciding who owns this stock window.
.macro if_owned fallback
    push    {r0, ip}
    mrs     ip, cpsr
    ldr     r0, =aprs_popup_owned
    ldrb    r0, [r0]
    cmp     r0, #0
    bne     1f
    msr     cpsr_f, ip
    pop     {r0, ip}
    b       \fallback
1:
    msr     cpsr_f, ip
    pop     {r0, ip}
.endm

.macro replace_strip base
    push    {ip, lr}
    mrs     ip, cpsr
    ldr     lr, =0x20393020
    cmp     \base, lr
    bne     1f
    ldr     lr, =0x203e2128
    ldrb    lr, [lr]
    lsr     lr, lr, #4
    cmp     lr, #7
    bne     1f
    ldr     lr, =aprs_channel_hz
    ldr     lr, [lr]
    cmp     lr, #0
    ldrne   \base, =aprs_strip
1:
    msr     cpsr_f, ip
    pop     {ip, lr}
.endm

entry aprs_strip_valid
    replace_strip r0
    ldrb    r0, [r0, #2]
    ldr     pc, =0x2004a910

entry aprs_strip_kind
    replace_strip r1
    ldrb    r1, [r1, #6]
    ldr     pc, =0x2004a930

entry aprs_strip_icon
    replace_strip r2
    ldrb    r1, [r2, #6]
    push    {ip}
    ldr     ip, =aprs_strip
    cmp     r2, ip
    pop     {ip}
    bne     1f
    tst     r1, #4
    movne   r0, #2           @ The position icon can outlive the call line.
    bxne    lr
1:
    ldr     pc, =0x2004a964

entry aprs_strip_draw
    replace_strip r4
    ldrb    r0, [r4, #3]
    ldr     pc, =0x2004b814

entry aprs_strip_clear
    replace_strip r4
    push    {ip}
    ldr     ip, =aprs_strip
    cmp     r4, ip
    moveq   r2, r4
    ldrbeq  r3, [r4]
    pop     {ip}
    cmp     r3, #0
    ldr     pc, =0x2004a0b4

entry aprs_strip_keep_position
    @ Clearing the brief call line must leave the latest APRS position accessible.
    push    {r0, ip}
    mrs     ip, cpsr
    ldr     r0, =aprs_strip
    cmp     r4, r0
    bicne   r1, r1, #4
    msr     cpsr_f, ip
    pop     {r0, ip}
    ldr     pc, =0x2004a0ec

entry aprs_strip_caption
    push    {r0-r3, ip, lr}
    bl      aprs_icon_without_call
    cmp     r0, #0
    pop     {r0-r3, ip, lr}
    ldrne   pc, =0x201633a4   @ The native icon stays visible without an empty RX: label.
    ldrb    r1, [r4, #1]
    ldr     pc, =0x20163350

entry aprs_position_request
    if_owned 2f
    cmp     r4, #1           @ own-position requests use their stock state
    ldrne   r0, =aprs_window_state
2:
    strb    r4, [r0, #79]
    ldr     pc, =0x20048540

entry aprs_position_timer_state
    if_owned 2f
    ldr     r4, =aprs_window_state
2:
    ldr     r5, =0x203806f7
    ldr     pc, =0x200485ac

entry aprs_position_timer_limit
    if_owned 2f
    mov     r0, #1
    ldr     pc, =0x20048618
2:
    ldrb    r0, [r0, #1001]
    ldr     pc, =0x20048618

entry aprs_position_clear
    if_owned 2f
    ldr     r1, =aprs_window_state
2:
    strb    r0, [r1, #79]
    ldr     pc, =0x20049380

entry aprs_position_reason
    if_owned 2f
    ldr     r1, =aprs_window_state
2:
    ldrb    r1, [r1, #79]
    ldr     pc, =0x20049390

entry aprs_position_leave
    if_owned 2f
    ldr     r0, =aprs_window_state
2:
    ldrb    r0, [r0, #79]
    ldr     pc, =0x20049730

entry aprs_position_prepare
    if_owned 2f
    ldr     pc, =0x20049698   @ native Back preparation
2:
    ldrb    r0, [r7]
    ldr     pc, =0x20049468

entry aprs_position_draw
    if_owned 2f
    b       aprs_j140_popup_body
2:
    mov     r2, #43
    ldr     pc, =0x201884ec

entry aprs_position_dv_data
    if_owned 2f
    push    {r0, ip}
    mrs     ip, cpsr
    ldr     r0, =0x20048320   @ native auto-open
    cmp     lr, r0
    ldrne   r0, =0x20048578   @ native icon request, via tail call at 0x2004833c
    cmpne   lr, r0
    ldrne   r0, =0x200493b0   @ native window refresh
    cmpne   lr, r0
    ldrne   r0, =0x200493f0   @ native detail draw snapshot
    cmpne   lr, r0
    bne     1f
    msr     cpsr_f, ip
    pop     {r0, ip}
    bx      lr
1:
    msr     cpsr_f, ip
    pop     {r0, ip}
2:
    push    {r4-r10, lr}
    ldr     pc, =0x20048010

entry aprs_position_reopen
    push    {r0-r3, ip, lr}
    bl      aprs_allow_position_touch
    cmp     r0, #0
    pop     {r0-r3, ip, lr}
    moveq   r0, #1
    bxeq    lr
    push    {r4, lr}
    ldr     pc, =0x200801c4

entry aprs_j140_panel_step
    push    {r4, lr}
    ldr     ip, =0x200964bc
    blx     ip
    push    {r0-r3, ip, lr}
    mrs     r0, cpsr
    push    {r0, r1}
    bl      aprs_update_panel
    pop     {r0, r1}
    msr     cpsr_f, r0
    pop     {r0-r3, ip, lr}
    pop     {r4, pc}

entry aprs_menu_empty_row
    push    {r0}
    movw    r0, #0xffff
    cmp     r5, r0
    pop     {r0}
    ldreq   pc, =0x200ce238
    cmp     r5, #0x47
    ldr     pc, =0x200cdd0c

entry aprs_selector_back
    push    {r0-r3, ip, lr}
    bl      aprs_back_from_mode
    cmp     r0, #0
    pop     {r0-r3, ip, lr}
    movne   r0, #4
    bxne    lr
    push    {r4, lr}
    ldr     pc, =0x200cd82c

entry aprs_gps_text
    movw    ip, #807
    cmp     r1, ip
    bne     1f
    ldr     ip, =0x203e84c9
    ldrh    ip, [ip]
    cmp     ip, #218
    bne     1f
    ldr     ip, =0x203804da
    ldrh    ip, [ip]
    cmp     ip, #0
    bne     1f
    ldr     ip, [sp, #12]
    push    {r0}
    mov     r0, #37
    strh    r0, [ip, #2]
    pop     {r0}
    ldr     ip, [sp, #16]  @ right-aligned stock setting value
    cmp     ip, #2
    bne     1f
    ldr     ip, =aprs_channel_hz
    ldr     ip, [ip]
    cmp     ip, #0
    beq     1f
    push    {r0-r3, ip, lr}
    bl      aprs_active_frequency
    cmp     r0, #0
    pop     {r0-r3, ip, lr}
    ldreq   r2, =aprs_gps_mode_paused
    moveq   r3, #13
    ldrne   r2, =aprs_gps_mode_name
    movne   r3, #4
1:
    ldr     pc, =0x20142698

entry aprs_gps_mode_select
    push    {r0-r3, ip, lr}
    bl      aprs_gps_mode_tap
    cmp     r0, #0
    pop     {r0-r3, ip, lr}
    bxne    lr
    push    {r4-r6, lr}  @ displaced selector dispatch prologue
    ldr     pc, =0x200a34c0

entry aprs_gps_mode_highlight
    ldrb    r7, [r0]
    ldr     ip, =0x203eb172
    cmp     r0, ip
    bne     1f
    ldr     ip, =aprs_channel_hz
    ldr     ip, [ip]
    cmp     ip, #0
    movne   r7, #3
1:
    ldr     pc, =0x200a25e0

entry aprs_tx_request_hook
    push    {r0-r3, ip, lr}
    bl      aprs_tx_requested
    mov     r1, r0, lsr #5
    str     r1, [sp, #4]
    pop     {r0-r3, ip, lr}
    ldr     pc, =0x20109678

entry aprs_tx_source_hook
    push    {r1-r3, ip, lr}
    mrs     r2, cpsr
    push    {r2}
    bl      aprs_tx_source
    pop     {r2}
    msr     cpsr_f, r2
    pop     {r1-r3, ip, lr}
    ldrb    r0, [r0, r1]
    ldr     pc, =0x20060d2c

entry aprs_comment_editor_hook
    push    {r4, lr}
    bl      aprs_load_comment_editor
    cmp     r0, #0
    pop     {r4, lr}
    bxne    lr
    push    {r2, r3, r4, lr}
    ldr     pc, =0x20052fb4

.section .rodata
.balign 4
.global aprs_quick_menu
aprs_quick_menu:
    .word   0, 0, 0, 0, 0
.global aprs_history_descriptor
aprs_history_descriptor:
    .word   0
.global aprs_settings_descriptor
aprs_settings_descriptor:
    .word   0
.global aprs_symbol_descriptor
aprs_symbol_descriptor:
    .word   0
aprs_gps_mode_paused:
    .asciz  "APRS (Paused)"
