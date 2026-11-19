# IC-705 固件 · IC-705 Firmware

BI1BIF 的非官方日版 IC-705 固件研究项目。当前源码基线 **J140 · CW D6 · SSTV RX4-TX4**，基于 Icom 日版 1.40。使用下方转换页，在浏览器本地从原厂 DAT 生成当前版本。

BI1BIF’s independent firmware research for the Japanese Icom IC-705. The current source baseline is **J140 · CW D6 · SSTV RX4-TX4**, based on Japanese firmware 1.40. Build the current firmware locally in your browser from the original DAT.

**[打开固件转换页 · Open firmware converter](https://bi1bif.github.io/IC-705-Firmware/)**

## 电台功能 · Radio features

| 功能 / Feature | 中文 | English |
| --- | --- | --- |
| CW DECODE | 在 CW 模式下查看译文、速度和波形；点 HOLD/CLR 可冻结译文，长按清屏。 | Read decoded Morse text, speed and waveform in CW mode. Tap HOLD/CLR to freeze the text, or hold it to clear. |
| SSTV RX | 在 PICTURE → SSTV 自动识别模式，使用 SAVE/HIST 保存、回看图片。Robot 36 收到帧头后可在短暂衰落中保留行号。 | Open PICTURE → SSTV for automatic mode detection. SAVE/HIST saves and recalls images. After a valid header, Robot 36 retains the scan position through short fades. |
| SSTV TX | 从 SD 卡选图并确认，点 MODE 选模式，返回后点 SEND 发射。 | Select and confirm a photo from the SD card, choose a mode under MODE, then return and tap SEND. |

**23 种收发模式 / 23 RX and TX modes**

Robot 36/72 · Martin M1–M4 · Scottie S1/S2/DX · Wraase SC2-180 · PD50/90/120/160/180/240/290 · BW 8/12/24 · Pasokon P3/P5/P7

TX3 已收到 CW 和 SSTV 的真机使用反馈。TX4 的 23 种发送模式已通过模拟面板点选和整帧音频验证，新增模式的逐项射频互收仍待完成。

Operators have tested CW and SSTV on hardware with TX3. All 23 TX4 modes passed emulated menu selection and full-frame audio tests. Over-the-air checks for the added modes are still pending.

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
