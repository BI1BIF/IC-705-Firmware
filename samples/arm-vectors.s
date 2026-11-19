.syntax unified
.arm
.text
.global vectors
vectors:
    b handler
    ldr pc, handler_address
    b handler
    b handler
    b handler
    .word 0
    b handler
    b handler
handler_address:
    .word handler
handler:
    bx lr
