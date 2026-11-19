.syntax unified
.arm
.text

@ Emulator-only entry called by the stock RTX thread startup.
.global cw_rtx_worker
cw_rtx_worker:
    ldr r4, =0x202d488c
.global cw_rtx_wait
cw_rtx_wait:
    mov r0, #1
    mvn r1, #0
    blx r4
    cmp r0, #8
    bne cw_rtx_wait
1:
    mov r0, #64
    bl cw_lab_work
    cmp r0, #64
    beq 1b                     @ Recheck if it may still be nonempty.
    b cw_rtx_wait

.ifdef CW_RTX_ALLOC_STATE
.global cw_state_anchor
cw_state_anchor:
    .word 0                    @ Initialized before any bridge uses the session.
.endif
