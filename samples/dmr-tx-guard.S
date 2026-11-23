.syntax unified
.arm
.text
.global dmr_tx_guard
dmr_tx_guard:
    ldr     r0, =DMR_RX_ENABLE
    ldrb    r0, [r0]
    adr     r1, dmr_guard_held
    ldrb    r2, [r1]
    orrs    r2, r2, r0
    beq     stock_filter
    ldr     r2, =0x203809ac
    ldr     ip, [r2]
    orr     r0, ip, r0
    /* The original wired MICPTT debounce can take 35 clock ticks. */
    ldr     ip, =0x203e1e6b
    ldrb    ip, [ip]
    orrs    r0, r0, ip
    movne   r0, #1
    strb    r0, [r1]
    beq     stock_filter
    mov     r0, #0
    str     r0, [r2, #4]
    bx      lr
stock_filter:
    push    {r3-r11, lr}
    ldr     pc, =DMR_FILTER_RESUME
.ltorg
/* The resident module resides in writable CPU RAM. Cold and warm load reset the latch. */
dmr_guard_held:
    .word   0
