/* J140 renderer call sites in Unicorn RAM. Preserve the stock instruction at each return. */
.syntax unified
.arm
.section .text.entries, "ax"

.macro save
    push {r0-r3,r12,lr}
    mrs r3, APSR
    push {r3,r4}
.endm

.macro resume
    pop {r3,r4}
    msr APSR_nzcvqg, r3
    pop {r0-r3,r12,lr}
.endm

.macro selection name, count, next
    .global \name
\name:
    save
    mov r1, \count
    bl apply
    cmp r0, #0
    movne \count, r0
    ldrne r1, =0x204C9FC0
    strne r1, [sp, #8]
    resume
    mov r4, r0
    ldr pc, =\next
.endm

.macro cleanup name, stack_bytes, next
    .global \name
\name:
    save
    bl restore
    resume
    add sp, sp, #\stack_bytes
    ldr pc, =\next
.endm

selection layout_select, r7, 0x20146868
selection draw_select, r5, 0x20146AE0
cleanup layout_finish, 8, 0x2014695C
cleanup draw_finish, 20, 0x20146B94

/* Stock callers only understand 0/1, including list builders that never read the packed UI bits. */
.global compat_display_preview
compat_display_preview:
    push {r2}
    mrs r2, APSR
    cmp r0, #2
    moveq r0, #1
    msr APSR_nzcvqg, r2
    pop {r2}
    bx lr

/* Retain a separate render mode without widening the stock display or system bits. */
.global sync_display_preview
sync_display_preview:
    push {r2,r3,r12,lr}
    mrs r2, APSR
    mov r12, r0
    cmp r0, #1
    ldreq r3, =0x203EAE44
    ldrbeq r3, [r3]
    cmpeq r3, #2
    moveq r12, #2
    ldr r3, =0x2100AFFC
    str r12, [r3]
    bfi r1, r0, #1, #1
    msr APSR_nzcvqg, r2
    pop {r2,r3,r12,lr}
    ldr pc, =0x20095E98
.ltorg
