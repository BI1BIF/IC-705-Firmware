.syntax unified
.arch armv7-a
.arm
.global demo
.type demo,%function
demo:
    mov r0, #7
    bx lr
.size demo, . - demo
