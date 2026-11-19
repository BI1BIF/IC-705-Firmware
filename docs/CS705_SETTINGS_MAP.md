# IC-705 设置字段：从 CS-705 到官方 ICF

2026-11-13。对 [CS-705 1.21/1.30](CS705_MENU_REFERENCE.md) 做静态反汇编，关联界面选项、单字节设置和官方设置文件。证据支持 **PC 端的设置数据布局**。对现有 12 个 IC-705 原始 DAT 复查后，仍未找到可确认的机内对应结构、ARM 入口或中文字库。

## 设置字段与证据

Icom 的 [J140 更新公告](https://www.icom.co.jp/support/drivers/8603/) 和 [CS-705 1.30 公告](https://www.icom.co.jp/support/drivers/8597/) 同时记录了数字中继和国内中继监控计时器的选项变化。两版 PC 程序均将设置缓冲区指针加上 `0x392C0`（1.21 指令 `0x4A26F0`；1.30 `0x463810`），保存到栈上同一局部槽。各分支从该指针读取一个字节给对应界面选择器，并在选择成功后把结果写回同一字段。

| 设置 | 相对 `0x392C0` | 解码后 ICF 逻辑偏移 | CS-705 1.21 → 1.30 的取值 |
| --- | ---: | ---: | --- |
| 显示语言（Display Language） | `+0x3FB` | `0x396BB` | `00` 英语、`01` 日语，两版相同 |
| 系统语言（System Language） | `+0x3FC` | `0x396BC` | `00` 英语、`01` 日语，两版相同 |
| 数字中继设置 | `+0x6FB` | `0x399BB` | `00` OFF、`01` ON；新增 `02` ON (GW) |
| 中继监控计时器（日本国内） | `+0x700` | `0x399C0` | `00/01/02` 为 10/20/30 分钟；新增 `03` 为 60 分钟 |

语言值也与 Icom [CI-V 指南](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf)的 `1A / 05` 选择器 `0163`（显示语言）及 `0164`（系统语言）一致。选择器编号、PE 虚拟地址、ICF 逻辑偏移和升级包文件偏移是四种独立的坐标。

| 设置 | 1.21 读 → 写（PE VA） | 1.30 读 → 写（PE VA） |
| --- | --- | --- |
| 显示语言 | `0x4B1D23` → `0x4B1D5B` | `0x472E43` → `0x472E7B` |
| 系统语言 | `0x4B1D91` → `0x4B1DCD` | `0x472EB1` → `0x472EED` |
| 数字中继设置 | `0x4AE49B` → `0x4AE4D7` | `0x46F5BB` → `0x46F5F7` |
| 中继监控计时器 | `0x4AE9D7` → `0x4AEA13` | `0x46FAF7` → `0x46FB33` |

- 数字中继的选择器由 `GI_Sheet_Sel_Misc_OnOff` 换成 `GI_Sheet_Sel_Common_DigiRpt`；英文界面表在 PE 文件 `0x3964AA`（1.21）和 `0x3B77BC`（1.30）。计时器选择器 `GI_Sheet_Sel_Common_RepeaterMonitorTimer` 不变，表在 `0x3B2866` / `0x3B81FE`。语言共用 `GI_Sheet_Sel_Common_Language`，表在 `0x3BC501` / `0x3C1EAD`。两版另各有两套 CP932 界面记录。以完整选择器表的 `Flex0` 索引为依据，单搜 `60min` 会误把 1.21 的其他项目算进去。
- 1.30 的设置版本转换函数 `0x4DF884` 在 `0x4DF97A` 读反向转换表 `0x85B864` 的第 6 项（表项地址 `0x85B88C`），调用 `0x4DFA38` 后将当前版本减为 5。该函数把 `0x399BB` 的 `>= 2` 值降为 `1`（`0x4DFA5E`–`0x4DFA69`），把 `0x399C0` 的 `>= 3` 值降为 `2`（`0x4DFA72`–`0x4DFA7D`）。这是两个新增值确实进入设置缓冲区的独立证据。
- 1.30 的 ICF 导出路径在 `0x425589` 调用转换、在 `0x4255A4` 把转换后缓冲区描述符交给序列化对象，从逻辑地址 0 登记数据（`0x4132D0`）。写记录时 `0x413608` 使用 `%08X%02X` 输出记录地址和长度，`0x41361F`–`0x413640` 按逻辑地址加行内偏移取字节，再用 `%02X` 序列化。读取单字节的实际寻址为 `0x412FF8`–`0x412FFB`。官方 ICF 的记录布局与这条路径一致。

## 官方 ICF 样本

从 [Icom 日本中继列表](https://www.icom.co.jp/support/drivers/8924/)和 [Icom America IC-705 中继列表](https://www.icomamerica.com/support/firmware_driver/3071/)取得原始 ZIP；实际下载地址和 SHA-256 在[来源清单](../research/icom-705-settings-provenance.json)。成员名以实收 ZIP 为准。两份 ICF 文件均为 589,697 字节，以 `40750001` 开头；各有 7,758 条 32 字节记录，解码后逻辑范围 `[0, 0x3C9C0)`。脚本检查记录地址、长度、连续性和尾部 `#CD=` 的语法；此次未校验 `#CD=` 的值。只提取原厂成员，没有生成或改写设置内容。

| 原厂样本 | `MapRev` | 显示 / 系统语言 | 数字中继 | 计时器原始值 |
| --- | ---: | --- | --- | --- |
| `705_JPN_260627.icf` | `6` | `01 / 01`（日语） | `01`（ON） | `00`（10 分钟） |
| `705_USA_221222.icf` | `3` | `00 / 00`（英语） | `01`（ON） | `01`（仅作原始值对照） |

两份样本按已定位字段读出的语言差异符合地区对照；没有拿到实际含 `02` / `03` 新选项的官方设置文件，这两个值由界面表、读写和降版路径证明。美国版样本不用于推断国内计时器的可用性。这些结果不确定 ICF 以外的机内内存或 Flash 布局。

## 与原始 DAT 的对照

对 9 个 J 版和 3 个 E 版逐包核对外层布局，再分别搜索全包、A 前段 `[0x64, 0x600064)` 和 A 尾段 `[0x600064, 0x9C0064)`。使用两份 ICF 中覆盖语言对及中继设置对的 16/32/64 字节窗口（共 12 个；每个至少 4 种字节）、选项和完整选择器标识，以及 24/32 位大小端字段偏移对（起点间隔最多 64 字节、不重叠、任意对齐和顺序）。

- **12 个 DAT 均无**窗口、标识或偏移对命中。12 个 ICF 窗口在各自样本里都能准确找回，PC 程序命中相应选择器。合成测试确认了非对齐偏移对可以找回，并排除距离过远的组合。
- J132、J140 和 E140 每个只有一个孤立的偏移字面值 `03 99 C0`，同在 DAT `0x787B2E`。同一位置在全部 12 个样本中出现；J120 另在 `0x1C5DAC` 出现一次，仍无邻近的中继字段偏移。此值既不随 1.40 新选项出现，也无代码引用链，不作为计时器定位证据。
- 结果排除了所查的**明文字节表示**。机内程序可能使用不同布局、通过其他方式寻址，或位于尚未解析的载荷中；没有证据确定哪一种。没有把原始 DAT 强行当作 ARM 程序。

对整机汉化，两个相邻语言字段可以作为日英选择的语义参照。机内显示语言读取、语言表、字形与 LCD 绘制仍未建立引用链。[CS-9700 1.50](https://www.icom.co.jp/support/drivers/8600/) 与 1.40 仍可用来区分共用选项和型号特定的设置，但不能替代机内代码证据。按[修订后的路线](../ROADMAP.md)，先找能验证的主 CPU 程序。

## 工具和复现

REA 6.8.0 对 1.30 程序的 `open_binary` 验证了 x86 PE 及其 SHA-256。该 Windows 会话的 `inspect_with_objdump` 返回 `ERR_REA_WINDOWS_NATIVE`；依赖深度 Provider 的 `read_bytes`、`search_bytes` 返回 `provider_unavailable`。复用 Debian WSL2，在 `.analysis/cs-705-objdump/` 解包 [Debian trixie GNU Binutils 2.44-3](https://packages.debian.org/trixie/amd64/binutils-x86-64-linux-gnu) 及其依赖，逐包与 APT 索引 SHA-256 核对。仅运行 `objdump` 读取 PE，没有运行 Icom 安装器或程序，也没有修改系统或 REA 配置。

REA `open_binary` + `inspect_artifact` 独立核对两份 ICF 外层 ZIP 的格式和根 SHA-256：日版 `ev_70899c869e582eec96f8a1ac21cc15c835dddfd265b1875eb3400fac364c6f68`，美国版 `ev_a3c361b96ec6708e665bee68b8151a81da0dbe2b1ea750f8877b6ee34f30bc16`。会话均已关闭，输出存 `.analysis/cs-705/rea-official-settings-{jpn,usa}.json`。ICF 成员 SHA-256 用本地 ZIP 库另行核对。

解包步骤见 [CS-705 菜单报告](CS705_MENU_REFERENCE.md#工具和复现)。在支持 x86 PE 的 GNU objdump 上，可查阅关键指令和关联数据；示例地址为 1.30，1.21 用上表对应地址：

```sh
pe=.analysis/cs-705/1.30/extracted/DefaultComponent/CS705.exe
objdump -h "$pe"
objdump -d -Mintel --start-address=0x463802 --stop-address=0x463822 "$pe"
objdump -d -Mintel --start-address=0x46F5B3 --stop-address=0x46F5FD "$pe"
objdump -d -Mintel --start-address=0x4DFA38 --stop-address=0x4DFAA9 "$pe"
objdump -s -j .data --start-address=0x85B864 --stop-address=0x85B894 "$pe"
objdump -d -Mintel --start-address=0x413600 --stop-address=0x413650 "$pe"
```

从两份 ZIP 中各提取上表所列的 ICF 成员到 `firmware/comparators/`。在项目根目录运行设置探针，输出只含偏移、选项、哈希及命中统计：

```powershell
$datArgs = Get-ChildItem firmware -Filter '705*.dat' | Sort-Object Name | ForEach-Object {
    '--firmware'; "firmware/$($_.Name)"
}
.\.venv\Scripts\python.exe -m tools.probe_705_setting_map `
    --icf firmware/comparators/705_JPN_260627.icf --icf firmware/comparators/705_USA_221222.icf `
    --cs .analysis/cs-705/1.21/extracted/DefaultComponent/CS705.exe `
    --cs .analysis/cs-705/1.30/extracted/DefaultComponent/CS705.exe @datArgs |
    Set-Content -Encoding UTF8 .analysis/cs-705/settings-map-all.json
```
