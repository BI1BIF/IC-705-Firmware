# Icom DAT：首段与稳定尾段的跨机型对照

2026-11-13。为检验日版 IC-705 A 组的 6 MiB 切分，加入 [IC-705 1.11](https://www.icom.co.jp/support/drivers/5612/)（2020-08-28），另比较 IC-905 [1.15](https://www.icom.co.jp/support/drivers/7802/) / [1.20](https://www.icom.co.jp/support/drivers/8671/) 和 IC-9700 [1.44](https://www.icom.co.jp/support/drivers/7495/) / [1.50](https://www.icom.co.jp/support/drivers/8599/)。下载 URL、大小、ZIP/DAT SHA-256 和 DAT 成员 CRC-32 分别见 [705J 清单](../research/705j-provenance.json)和[跨机型清单](../research/icom-comparator-provenance.json)。所有数据留在本地；对照包没有用于电台。

## 切分点和摘要

表中地址均是 DAT 文件偏移，范围左闭右开；字段为小端 32 位值。先依据头部候选长度划定首段，再单独扫描至少 4 KiB 的精确 256 字节周期区，并核对首段后 16 字节。

| 包 | 魔数 | 首段范围、长度字段 | 切分点与尾长 | 相邻首段 MD5 |
| --- | --- | --- | --- | --- |
| IC-705 J111 / J140 | `44 00 77 55` | `[0x64, 0x9C0064)`，`0x38 = 0x9C0000` | `0x600064`；`0x40 = 0x3C0000` | 两版匹配；整个 IC-705 包亦通过既有布局检查 |
| IC-905 J115 / J120 | `44 22 00 99` | 候选 `[0x88, 0x9C0088)`，`0x3C = 0x9C0000` | `0x600088`；`0x44 = 0x3C0000` | 两版都不匹配；首段范围仍为候选 |
| IC-9700 J144 / J150 | `33 99 11 33` | `[0x38, 0x800038)`，`0x1C = 0x800000` | `0x400038`；由周期终点和两版稳定后段支持，未识别尾长字段 | 两版匹配 |

- **IC-705 1.11 复核通过。**A、C、D 的 MD5 和 B 零占位均匹配，尾标仍为 `40 75`。现在 **12 个 IC-705 DAT（9 个 J、3 个 E）**都在 `0x600064` 切分，后 3.75 MiB 逐字节相同。
- **IC-905 提供同几何布局、不同外层封装的对照。**两个版本的三个相邻值是 `0x9C0000 / 0xC00000 / 0x3C0000`，整体比 IC-705 的字段位置后移 4 字节。倒推的切分点恰是周期终点；两版首段前部变化、后 3.75 MiB 不变。用 IC-705 的相邻摘要规则检验失败，不能复用其整包解析器。
- **IC-9700 提供切分位置变化的对照。**首段只有 8 MiB，相对切分点是 4 MiB。两个版本首段前部不同，后 4 MiB 不变。两版第二段 `[0x800058, 0xEE3FDE)` 的长度等于头部 `0x30` 的值 `0x6E3F86`，相邻 MD5 也匹配。首段摘要之后是 16 个零字节；第二段摘要之后是 16 个版本样 ASCII 字节及尾标 `39 13`。没有找到等价于 IC-705 `0x40` 的字段。

三个机型在切分前后都能找到相同的 256 字节周期模式（循环旋转归一后哈希相同）。例如尾段相对 `[0x3975D7, 0x39AA6B)` 的周期地标在三个机型中长度、位置和模式都一致。跨机型证据支持**文件布局存在关联**，仍不能确定 IC-705 `0x3C = 0xC00000` 的语义，也没有验证 `0x40` 改变时 IC-705 自身边界如何变化。

## 尾段字节相关性和错位对照

用 J140 尾段作基准，比对另外两个机型尾段前 3.75 MiB。按 4 KiB 分窗，排除任一侧整个窗完全按 256 字节重复的窗。对每窗只数逐字节异或结果有多少种不同取值；表中统计不超过 16 种的窗。向右错开一页再比较，越过候选尾段的字节不参与。IC-905 的观测确定了检查阈值，IC-9700 用来复核。

| 与 J140 对照 | 对齐后相同字节 / 3,932,160 | 对齐后 ≤16 种 / 非周期窗 | 错开 4 KiB 后 ≤16 种 / 非周期窗 |
| --- | ---: | ---: | ---: |
| IC-905 J115 / J120 | 0 | 936 / 936 | 0 / 933 |
| IC-9700 J144 / J150 | 78 | 928 / 929 | 0 / 927 |

IC-905 在对齐的 3.75 MiB 内总共只有 14 种异或值，尽管没有一字节直接相同。IC-9700 也有显著的位置相关性，但对齐后仍有 **7 个连续的 4 KiB 窗**出现超过 32 种异或值，对应 J140 的 `[0x9A2064, 0x9A9064)`。

进一步比较覆盖这些窗右边界的周期区起点，发现 IC-9700 **提前 25,640 字节**进入周期区。三个对齐区间分别为 J140 `[0x9A25ED, 0x9A8A15)`、905J120 `[0x9A2611, 0x9A8A39)`、9700J150 `[0x7A25C1, 0x7A89E9)`。逐字节比较每个区间和自身滞后 256 字节的序列，只有 IC-9700 在整个区间内完全匹配。J140 该区间未命中 `firmware_scan.py` 的常见格式签名。原始检查见 `.analysis/icom-tail-periodic-edge.json`。

统计表明相似性超出了少数纯周期区；它不能识别编码方式、证明相同明文、定位字库或确认可执行代码。没有进行逆变换或尝试绕过校验。

[尾段续测](TAIL_RECORD_ANALYSIS.md)在这个 25,640 字节窗口里找到 IC-705 与 IC-905 位置一致的四组重复地标；IC-9700 周期对照为零。没有确认记录边界、明文索引或资源格式。

## REA 复核

现有 REA MCP 6.8.0 通过 `open_binary` 识别 ZIP 并用 `inspect_artifact` 核对 DAT 成员 SHA-256，两次归档会话均已关闭。另用 `inspect_byte_entropy` 检查候选切分点前后各 4 KiB：

| 版本 | ZIP Evidence | 边界两侧熵（bit/byte）与 Evidence |
| --- | --- | --- |
| 905J120 | `ev_c8ca52b925df79daf3bd5bd4f30f1009dad5d26cbaa402d3818b4a25b6127df8` | 8.0000 → 7.9584；`ev_872e33853123cd086466e419152ff20dc7aa9de07d84d217c8005fc579bec62d` |
| 9700J150 | `ev_744a10b93c6e50d8d4fbd3ead45d09d74282fb6f2d9b59de8c5eb07e0e6950b8` | 8.0000 → 7.9534；`ev_77096aa17738868193e2015c022fc3425b5bf81089023b69c995f634aac01389` |

熵只作辅助观测，边界以实际 MD5、逐字节周期和版本差异为依据。完整 Evidence 保存于 `.analysis/rea-zip-{905J120,9700J150}.json` 和 `.analysis/rea-entropy-{905J120,9700J150}-boundary.json`。没有确认兼容的可执行组件，因此还不能用 REA 分析固件函数。

## 复现

按来源清单获取 ZIP，在本地保留并核对指定的 DAT 成员；将 IC-905 和 IC-9700 放在 `firmware/comparators/`。脚本只读 DAT，输出候选范围、实际周期地标、SHA-256、摘要匹配和字节统计。

```powershell
$data = @(
    'firmware/705J140.dat', 'firmware/705J111.dat',
    'firmware/comparators/905J120.dat', 'firmware/comparators/905J115.dat',
    'firmware/comparators/9700J150.dat', 'firmware/comparators/9700J144.dat'
)
New-Item -ItemType Directory -Path .analysis -Force | Out-Null
.\.venv\Scripts\python.exe -m tools.probe_icom_comparators @data |
    Set-Content -Encoding UTF8 .analysis/icom-cross-model.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`periodic_spans_payload_relative` 相对首段起点；异或统计的窗偏移相对被比较尾段。要复核精确差异范围，从覆盖最后一个差异窗右边界的周期区起点减去各自的 `tail.relative_start`，可得到尾段相对边缘 `0x3A2589` 和 `0x3A89B1`。在每个 DAT 上将这两个值加到 `tail.start`，比较切片的 `slice[:-256] == slice[256:]`。12 个 IC-705 的独立验证见 [A 组复现](MAIN_CPU_ANALYSIS.md#复现)。
