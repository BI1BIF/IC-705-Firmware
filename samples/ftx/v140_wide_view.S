.syntax unified
.cpu cortex-a9
.thumb

.section .wide_number,"ax"
.global wide_number
.thumb_func
wide_number:
    /* FT rows contain an SNR, four-digit audio frequency or five-digit distance. */
    mov r3, r0
    subs r1, #7
    cmp r3, #0
    itt mi
    rsbmi.w r3, r3, #0
    submi.w r1, r1, #7
    cmp r3, #10
    blo 1f
    subs r1, #7
    cmp r3, #100
    blo 1f
    subs r1, #7
    cmp.w r3, #1000
    blo 1f
    subs r1, #7
    movw ip, #10000
    cmp r3, ip
    it hs
    subhs.w r1, r1, #7
1:  b.w resident_number

.section .number_import,"ax"
.global resident_number
.thumb_func
resident_number:
    nop
