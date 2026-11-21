/* Fit the shared AF rectangle test into the two existing v1.3.2 callers.
   r4/r5/r6/r7 in finish are left, pixels, top and right respectively. */
.syntax unified
.cpu cortex-a9
.thumb
.section .af_draw,"ax"
draw_start:
    bl af_top
    cmp.w r0,#272
    beq.w draw_start + (0x2037c7bc - 0x2037c730)
    str r0,[sp]
    movs r4,#118
    movs r1,#0
    mov r2,r6
    mov r3,r4
    mov r0,r5
    bl draw_start + (0x2037ed84 - 0x2037c730)
    b.w draw_start + (0x2037c754 - 0x2037c730)

.section .af_touch,"ax"
touch_start:
    cmp r4,#118
    bhs.w touch_end
    bl af_top
    cmp r5,r0
    blo.w touch_end
    cmp.w r5,#272
    blo.w touch_start + (0x2037443a - 0x20374450)
touch_end:
    /* At 24 bytes this falls through to touch_rest. */
