.syntax unified
.thumb
.thumb_func
.global aprs_restore_picker
aprs_restore_picker:
    @ Scatter records are entered before the stack is initialized. Preserve
    @ r0/r1 (stream/destination), the scatter cursor and its return address.
    ldr r2, =__bss_start__
    ldr r3, =__bss_end__
    mov.w ip, #0
1:  cmp r2, r3
    bhs 2f
    str ip, [r2], #4
    b 1b
2:  ldr r2, =restore_picker_thumb
    bx r2

#include "aprs-overlay-layout.h"
.arm
.align 2
.global aprs_mode_tap, aprs_mode_highlight, aprs_mode_text
.global aprs_picker_open, aprs_native_open
aprs_picker_open:
    push {r0-r3,ip,lr}
    bl aprs_slot_restore_ui
    bl aprs_mode_closed
    pop {r0-r3,ip,lr}
aprs_native_open:
    push {r4-r6,lr}
    ldr pc,=OPEN_RESUME
aprs_mode_tap:
    push {r0-r3,ip,lr}
    bl aprs_mode_row
    cmp r0,#0
    pop {r0-r3,ip,lr}
    bxne lr
    push {r4-r6,lr}
    ldr pc,=MODE_RESUME
aprs_mode_highlight:
    ldrb r7,[r0]
    ldr ip,=0x203eb172
    cmp r0,ip
    bne 1f
    ldr ip,=bound_hz
    ldr ip,[ip]
    cmp ip,#0
    movne r7,#3
1:  ldr pc,=HIGHLIGHT_RESUME
aprs_mode_text:
    movw ip,#807
    cmp r1,ip
    bne 2f
    ldr ip,=0x203e84c9
    ldrh ip,[ip]
    cmp ip,#218
    bne 2f
    ldr ip,=0x203804da
    ldrh ip,[ip]
    cmp ip,#0
    bne 2f
    ldr ip,[sp,#16]
    cmp ip,#2
    bne 2f
    push {r0-r3,ip,lr}
    bl aprs_mode_label
    cmp r0,#0
    strne r0,[sp,#8]
    ldrne ip,=aprs_name
    cmpne r0,ip
    movne r1,#13
    moveq r1,#4
    cmp r0,#0
    strne r1,[sp,#12]
    pop {r0-r3,ip,lr}
2:  ldr pc,=DRAW_TEXT

.global aprs_slot_dma, aprs_slot_record
.macro preserve_call target
    push {r0-r3,ip,lr}
    mrs r0,cpsr
    push {r0,r1}
    bl \target
    pop {r0,r1}
    msr cpsr_f,r0
    pop {r0-r3,ip,lr}
.endm
aprs_slot_dma:
    preserve_call aprs_slot_note
    pop {r4-r6,lr}
    ldr pc,=DMA_RETURN
aprs_slot_record:
    push {r4,lr}
    ldr ip,=NATIVE_RECORD
    blx ip
    preserve_call aprs_slot_drain
    pop {r4,pc}

.global aprs_slot_panel
aprs_slot_panel:
    push {r4,lr}
    ldr ip,=NATIVE_PANEL
    blx ip
    preserve_call aprs_slot_update
    pop {r4,pc}
