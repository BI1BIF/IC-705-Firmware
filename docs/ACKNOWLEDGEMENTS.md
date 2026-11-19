# 分阶段引用与致谢

感谢下列作者、维护者和贡献者公开研究记录、代码与测试工具。表中使用 GitHub 账号和仓库名称标识来源，最后一栏链接到本项目记录。

| 阶段 | 参考内容 | GitHub 作者与项目 | 项目记录 |
| --- | --- | --- | --- |
| 容器、Flash 与安装历史 | 核对 DAT 编码、压缩、分段和布局，并查阅第三方固件的公开发布记录。 | [sq6emm/ic705-ic9700-ic905-bring-your-own-firmware](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware)、[sq6emm/icom-custom-firmware](https://github.com/sq6emm/icom-custom-firmware) | [记录](MAIN_CPU_DECODE.md) |
| 跨机型仿真与阳性对照 | 参考初代 IC-7300 的 QEMU 外设、DSP 研究和整包逐段验证方法。 | [jeskko/ic7300-homebrew](https://github.com/jeskko/ic7300-homebrew)、[zarthur/ic-7300_firmware](https://github.com/zarthur/ic-7300_firmware) | [记录](IC705_CROSS_MODEL_REUSE.md) |
| 派生仓库查重 | 比对公开分支历史，确认文档的原始来源。 | [OH2LAK/ic705-ic9700-ic905-bring-your-own-firmware](https://github.com/OH2LAK/ic705-ic9700-ic905-bring-your-own-firmware)、[iu2frl/ic705-ic9700-ic905-bring-your-own-firmware](https://github.com/iu2frl/ic705-ic9700-ic905-bring-your-own-firmware)、[iu2frl/icom-custom-firmware](https://github.com/iu2frl/icom-custom-firmware) | [记录](IC705_THIRD_PARTY_PRECEDENT.md) |
| 取证与 ARM 回放 | 使用固件分析、扫描、解包和 CPU 仿真工具，并核对反汇编工具的支持范围。 | [morluto/rea](https://github.com/morluto/rea)、[ReFirmLabs/binwalk](https://github.com/ReFirmLabs/binwalk)、[onekey-sec/unblob](https://github.com/onekey-sec/unblob)、[unicorn-engine/unicorn](https://github.com/unicorn-engine/unicorn)、[NationalSecurityAgency/ghidra](https://github.com/NationalSecurityAgency/ghidra) | [记录](REA_ANALYSIS.md) |
| 板级外设与音频 | 对照芯片设备树及 SCUX 寄存器定义。 | [torvalds/linux](https://github.com/torvalds/linux)、[ARMmbed/mbed-os](https://github.com/ARMmbed/mbed-os) | [记录](IC705_RX_AUDIO.md) |
| CW 离线基准 | 用已知文本、合成音频和 ARRL 录音对比译码表现。 | [EliasOenal/multimon-ng](https://github.com/EliasOenal/multimon-ng)、[TigreGotico/OpenTone](https://github.com/TigreGotico/OpenTone) | [记录](CW_BASELINE.md) |
| CW 方案调研 | 查阅其他 CW 算法、音调跟踪及电脑端收音方案。 | [w1hkj/fldigi](https://github.com/w1hkj/fldigi)、[aethersdr/AetherSDR](https://github.com/aethersdr/AetherSDR)、[ggerganov/ggmorse](https://github.com/ggerganov/ggmorse) | [记录](IC705_THIRD_PARTY_PRECEDENT.md) |
| SSTV 接收与同步 | 对照模式表、行时序、色彩通道、同步和 VIS 检测。 | [xdsopl/robot36](https://github.com/xdsopl/robot36)、[F4JTV/sstv_decoder](https://github.com/F4JTV/sstv_decoder)、[colaclanth/sstv](https://github.com/colaclanth/sstv) | [记录](IC705_SSTV_PICTURE.md) |
| SSTV 独立收发基准 | 用 pySSTV 生成独立发射参考，以 QSSTV 系列资料和离线解码交叉检查图像。 | [dnet/pySSTV](https://github.com/dnet/pySSTV)、[ON4QZ/QSSTV](https://github.com/ON4QZ/QSSTV)、[jbdubbs/QSSTV-Experimental](https://github.com/jbdubbs/QSSTV-Experimental) | [记录](IC705_SSTV_REPLAY.md) |
| 字体与资源格式研究 | 参考开源汉字字形及 FNT、PSF 格式实现。 | [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk)、[freetype/freetype](https://github.com/freetype/freetype)、[legionus/kbd](https://github.com/legionus/kbd) | [记录](TAIL_RECORD_ANALYSIS.md) |
| FT8、卫星与外部控制的早期调研 | 参考算法、轨道预测、选星操作及外部电台控制方案。这些功能属于长期研究路线。 | [wsjtx/wsjtx](https://github.com/wsjtx/wsjtx)、[kgoba/ft8_lib](https://github.com/kgoba/ft8_lib)、[dnwrnr/sgp4](https://github.com/dnwrnr/sgp4)、[csete/gpredict](https://github.com/csete/gpredict)、[BH6AAP/ic705controler](https://github.com/BH6AAP/ic705controler)、[Hamlib/Hamlib](https://github.com/Hamlib/Hamlib)、[wf-group/wfview](https://github.com/wf-group/wfview) | [记录](FEASIBILITY.md) |

另感谢 Icom 公开日版更新说明和使用资料，Renesas 提供芯片手册，ARRL W1AW 提供 CW 练习录音，以及提供实机反馈的业余无线电爱好者。官方资料、固定提交和测试数据的原始引用见[资料索引](../research/SOURCES.md)。
