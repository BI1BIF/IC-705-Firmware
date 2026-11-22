.syntax unified
.arm
.text
.align 2
.global aprs_j140_popup_body
.type aprs_j140_popup_body, %function
aprs_j140_popup_body:
    cmp     r6, #0
    ldreq   pc, =0x20188dd4    @ native partial redraw, including Back state
    push    {r0-r3, r12, lr}
    bl      aprs_draw_popup
    pop     {r0-r3, r12, lr}
    ldr     pc, =0x20188e30    @ continue at the native Back button
.size aprs_j140_popup_body, .-aprs_j140_popup_body

.global aprs_compass_arrow_upload
.type aprs_compass_arrow_upload, %function
aprs_compass_arrow_upload:
    ldr     ip, =0xff0000fe
    cmp     r9, ip
    beq     aprs_upload_filtered_arrow
    ldr     ip, =0x202639eb
    bx      ip
.size aprs_compass_arrow_upload, .-aprs_compass_arrow_upload
