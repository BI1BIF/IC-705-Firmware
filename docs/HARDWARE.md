# IC-705 硬件与软件系统架构分析

依据为 Icom 编写的 [IC-705 Service Manual，2021 年 5 月增补](https://www.passion-radio.com/index.php?controller=attachment&id_attachment=787)（第三方公开镜像）、Icom [产品页](https://www.icomjapan.com/lineup/products/IC-705/)及各芯片厂商资料。图纸确认器件或线路，数据手册确认芯片能力；没有用实机测量频率、波形或时序。“高”指来源直接支持该陈述；“中”指有多项一致的间接证据；“未验证”表示没有足够证据。

项目主样本为日版 705J。下表器件结论基于所引图纸的板号；尚未核实用户这台日版的板修订，不能直接套用图纸的 codec、批次或调试接口细节。Icom [日版 1.40 公告](https://www.icom.co.jp/support/drivers/8603/)也区分了部分日版批次的音频兼容性。

| 子系统 | 核实结果与来源 | 可信度及边界 |
| --- | --- | --- |
| 主 CPU | MAIN UNIT 6/8：IC701 **Renesas R7S721001VCBG**。两组增补图（#12/#13/#16/#17 和 #32/#33/#36/#37）一致。[两份公开实物照片](IC705_THIRD_PARTY_PRECEDENT.md#两份实物照片给出不同主板标识)上主控均标 `R7S721001VC`，主板却分别标 `B-8984F MAIN`、`B-9913A MAIN-A`。[Renesas 规格](https://www.renesas.com/en/products/rz-a1h/part-details/r7s721001vcbg-bc1)：RZ/A1H、32 位 Cortex-A9、最高 400 MHz、10 MiB 片上 SRAM、2D 绘图能力。 | 高。400 MHz 是器件规格，实际 CPU/总线频率及空闲 SRAM 未验证。照片未建立日版出厂批次到板号的对应表。 |
| 子 CPU | MAIN UNIT 7/8：IC901 **STM32L051R8H6**；与主板的串行控制线、按键和电源监测相关。MAIN UNIT 6/8、7/8 图纸与 [J140 原厂初始化](IC705_SD_RESOURCES.md#j140scif3-子控连线与两级等待)交叉确认，主控 SCIF3 连到 IC901，原厂启动轮询主控 P7_9 上的 `SCACK`。[ST 规格](https://www.st.com/en/microcontrollers-microprocessors/stm32l051r8.html)：Cortex-M0+，64 KiB Flash、8 KiB RAM。 | 器件与串口归属可信度高；帧格式、实际时钟及其他职责未验证。 |
| IF DSP | MAIN UNIT 2/8：IC202 **ADSP-21478BBCZ**，连 FPGA 的 `DFR_RXIF/DFR_SCIF/DFR_WFM` 等线路和音频编解码电路。[ADI](https://www.analog.com/en/products/adsp-21478.html) 确认为 SHARC。不同板版本的音频 codec 可见 AK4951AEN 和 TLV320AIC3105，不能假设完全一致。 | 器件与线路高；具体滤波、RTTY 算法、音频帧协议未验证。 |
| DV DSP | MAIN UNIT 5/8：IC602 **TMS320C5517AZCHA20**；`DDX_DVI/DDR_DVO`、串行音频及主 CPU 控制线见图。[TI 规格](https://www.ti.com/product/TMS320C5517) 为 C55x 定点 DSP。 | 器件与 DV 通路高；DV 算法边界及 DAT 归属未验证。 |
| FPGA | MAIN UNIT 4/8：IC521 **10CL025ZU256I8G**，[Altera Cyclone 10 LP](https://www.altera.com/products/fpga/cyclone-10/lp/10cl025-u256/10CL025ZU256I8G)。Icom 产品页说明 25 MHz 以下直接采样，高于或等于 25 MHz 走下变频 IF 采样；图纸连接 ADC/DAC 与 IF DSP。 | 高；内部 DDC/DUC 实现及 bitstream 格式未验证。 |
| 存储 | MAIN UNIT 6/8：IC704 **IS25LP128F** 串行 NOR，[ISSI 数据手册](https://www.issi.com/WW/pdf/25LP-WP128F.pdf) 为 128 Mbit / 16 MiB。IC705、IC706 标为 **GT24C1024**，[Giantec](https://www.giantec-semi.com/uploads/pdf/241105/ct/GT24C1024_DS.pdf) 每颗 128 KiB I²C EEPROM。MAIN UNIT 4/8 另有 IC553 **IS25LP016D**，[ISSI 数据手册](https://www.issi.com/WW/pdf/25LP-WP016D.pdf) 为 16 Mbit / 2 MiB。Icom 确认 microSD 承载配置、录音、RTTY 日志、GPS、截图及更新。 | 图纸器件可信度高；未确认用户板版、实存内容与更新写入范围。[日版原厂启动回放](SAFETY_AND_RECOVERY.md#启动时实际使用的板上数据)证实一种正常启动分支选择 EEPROM 中的数据。当前没有已证实的主 CPU 外置 SDRAM。 |
| 显示和输入 | MAIN UNIT 6/8 由主 CPU 接出 `LCD_R/G/B`、`LCD_CLK`、`LCD_HS/VS`、`LCD_DE`；Icom 确认 4.3 英寸彩色触屏。主控页可见拨盘、触控相关控制网。[两版静态链](MAIN_CPU_DECODE.md#从距离字段到原厂文字绘制)确认 GPS 和 RTTY 标题共用的文字绘制入口，关联 FreeType 与 OpenVG 字形操作。 | 并行接口和静态链可信度高。字库文件、哪些其它页面复用该路径、LCD 帧缓冲、视频控制器配置和触控事件未验证。 |
| USB | MAIN UNIT 8/8：IC1221 **TUSB2046IBVFR** hub、IC1191 **PCM2901E** USB 音频 codec；CPU USB 线路和 `USB_AF/USB_MOD` 均可在图纸追踪。Icom 文档确认两个 COM 端口及 USB 音频。 | 高。USB Audio 与 CI-V 是可分别使用的接口；USB AF/IF 输出不等同于已证实的原始复数 IQ。 |
| 蓝牙、Wi-Fi、GPS | MAIN UNIT 6/8、8/8 及 FRONT UNIT：主 CPU 有 `BT_RXD/TXD`、Wi-Fi 控制线、`GPS_RXD/TXD` 及电源/复位网。所查 Wi‑Fi 模块为 IC1101 **CC3120MODRNMMOBR**，有主机 SPI 与独立模块 Flash 总线；[TI 数据手册](https://www.ti.com/lit/ds/symlink/cc3120mod.pdf)确认模组内 4 MiB 串行 Flash。[Icom 规格与 FAQ](https://icomamericasupport.zendesk.com/hc/en-us/articles/35050966822036-IC-705-Instructions-and-FAQs)证实蓝牙 4.2；官方产品页确认 WLAN 与内置 GPS。 | 所查图纸线路、WLAN 器件及模组 Flash 容量可信度高；日版生产批次、其他模块型号和串口帧未完全核实。 |

## 音频、IQ、控制与 LCD 的边界

| 路径 | 当前证据 | 下一项验证 |
| --- | --- | --- |
| 接收信号 | RF/IF → ADC → FPGA → IF DSP，是产品页与 MAIN UNIT 2/8、3/8、4/8 所支持的硬件链路。FPGA 至 SHARC 有数字串行信号及帧/位时钟。 | 位宽、通道格式、IQ 与其他数据的映射；没有证据表明主 CPU 有连续宽带 IQ 缓冲。 |
| 解调音频 | 维修图确认 `DCX_REC` 到主 CPU SSIF0、`DCX_LAN` 到 SSIF5；[日版双版回放](IC705_RX_AUDIO.md)确认 DMA 后取 16 位 PCM，进入录音或 WLAN 的独立缓冲。 | 高（图纸、静态地址和受控回放）。录音 WAV 为 8 kHz；录音抽样前 48 kHz 为推断，实机时钟、模式和可扩展接口未验证。 |
| RTTY 文本 | 维修图中 IF DSP 的 `RTD` 经 R219 到主 CPU `P0_5`。两版[原厂 ARM 回放](MAIN_CPU_DECODE.md#rtty-从五位符号到正文)从该 GPIO 位组出五位码并填入正文；[CI-V 指南](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf)另列 USB(B) 解码文本。 | 线路和主 CPU 路径可信度高；DSP 判决算法和 USB(B)／日志分流未验证。 |
| CI-V 与 GPS | CI-V 指南公开两个 VFO 的频率和模式读写、Split 状态和本机定位/UTC 读取。J140 已离线验证[原厂 CI-V 分发表和双 VFO 读数](IC705_VFO_SPLIT.md)、[GPS 报文解析和有效性](IC705_GPS_INPUTS.md)。 | 用户这台日版的两个跨段方向未实测；CI-V 传输层与实体 GPS 硬件未在这两次回放建模。 |

## 启动和调试接口

[Renesas 硬件手册](https://www.renesas.com/en/document/mah/rza1h-group-rza1m-group-users-manual-hardware)与[开发板手册](https://www.renesas.com/en/document/mat/renesas-starter-kit-rza1-users-manual)给出芯片级参考：在串行 Flash 启动模式下，片内 Boot ROM 从高向量 `0xFFFF0000` 开始，配置 SPI 后转到 `0x18000000`；片内 SRAM 参考范围 `0x20000000–0x209FFFFF`。IC-705 的[引导镜像静态反汇编](MAIN_CPU_DECODE.md#从启动代码验证装载地址)与串行 Flash 地址相符，并验证搬运到 `0x20004000`、把主程序解压到 `0x20005000`、设置向量基址及跳转。实机启动绑带、设备冷启动与其后的完整 MMU 布局未验证。

主 CPU 图可见 MTCK/MTMS/MTDI/MTDO/MTRST，FPGA 也有 JTAG 网络；子 CPU 页有 SWDIO/SWCLK 与 SUBTXD/SUBRXD。UART 同样用于蓝牙/GPS 等通信。[原厂图逐线复核](SAFETY_AND_RECOVERY.md#维修图核实主控时钟两套-flash-与日版适用范围)确认相邻的 `CP706` 只连 `CKIO` 时钟输出。图纸证明信号存在，不能证明有可用调试连接器、调试被启用或允许读取 Flash。

[Icom 日版《取扱説明書》](https://www.icom.co.jp/support/manual/4873/) A7577D-1J-8（2026 年 10 月版，纸面 ii、I 页）明确列出 RTX、FreeType、zlib、libpng 和 Independent JPEG Group 软件，许可证将 RTX 标为 **CMSIS-RTOS RTX**。FreeType 另有主程序内的调用线索；其它库的 CPU 归属、版本和 RTX 任务表仍待验证。原厂 PDF 的版本和哈希见[资料索引](../research/SOURCES.md)。

Icom 公告确认用户从 microSD 菜单选择 DAT 更新，并提供设置备份。该流程与芯片冷启动是两条不同路径。DAT 已确认包含可分离的引导与主程序，但更新时如何映射到实际 Flash 分区、设备级恢复入口仍未验证。
