# 公开资料索引与实验记录

| 资料 | 定位 |
| --- | --- |
| [Icom Global IC-705](https://www.icomjapan.com/lineup/products/IC-705/) | 采样架构、LCD、microSD、GPS、USB，和固件入口。 |
| [Icom 日本 IC-705](https://www.icom.co.jp/lineup/products/IC-705/) · [日版 1.40](https://www.icom.co.jp/support/drivers/8603/) · [705J 下载来源与哈希](705j-provenance.json) | 日版主样本及八个历史版本。 |
| [Icom CS-705 1.21](https://www.icom.co.jp/support/drivers/7075/) / [1.30](https://www.icom.co.jp/support/drivers/8597/) · [CS-705 来源与哈希](cs-705-provenance.json) | 与日版固件 1.32/1.40 对应；独立验证菜单名称、选项变化及帮助主题。 |
| [Icom 日本 IC-705 中继列表](https://www.icom.co.jp/support/drivers/8924/) / [Icom America IC-705 中继列表](https://www.icomamerica.com/support/firmware_driver/3071/) · [官方 ICF 来源与哈希](icom-705-settings-provenance.json) | 只读验证设置记录格式及日/美语言字段。日本页面版号与实收 ZIP 名不同，按清单中的实收成员复核。 |
| [Icom CS-9700 1.40](https://www.icom.co.jp/support/drivers/7170/) / [1.50](https://www.icom.co.jp/support/drivers/8600/) | 1.50 公告记录与 CS-705 1.30 相同的两项设置变更，供下一步对照。 |
| [Icom IC-905 1.15](https://www.icom.co.jp/support/drivers/7802/) / [1.20](https://www.icom.co.jp/support/drivers/8671/) · [IC-9700 1.44](https://www.icom.co.jp/support/drivers/7495/) / [1.50](https://www.icom.co.jp/support/drivers/8599/) | [跨机型清单](icom-comparator-provenance.json)记录实际下载 URL、成员及哈希，仅用作首段边界对照。 |
| [Icom America 手册与 FAQ](https://icomamericasupport.zendesk.com/hc/en-us/articles/35050966822036-IC-705-Instructions-and-FAQs) / [官方维修手册入口](https://icomamericasupport.zendesk.com/hc/en-us/articles/38411837710228-Amateur-Radios-Service-Manual-Download-Portal) | 用户文档、接口信息、维修资料来源。 |
| [Icom 编写的维修手册公开镜像](https://www.passion-radio.com/index.php?controller=attachment&id_attachment=787) | 2021 年 5 月增补 MAIN UNIT 2/8、4/8、5/8、6/8、7/8、8/8 与 FRONT UNIT，按器件号定位。没有在 Git 中保存手册。 |
| [Icom CI-V 指南](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf) / [基础手册](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf) | CI-V、USB A/B、AF/IF、RTTY、GPS。 |
| [Icom 英文活用手册](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_4.pdf) | GPS Position 的 MY 与 RX 页面语义；RX 距离是相对本机的台站距离。[J140 离线回放](../docs/IC705_GPS_INPUTS.md)核对了 NMEA、距离缓存与过期。 |
| [Icom 日本站 IC-705 说明书入口](https://www.icom.co.jp/support/manual/4873/) · [Icom UK 英文基础手册](https://icomuk.co.uk/files/icom/PDF/productManual/IC-705_ENG_Basic_9.pdf) | 日版 A7577D-1J-8 纸面 ii、I、13-19 页（PDF 第 3、177、133 页）分别是整机软件声明、CMSIS-RTOS RTX 许可证、显示与系统语言。日版 PDF 27,978,626 字节，SHA-256 `906d81770ab5a3b6c725e116d9ce65ee798445df89c93289d4143b094392d26d`，下载副本仅存本地。 |
| [JR6BUL IC-705 实机记录](https://note.com/ukigumo1104/n/nbef1fc4316f4) · [AMSAT-SM Split 频道表](https://www.amsat.se/2020/11/12/satellite-memory-file-for-ic-705/) · [外部多普勒实作](https://www.amsat.se/2021/01/01/working-satellites-with-ic-705-pstrotator-sdr-console/) | [卫星报告](../docs/SATELLITE_TRACKING.md#跨段收发的证据)有手册页码、固定 CSV 版本与哈希，区分日版规格、跨段实机操作和频道配置。 |
| [CelesTrak GP 格式](https://celestrak.org/NORAD/documentation/gp-data-formats.php) · [SGP4 论文及参考实现](https://celestrak.org/publications/AIAA/2006-6753/) · [AMSAT 转发器数据库](https://satdb.amsat.org/) | 轨道数据、算法参考和上下行参数分开取证。 |
| [Icom 日版 1.11](https://www.icom.co.jp/support/drivers/5612/) · [1.20](https://www.icom.co.jp/support/drivers/6128/) · [TI SimpleLink 文档](https://software-dl.ti.com/ecs/SIMPLELINK_CC32XX_SDK/4_20_00_07/exports/tools/cc32xx_tools/servicepack-cc3x20/README.html) | D 组与 WLAN 组件版本变化，[九版复核](../docs/FIRMWARE_COMPONENTS.md)列全。 |
| [ARRL W1AW 20 WPM 档案](https://www.arrl.org/20-wpm-code-archive) · [OpenTone](https://github.com/TigreGotico/OpenTone) | 2026-01-06 的 MP3 与参考文本，及独立固定速率解码器。[CW 报告](../docs/CW_BASELINE.md#arrl-练习录音续测)记录来源和结果。 |
| [Verulam Amateur Radio Club 的 CW 课堂与转写](https://www.verulam-arc.org.uk/cw-class/) | 主办者公开第 3、7 课的 40 米实收录音和通联转写。[评分与哈希](../docs/CW_BASELINE.md#40-米通联实收验收)；电键类型及接收机型号尚未确认。 |
| [同一社团第 4 课原始录音](https://archive.org/download/morse-class-4/Morse%20Class%204.mp3) · [CWops 教材](https://cwops.org/wp-content/uploads/2025/04/Fundamental-Curriculum-v1.13.htm) | 37:36 起的练习段用于未参与调参的[文字和空格复验](../docs/CW_BASELINE.md#局部噪声门限与空格评分)，不计作独立短波通联或直键样本。 |
| [IZ4KBW 的意大利短波实收档案](https://swling.com/blog/2021/11/large-archive-of-cw-off-air-recordings-from-italy/) | 发布者列明 2021-11-21 的 7.036 MHz 桨键录音和参与呼号。只对可核对的两次呼号交换[计分](../docs/CW_BASELINE.md#按发报节奏分词)，不推断全段转写。 |
| [SideSwiper Net 40 米实收日志](https://www.sideswipernet.org/qni/us40m_2020.php) · [N1EA 侧摆键演示](https://www.sideswipernet.org/resources.php) | 分别作为实收与明确键型的独立对照，[评分和哈希](../docs/CW_BASELINE.md#冷启识别-0-与侧摆键实收)。前者评分场的键型未确证，后者不是实收。 |
| [Colorado QRP Club：AE5X 实收 100 mW 通联](https://www.coloradoqrpclub.org/audio/index.htm) | 2018-02-23 的 14.060 MHz 原录音用于自动 CW 降误报后的[独立测试](../docs/CW_BASELINE.md#自动选音没有来报时别出字)；单列原录音与人为衰减、加噪的对照。 |
| [Renesas R7S721001VCBG](https://www.renesas.com/en/products/rz-a1h/part-details/r7s721001vcbg-bc1) / [硬件手册](https://www.renesas.com/en/document/mah/rza1h-group-rza1m-group-users-manual-hardware) | CPU、SRAM、图形、启动模式和芯片地址图。 |
| [Khronos OpenVG 1.1](https://registry.khronos.org/OpenVG/specs/openvg-1.1.pdf) | §5.1 的上下文参数、§11.5 的字形绘制接口，对照 GPS 与 RTTY 标题实际使用的绘制路径。 |
| [REA](https://github.com/morluto/rea) · [安装](https://github.com/morluto/rea/blob/main/docs/getting-started/installation.md) · [固件](https://github.com/morluto/rea/blob/main/docs/guides/firmware/firmware-analysis.md) · [Raw Binary](https://github.com/morluto/rea/blob/main/docs/providers/raw-binary.md) | Provider 和格式支持；实际状态以 [本机工具目录](rea-tool-inventory.tsv) 与 [REA 报告](../docs/REA_ANALYSIS.md) 为准。 |
| [SQ6EMM 的 IC-705 DAT 格式研究（固定提交）](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/6adfab19d58e64f3362d72e8fd7d41dbd47a8eee/IC705_DAT_FORMAT.md) | 给出 A 内层编码及 LZSS；仅使用公开格式说明，[独立复核两个日版和一个 E 版](../docs/MAIN_CPU_DECODE.md)，未运行第三方脚本。 |

2026-11-12 至 13 日：核对 Windows REA、Debian WSL2，下载并核对三个 Icom E 包；REA 检查 1.40 外层 ZIP 和 DAT 熵；在 Python 中复算 MD5、对齐版本、切出四组。命令见 [README](../README.md) 和 [固件报告](../docs/REA_ANALYSIS.md)。所有固件及派生字节只存本机，实验 JSON 存 `.analysis/`。硬件资料核验只使用文档，没有连接设备。

2026-11-13：改以日版 705J 为主样本，下载六个官方包并对齐 E/J，日版切出 A/C/D；用 REA 复核 J140 哈希与熵。[日版报告](../docs/JAPAN_FIRMWARE.md)记录发现。另依 [ITU-R M.1677-1](https://www.itu.int/rec/R-REC-M.1677-1-200910-I/en)生成三个 CW WAV。

续：从日本站追加 [1.20](https://www.icom.co.jp/support/drivers/6128/) 和 [1.24](https://www.icom.co.jp/support/drivers/6192/) 两个独立样本，验证 [A 组 6 MiB 切分点](../docs/MAIN_CPU_ANALYSIS.md)；ZIP/DAT 哈希、CRC 和下载地址已追加至[来源清单](705j-provenance.json)。

续：追加 [IC-705 1.11](https://www.icom.co.jp/support/drivers/5612/) 和 IC-905、IC-9700 各两个版本。核对相邻摘要、精确周期终点和尾段字节相关性；REA 独立核对两台对照机型的 ZIP 成员及边界熵。方法及结果见[跨机型封装对照](../docs/CROSS_MODEL_FORMAT.md)。

续：对 7 个 DAT 做[尾段重复与资源探针](../docs/TAIL_RECORD_ANALYSIS.md)；以官方 [CS-705 两版](../docs/CS705_MENU_REFERENCE.md)独立验证三个菜单键及其帮助主题。只解析归档、PE 和 HTML 字节；下载件及实验材料分别留在 `firmware/` 和 `.analysis/`。

续：用 REA 核验官方 ICF 外层 ZIP，结合两版 x86 反汇编，核对 [四个设置字段和 12 个 DAT 阴性结果](../docs/CS705_SETTINGS_MAP.md)。两份 ICF 及完整实验输出仅存本地。

续：重新核验九个官方 DAT 与公告部件版本；核对日文手册的 RTX/FreeType 声明，用两种解码器和独立点划测量复测 ARRL 练习录音。原始证据留在 `.analysis/source-triage/` 和 `.analysis/cw-baseline/arrl-20260106/`。

续：核对日文手册的 Split、GPS 和定格页，以及 JR6BUL 的发送截图；只读解析 AMSAT-SM 的公开 CSV，统计两个跨段方向，并为[五项长期需求](../ROADMAP.md#五项功能与下一份证据)补充各自的离线验收。

续：从 `705J140`、`705J132`、`705E140` 独立提取主 CPU 程序。REA 复核输出哈希及 J140 复位段；对照 [Icom 1.40 公告](https://www.icom.co.jp/support/drivers/8603/)定位 GPS 距离格式化的实际改动，并追到 RTTY 标题也使用的绘制入口。两版日英选项表已定位。复现命令、地址与证据见[主程序报告](../docs/MAIN_CPU_DECODE.md)，原厂字节与本地工具证据留在 `.analysis/main-decode/`。
