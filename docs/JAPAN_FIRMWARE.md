# IC-705 日版固件：705J 为主样本

2026-11-13。用户确认电台为日版。Icom [日本产品页](https://www.icom.co.jp/lineup/products/IC-705/)列出的最新日版固件是 [1.40，2025-08-21](https://www.icom.co.jp/support/drivers/8603/)，公告明确使用 `705J140.dat`。后续以 705J 为基线；705E 仅用于文件级对照。本机实际安装版本、序列号和板修订未核实，也不需要这些信息才能继续静态分析。[主程序报告](MAIN_CPU_DECODE.md)记录 1.32/1.40 两版的实际解包、入口和 GPS 代码对照；下文侧重外层布局。

## 来源与核验

已下载 1.11、1.20、1.24、1.26、1.27、1.30、1.31、1.32、1.40 九个版本；1.20 和 1.24 用于 A 组切分点的留出检验，1.11 用于进一步向前验证。来源为日本站[官方历史列表](https://www.icom.co.jp/support/personal/firmware_driver/?business=2&class=&frm_name=IC-705&frm_type=%E3%83%95%E3%82%A1%E3%83%BC%E3%83%A0%E3%82%A6%E3%82%A7%E3%82%A2&old=true&open=tab2&product=%7CIC-705%7C&type=5)各发布页的下载按钮。[来源清单](../research/705j-provenance.json)逐版记录发布页、实际下载 URL、ZIP/DAT 字节数、两者的 SHA-256 和 DAT 的 ZIP CRC-32。Python `zipfile` 读取指定 DAT 成员并验证 CRC，原厂文件和派生切片均保存在被 Git 忽略的 `firmware/`。

`705J140.dat` 是 **12,259,086 字节**，SHA-256 为 `2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45`。现有 REA MCP 6.8.0 打开的是 ZIP，归档分析独立得到同一 DAT 哈希；会话已关闭。归档 Evidence `ev_0f3127a753a02dce1c3f535e01ea8e0a06c0aa41c1191edf8a4ec02a907ce671`；DAT 熵 Evidence `ev_0be0c1dd8c5207eef522fb960179fc9db52d20cad1f7420774818d12ccb42669`（7.9969 bit/byte，188 个窗口）。原始结果分别保存在 `.analysis/rea-zip-705J140.json`、`.analysis/rea-entropy-705J140.json`。

## 日版布局与实际切片

九个 J 包均通过如下检查：同一 `44 00 77 55` 魔数、0x64 字节头部、同一组小端长度字段和 `40 75` 尾标；头部版本样字段在 `0x08` 之后带 `-J`，E 版对应字节是 `-E`。J 版头部的 B 两段长度均为零，B 位置仅有 **16 个零字节**；这不是空文件的 MD5。其余 A、C、D 三段分别通过原始 MD5 检查。E 版 B 有 `0x4DDE` 字节载荷，两个版本的 1.40 DAT 长度也恰好相差这么多。

以下是 1.40 的左闭右开文件偏移。A、C、D 已提取到 `firmware/705J140-carved/`，原文件未改动。

| 组 | 文件范围 | 实际 SHA-256 / 占位 |
| --- | --- | --- |
| A | `[0x64, 0x9C0064)` | `7d0219d2ce482aa83a54c8de395236b525e2a29795f7b0700fe9d0bdb377a626` |
| B | `[0x9C0074, 0x9C0084)` | 16 字节零占位；无载荷，无切片 |
| C | `[0x9C0084, 0xB2298A)` | `d82fec3ece3bb097378e59d1f9a19ea93e5a8f033a6a41209c00292ec09ff6f5` |
| D | `[0xB2299A, 0xBB0EFC)` | `e59a6a6ba2f91e4d4f7c5920bcf88f39fc66602b34c9f2620bf7e47733bb5e42` |

## 版本与地区差异

以校验通过的组边界对齐，再比较字节。表中“变化范围”是 A 组第一个和最后一个不同字节所包围的区间（左闭右开），区间内也有不变字节。

| 对照 | 变化的载荷组 | A 组差异字节数 | A 组变化范围（文件偏移） |
| --- | --- | ---: | --- |
| J 1.26 → 1.27 | A | 1,981,875 | `[0x64, 0x2015D8)` |
| J 1.27 → 1.30 | A、C | 4,389,438 | `[0x64, 0x5E649D)` |
| J 1.30 → 1.31 | A | 2,051,325 | `[0x64, 0x207AB6)` |
| J 1.31 → 1.32 | A、C | 3,135,519 | `[0x64, 0x5E84FD)` |
| J 1.32 → 1.40 | A | 4,247,403 | `[0x64, 0x5EFABD)` |
| E → J 1.26 / 1.32 / 1.40 | A，J 无 B；C、D 逐字节一致 | 2,045,133 / 2,082,645 / 2,080,983 | 三对均为 `[0x64, 0x267A98)` |

- **A 是主 CPU 程序的优先候选。**三次只有 A 载荷改变的更新中，官方部件表的 Main CPU 版本发生变化，列出的 DSP、DV DSP 和 FPGA 不变。1.26→1.27 以及 1.30→1.31 的变化集中在前约 2 MiB，可优先与后段做对照；变动不等于该处是代码。首轮的六个 J 包和三个 E 包在 `[0x5EFABD, 0x9C0064)`（3,999,143 字节）完全相同，可用作对照。
- **C 与 DSP 版本有关，D 是 WLAN 相关载荷的强候选。**[九个日版对照](FIRMWARE_COMPONENTS.md)发现，C 在两个 DSP 程序版本中的任一个单独变化时都会变，不能只归给 DV DSP。D 唯一一次变化（1.11→1.20）和 WLAN 版本变化一致，从 1.20 起八个日版的 D 逐字节相同。
- **高熵和 ARM 归属是不同的问题。**J140 A 内有六个按 A 起点划分的 64 KiB 窗逐字节呈 256 字节周期（文件偏移 `0x210064` 至 `0x250064`，及 `0x5F0064`），未命中扫描脚本内置的常见格式标识。尚无足够证据确认 A32/Thumb、装载地址、入口或任一 RTTY/LCD 函数；没有将 DAT 或切片强行导入反汇编工具。

## 复现和下一项验证

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py tools/firmware_scan.py layout firmware/705J140.dat
& $py tools/firmware_scan.py compare-groups firmware/705J132.dat firmware/705J140.dat
& $py tools/firmware_scan.py compare-groups firmware/705E140.dat firmware/705J140.dat
& $py tools/firmware_scan.py scan firmware/705J140-carved/group-A.bin --block 0x10000
```

`compare-groups` 里的差异偏移相对载荷组起点，须加该组的文件偏移才能和上表对照。`layout` 对空 B 的 `match` 返回 `null`；用 `all_records_valid` 检查全部实际 MD5 与零占位。按 [REA 报告](REA_ANALYSIS.md#复核)的脚本复现原始切片。反汇编使用[另行提取的主程序](MAIN_CPU_DECODE.md#复现)。

针对菜单文本和字体的额外探针及验收范围见[整机简体中文化](LOCALIZATION_ZH_CN.md)。

A 组的稳定区、周期标记和 A32 探针见[主 CPU 候选区域分析](MAIN_CPU_ANALYSIS.md)。`0x600064` 切分已由 12 个 IC-705 样本验证；与其他机型的边界和尾段差异见[跨机型封装对照](CROSS_MODEL_FORMAT.md)。

[WSL2 上的 REA 复测](REA_ANALYSIS.md#wsl2-固件工具实测)通过已知 gzip 的扫描与完整提取对照。J140/J132 的 Binwalk 候选均未通过标准格式复核；Unblob 对两份 DAT 和 J140 的 A 组切片均无识别文件。这补足了 Windows 无法运行这些接口的测试空缺。
