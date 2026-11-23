/* FT uses the signed minutes behind the original SET > Time Set > UTC Offset.
 * All sections replace existing FT code in the J140/E140 v1.4.0 images. */
.syntax unified
.cpu cortex-a9
.thumb
.equ stock_offset, 0x203eae88

.section .stamp,"ax"
    ldrsh.w r3, [r3]          /* literal in .offset_ptr; r4 is local minutes */
    nop
    nop

.section .offset_ptr,"a"
    .word stock_offset

.section .touch,"ax"
    b.w ignore_touch          /* offset is now changed in the factory settings */

.section .display,"ax"
    add r5, sp, #16           /* original caller's 14-byte label buffer */
    adr r1, zone
    mov r0, r5
    movs r2, #14
copy_zone:
    ldrb r3, [r1], #1
    strb r3, [r0], #1
    subs r2, #1
    bne copy_zone
    movw r3, #:lower16:stock_offset
    movt r3, #:upper16:stock_offset
    ldrsh.w r4, [r3]
    cmp r4, #0
    bge magnitude
    negs r4, r4
    movs r3, #45
    strb r3, [r5, #7]
magnitude:
    movs r1, #0
hours:
    cmp r4, #60
    blo minutes
    subs r4, #60
    adds r1, #1
    b hours
minutes:
    add r0, r5, #8
    bl number2
    add r0, r5, #11
    mov r1, r4
    bl number2
    b.w show_zone
.balign 4
zone:
    .asciz "RTC UTC+00:00"

.macro import_thumb name
.section .import_\name,"ax"
.thumb_func
\name:
.endm
import_thumb ignore_touch
import_thumb number2
import_thumb show_zone
