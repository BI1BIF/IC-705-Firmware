# CW 窗口与黑屏唤醒

2026-11-18，日版 IC-705 1.40。用户反馈：使用电池、屏幕超时变黑后，点下方区域有提示音却不亮屏，点上方能亮。**已在电脑定位为触摸分派问题，并完成唤醒修复的专项验证；真机亮屏仍待下一次测试。**

CW 窗口先拿到了下方触摸并直接执行自己的按钮，原厂负责取消屏保、恢复显示和重置闲置计时的处理没有收到这次操作。上方触摸交回原厂，因此可以唤醒。这里的“占位”具体发生在输入处理顺序，不是增加窗口高度就能解决。

## 修复后的行为

- 有效的新触摸先运行原厂唤醒函数，再分派 CW 或原厂按键。
- 如果这次触摸用于唤醒，整次按住、移动、松手都只用于唤醒，不触发背后的 SET、HOLD/CLR 或上方模式键。
- 原厂屏保还在恢复时，后续点击也不落到隐藏按钮；恢复完成后的新一次点击照常操作。
- 正常点击 CW 同样重置原厂闲置计时。退出解码器、原厂设置和提示音开关沿用原逻辑。

生产修改只在 `samples/cw-j140-lab.c` 的 `cw_lab_touch`：先按原厂顺序调用 `0x20090630`、`0x20090a80(0)`；任一报告已消费，或 `0x20380721` 仍表示屏保恢复中，就将本手势标记为已处理。没有直接强制写亮度、背光 GPIO 或电源配置。

## 为什么增加恢复中保护

第一版 WAKE1 可以唤醒，但原厂屏保从 phase 1 进入恢复 phase 2 后，原厂函数不再重复返回“本次已唤醒”。这时松手再点，仍可能打开隐藏的 SET 或长按清屏。电脑实际反例保留在 [WAKE1 阶段对照](../.analysis/cw-backlight-1118/rx2-wake1-phase.json)，没有把该中间版算作通过。

WAKE2 补上原厂屏保活动标志，覆盖恢复中的再次点击。普通 LCD-off 分支在正常 CW 页会同步清除关闭标志并报告消费，未增加强制更改其私有状态的逻辑。

## 最终电脑结果

| 验收 | 结果 |
| --- | --- |
| D5 / 原厂上下区域对照 | 复现下方触摸绕过原厂唤醒，上方可进入原厂路径 |
| 首击、恢复中再击、长按、拖移、短空报告、正常按键及无效坐标 | 最终 RX3 的 [17 项手势](../.analysis/cw-backlight-1118/wake3/gestures.json)全部通过 |
| 原厂与 CW 的屏保 phase、上下位置 | [30 组对照](../.analysis/cw-backlight-1118/wake3/phases.json)无异常；12 组冷屏上下点击均被消费，没有暗中触发 CW SET/HOLD 或新增 CW 按键音 |
| 正常 SET、999/1000/1001 ms HOLD/CLR | 有效，单次按下不重复执行；唤醒手势不清译文 |
| 原厂 UI、原默认及正常操作 | [15 个原厂画面检查点](../.analysis/cw-backlight-1118/wake3/native/evidence.json)，覆盖两个 LCD bank；SET、速度、调频、KEYER、EXIT 和重入通过 |
| 同候选的开页、手动设置、速度、队列及状态边界 | [22 项整合](../.analysis/cw-reacquire-1118/integration/subset-exact-evidence.json)通过 |

最终局部修复电脑镜像是 `CW-RX3-WAKE2-PC.ic705sim`：bundle SHA-256 `e5aed9437d46df0835fe9350f6ec9eac027cdae03ed653b6e433d104bce71c88`，main SHA-256 `8a5aa8c6083fb49dc6889871357dcd4cdb98eb7bda70d384c0f00f321d9c4aa6`。[编译输入和源码快照](../.analysis/cw-reacquire-1118/CW-RX3-WAKE2-PC/build.json)固定全部六个输入及编译器，[最终校验索引](../.analysis/cw-backlight-1118/wake3/verified.json)与 [局部验收索引](../.analysis/cw-reacquire-1118/acceptance-partial.json)分别固定结果。当前只保留唤醒及 AUTO 长静默规则，默认恢复 D5 WIDE；不能用唤醒专项通过替代默认解码质量通过。

此前 RX2-WAKE2 的 17+30 手势/状态、7 个默认 FIX 原厂画面和 24 项整合均保留在 `wake2/` 和 `integration/center-wake2-exact-evidence.json`。但其默认 FIX 未通过独立自然录音，已撤回，不得作为新 DAT 来源。源码中的同一 WAKE2 修复已用最终 RX3 重新验证；完整经过见 [RX 修复记录](IC705_CW_RX_REACQUIRE.md)。

## 复现和边界

在项目根目录设置 `PYTHONPATH=.;.analysis/ic705-emulator/deps`，用现有 Python 3.14：

```powershell
python -X utf8 .analysis/cw-backlight-1118/probe_gestures.py --bundle .analysis/cw-reacquire-1118/CW-RX3-WAKE2-PC/CW-RX3-WAKE2-PC.ic705sim --symbols .analysis/cw-reacquire-1118/CW-RX3-WAKE2-PC/symbols.json --output .analysis/cw-backlight-1118/wake3/gestures-new.json
```

这是对冻结 ARM 指令、原厂输入分派及原厂唤醒函数的定向测试。初始黑屏状态和恢复完成通知由电脑提供，未等待真实电池超时，也没有物理 LCD、背光 PWM 或恢复耗时模型。详细方法、状态轨迹与图片保存在 `.analysis/cw-backlight-1118/`。REA 当前 Windows 原始 ARM 分析不满足本目标要求，沿用已建立的原厂解包、GNU 反汇编及 ARM 仿真路径，没有重复安装或修改工具配置。

上述电脑专项没有生成 DAT。随后按用户指示，将同一已验收 RX3 静态导出为 [D6 日版 1.40 测试包](IC705_CW_RELEASE.md#d6-黑屏唤醒测试版)，默认保持 D5 WIDE，未重新编译、重测升级和开机或操作电台。真机专项需要确认：电池超时后点上／下方都能唤醒，唤醒首击不误触按钮，第二次正常操作。尚未取得该实体反馈。
