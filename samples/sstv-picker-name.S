.syntax unified
.arm
.text
.global sstv_picker_name
sstv_picker_name:
    @ A paired FAT entry has already supplied the short filename, size and dates.
    @ Keep its name when a long name fills the native filename field.
    ldrb r2, [r1, #12]
    cmp r2, #27
    blo stock_name
    ldr r2, =0x20828170
    ldr r2, [r2]
    cmp r2, #0
    beq stock_name
    ldr r2, =0x203e84c9
    ldrb r3, [r2]
    cmp r3, #0x17
    ldrbeq r3, [r2, #1]
    cmpeq r3, #1
    bxeq lr
    b stock_name
    .ltorg
