# 日版 1.40：原厂面板单行简体验证

2026-11-13，Windows x64。双击 [Open-IC705-Chinese-Preview.cmd](../Open-IC705-Chinese-Preview.cmd)，由主屏按 `MENU → SET`，在 `セット 2/4` 选「ディスプレイ設定」，翻到 `6/6`。原厂第一行显示「显示语言」，点击后选择页标题也显示「显示语言」。第二行仍为「システム言語」。选「英語」后恢复原厂全英文标签，选 `Japanese` 回到单行简体预览。用 [Open-IC705-Panel.cmd](../Open-IC705-Panel.cmd) 打开不带实验钩子的日英原版。

这项验证只在日语界面的指定标签注入中文。语言列表仍只有日语、英语，未写入第三种语言值。使用原厂主程序、图形资源、菜单逻辑与 FreeType；PC 提供模拟输入和软件 OpenVG。没有把中文叠加到成品截图上。

| 证据 | 实测 |
| --- | --- |
| 文字转换 | 原厂日语条目 `0x202F0DFC` 对应 `95 5C 8E A6 8C BE 8C EA`。原厂先把它转成 `8868 793A 8A00 8A9E`；原厂转换表无法产出 `663E`（显）或 `8BED`（语）。只在这条标签的日语测宽和绘制路径，宿主将输出缓冲 `0x204CC1D4` 换成 `663E 793A 8BED 8A00`。 |
| 真实字库 | 使用已验证的 [Noto Sans SC 静态子集](IC705_ZH_CN_PAGE.md#来源和复跑)，在原厂 `0x20197410` 中建立独立的内存字体实例。调用原厂字符查找 `0x2025B668`，原厂字库对「显／示／语／言／表」返回 `0/1893/0/1541/3136`；新增字库返回 `37/43/57/53/51`。`表` 是阳性对照，没有改原厂字库。 |
| 作用域 | 只在菜单 `67`/`286`、语言字节 `01/01`、原厂转换结果完整匹配四字时触发。测宽和绘制各使用新增实例，完成即恢复原厂槽位和缓冲。原厂 `0x20197A90` 查到四个索引并提交四条非空字形轮廓；点击和页面跳转仍经原厂流程。 |
| 像素差分 | 25 帧中只有 5 帧有差异，均来自同一行或标题。列表差异边界 `[11,33,83,50)`，选择页标题 `[213,5,268,19)`，坐标原点在左上。原厂英文列表、英文选择页及日文系统语言选择页与对照逐像素一致。 |
| 状态和复跑 | 25 帧的事件、页面状态、返回高亮和写入均与原厂对照相同。原厂切换仅写显示语言 `0x203EAE44`，系统语言 `0x203EAE45` 始终是 `01`。两次简体重放的 25 张 PNG 和 JSON 逐字节一致；Windows Tk 点击重放也逐像素一致。36 个项目测试通过。 |

REA MCP 单独复核了原厂主程序中的[文字、字体和绘制入口](REA_ANALYSIS.md#j140-单行简体实验)；执行和像素证据来自 Unicorn 和 Windows Tk。所有实验输出放在 Git 忽略的 `.analysis/`，没有改动原厂 DAT、未操作电台。

## 复现

从仓库根目录使用已安装的 Unicorn；字体缺失时按[子集复现步骤](IC705_ZH_CN_PAGE.md#来源和复跑)生成。实验脚本只接受已验证的 J140 DAT 与子集 SHA-256。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
$font = '.analysis/zh-cn-preview/noto-page/IC705LabSC-Regular.ttf'
py -3.14 -X utf8 -m tools.virtual_705_panel firmware/705J140.dat --panel-replay .analysis/ic705-emulator/j140-stock-zh-control
py -3.14 -X utf8 -m tools.virtual_705_panel firmware/705J140.dat --panel-replay .analysis/ic705-emulator/j140-zh-native --zh-font $font
```

看 `07-display-page6.png`、`11-display-language.png`、`12-switch-to-english.png`、`14-switch-back-to-japanese.png` 与 `trace.json`。去掉 `--panel-replay` 及其目录参数，便可用鼠标操作实验面板。

续测已完成[显示设置第一页](IC705_ZH_DISPLAY_PAGE.md)。本页保留单行实验的历史证据；现在简体启动器默认使用支持第一页的新子集，上方命令仍可用原子集复现单行版本。
