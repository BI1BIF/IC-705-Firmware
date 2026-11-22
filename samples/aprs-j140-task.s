.syntax unified
.arm
.text
.align 2

.global aprs_j140_dma_done
.type aprs_j140_dma_done, %function
aprs_j140_dma_done:
    push    {r0-r3, r12, lr}
    mrs     r0, cpsr
    push    {r0, r1}
    bl      aprs_note_dma
    pop     {r0, r1}
    msr     cpsr_f, r0
    pop     {r0-r3, r12, lr}
    pop     {r4, r5, r6, lr}  @ displaced 0x200ffd38
    ldr     pc, =0x200ffd3c
.size aprs_j140_dma_done, .-aprs_j140_dma_done

.global aprs_j140_record_step
.type aprs_j140_record_step, %function
aprs_j140_record_step:
    push    {r4, lr}
    ldr     r12, =0x20110384   @ native record and receive step
    blx     r12
    push    {r0-r3, r12, lr}
    mrs     r0, cpsr
    push    {r0, r1}
    bl      aprs_record_receive
    pop     {r0, r1}
    msr     cpsr_f, r0
    pop     {r0-r3, r12, lr}
    pop     {r4, pc}
.size aprs_j140_record_step, .-aprs_j140_record_step
