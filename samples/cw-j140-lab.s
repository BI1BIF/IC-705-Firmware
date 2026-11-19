.syntax unified
.arm
.text

.ifdef CW_MERGED_ENTRY
.balign 4
.global cw_picker_choice
cw_picker_choice:
    .word 0

.global cw_picker_empty_row
cw_picker_empty_row:
    movw r0, #65535
    cmp r5, r0
    ldreq pc, =0x200ce238 @ Preserve the blank marker without indexing the table at 0xffff.
    cmp r5, #71         @ Reissue the stock comparison for real rows.
    ldr pc, =0x200cdd0c
.endif

.macro save
    push {r0-r4, lr}
    mrs r4, cpsr
    push {r4, r5}
.endm

.macro restore
    pop {r4, r5}
    msr APSR_nzcvqg, r4
    pop {r0-r4, lr}
.endm

.macro skip_before_cw_init label
    .ifdef CW_SIM_BOOT
    ldr r4, =cw_state_anchor
    ldr r4, [r4]
    cmp r4, #0
    beq \label
    .endif
.endm

.global cw_touch_bridge
cw_touch_bridge:
    save
    skip_before_cw_init 1f
    bl cw_lab_touch
    cmp r0, #0
    beq 1f
    restore
    mov r0, #0
    ldr pc, =0x2007f110
1:
    restore
    @ Reissue the stock BL at 0x2007f10c for all other samples.
    ldr lr, =0x2007f110
    ldr pc, =0x201085fc

.global cw_input_bridge
cw_input_bridge:
    save
    skip_before_cw_init 1f
    bl cw_lab_input
1:
    restore
    @ Reissue the stock BL at 0x2007f1a4.
    ldr lr, =0x2007f1a8
    ldr pc, =0x2007d4f4

.global cw_pcm_bridge
cw_pcm_bridge:
    save
    skip_before_cw_init 1f
    add r0, sp, #40
    bl cw_lab_pcm
1:
    restore
    @ Reissue the stock MOV at 0x2010feac, then resume.
    mov r4, #0
    ldr pc, =0x2010feb0

.ifdef CW_RX_DIAGNOSTICS
.global cw_diag_raw_bridge
cw_diag_raw_bridge:
    save
    skip_before_cw_init 1f
    add r0, sp, #64             @ Original SP + 32, before the stock 6:1 copy.
    bl cw_diag_raw
1:
    restore
    ldr r0, [sp, #4]           @ Original AUDIO SCOPE flag load.
    ldr pc, =0x2010fe38
.endif

.ifdef CW_RTX_DRAW
.global cw_rtx_draw_bridge
cw_rtx_draw_bridge:
    save
    skip_before_cw_init 1f
    push {r5, r12}
    vpush {d0-d7}
    vpush {d16-d31}
    vmrs r4, fpscr
    push {r4, r5}
    bl cw_rtx_draw
    pop {r4, r5}
    vmsr fpscr, r4
    vpop {d16-d31}
    vpop {d0-d7}
    pop {r5, r12}
1:
    restore
    @ Reissue the load immediately after stock frame composition.
    ldr r0, =0x20380c98
    ldr pc, =0x2013d4ac
.endif

.ifdef CW_SIM_BOOT
.global cw_sim_boot
cw_sim_boot:
    save
    and r0, r4, #0xbf
    cmp r0, #0x1f
    bne 2f
    skip_before_cw_init 1f
    b 2f
1:
    ldr r0, =0x20381e90
    ldr r0, [r0]                @ Current RTX thread
    cmp r0, #0
    beq 2f
    ldrb r0, [r0, #2]
    cmp r0, #0xf4               @ Original main task
    bne 2f
    ldr r0, =0x20380cc4
    ldr r0, [r0]                @ UI thread created by stock startup
    cmp r0, #0
    beq 2f
    ldrb r0, [r0, #2]
    cmp r0, #0xee
    bne 2f

    mov r0, #5120
    ldr ip, =0x20127a28
    blx ip
    cmp r0, #0
    beq 2f
    mov r5, r0
    mov r1, #0
    mov r2, #5120
3:
    subs r2, r2, #4
    str r1, [r5, r2]
    bne 3b
    add r0, r5, #0x700
    ldr r2, =cw_rtx_worker
    str r2, [r0, #4]           @ State + 0x704: original RTX thread descriptor.
    mov r2, #0xe8
    str r2, [r0, #8]
    mov r2, #1
    str r2, [r0, #12]
    mov r2, #4096
    str r2, [r0, #16]
    add r0, r0, #4
    ldr ip, =0x202d48c1
    blx ip
    cmp r0, #0
    beq 4f
    str r0, [r5, #0x700]
    ldr r4, =cw_state_anchor
    str r5, [r4]
    b 2f
4:
    mov r0, r5
    ldr ip, =0x20127a78
    blx ip
2:
    restore
    @ Resume the displaced original BL at 0x200d4ef0.
    ldr lr, =0x200d4ef4
    ldr pc, =0x2011df40
.endif
