# 研究路线与早期原型


从 [项目接续记录](docs/PROJECT_HANDOFF.md) 查看当前断点、已关闭事项和下一个验收点。

本项目研究日版 IC-705 官方更新包、硬件架构和第三方功能。五项长期需求是机内 CW 自动解码、SSTV 图像接收、FT8 接收解码、本机选星后用内置 GPS 做上下行多普勒补偿，以及保留日语和英语选项的**整机简体中文化**。下文记录早期可行性研究和电脑端原型。

研究对象是日版 IC-705，主样本为 `705J140.dat`。`705E*.dat` 仅作跨地区对照；IC-905 与 IC-9700 仅用于比较封装。

当前已从日版 1.32 和 1.40 提取 Cortex-A9 主程序，并在 PC 上复现 GPS 距离显示的版本差异。双击 [Open-IC705-Panel.cmd](Open-IC705-Panel.cmd)，从[日版 1.40 的原厂主屏](docs/IC705_EMULATION.md#日版-140原厂主屏与-menu)按 `MENU`，点右下 `SET`，即可进入显示设置。独立的[保存与重载回放](docs/IC705_LANGUAGE_PERSISTENCE.md)验证原厂日英切换可经模拟存储跨实例保留，系统语言仍为日语。面板窗口使用离线状态；整机冷启动、实时射频与简体资源接入尚未实现。

双击 [Open-IC705-Chinese-Preview.cmd](Open-IC705-Chinese-Preview.cmd) 可在同一原厂面板查看[显示设置第一页的简体标题、四个设置和当前值](docs/IC705_ZH_DISPLAY_PAGE.md)。在 `6/6` 仍可用「显示语言」切到原厂英语，再切回日语恢复预览。

[Open-IC705-ARM-Preview.cmd](Open-IC705-ARM-Preview.cmd) 使用[在模拟 ARM 上运行的词表和字库](docs/IC705_ZH_CATALOG.md)，覆盖「显示设置」六页、各选项及「显示单位」子菜单。「时间设置」也可预览。需使用现有 Arm GNU Toolchain；不生成刷机文件。

双击 [Open-IC705-Third-Language.cmd](Open-IC705-Third-Language.cmd)，可从[电脑预览面板的首页](docs/IC705_ZH_THIRD_LANGUAGE.md)进入设置，选「简体中文」。点窗口底部的「保存」后可以关闭窗口，再双击打开；中文选择仍会保留。系统语言保持独立。预览从首页开始，整机从通电到首页仍待验证。

双击 [Open-IC705-CW-Panel.cmd](Open-IC705-CW-Panel.cmd)，用 `CW → MENU → CW DECODE` 验收左侧译文和右侧波形、频谱、瀑布。短按 `HOLD/CLR` 冻结译文，再按恢复；按住约一秒清屏。点标题右侧 WPM，或翻到底栏第 2 页点 `ADJ`，可选 `AUTO`、`LOCK` 或 `MANUAL`。按机身 **EXIT** 返回；原厂 KEYER 和 RTTY DECODE 仍可打开。详见 [CW 验收记录](docs/IC705_CW_DISPLAY.md)。实验仅在电脑运行。

用 `./Open-IC705-CW-Panel.cmd --track-demo` 打开[自动跟音样本](docs/IC705_CW_DISPLAY.md#auto-跟音与-fix-对照)；进入 CW 解码后选 `< 1 > → ADJ → FILTER → AUTO`。白线应先跟到 600 Hz，再跟到 900 Hz；两段译文合为 `CQ TEST DE IC705`。

日版 1.40 的 [CW 电脑启动镜像与复跑命令](docs/IC705_BOOT_CW_JOIN.md#打包镜像启动验收)可以验证从主 CPU 复位到收音、显示和退出的全过程。`.ic705sim` 与上面的点击面板用途不同，只供电脑仿真。

[同一 CW DAT 的 RZ/A1 仿真](docs/IC705_CW_RELEASE.md#同一-cw-dat-的-rza1-仿真)已通过原厂验包、写入、冷启动和 `CQ` 显示，原厂引导没有擦写。该试验仅在电脑内存中生成 DAT，输出为日志和截图。

当前只推进机内 CW 接收解码。见[独立 ARM 实测和可刷写交付门槛](docs/IC705_CW_RELEASE.md)；其他功能等 CW 真机交付后再推进。

2026-11-18 CW 当前交付：[D6 日版 1.40 黑屏唤醒 DAT](docs/IC705_CW_RELEASE.md#d6-黑屏唤醒测试版)已由同一 RX3 静态导出，默认保持 D5 WIDE，未加入独立实录失败的 AUTO/FIX 默认方案。[下方触摸不唤醒](docs/IC705_CW_BACKLIGHT.md)修复已过电脑专项，现等真机电池超时后上下唤醒及首击防误触测试。保留手选 AUTO 的长静默规则，开发误字 15→6，仍未消除；[默认覆盖缺口](docs/IC705_CW_RX_REACQUIRE.md)和轻微掉帧仍在。本轮没有重新编译、操作电台或重测升级/开机，最新断点以项目接续记录为准。

| 交付 | 内容 |
| --- | --- |
| [硬件与软件系统架构](docs/HARDWARE.md) | 处理器、存储、LCD、音频与控制路径；区分实证和推断 |
| [官方固件结构及 REA 分析](docs/REA_ANALYSIS.md) | 三个官方版本、哈希、四组载荷、REA Provider 实测、静态分析限制 |
| [日版固件与地区差异](docs/JAPAN_FIRMWARE.md) | 九个日版包、零占位、三组切片、版本对照和候选范围 |
| [DAT 组件归属复核](docs/FIRMWARE_COMPONENTS.md) | 九版公告对照、WLAN 和 DSP 证据及外层头字段 |
| [主 CPU 提取与静态验证](docs/MAIN_CPU_DECODE.md) | 两个日版和一个 E 版的主程序哈希、启动映射、GPS 改动与资源引用 |
| [PC 上执行原厂主程序](docs/IC705_EMULATION.md) | 原厂设置导航、菜单绘图、GPS 对照、启动外设停点与后续验收标准 |
| [板级启动验收脚本](Verify-IC705-Board-Startup.cmd) | 双击复跑日版 1.40 串口返回、复位入口和待机分支；详见[实验记录](docs/IC705_SD_RESOURCES.md#j140原厂串口返回与板级电源分支) |
| [原始 A 组探针](docs/MAIN_CPU_ANALYSIS.md) | A 组 6 MiB 切分、周期标记、跨版本索引与 A32 盲扫的历史记录 |
| [跨机型封装对照](docs/CROSS_MODEL_FORMAT.md) | IC-705、IC-905、IC-9700 首段、摘要与稳定尾段 |
| [A 组尾段探针](docs/TAIL_RECORD_ANALYSIS.md) | 跨机型重复地标、索引和字体反例 |
| [CS-705 菜单对照](docs/CS705_MENU_REFERENCE.md) | 两版官方 PC 软件中的菜单键、帮助主题和新增选项 |
| [CS-705 设置字段](docs/CS705_SETTINGS_MAP.md) | 四个单字节设置、官方 ICF 样本、12 个 DAT 的明文对照 |
| [第三方功能扩展可行性](docs/FEASIBILITY.md) | 算法候选、许可证、资源估算与验证标准 |
| [本机卫星跟踪与多普勒补偿](docs/SATELLITE_TRACKING.md) | 本机选星、内置 GPS、上下行独立补偿、跨段半双工证据与验收 |
| [日版 1.40 原厂 GPS 输入回放](docs/IC705_GPS_INPUTS.md) | NMEA、经纬度、UTC 跨日和独立过期；原厂计算及 RX 距离文字 |
| [日版 1.40 离线卫星过境](docs/IC705_SATELLITE_PASS.md) | 从离线列表选星、核对双向补偿、定位或 UTC 过期立即停更 |
| [PC 卫星选星和状态页](docs/IC705_SATELLITE_PANEL.md) | 原厂 ARM 回放、双路异常、PTT 冻结与确认接收后恢复 |
| [日版 1.40 双 VFO 与 Split](docs/IC705_VFO_SPLIT.md) | A/B 四种状态、原厂 CI-V 回复、收发候选与面板副频文字 |
| [日版 1.40 双 VFO 调谐与 PTT](docs/IC705_PTT_TUNING.md) | 两个跨段方向的原厂调谐和恢复、频率范围初始化，以及 PTT 请求与状态回读的区别 |
| [整机简体中文化](docs/LOCALIZATION_ZH_CN.md) | 第五项长期需求、菜单与字库证据、覆盖及回退标准 |
| [显示语言到字库](docs/IC705_LANGUAGE_FONT.md) | 日版两版设置与绘制链、两份字体的哈希及「表」的轮廓验证 |
| [开机图片与字体加载对照](docs/IC705_SD_RESOURCES.md) | 双版文件任务、BMP 校验、RGB565 与固定 Flash 字体来源 |
| [RTTY 从 GPIO 到正文](docs/MAIN_CPU_DECODE.md#rtty-从五位符号到正文) | 双版回放 GPIO 位采样、帧校验、字母／数字切换和正文 |
| [接收 PCM：录音与 WLAN](docs/IC705_RX_AUDIO.md) | 双版回放 IF DSP 音频 DMA、录音缓冲、WAV 格式及 WLAN 帧读取 |
| [SSTV Robot 36 离线回放](docs/IC705_SSTV_REPLAY.md) | 双版原厂 8 kHz 输出、已知色卡、低通对照与混叠反例 |
| [简体中文样页](docs/IC705_ZH_CN_PAGE.md) | 开放 TrueType 子集、中英混排及原厂日英缺字回退的桌面实验 |
| [下一阶段技术路线](ROADMAP.md) | 证据顺序、成功判据和停止条件 |
| [恢复和完整性评估](docs/SAFETY_AND_RECOVERY.md) | 摘要、签名、备份、启动恢复的证据状态 |
| [发现台账](FINDINGS.md) · [公开资料](research/SOURCES.md) | 追踪依据、版本和未解决问题 |

静态分析使用 Python 3.11 或更高版本，无第三方依赖。本机已用 Python 3.12.13 建立 `.venv`。仿真脚本另用可选的 Unicorn，安装和运行见[仿真复现](docs/IC705_EMULATION.md#复现)。

```powershell
python -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m unittest discover -s tests -v
& $py tools/firmware_scan.py --help
& $py tools/firmware_scan.py layout firmware/705J140.dat
& $py tools/firmware_scan.py scan firmware/705J140.dat --block 0x10000
& $py tools/firmware_scan.py compare-groups firmware/705J132.dat firmware/705J140.dat
& $py tools/firmware_scan.py strings firmware/705J140.dat --minimum 16 --limit 20
& $py tools/firmware_scan.py arm firmware/705J140.dat --start 0x68 --end 0x1068
& $py -m tools.decode_705_main firmware/705J140.dat .analysis/main-decode/repro-J140
& $py -m tools.probe_705_fonts firmware/705J140.dat
& $py -m tools.probe_705_menu_text firmware/705J140.dat
```

Linux/macOS 使用 `.venv/bin/python`。脚本只读输入；范围为左闭右开。`compare-groups` 先对齐校验过的组，返回相对组起点的差异偏移；`compare` 直接比较相同文件偏移。两者都不重对齐组内插入或删除。`firmware_scan.py arm` 只报告 A32 小端位模式；分析实际函数要先用 `decode_705_main` 输出引导、主程序及 JSON 清单到新目录，再按[已验证地址](docs/MAIN_CPU_DECODE.md#从启动代码验证装载地址)反汇编。离线 CW 样本见[生成及校验说明](samples/README.md#cw-离线测试样本)。

原厂 ZIP、DAT、ICF、切片和本地证据分别留在被 Git 忽略的 `firmware/` 与 `.analysis/`。版本、来源和 SHA-256 写入报告。不要提交或分发原厂文件、设备备份或固件切片。
