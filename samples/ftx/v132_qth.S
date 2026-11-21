.syntax unified
.cpu cortex-a9
.thumb
.section .row_site,"ax"
    mov r0,r4
    ldr r1,[sp,#28]             /* immutable DisplayRow */
    sub.w r2,r9,#15             /* Chinese glyph baseline */
    ldr r3,[sp,#40]             /* selected message tile offset: 208 or 432 */
    lsrs r3,r3,#8
    bl qth_row
    b.n . + (0x2037d6ce - 0x2037d698)

/* Publish the extra Thumb instructions copied alongside the FT constants. */
.balign 4
.global qth_copy
.thumb_func
qth_copy:
    push {r4,r5,r6,lr}
    add r5,r0,r2
    mov r4,r0                  /* FT constants are 32-byte aligned */
    bl memcpy
    mov r6,r4
1:  mcr p15,0,r4,c7,c11,1
    adds r4,#32
    cmp r4,r5
    blo 1b
    dsb sy
2:  mcr p15,0,r6,c7,c5,1
    adds r6,#32
    cmp r6,r5
    blo 2b
    dsb sy
    isb sy
    pop {r4,r5,r6,pc}
    .ltorg

/* Type the existing firmware entries as Thumb functions for the linker. */
.macro import_thumb symbol
.section .import_\symbol,"ax"
.global \symbol
.thumb_func
\symbol:
    nop
.endm
import_thumb memcpy
import_thumb sender_flag
import_thumb panel_word
import_thumb rectangle
import_thumb text
import_thumb __aeabi_uidiv
