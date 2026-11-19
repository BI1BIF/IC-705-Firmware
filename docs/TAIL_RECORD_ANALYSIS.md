# 日版 IC-705 A 组尾段：重复地标和资源探针

2026-11-13。对 [跨机型对照](CROSS_MODEL_FORMAT.md) 确定的尾段相对区间 `[0x3A2589, 0x3A89B1)` 做了 7 个官方 DAT 的只读实验。焦点是 25,640 字节，文件偏移在 IC-705 为 `[0x9A25ED, 0x9A8A15)`、IC-905 为 `[0x9A2611, 0x9A8A39)`、IC-9700 为 `[0x7A25C1, 0x7A89E9)`。

续测已解开两个日版 IC-705 的 A 尾段：实际小字体记录是 DAT `[0x9A25EC, 0x9A8A14)`，比上述原始地标窗口早一字节，内含 4 字节长度和 25,636 字节 TrueType。下文保留未解码时的探针结果；验证见[语言和字库报告](IC705_LANGUAGE_FONT.md)。其他机型未在续测覆盖。

## 可复现的重复位置

在焦点、紧邻其前及紧邻其后各取一个等长窗口。枚举 256 的整数倍间隔，保留两份都在同一窗内、至少 16 字节的最长连续相等区间；任一份完整匹配其本地前后 256 字节处副本时排除。比较各文件的「第一份起点相对窗的偏移、间隔、长度」三元组。下表是每个文件各窗的数量；左窗的 548 个三元组在全部 7 个样本中逐项相同。

| 机型与样本 | 左窗 | 焦点 | 右窗 |
| --- | ---: | ---: | ---: |
| IC-705 J140、J111、E140 | 548 | 4 | 0 |
| IC-905 J120、J115 | 548 | 4 | 0 |
| IC-9700 J150、J144 | 548 | 0 | 0 |

全部右窗及 IC-9700 焦点完全按 256 字节周期重复。IC-705 各版本的焦点字节本来相同；跨机型复现的价值在于 IC-905 焦点有同样的四个三元组，原始内容却不同。下表为 J140 的 DAT 文件偏移；IC-905 对应起点各加 `0x24`。

| 第一份 | 第二份 | 字节 | 间隔 |
| --- | --- | ---: | ---: |
| `0x9A498B` | `0x9A598B` | 67 | `0x1000` |
| `0x9A5A90` | `0x9A6390` | 26 | `0x0900` |
| `0x9A2AF5` | `0x9A81F5` | 20 | `0x5700` |
| `0x9A342B` | `0x9A5C2B` | 16 | `0x2800` |

最长的 67 字节在两个机型各只有两份（在各自焦点窗内精确计数），两端外侧字节均不再相等。把间隔改为 `0x0FFF / 0x1000 / 0x1001`，J140 相等字节数为 `1 / 67 / 1`，IC-905 为 `2 / 67 / 2`。两机型同位置的原始字节只匹配 `0/67`。比较重复点前 512 字节起的两个 4 KiB 窗，J140 只有 `143/4096` 相同，IC-905 为 `151/4096`。因此可把这四处用于对齐；没有证据划出 4 KiB 记录或确定其内容。

## 长度、索引和资源检验

- 在两份最长重复各自前后 64 字节搜索它们的位置（文件、尾段、焦点相对偏移）、长度和间隔，覆盖可容纳的 16/24/32 位大小端表示，并查其 CRC32、MD5。J140、905J120 均无命中。结论只覆盖这些字段形式和范围。
- 在焦点窗枚举 16/32 位大小端及所有字节对齐方式，保留至少 8 个连续递增、且都在窗内的数值。IC-705 得到 19 处、IC-905 23 处、IC-9700 0 处，全为 16 位。IC-705 和 IC-905 仅两处的起点及字节序相同（大端 `+0x17A`、小端 `+0x179`）；所有候选都没有指向任一重复区的起止边界。J140 最长序列的 41 步中有 38 步为 `0x0202`，简单的数值斜坡即可产生这种候选。未确认索引。
- 焦点前后各扩 4 KiB，搜索通用容器、图像和字体标识。J140 的 7 个短标识均未通过最小头部检查：2 个 BMP 的大小或保留字段不符、4 个 FNT 3 的 `dfSize` 超出完整文件、左侧的 1 个 PSF1 模式值为 `0xFD`。IC-905 的 4 个 BMP 和 4 个 FNT 同样被排除，IC-9700 无匹配。校验依据为 [Microsoft BMP 头](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-bitmapfileheader)、[FreeType 的 FNT 解析](https://github.com/freetype/freetype/blob/master/src/winfonts/winfnt.c) 和 [kbd 的 PSF 实现](https://github.com/legionus/kbd)。排除的是这些匹配；无法据此排除其他字体、索引、位图或编码。
- 焦点窗内 10 个常见日英菜单标签（UTF-8、UTF-16LE/BE、CP932）、完整 CI-V 语言选择前缀及相邻选择器表均无匹配。J132 和 J140 的整个原始 DAT 同样未找到 [Icom 1.40 公告](https://www.icom.co.jp/support/drivers/8603/)所列两个设置标签。该尾段跨版本不变，不能用其中某处差异追踪 1.40。已转到 [CS-705 菜单对照](CS705_MENU_REFERENCE.md)取独立语义证据。

## REA 复核与复现

REA MCP 6.8.0 的 `inspect_byte_entropy` 在尾段相对 `[0x3A1000, 0x3AA000)` 输出 144 个 256 字节块。J140、905J120 各 22 块为 8.0000 bit/byte，9700J150 有 122 块；最小值分别为 6.8244、6.6455、7.1139。证据在本地 `.analysis/rea-tail-records-{705J140,905J120,9700J150}.json`；边界的主要依据是逐字节周期和精确重复，熵不用于判断加密。

| 样本 | REA Evidence |
| --- | --- |
| 705J140 | `ev_48811006ff43d5bb04b8ab6aae5c17808851c5da4cfc9d8cb823193298ad284a` |
| 905J120 | `ev_0ce53fc690605b71e6a26e8d1ca88484462606560d1e1742bac9871dd1ba7c59` |
| 9700J150 | `ev_02cb47061e5abbebea03585e1b5f73598a01919fa22c49ca551c6257b7ed1fbb` |

从项目根目录运行，输入路径和 SHA-256 可与 [日版](../research/705j-provenance.json)、[跨机型](../research/icom-comparator-provenance.json) 和 [E 系列](REA_ANALYSIS.md#来源和校验)记录核对：

```powershell
$paths = @(
    'firmware/705J140.dat', 'firmware/705J111.dat', 'firmware/705E140.dat',
    'firmware/comparators/905J120.dat', 'firmware/comparators/905J115.dat',
    'firmware/comparators/9700J150.dat', 'firmware/comparators/9700J144.dat'
)
New-Item -ItemType Directory -Path .analysis -Force | Out-Null
.\.venv\Scripts\python.exe -m tools.probe_705_tail_records @paths |
    Set-Content -Encoding UTF8 .analysis/705-tail-records.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`images[*].zones.focus.repeat_runs` 存三元组，起点加 `zones.focus.start` 转为 DAT 偏移；`packed_offset_candidates` 存候选条数、步长和命中的重复区边界，`near_longest_repeat` 存最长重复段周边的字段命中。合成测试覆盖精确 67 字节匹配、纯周期排除、边界索引及短魔数反例。文件结构和上述否定结果可信度高（限于所列探针）；记录语义、字库、装载地址、ARM 入口和函数均未验证。
