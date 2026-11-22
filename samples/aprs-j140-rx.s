.syntax unified
.arm
.text
.align 2
.global aprs_j140_rx
.type aprs_j140_rx, %function
aprs_j140_rx:
    push    {r0-r3, r12, lr}
    ldr     r0, =0x203e2128   @ VFO A receive mode
    ldrb    r0, [r0]
    lsr     r0, r0, #4
    cmp     r0, #7            @ FM
    bne     1f
    ldr     r0, =0x203809a1   @ original DSP status mirror
    ldrb    r0, [r0]
    tst     r0, #0x10         @ TX
    bne     1f
    add     r0, sp, #56       @ original SP+32, before the six-register push
    mov     r1, #36
    bl      aprs_rx_feed
    b       2f
1:
    bl      aprs_rx_gap
2:
    pop     {r0-r3, r12, lr}
    ldr     r0, [sp, #4]      @ original 0x2010fe34 instruction
    ldr     pc, =0x2010fe38
.size aprs_j140_rx, .-aprs_j140_rx
