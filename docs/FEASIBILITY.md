# 第三方功能扩展可行性评估

外部原型可用录音、公开测试向量和模拟 CI-V。以下数字是按样本和像素计算的预算示例，不是 IC-705 实测性能或可用 SRAM。日版两版已确认[主 CPU 读录音和 WLAN 的 PCM](IC705_RX_AUDIO.md)；下一关是测出各模式的带宽与连续性、可用资源，并证明有安全的集成与恢复路线。

已用[合成 WAV](../samples/README.md#cw-离线测试样本)和 [ARRL 练习录音](CW_BASELINE.md#arrl-练习录音续测)测过 multimon-ng。ARRL 正文 670 个字符均正确；解码器的末次速度折算为 30 WPM，录音的独立测量为 20 WPM。第二个解码器 OpenTone 在干净合成阳性对照通过，未能完整解出这段录音。下一步用有参考文字的实收录音验证抗干扰和持续测速。

第五项长期需求是[整机简体中文化](LOCALIZATION_ZH_CN.md)。已确认日英选项表和 [GPS/RTTY 标题共用的文字绘制入口](MAIN_CPU_DECODE.md#从距离字段到原厂文字绘制)。关键门槛是确认语言选择、字体加载和字符覆盖，以及保持原厂语言、动态数据和设置兼容。SSTV 的图像绘制仍须另证。

| 功能 | 输入和计算 | 工作内存与存储示例 | 原生集成及影响 | 外部验证 |
| --- | --- | --- | --- | --- |
| CW 自动解码 | 解调 PCM 足够。窄带能量跟踪、噪声门限、点划/间隔估计、字符状态机；跟踪 WPM 和目标音调。无需宽带 IQ。 | 8 kHz 16-bit 单声道 1 秒为 16,000 B；可按更短块处理，文本为小环形缓冲。 | 四项中计算负担最轻。优先比较录音前后的 PCM，再研究 RTTY 文本事件、滚屏和日志能否复用。噪声、手键节奏、AGC、带宽都会影响识别。 | 将合成与有标注的 WAV 输入 Fldigi 或离线原型，记录字符错误率、WPM 误差、延迟，按噪声和手键分组。 |
| SSTV 接收 | 解调 PCM。先做 VIS、同步、瞬时频率和逐行色彩恢复；先 Robot 36 / Martin M1，再扩展模式。 | 320×256 RGB565 单缓冲 160 KiB；RGB888 240 KiB；双缓冲至少翻倍。12 kHz 16-bit 流每秒 24 kB，可流式处理，不必保存整段音频。 | 需要图像页面、刷新、写 SD 的权限/缓冲与异常处理；原厂 Photo Share 是 D-STAR 业务，不等于 SSTV，但其显示/文件流程是可调查线索。SD 写入不得阻塞采样或录音。 | QSSTV 对照公开 WAV 与期望图，测 VIS 检出、丢行、颜色偏差和落盘完整性。 |
| FT8 接收 | 12 kHz 附近的单声道 SSB 音频足够作参考；15 秒 UTC 时隙，需频时搜索、软解调、LDPC 和 CRC，输出呼号、SNR、网格。 | 12 kHz/16-bit/15 s 单 PCM 窗 360,000 B；两窗 720,000 B。FFT、瀑布、候选与 LDPC 另计。 | 四项中实时计算和内存压力最高；实测 P95 计算时间、峰值内存和丢帧后才谈原生。FT8 预置是已知操作功能，不是机内解码证据；只评估接收。 | 用同一 UTC 标注 WAV 对照 WSJT-X 和 ft8_lib，统计弱信号召回、误报、耗时、内存和输出字段一致性。 |
| [本机选星和自动多普勒](SATELLITE_TRACKING.md) | 无需 PCM/IQ。用卫星轨道根数、内置 GPS 位置与 UTC 计算过境；用转发器参数和距离变化率分别修正上下行频率。 | 按所选卫星流式计算即可；原生 RAM、数学库与刷新周期待测。 | 原厂 VFO 与 Split 是跨段半双工候选，实机操作记录支持 144 MHz 段发、430 MHz 段收。主要难点是 GPS/轨道数据有效性、VFO 所有权和手动 PTT 状态协调。 | 用 SGP4 参考向量核对轨道，用固定过境复核两条频率曲线，模拟两种跨段方向、PTT、人工接管及断连。 |

## 上游选择和移植条件

| 项目 | 上游许可证 | 用法及适配性 |
| --- | --- | --- |
| [Fldigi](https://github.com/w1hkj/fldigi) | GPL-3.0；移植前核对具体源文件条款 | CW 接收与速度跟踪的参考；桌面 FLTK 层不适合嵌入，先做外部基准。 |
| [QSSTV](https://github.com/ON4QZ/QSSTV) | 上游提供 GPL-3.0 COPYING；另有 LICENSE，须核对选中文件 | SSTV 模式和解码基准。桌面版依赖 Qt、FFTW、音频栈等；原生候选限于接收核心或独立实现。 |
| [WSJT-X](https://github.com/wsjtx/wsjtx) | GPLv3，见[上游开发与许可说明](https://wsjt.sourceforge.io/devel.html) | FT8 参考解码、WAV 基准；Fortran DSP 与 Qt/C++ 桌面依赖增加嵌入式移植成本。 |
| [kgoba/ft8_lib](https://github.com/kgoba/ft8_lib) | MIT；另核对所选 FFT/音频代码 | 轻量 C 实现优先做资源和精度对照。独立 FFT 后端、峰值内存、候选数量、覆盖消息类型均需实测。 |
| [dnwrnr/sgp4](https://github.com/dnwrnr/sgp4) | [Apache-2.0](https://github.com/dnwrnr/sgp4/blob/master/LICENSE) | C++ 轨道核心候选；先测双精度数学库、UTC/历元转换及 TLE 边界。 |
| [Gpredict](https://github.com/csete/gpredict) | 上游 COPYING GPL-2.0，逐文件核对 | 桌面对照：SGP4/SDP4、过境预测、频率调节；GTK 界面不直接移植。 |
| [Hamlib](https://github.com/Hamlib/Hamlib) / [wfview](https://github.com/wf-group/wfview) | [Hamlib 库与主要后端 LGPL-2.1](https://github.com/Hamlib/Hamlib/wiki/Licensing)，其他文件见上游；[wfview GPLv3](https://wfview.org/download/) | Hamlib [型号 3085](https://github.com/Hamlib/Hamlib/wiki/Supported-Radios) 和 [wfview](https://wfview.org/about/) 可作外部 CI-V/音频参考。当前用离线录音或模拟端口。 |

可从现有 [Icom USB AF/IF 与 CI-V 文档](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf)推导外部验证路径；当前输入用现成录音或合成样本。任何原生移植都需要独立确认兼容许可和设备侧资源，不能把桌面项目直接编进原厂系统。
