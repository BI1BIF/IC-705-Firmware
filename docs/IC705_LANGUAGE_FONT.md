# 日版 IC-705：从「显示语言」到「表」字形

2026-11-13。以日版 `705J140.dat` 为主样本，`705J132.dat` 作对照。两版均已在本地追通**显示语言设置 → 菜单文字 → 字符转换 → 原厂字库 → 字形**。结果来自 A32 反汇编、原厂字节与独立字体读取；语言、菜单行绘制请求和字符转换又经过[原厂代码离线执行](IC705_EMULATION.md#原厂菜单行和-gps-函数的动态证据)。未在电台上执行固件或读取、更改设备状态。输入来自 Icom 日本 [1.40](https://www.icom.co.jp/support/drivers/8603/) 和 [1.32](https://www.icom.co.jp/support/drivers/7074/) 发布包，见[来源与输入哈希](../research/705j-provenance.json)和[主程序提取](MAIN_CPU_DECODE.md)。

## 显示语言与系统语言

Icom [日版手册](https://www.icom.co.jp/support/manual/4873/) `A7577D-1J-8` 印刷页 13-19 在 `SET > ディスプレイ設定` 分开说明「表示言語」和「システム言語」，日版两项默认均为日语。显示语言选菜单文字；系统语言控制可用字符及名称编辑。日语名称在英文系统模式下显示为 `=`、`_` 等占位，切回日语后可以重新显示和编辑。[Icom 英文基础手册](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)第 8-19 页还明确说明，系统语言为英语时隐藏「显示语言」。[原厂 CI-V 指南](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf)第 9 页为两项分别定义 `0163`、`0164`，`00` 为英语、`01` 为日语。以下 `0xA7` / `0xA8` 是固件内部菜单记录索引。日版 PDF 核对用副本位于 `.analysis/source-triage/IC-705_JPN_IM_8.pdf`，SHA-256 `906d81770ab5a3b6c725e116d9ce65ee798445df89c93289d4143b094392d26d`。

| 设置 | J140：记录 → RAM 字段 | J132：记录 → RAM 字段 |
| --- | --- | --- |
| 显示语言 `0xA7` | `0x202F0DFC` → `0x203EAE44` | `0x20304D2C` → `0x203EADBC` |
| 系统语言 `0xA8` | `0x202F0E38` → `0x203EAE45` | `0x20304D68` → `0x203EADBD` |

记录步长 `0x3C`，表基址 J140 `0x202EE6D8`、J132 `0x20302608`。两项范围均为 `0–1`（记录 `+0x0C`、`+0x10`），共享日英选项表（J140 `0x202ED520`、J132 `0x20301478`）。英语与日语标签指针分别在记录 `+0x24`、`+0x30`。「表示言語」字节 `95 5C 8E A6 8C BE 8C EA` 位于 J140 `0x2035CAE0` 和 J132 `0x203702EC`。

J140 `0x2009F520` / J132 `0x2009E02C` 读取两个字节：系统语言为 0 则返回英语，否则返回显示语言。显示语言记录有独立的系统语言判定（J140 `0x200A0114` / J132 `0x2009EC04`），与手册描述的可见性相符。J140 `0x20095E8C–0x20095EA8` / J132 `0x200949EC–0x20094A08` 把有效显示语言写到界面状态的 bit 1、系统语言写到 bit 0；语言选项编辑期间读取的是进入编辑前的快照。普通状态如下：

| 系统语言 | 显示语言字段 | 有效菜单语言 | 「显示语言」项 |
| --- | --- | --- | --- |
| 英语 | 任一现有值 | 英语 | 隐藏 |
| 日语 | 英语 | 英语 | 可见 |
| 日语 | 日语 | 日语 | 可见 |

在[可点击的日版 1.40 原厂面板](IC705_EMULATION.md#日版-140用鼠标操作原厂设置)中，从屏幕坐标打开「表示言語」并选「英語」后，原厂 `0x200A29C0` 在模拟 RAM 将 `0x203EAE44` 从 `01` 写成 `00`，`0x203EAE45` 未被写入，仍为 `01`；原厂随后画出 `Display Language: English` 与 `System Language: Japanese`。再点 `Japanese` 恢复日文。[设置保存与重载续测](IC705_LANGUAGE_PERSISTENCE.md)用原厂例程和模拟存储完成日英往返，并确认第三值可保存，但会在界面状态打包时退化为英语位。

## 菜单文字怎样到达字库

1. **选择文字。** J140 `0x201549B4` 读取 `0x204BAB5C+9` 的两个语言位，调用 `0x20179F8C` 取文字索引；设置类型 4 走 `0x2014BA80 → 0x2014B548 → 0x2014B390`。设置记录类型 2 下按 `行索引 × 0x3C + 语言索引 × 12` 查标签，`0xA7` 日语路径取 `0x2035CAE0`。J132 对应界面状态 `0x204BAABC+9`、选择器 `0x20176570`、标签查询 `0x20147C74`。
2. **转换为 Unicode。** 标签以原有 Shift-JIS 型字节传给文字入口 `0x20142698 → 0x20146970`。J140 字符转换 `0x20144CAC` 的优先表不含这四个双字节，转到 `0x201DED50`。以「表」为例，`95 5C` 走 63 列索引，`(0x95−0x81)×63+(0x5C−0x40)−0x1B9 = 847`；最后一项来自固件跳过表。J140 `0x203317C2` 和 J132 `0x2034511A` 的半字都是 `68 88`，即 `U+8868`。完整标签得到 `U+8868 U+793A U+8A00 U+8A9E`。J132 的文字入口和转换分别在 `0x2013EF7C → 0x20143254`、`0x20141590 → 0x201DAA84`。
3. **取得字体实例。** J140 `0x2014B60C` 把文字样式 1 传给该行绘制函数；`0x20141D94` 查询 `0x2032504C` 得字体标志 1。`0x201450F4` 按标志和字号找缓存，否则用第 `3+标志` 个已创建的实例。因此这行用大日文字体，字体标志独立于菜单文字语言。资源初始化 J140 `0x20104984` / J132 `0x20101364` 读取 Flash 映射 `0x18C00000`、`0x18FA2588` 的两个长度，并把紧跟长度的字体指针保存下来。J140 `0x20144F00`、J132 `0x201417E4` 选取相应的指针和长度，经各自包装器传给 FreeType 的 [`FT_New_Memory_Face`](https://freetype.org/freetype2/docs/reference/ft2-face_creation.html#ft_new_memory_face)（调用 J140 `0x20196E5C`、J132 `0x20192B9C`；诊断字符串确认名称）。字库在初始化时注册；没发现选中日语菜单就重新载入字体的操作。
4. **查找并加载字形。** J140 `0x201971D4` / J132 `0x20192F08` 用 Unicode 字符查字形索引；非 0 才进入 `FT_Load_Glyph`。实测大字体的 `U+8868` 为字形 **3136**，Windows WPF `GlyphTypeface` 直接打开本地原厂字体，未使用系统回退，取得非空轮廓：24 像素下宽 `22.8515625`、高 `22.3125`。小字体没有「表」，两份字体都能找到 `A`、`7`，作为读取的阳性对照。J140 索引为 0 时在 `0x20197224` 返回失败，未缓存字形的调用者在 `0x20197B98` 退出，未到这一串文字的绘制提交；这条路径没有自动换字体。手册中的 `=`、`_` 是名称规则，不是此处的缺字回退。

## 固件里的实际字体

两版解码后 A 组尾段对应 DAT `[0x600064, 0x9C0064)`，逐字节相同，SHA-256 `9cc3924d72b8468b814eae79410c964742cb17d234b10ef830dcce2fee19ab1d`。每份 TrueType 之前有一个 4 字节小端长度；后接 95,808 字节 `FF`，再是位于 `0x9C0054` 的 16 字节标记 `SX4075 V1.00-000`。这里的 25,640 字节记录也解释了[过去在原始 DAT 尾段只看到重复地标](TAIL_RECORD_ANALYSIS.md)的现象：记录是 4 字节长度加 25,636 字节字体，通用扫描看到的还是外层编码。

| 字体 | DAT 字体起点 | 运行时字体指针 | 字节数 / 字形数 | SHA-256 |
| --- | --- | --- | --- | --- |
| `ICOMp_UD_Medium_JP` | `0x600068` | `0x18C00004` | 3,810,692 / 7,739 | `f879b35945b7ce130f7a99be1795c0a9d827a722d4e89bfad4401376b1d940d9` |
| `SUDGoDspIWA-HW-Md` | `0x9A25F0` | `0x18FA258C` | 25,636 / 163 | `19d2af9e822a9ff738e4aafa4041c6e08b7bd5745defb53bbb5a14ff64dc841d` |

两份字体均通过 TrueType 文件校验和、目录、`head`、`maxp`、轮廓表存在性和两张 Unicode format 4 `cmap` 的一致性检查。运行指针来自指令和字库间距交叉验证，不能用 DAT 偏移加引导基址来推算。原厂字体文件仅留本地。

| 字符 | 大字体的字形编号 | 小字体的字形编号 |
| --- | ---: | ---: |
| 表 / 示 / 言 / 語 | 3136 / 1893 / 1541 / 1585 | 0 / 0 / 0 / 0 |
| 中 / 文 | 2613 / 3225 | 0 / 0 |
| A / 7 | 35 / 25 | 35 / 25 |
| 频 / 设 / 蓝 / 简 / U+0378（缺字对照） | 0 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 |

`0` 表示[字库没有这个字符](https://learn.microsoft.com/en-us/typography/opentype/spec/cmap)。进一步拿已有[汉化样页](../samples/zh-cn-display.json)的 59 个不同字符作输入：大字体缺 16 个，包括「显、语、设、简」；小字体缺 40 个。另一项检查按两版菜单转换函数的优先表、查表分支、半角字及私用区规则枚举可能输出。两版均有 17 个样页字符无法经这条路径表示：大字体也缺其中 16 个；额外一项是中点 `·`（原厂字节 `81 45` 产生的是 `・`）。独立 CP932 对照对本样页给出同样的 17 个，未据此假定两者完全等价。原厂路径、字形覆盖和样页字符都是**高可信度离线结果**，范围限于本次的两版程序和菜单绘制器。

## 复现

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -m tools.probe_705_fonts firmware/705J140.dat --extract-to .analysis/font-check-J140
& $py -m tools.probe_705_fonts firmware/705J132.dat --extract-to .analysis/font-check-J132
& $py -m tools.probe_705_menu_text firmware/705J140.dat
& $py -m tools.probe_705_menu_text firmware/705J132.dat
& $py -m unittest discover -s tests

# Windows WPF 独立对照：只打开这个字体，查看「表」的轮廓。
Add-Type -AssemblyName PresentationCore
$path = (Resolve-Path .analysis/font-check-J140/font-0.ttf).Path
$face = [Windows.Media.GlyphTypeface]::new([uri]$path)
$gid = $face.CharacterToGlyphMap[0x8868]
$gid
$face.GetGlyphOutline($gid, 24, 24).Bounds

# A32：用现有主程序，回看选定文本样式和绘制调用。
$main = '.analysis/main-decode/705J140/main.bin'
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x2014B5F4 --stop-address=0x2014B63C $main
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x20104984 --stop-address=0x201049AC $main
arm-none-eabi-objdump -s -b binary --adjust-vma=0x20005000 --start-address=0x203317C2 --stop-address=0x203317C4 $main

# 汉化样页：查询菜单转换与字体，分别查看无法编码和缺字的字符。
$s = Get-Content samples/zh-cn-display.json -Encoding UTF8 -Raw | ConvertFrom-Json
$chars = @($s.title, $s.badge, $s.breadcrumb, $s.fallback_note,
    ($s.mixed_format -f $s.frequency, $s.mode)) -join ''
foreach ($choice in $s.choices) { $chars += $choice.label + $choice.status }
& $py -m tools.probe_705_menu_text firmware/705J140.dat --chars $chars
$r = & $py -m tools.probe_705_fonts firmware/705J140.dat --chars $chars | ConvertFrom-Json
foreach ($font in $r.fonts) {
    $glyphs = $font.glyphs.PSObject.Properties.Value
    '{0} queried, {1} missing' -f @($glyphs).Count, @($glyphs | Where-Object glyph_id -eq 0).Count
}
```

`--extract-to` 可省略，仅输出 JSON；指定时使用 `.analysis/` 下的新目录。菜单探针按主程序哈希限定原厂 J132/J140。现有 REA MCP 6.8.0 的 `inspect_byte_entropy` 独立复核了两份字体 SHA-256，证据 `ev_3fa0a37b7b9c85fb8b69a9ad5dbf31aac4fd6defc4821b8cae958c281561787d`、`ev_cc2c991fd2645df0ff59661dd7628203a2c623cc21a4587f86291dbb3b483d18`。REA 用于字节复核；A32 用本机 Arm GNU objdump，字体分别用 Python 和 WPF 检查。本轮无需新 Linux 环境或设备连接。工作区原始记录在 `.analysis/language-font-705J{132,140}/`（`manifest.json`、`menu-map*.json`、J140 的 `rea-font-*.json`）和 `.analysis/language-font-wpf.json`。测试包含两版 DAT 的原厂菜单与字形对照；两版引导和主程序重提取哈希均与改动前一致。

## 下一关

J140 `0x20197A90` / J132 `0x201937C4` 的绘制后端直接接收 16 位字符缓冲（`r1` 为指针，`r2` 为字符数）。用[引用探针](../tools/probe_arm_callers.py)遍历两版解包主程序，对每个后端入口均找到 4 条 A32 直接调用，逐处确认均先走日文字符转换。未发现跳到该入口的 A32 `B`、Thumb `BLX` 或值恰等于入口地址的对齐字。扫描只认这些模式，不能排除计算地址、间接跳转或其他绘制器；命中由 objdump 和上下文确认。

| 已核实的路径 | J140 | J132 | 对简体中文的含义 |
| --- | --- | --- | --- |
| 直接提交一串 16 位字符 | `0x20146B5C`、`0x20146E44`、`0x201472F4`、`0x201475EC` | `0x20143440`、`0x20143728`、`0x20143BD8`、`0x20143ED0` | 后端能处理字库中的 BMP 字形；这些上游调用仍受原厂转换表约束。 |
| 按 16 位字符预加载字形 | `0x2014503C` 转换 → `0x20145074` 调用 `0x20198024` | `0x20141920` 转换 → `0x20141958` 调用 `0x20193D58` | J140 `0x2019806C` 读半字，查字形并更新缓存位图；不提交一串文字，且唯一直接调用者仍用相同转换。 |
| 检查缓冲中字符是否已缓存 | `0x201450DC` 调 `0x201981C4` | `0x201419C0` 调 `0x20193EF8` | 按 Unicode 检查已有字形缓存，仅返回是／否，不提供新的显示或字体资源入口。 |

J140 字体实例选择函数 `0x201450F4` 的 8 个直接调用也都能回溯到转换路径。这解释了为什么换一份有中文轮廓的字体仍无法让原厂菜单显示完整简体。根据菜单记录 `+0x24` 的英语指针，J140 `0x2035B828` 和 J132 `0x2036F034` 的原文均是 `Display Language`；日语为 `表示言語`。两条原文已用于[PC 上的原厂字体回退对照](IC705_ZH_CN_PAGE.md)。

原始扫描结果在 `.analysis/zh-cn-preview/j{140,132}-arm-callers.json`。复查示例：

```powershell
py -3.14 -m tools.probe_arm_callers .analysis/main-decode/705J140/main.bin 0x20197A90 0x201971D4 0x20198024 0x201981C4
py -3.14 -m tools.probe_arm_callers .analysis/main-decode/705J132/main.bin 0x201937C4 0x20192F08 0x20193D58 0x20193EF8
```

## 字体指针的来源

两版进一步向上追到了初始化时写入的四个字：两个字体指针和两个长度。J140 将它们写到 `0x2038089C` 起始对象的 `+4/+8/+12/+16`，J132 对象起点为 `0x20380898`。它们来自固定 Flash 记录 `0x18C00000` 和 `0x18FA2588`：指针为记录地址加 4，长度为首个 32 位字。下面各函数间的直接引用在两版都能复核：

| 路径 | J140 | J132 |
| --- | --- | --- |
| 写入字体来源 | `0x20104984–0x201049A8` | `0x20101364–0x20101388` |
| 初始化字体实例，按标志选两组来源之一 | `0x20145244 → 0x20144F00` | `0x20141B28 → 0x201417E4` |
| 把指针和长度送给 FreeType | `0x20197410 → 0x20196E24 → 0x2025D1BC` | `0x20193144 → 0x20192B64 → 0x20258A1C` |

每版 `FT_New_Memory_Face` 实现均只命中一个 A32 调用点，上溯到上表的初始化；按地址扫描未发现另一个普通文件读取入口。原始引用列表在 `.analysis/zh-cn-preview/j{140,132}-font-init-rtty-xrefs.json`。证据涵盖已匹配的主程序直接引用和对齐字，不排除计算地址、其他资源模块或其他区段的间接调用。**现有菜单和字库调用链都只通向内置数据，未证实有受支持的第三语言资源接口。** PC 样页通过不能推导出在 SD 卡上放一个 TTF 就能加载，也不能证明可以重编整机。后续优先验证 [RTTY 正文与接收音频](MAIN_CPU_DECODE.md#rtty-正文的静态入口)，同时保留汉化这项接入门槛。系统语言、名称存储和真机保持原样。

[J140 动态复现](IC705_EMULATION.md#日版-140原厂菜单行像素)已用原厂内置 FreeType 和日文字库从「表示言語」取得「表」的字形 3136 和原厂 OpenVG 轮廓，再输出像素。「系统语言」和「显示语言」的标签、当前值及可见性也在四组模拟 RAM 状态下分别复现。这给后续汉化提供日版原厂对照，不代表已经接入新的语言。

[双版开机图片与字体加载对照](IC705_SD_RESOURCES.md)进一步验证：图片请求进入文件任务并走 BMP 校验；这十条字体初始化指令从两处固定 Flash 读取长度，结果不经过文件任务。没有发现把开机图片导入用于安装菜单文案或字体的接口。
