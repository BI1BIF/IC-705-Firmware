# IC-705 固件 · IC-705 Firmware

BI1BIF 的非官方 IC-705 固件研究项目。转换页支持 Icom 1.40 日版（J140）与欧／美版（E140），两版均提供 **CW D6 · SSTV RX4-TX4.1 · FT8/FT4 TX2j.1**。选择对应电台的原厂 DAT，浏览器会识别版本并在本地生成固件。

BI1BIF’s independent firmware research for the Icom IC-705. The converter supports Japanese (J140) and European/US (E140) Icom 1.40 firmware. Both include **CW D6 · SSTV RX4-TX4.1 · FT8/FT4 TX2j.1**. Select the original DAT for your radio to build its firmware locally in your browser.

**[打开固件转换页 · Open firmware converter](https://bi1bif.github.io/IC-705-Firmware/)**

## 电台功能 · Radio features

| 功能 / Feature | 中文 | English |
| --- | --- | --- |
| CW DECODE | 在 CW 模式下查看译文、速度和波形；点 HOLD/CLR 可冻结译文，长按清屏。 | Read decoded Morse text, speed and waveform in CW mode. Tap HOLD/CLR to freeze the text, or hold it to clear. |
| SSTV RX | 在 PICTURE → SSTV 自动识别模式，使用 SAVE/HIST 保存、回看图片。Robot 36 收到帧头后可在短暂衰落中保留行号。 | Open PICTURE → SSTV for automatic mode detection. SAVE/HIST saves and recalls images. After a valid header, Robot 36 retains the scan position through short fades. |
| SSTV TX | 从 SD 卡选图并确认，点 MODE 选模式，返回后点 SEND 发射。 | Select and confirm a photo from the SD card, choose a mode under MODE, then return and tap SEND. |
| FT8 / FT4 | MODE → FT8/4，十行收听、点选应答、主动 CQ、自动通联；日志存入 SD 卡。 | Open MODE → FT8/4 to decode, reply, call CQ and sequence contacts. Completed QSOs are logged to the SD card. |

**23 种收发模式 / 23 RX and TX modes**

Robot 36/72 · Martin M1–M4 · Scottie S1/S2/DX · Wraase SC2-180 · PD50/90/120/160/180/240/290 · BW 8/12/24 · Pasokon P3/P5/P7

TX3 已收到 CW 和 SSTV 的真机使用反馈。TX4 的 23 种发送模式已通过模拟面板点选和整帧音频验证，新增模式的逐项射频互收仍待完成。

Operators have tested CW and SSTV on hardware with TX3. All 23 TX4 modes passed emulated menu selection and full-frame audio tests. Over-the-air checks for the added modes are still pending.

## 更新日志 · Release notes

**2026-11-21 · SSTV RX4-TX4.1 · J140 / E140**

修正 SSTV 待机时隐藏的音量峰值反复请求界面重绘。模拟回放中，32 次峰值变化触发的多余重绘从 32 次降到 0；收图状态及进度仍会刷新。实际频谱流畅度待真机复测。

Fixed redundant screen redraw requests from the hidden audio peak meter in SSTV standby. In emulation, 32 peak changes caused zero extra redraws, down from 32. Receive status and image progress still update. Spectrum smoothness awaits hardware confirmation.

**2026-11-21 · FT8/FT4 TX2j.1** — 日版和欧／美版修正了部分 SD 卡状态下本台呼号无法保存或读回的问题。输入呼号后先在键盘确认，再回「本台设置」点「保存」。同一张卡重启后应能恢复呼号。欧／美版同时修正了通联日志停在「待存卡」的问题。两版已通过模拟冷启动读回；实体卡待复测。

Both regions now recognize a second valid SD state when saving or loading the FT station callsign. Confirm the keyboard entry, then tap Save in station settings. The E140 build also fixes QSO logs that could remain pending after a retry. Callsign recovery passed on fresh simulated radios in both regions. Physical card verification is pending.

**2026-11-20 · E140** — 欧版和美版共用原厂 `705E140.dat`。欧版补丁已通过双槽模拟安装与启动、CW 译码、SSTV 23 种模式整帧收发、FT8／FT4 收发与 SD 日志回放。欧／美版实体电台安装和射频收发仍待实测。

The European and US releases use the same original `705E140.dat`. The E140 patch passed emulated installation and boot from both slots, CW decoding, full-frame SSTV tests for 23 modes, FT8/FT4 RX/TX and SD logging. Installation and RF operation on physical E140 radios still await confirmation.

**2026-11-20 · FT8/FT4 TX2j** — 首次公开机内 FT8（15 秒）和 FT4（7.5 秒）收发。支持 GPS／机内时钟、中文软键、十行历史分页、CQ 筛选、自动选台及自动通联。FT8 和 FT4 共用 SD 卡上的 `IC-705/FTLOG.ADI`。本版校正顶栏对齐，并减少收听页的重复绘字。

First public release of on-radio FT8 (15 s) and FT4 (7.5 s) RX/TX. Select GPS or the internal clock, browse and filter decodes, and reply manually or use automatic caller selection and sequencing. Both modes share an ADIF log. TX2j aligns the header and reduces repeated text drawing.

| 日期 / Date | 版本 / Version | 更新内容 / Changes |
| --- | --- | --- |
| 2026-11-19 | SSTV RX4-TX4 | SSTV 发射扩展到 23 种模式。 / Expanded SSTV transmission to 23 modes. |
| 2026-11-19 | SSTV RX4-TX3 | 改善 Robot 36 弱信号续画，减少发射忙误报，并将 SEND 移到下方。 / Improved Robot 36 reception during fades, reduced false TX busy indications and moved SEND to the lower button. |
| 2026-11-19 | SSTV RX4-TX2 | 新增触屏一键发图。 / Added one-tap picture transmission. |
| 2026-11-19 | SSTV RX4-TX1 | 接入原厂选图，支持发送 Robot 36 和 Martin M1。 / Added the native picture picker and transmission in Robot 36 and Martin M1. |

[操作与验证记录 · Operation and test notes](docs/FTX-TX2j.md) · [模拟操作 GIF · Simulator walkthrough](docs/images/ftx-tx2j.gif) · [第三方许可 · Third-party notices](docs/converter/ftx-notices.txt)

## 微信交流群 · WeChat test group

用微信扫描下方二维码加入 **IC-705 魔改固件内测群**。进群后请将群昵称改为自己的呼号。

Scan in WeChat to join the **IC-705 firmware test group**. Please use your call sign as your group nickname.

<img src="docs/images/wechat-group.png" alt="IC-705 内测微信群二维码 / WeChat invitation QR code for the IC-705 firmware test group" width="320">

二维码有效至 **11 月 26 日前**，过期后请向群管理员索取新码。

The invitation is valid **before November 26, 2026**. After it expires, ask a group administrator for a new code.

## 源码与文档 · Source and documentation

| 路径 / Path | 内容 / Contents |
| --- | --- |
| [samples](samples) | 机内 C 和汇编代码 / On-device C and assembly |
| [tools](tools) · [tests](tests) | 构建、仿真和回放测试 / Build tools, emulation and replay tests |
| [CW](docs/IC705_CW_RELEASE.md) · [SSTV](docs/IC705_SSTV_PICTURE.md) | 功能说明和各版本实测记录（中文） / Feature guides and version-specific test notes (Chinese) |
| [RESEARCH](RESEARCH.md) · [PROJECT_HANDOFF](docs/PROJECT_HANDOFF.md) | 早期原型、环境准备和项目进度（中文） / Early prototypes, environment setup and project status (Chinese) |

## 引用与致谢 · Acknowledgements

感谢下列作者与贡献者公开代码、协议研究和验证方法。按阶段整理的完整来源见[引用与致谢](docs/ACKNOWLEDGEMENTS.md)。

We thank the authors and contributors who shared their code, protocol research and verification methods. The [credits by development stage](docs/ACKNOWLEDGEMENTS.md) list the full references.

| 阶段 / Stage | 作者与项目 / Authors and projects |
| --- | --- |
| 固件格式与跨机型仿真 / Firmware format and cross-model emulation | [SQ6EMM](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware) · [jeskko](https://github.com/jeskko/ic7300-homebrew) · [zarthur](https://github.com/zarthur/ic-7300_firmware) |
| CW 独立验证 / CW decoder references | [EliasOenal et al. · multimon-ng](https://github.com/EliasOenal/multimon-ng) · [TigreGotico · OpenTone](https://github.com/TigreGotico/OpenTone) |
| SSTV 模式与收发验证 / SSTV mode and signal verification | [xdsopl · Robot36](https://github.com/xdsopl/robot36) · [F4JTV](https://github.com/F4JTV/sstv_decoder) · [dnet · pySSTV](https://github.com/dnet/pySSTV) · [colaclanth · sstv](https://github.com/colaclanth/sstv) · [ON4QZ · QSSTV](https://github.com/ON4QZ/QSSTV) · [jbdubbs · QSSTV-Experimental](https://github.com/jbdubbs/QSSTV-Experimental) |

## 创作说明 · AI disclosure

**以上内容均为 AI 完成。**

The project content presented above was produced by AI. Upstream work is credited to its original authors, and on-device test feedback was provided by radio operators.
