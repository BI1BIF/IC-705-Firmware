# 日版 IC-705 1.40：「显示设置」第一页简体预览

续测已覆盖[亮度编辑器和三个选项页](IC705_ZH_ARM.md)，现有重放命令会执行扩展后的 62 帧。本页的 56 帧与未汉化子页描述为上一轮实验的历史结果。

2026-11-13，Windows x64。双击 [Open-IC705-Chinese-Preview.cmd](../Open-IC705-Chinese-Preview.cmd)，按 `MENU → SET → セット 2/4 → ディスプレイ設定`。进入后，第一页 `1/6` 的标题、四条设置和适用的右侧值使用简体。原厂对照用 [Open-IC705-Panel.cmd](../Open-IC705-Panel.cmd) 打开。

输入是[日本 Icom 1.40 官方更新](https://www.icom.co.jp/support/drivers/8603/)中的 `705J140.dat`（SHA-256 `2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45`）。四条设置的含义对照 [Icom 基础手册第 8 章 Display](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)。模拟器没有恢复真实设备的出厂设置；起始的 `0% / OFF` 是受控内存状态。

| 项目 | 中文显示与验证 |
| --- | --- |
| 标题和页码 | `显示设置`，原厂页码 `1/6` 保留；标题宽度由原厂代码重新计算。 |
| LCD 背光 | `LCD 背光`、`LCD 背光（自动调节中）`；原厂代码生成 `0%`、`9%`、`50%`、`100%` 及对应亮度条。 |
| 屏幕保护 | 电池和外部供电两行分别显示当前选项；`OFF` 显示为「关闭」，原厂 `1/2/5/15/30/60分` 保留数字并显示「分钟」。 |
| 屏幕熄灭 | 保留实体按键标识 `[POWER]`，`OFF/ON` 显示为「关闭／开启」。 |
| 显示语言和系统语言 | 用原厂触摸流程从日语切换到英语，再回到日语。英语第一页及日语系统语言选择页与对照逐像素一致；回到日语再翻到第一页时重新显示简体。模拟 RAM 中只有原厂切换操作写 `0x203EAE44`（`01 → 00 → 01`），`0x203EAE45` 始终为 `01`，没有写入。 |

两种屏幕保护和 `[POWER]` 设置可通过原厂选项子页操作。实际点击选了电池 5 分钟、外部供电 60 分钟和开启；用于补测的 1/2、15/30 分钟及亮度上下限由脚本向已验证的模拟 RAM 字节输入，再由原厂列表构建和渲染。自动调节例显示 0% 是因为模拟器没有输入环境光读数。点亮度行会进入尚未建模的原厂亮度编辑器；本轮只验证列表呈现。选项子页仍为原厂日语，第六页只保留先前的「显示语言」单行实验。

## 证据

- 原厂 `0x200ACBDC` 构建列表值；`0x200ACD34` 读取两种保护时间和电源键偏好 `0x203EAE37–39`；亮度读取函数 `0x20061C64` 读取亮度 `0x203EAE26` 与自动调节开关 `0x203EAE27`。[REA](REA_ANALYSIS.md#j140-显示设置第一页简体实验)复核同一主程序的相关区段，GNU objdump 与 Unicorn 的指令和读写记录共同用于确定含义。
- 宿主只在日语界面第一页匹配原厂 UTF-16 文本。原厂先选择字库；测宽与绘制再使用独立 FreeType 实例及翻译后的字符数。ASCII 值原本用缓存字库槽，翻译时改走原厂临时槽，完成即恢复槽位与文字缓冲。保留阳性对照「表」的原厂字形 3136。开放子集由原厂 FreeType 实际加载和绘制，12,852 字节，51 个字符映射，60 个字形；SHA-256 `3fab4325c600893616349c329439b1d1b3dc2245062d41af7d4cc38f1059718d`。
- 56 帧使用相同输入，菜单状态、选中行与偏好写入相同。9 帧只在第一页的标题、行名和选项值区域有像素差异，页码、亮度条、亮度百分比和导航区域不变；6 帧差异来自原有的「显示语言」实验，其余 41 帧完全相同。两次中文重放的 PNG 与 JSON 逐字节一致。Windows Tk 重放至第一个受控 RAM 注入点，42 帧逐像素一致；项目 36 个测试通过。

## 复跑

从项目根目录运行。若源字体不在本地，按[固定版本和许可证说明](IC705_ZH_CN_PAGE.md#来源和复跑)取得 `NotoSansSC-VF.ttf` 和 `upstream-OFL.txt`。使用已有 Python 3.14、Unicorn 2.1.4、fontTools 4.63.0、Pillow 12.1.1。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
$src = '.analysis/zh-cn-preview/noto'
$out = '.analysis/zh-cn-preview/display-page'
$font = "$out/IC705LabSC-Regular.ttf"
New-Item -ItemType Directory -Force $out | Out-Null
py -3.14 -X utf8 -c "from pathlib import Path; from tools.probe_zh_cn_page import build_font; from tools.zh_705_row import PAGE_CHARS; import sys; build_font(Path(sys.argv[1]), Path(sys.argv[2]), PAGE_CHARS)" "$src/NotoSansSC-VF.ttf" $font
Copy-Item "$src/upstream-OFL.txt" "$out/OFL.txt"
$stock = '.analysis/ic705-emulator/j140-stock-display-check'
$zh = '.analysis/ic705-emulator/j140-zh-display-page'
py -3.14 -X utf8 -m tools.virtual_705_panel firmware/705J140.dat --display-check --panel-replay $stock
py -3.14 -X utf8 -m tools.virtual_705_panel firmware/705J140.dat --display-check --panel-replay $zh --zh-font $font
py -3.14 -X utf8 -m tools.compare_705_display_preview $stock $zh
```

主要产物：`02-display-page1.png`（进入页）、`50-percent.png`（两种参数和开关值）、`auto-backlight.png`、`english-display-page1.png` 及 `trace.json`。所有生成文件留在 Git 忽略的 `.analysis/`。没有操作真实电台，也没有修改 DAT。下一项验证可使用同样的规则覆盖原厂选项子页，再决定能否把词表接到固件自己的资源入口。当前只验证了 PC 内存中的渲染路径，原生第三语言和设置持久化尚未验证。
