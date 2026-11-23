.syntax unified
.cpu cortex-a9
.thumb

.section .text.operating_bridge,"ax",%progbits
.thumb_func
.global operating_list_page
operating_list_page:
    /* This view has already consumed its decode batch. Keep the transmit
       engine's page value while showing its state next to the receive list. */
    bl operating_after_decode
    ldr r3,=ft_page
    ldr r3,[r3]
    ldr r8,=cached
    cmp r3,#1
    it eq
    moveq r3,#0
    b.w view_page_compare

.thumb_func
.global operating_list_rail
operating_list_rail:
    bl operating_draw_rail
    b.w view_finish

.thumb_func
operating_clear:
    /* This code is already at its final address outside the clear spans. */
    add r2,r1,r2
    ldr r3,=operating_ram
    movs r0,#0
1:  str r0,[r1],#4
    cmp r1,r3
    blo 1b
    ldr r1,=operating_end
2:  str r0,[r1],#4
    cmp r1,r2
    blo 2b
    bx lr

.section .text.operating_boot,"ax",%progbits
.thumb_func
.global operating_boot
operating_boot:
    /* RF and graphic code are resident before the original scatter completes.
       The decompressed source lives in the OEM zero-fill interval. */
    ldr r0,=operating_payload
    ldr r1,=operating_ram
    ldr r2,=operating_end
1:  ldr r3,[r0],#4
    str r3,[r1],#4
    cmp r1,r2
    blo 1b
    ldr r1,=operating_ram
2:  mcr p15,0,r1,c7,c11,1
    add r1,#32
    cmp r1,r2
    blo 2b
    dsb sy
    movs r1,#0
    mcr p15,0,r1,c7,c5,0
    dsb sy
    isb
    ldr r1,=0x20381f44
    ldr r2,=0x004aeefc
    ldr pc,=operating_clear
