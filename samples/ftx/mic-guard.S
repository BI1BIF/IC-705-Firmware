.syntax unified
.cpu cortex-a9
.thumb

.section .text.operating_bridge,"ax",%progbits
.thumb_func
ft_mic_inhibit:
    /* Keep the radio inhibit bits and use the native sampled P5_5 MICPTT. */
    tst.w r0,#0xc0
    bne 1f
    ldr r0,=0x203e1e6b
    ldrb r0,[r0]
    cmp r0,#0
1:  bx lr
.ltorg

.section .hook_2037ad3e,"ax",%progbits
    bl ft_mic_inhibit
    .hword 0xd117 /* Existing BNE to the inhibit branch. */
