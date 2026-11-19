# CW 默认选音与长静默：电脑修复记录

2026-11-18。此轮承接 [D5 内测审核](IC705_CW_D5_AUDIT.md)，在电脑修改接收译码及触摸唤醒、构建 PC 候选并验证。电脑研究阶段没有生成新 DAT；随后按用户指示将同一 RX3 静态导出为 [D6 唤醒测试包](IC705_CW_RELEASE.md#d6-黑屏唤醒测试版)，默认保持 D5 WIDE，失败默认方案未混入。原 D5 DAT 保留；没有重新执行升级／开机或操作电台。

## 当前结论：默认选音未通过，撤回默认改动

**黑屏唤醒修复和 AUTO 长静默改善可以分别保留，新的默认选音不能交付。** RX1 默认 AUTO 在第一份独立实录上增加总错；RX2 默认 FIX 跟随原厂 CW Pitch，在另一份独立弱台冷启时漏字，并对独立设备干扰多报字。两次失败均保留，没有改变参考、门槛或用这些结果继续调参。

当前源码已恢复 D5 原默认 WIDE，冻结为 `CW-RX3-WAKE2-PC.ic705sim`。这是**局部修复电脑候选**，只保留 AUTO 长静默重获规则和 [黑屏唤醒修复](IC705_CW_BACKLIGHT.md)。默认有声不出字的覆盖缺口仍在，不是已经解决后仅等真机。AUTO、FIX、WIDE 仍可在本次会话手选；同一镜像已静态导出 D6，独立解包与原验收主程序逐字节一致，默认方案的失败结论不变。全部六个编译输入及工具链记录在 [RX3 build.json](../.analysis/cw-reacquire-1118/CW-RX3-WAKE2-PC/build.json)。

## RX2：围绕原厂中心的默认方案仍失败

RX2 在开页时读取原厂 CW Pitch 的 300–900 Hz，选择已有 FIX；异常值回退 600 Hz，原厂设置只读。这个方案不追较强邻台。[原厂 CI-V 指令回放](../.analysis/cw-reacquire-1118/wide-study/stock-pitch-evidence.json)确认原厂把 Hz 存在 `0x203eb127/128`；两个 U8 拼读避免 C 的未对齐指针。独立合成研究和最终 RX2 机器码的 36 个中心／弱音／短应答／变速案例均通过，实际开页、退出重入和原厂画面也通过，但这些不能代替自然实录验收。

新保留集在任何解码前冻结参考和原始幅度 PCM。唯一能够完整独立转写的自然弱台是 EA6VQ 收到的 144 MHz 弱信标 `F5XAL JN12LL`，不是短波弱应答；另一份是 ARRL/W1RFI 电热毯 USB 干扰。目标音调由原音独立测为约 492 Hz，统一在电脑设原厂 Pitch 490 Hz，模拟用户对准中心；不知道原录音接收机的实际 Pitch。冷启与训练后静默 12 秒使用同一自然正文，不是两份独立来报。

| 独立正文／历史 | D5 原默认 WIDE | D5 手选 AUTO | RX2 新默认 FIX | 判定 |
| --- | --- | --- | --- | --- |
| 弱信标冷启，参考 11 字符 | `SXAL JN12LL`，2 错 | 完整正确 | `HXALJN12LL`，1 替换 + 1 漏字 | 失败：相对 AUTO 多漏 1 字、总错多 2 |
| 同信标，训练后静默 | 完整正确 | 完整正确 | 完整正确 | 通过 |
| 无来报设备干扰冷启 | 0 误字 | 0 误字 | `E E E E E`，5 误字 | 失败 |
| 同干扰，训练后静默 | 0 误字 | 0 误字 | 0 误字 | 通过 |

RX2 默认 2/4 通过，AUTO 控制 4/4 与 D5 AUTO 逐字相同。D5 手选 FIX 的四份输出也与 RX2 FIX 相同，问题是把已有 FIX 作为默认没有达到约定质量门槛，不能归咎于唤醒补丁破坏了 FIX。20 次 exact worker 回放均零丢组、状态哨兵及原厂 Pitch／频率／KEYER 字节不变。主评分只去空格，保留所有 `~` 和标点，统计替换／漏字／增字；完整逐字事件、对齐和空格评分均保留。

[独立报告](../.analysis/cw-reacquire-1118/holdout-next/REPORT.md) · [逐项判定](../.analysis/cw-reacquire-1118/holdout-next/comparison.json) · [冻结协议](../.analysis/cw-reacquire-1118/acceptance-rx2-plan.json)。清单 SHA-256 `3c255497694795ac26bfbd7a5da18684bc691c91ec0ff66aa73392ba2ef65294`，基线 `32ef37643303d08552304495422c73a21fddcb2c4b4407b8f61ab6a967bdafd0`，候选 `fd1dbba7657f82b42336536f804b15d7c4be6c8b9589e7fe4bce3c006ba076a0`。另三份弱/QSB 来源因无法可靠独立转写，解码前排除，不计作额外弱台验收。

## RX3：回退默认后的局部修复

RX3 移除原厂 Pitch helper 及两个入口新增的 FIX 赋值，恢复与 D5 相同的默认和 EXIT 行为。`cw-j140-lab.c` 相对 D5 仅增加原厂唤醒优先的 8 行；`cw-arm.c` 保留长静默重获规则，另四个传递输入与 D5 相同。不会把 RX2 的 36 个默认 FIX 成绩冒充 RX3 默认 WIDE 通过。

[22 项整合](../.analysis/cw-reacquire-1118/integration/subset-exact-evidence.json)已实际执行 RX3 原默认进入、600 Hz 正文、手选 AUTO 的 300/600/1000/1250 Hz、静默保速、LOCK/MANUAL、换档丢旧队列、EXIT 重开和 KEYER 回调。状态保持 5 KiB，Decoder 仍 88 字节，无新增分配。候选 bundle SHA-256 `e5aed9437d46df0835fe9350f6ec9eac027cdae03ed653b6e433d104bce71c88`，main `8a5aa8c6083fb49dc6889871357dcd4cdb98eb7bda70d384c0f00f321d9c4aa6`。

保留的 AUTO 规则只在自动门限、自动速度下生效：已训练、连续 3 秒无载音后重新检查噪声，保留报速和首字，三个符合时序的完整点划后恢复普通跟踪。FIX、手动门限、LOCK/MANUAL 不使用此规则。开发干扰仍是 15→6 误字，**不是零误报，也不是全体自然弱台改善**。

[RX3 最终 25 项 AUTO 控制](../.analysis/cw-reacquire-1118/wide-study/rx3-auto25-evidence.json)已通过：与 RX2-WAKE2 的 PCM SHA、逐字事件、完整输出和组数全相同，22 项短／弱／变速／旁路正文零错，开发干扰仍 6 字，LOCK/MANUAL 干扰各 21 字保持原样。[源码子集核对](../.analysis/cw-reacquire-1118/wide-study/rx3-source-evidence.json)确认当前六源 = RX3 快照 = 构建清单，回退没有留下原厂 Pitch 依赖。

同一 RX3 的 [17 项唤醒手势](../.analysis/cw-backlight-1118/wake3/gestures.json)、[30 个状态对照](../.analysis/cw-backlight-1118/wake3/phases.json)及 [15 个原厂 UI 检查点](../.analysis/cw-backlight-1118/wake3/native/evidence.json)通过。原厂频率可由 7.030 MHz 调至 7.030320 MHz 再调回，SET／速度／KEYER／EXIT 正常。[总索引](../.analysis/cw-reacquire-1118/acceptance-partial.json)明确标记 `PARTIAL_PC_FIX_ONLY`，固定六源、每份证据摘要及官方/D5 DAT 未变；这不是默认质量或真机全部通过。

## RX1：开发通过，独立验收未通过

**RX1 不能作为通过验收的新默认版交付。** 直接把默认 WIDE 换成 FILTER AUTO，确实补上了部分音调整段不出字的问题，但独立实录上出现更多错字。长静默规则有局部改善，尚不能称为消除误报或完成自然弱台专项。

| 检查 | 实测结果 | 含义 |
| --- | --- | --- |
| 默认选音、300/600/1000/1250 Hz 的合成 `CQ TEST` | 精确完整候选均正确；原 D5 WIDE 在 300/1000/1250 Hz 空白 | 证明这些测试音调可接收，不证明噪声下默认行为更好 |
| 已训练 `CQ TEST`、静默 10 秒、同相位 30 秒开发干扰 | 非空白误字 15 → 6，减少 60% | 仅限这段已参与开发的输入，仍有 6 字误报 |
| 开发短应答、弱码、短衰落、变速及旁路 | 25 项完整候选重放通过；其中 22 项正文零字符错，另两项固定速度干扰各 21 误字、保持原样 | 短首字未被统一丢弃；合成弱码不等于自然弱台 |
| 独立自然 `MDR` 实录，冷启／长静默 | D5 WIDE 总编辑数各 3；D5 AUTO 与 RX1 各 2 | 有限改善，仍错漏 |
| 独立自然 `DX DE` 实录，冷启／长静默 | D5 WIDE 总编辑数各 4；D5 AUTO 与 RX1 各 6 | 两例失败；漏字少了，但多字及总错增加，不能据此宣布通过 |
| 独立队列回放 | 42 次、1,346,118 组六采样，零丢组，状态尾哨兵保留 | 直接输入 worker 队列的边界，不是硬件实时性测试 |
| 整合及原厂 UI | 精确整合 21 项、原厂 UI 16 项通过；双 LCD bank、调频、KEYER、手动滤波、EXIT 重开 | 没有证明实体帧率、全固件无缺陷或黑屏触摸正常 |

独立验收共 14 项，12 项通过。新候选的 14 项输出均与 D5 手动选择 AUTO 时相同。新录音的作者描述经复核为**强信号伴 QSB**，初始来源说明有误；冻结清单未覆盖，另存来源更正。不能将它写成已经完成自然弱台验收。后续真正弱信号保留集及其失败见上文 RX2。

这 14 项并非 14 个全新独立自然来源：`noise7405` 尾段的零文本参考为暂定、中等置信，`noise2023` 是历史回归；合成及不同历史重复正文也另有标注。原始报告和更正保留，不能用汇总通过数扩大覆盖。

## RX1 历史改动和固定对象

`cw-j140-lab.c` 的两个进入分支和退出重置改用 FILTER AUTO；WIDE/FIX 仍可手选。`cw-arm.c` 在 AUTO、自动门限及自动速度组合中，收过来报又连续 3 秒无载音后重新启用原有捕获噪声检查，保留已学报速和首字；三个结束且与时序先验相符的点划后回到普通跟踪。没有增加全局音量门限。FIX、手动门限、LOCK、MANUAL 走原分支。

Decoder 仍为 88 字节，使用原保留字节；整块状态仍为 5 KiB，无新增分配。原厂字库、PCM 入口、收发保护、射频、绘图和 KEYER 未改变。两个进入分支中，实际日版合并入口已经执行，旧非合并入口仅作源码复核。

| 固定对象 | SHA-256 |
| --- | --- |
| RX1 电脑包 | `b0ee39a0b873983429d8603fccc7ab934046d61bfbda252427fee2e56aa17c91` |
| RX1 主程序 | `88ac251c088ce3373f2eab12f8b2ce869b6bf701343b27601d79470befbb6832` |
| 独立保留集清单 | `b6c3204067f1617847d489da755945f5dc45271de1477ee6e254390ffc62cb69` |
| 独立 D5 结果 | `785fa2a32ecac4abe0795c02e66953510a7c1dacf7cc8015697909461f8ebbda` |
| 独立 RX1 结果 | `d7401c7d7eb8308c4ed5e50af3f695cb7275f7cab26018597d42a793116a99d2` |

完整六个编译输入、源码快照、编译器文件摘要和编译／链接命令在 [build.json](../.analysis/cw-reacquire-1118/CW-RX1-PC/build.json)。所有测试均读取这份冻结主程序；独立验收没有重新编译解码器、用项目输出充当参考或拿结果追调当前候选。

## 证据与接续

- [开发规则及对照](../.analysis/cw-reacquire-1118/development/README.md)，完整候选 [25 项结果](../.analysis/cw-reacquire-1118/development/final-exact-evidence.json)。
- [独立验收报告](../.analysis/cw-reacquire-1118/holdout/REPORT.md)、[逐项评分](../.analysis/cw-reacquire-1118/holdout/comparison.json)、[来源更正](../.analysis/cw-reacquire-1118/holdout/provenance-erratum.json)。
- [整合复核](../.analysis/cw-reacquire-1118/integration/REVIEW.md)、[21 项及 16 项索引](../.analysis/cw-reacquire-1118/integration/verified.json)。

下一项质量门槛是：在保留已有弱台捕获能力和无来报对照的前提下，解决默认音调覆盖。先拆开“音调没覆盖”“初始几个点划被拒”“估速错误”三种原因，再提出一个可解释的窄改动；不能再简单把默认整体换成 AUTO 或 FIX。两轮已评分录音只能作为公开回归，下一次独立验收需要新的可靠转写来源，不得降低门槛改判。当前黑屏问题已另行定位并修复，见 [唤醒记录](IC705_CW_BACKLIGHT.md)；其电脑通过不替代解码质量通过。
