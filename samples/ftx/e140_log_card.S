/* Small overlays for the published E140 TX2j layout. The original PICTURE
   media check returns 0 when its file operation may proceed, 1 otherwise. */
.syntax unified
.cpu cortex-a9
.thumb
.text
.macro edit name, address
    .org \address-0x203744ec
    .global edit_\name
edit_\name:
.endm
.macro done name
    .size edit_\name, .-edit_\name
.endm

edit feedback, 0x203744ec
detail_available:
    ldr r3, [r4,#1548]          /* pending count */
    ldr r2, [r4,#1596]          /* last I/O failed */
    orrs r3,r2
    ite eq
    ldrbeq r3,[r4,#1213]        /* cached contact text */
    movne r3,#0
    bx lr
status:
    ldr r1,[r4,#1612]
    cmp r1,#1
    beq busy
    ldr r1,[r4,#1600]          /* last media check */
    cbz r1,no_card
    ldr r1,[r4,#1596]
    cbnz r1,failed
    ldr r1,[r4,#1548]
    cbz r1,empty
    ldr r0,=0x20825376         /* existing 待存卡 label */
empty:
    bx lr
busy:
    adr r0,busy_text
    bx lr
failed:
    adr r0,fail_text
    bx lr
no_card:
    adr r0,card_text
    bx lr
retry_row:
    ldr r3,[r4,#1612]
    cmp r3,#1
    beq.w end_draw
    ldr r3,[r4,#1548]
    b.w draw_retry
.balign 4
busy_text: .asciz "SD busy"
fail_text: .asciz "SD error"
.balign 4
card_text: .asciz "Check SD"
.ltorg
done feedback

edit poll, 0x2037dd26
    blx stock_sd_check
    mov r8,r0
    eor r5,r0,#1
    ldr.n r3,poll_radio_ptr
    ldr.w r0,[r3,#1556]        /* stock frequency argument to log_band */
    nop
    nop
done poll
edit poll_gate, 0x2037dd8a
    cmp.w r8,#0
done poll_gate
.org 0x2037deb0-0x203744ec
poll_radio_ptr:
edit detail, 0x2037df6c
    bl detail_available
done detail
edit retry, 0x2037e000
    b.w retry_row
done retry
draw_retry:
.org 0x2037e01e-0x203744ec
end_draw:
edit label, 0x2037e02c
    mov r0,r5                   /* existing 暂无通联 label */
    bl status
    movs r1,#8
    movs r2,#125
    movs r3,#14
    nop
    nop
    nop
done label
edit worked, 0x2037e676
    blx stock_sd_check
    cmp r0,#0
    nop
done worked
edit prefs, 0x2037e7ce
    blx stock_sd_check
    cmp r0,#0
done prefs
