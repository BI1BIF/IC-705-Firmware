# 日版 IC-705「显示语言」：开放字体与原厂回退

2026-11-13。以 J140 为主，用 J132 重跑。**这是字库和排版样页，与原厂 705 页面布局和交互无关。** 480×272 是参考尺寸；固件中识别的原文、字库及字符转换见[显示语言到字库](IC705_LANGUAGE_FONT.md)。运行原厂代码、生成原厂画面的研究见[PC 仿真报告](IC705_EMULATION.md)。未连接电台或更改原厂程序、字库和语言设置。

| 核对项 | 可复现结果 |
| --- | --- |
| 简体子集 | Noto Sans SC 2.004，固定 `wght=400`；62 个请求字符（页面 59 个，加 3 个额外对照字），70 个字形。15,384 字节，SHA-256 `5995e4107666666dbbb388930fe694b580d42e372200736ec3f8afb935867426`。 |
| 与原厂格式对照 | 同为静态 TrueType `glyf/loca`，Unicode `cmap` 的 0/3 和 3/1 记录均为 format 4；校验和、表界限与字形索引通过项目探针。PC FreeType 2.14.1 能从指定文件实际栅格化，不经系统字体替换。电台内 FreeType 的版本和加载条件仍需验证。 |
| 原厂阳性和缺字对照 | 大字库的「表」仍是字形 3136，24 px 有可见笔画；同一原厂字库的「频、设、蓝、简」映射为 0。简体子集对这 5 个字都产生非空位图。 |
| 正常样页 | 59 个字符全部有字形，9 个文本框无越界。最长一行 270 / 444 px；`状态预览：145.500 MHz · CW` 为 206 / 444 px。 |
| 缺字整行回退 | 在标题附加 U+0378。日语样张以原厂大字体绘制「表示言語」（96 / 290 px），英语样张以原厂小字体绘制 `Display Language`（192 / 290 px）。像素比较只有标题区改变；其他行仍是简体样页。字体选择是此实验的配置；机内实际字体按样式选择。 |
| 跨版重跑 | J132 原厂字库跑出的 3 张 PNG 和简体 TTF 与 J140 逐字节一致。REA MCP 复核了子集字节数及 SHA-256，证据 `ev_5d5d6726d5e6d436fbda0e9e7051b441ed46ab375c7c0dd16edded47d9ad02f6`。 |

缺字回退是这里实现的桌面规则。它没有改动电台的「系统语言」，也不会证明原厂菜单有相同回退行为。原厂前端的字符转换、显示语言第三选项、可支持的资源装载是三个独立条件。15,384 字节仅是本页字体文件大小，不能用于推定整机字库大小、运行内存或 Flash 可用空间。

## 来源和复跑

[上游 TrueType](https://github.com/notofonts/noto-cjk/blob/Sans2.004/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf)与[许可证 SIL OFL 1.1](https://github.com/notofonts/noto-cjk/blob/Sans2.004/LICENSE)固定到 `523d033d6cb47f4a80c58a35753646f5c3608a78`。源字体 17,773,132 字节，Git blob `5371a543be5fc670c7cdee9760c03554ee3e9b8e`，SHA-256 `d68bafcb48a2707749396aa12bbbd833cb70401f3a9a689fd2902c7e0d295964`。衍生字体改名为 `IC705 Lab SC`，保留版权和许可元数据；副本的 `OFL.txt` 放在生成目录中。原厂字体和实验产物只放在 Git 忽略的 `.analysis/`。

从项目根目录运行，复用本机 Python 3.14、fontTools 4.63.0、Pillow 12.1.1；基础分析工具仍只需标准库。以下用 GitHub 官方 Contents API 下载固定版本，输出目录用尚未存在的新路径。

```powershell
$ref = '523d033d6cb47f4a80c58a35753646f5c3608a78'
$api = 'https://api.github.com/repos/notofonts/noto-cjk/contents'
$src = '.analysis/zh-cn-preview/noto'
$out = '.analysis/zh-cn-preview/noto-page-repro'
New-Item -ItemType Directory -Force $src | Out-Null
curl.exe -fSL -H 'Accept: application/vnd.github.raw+json' "$api/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf?ref=$ref" -o "$src/NotoSansSC-VF.ttf"
curl.exe -fSL -H 'Accept: application/vnd.github.raw+json' "$api/LICENSE?ref=$ref" -o "$src/upstream-OFL.txt"
Get-FileHash "$src/NotoSansSC-VF.ttf","$src/upstream-OFL.txt"
py -3.14 -X utf8 -m tools.probe_zh_cn_page "$src/NotoSansSC-VF.ttf" .analysis/language-font-705J140/font-0.ttf .analysis/language-font-705J140/font-1.ttf $out
Copy-Item "$src/upstream-OFL.txt" "$out/OFL.txt"
```

先按[原厂字体报告](IC705_LANGUAGE_FONT.md)提取两份字库。替换路径中的 `705J140` 和输出目录即可用 J132 对照。现有成果在 `.analysis/zh-cn-preview/noto-page/`：`language-preview.png`、`fallback-ja.png`、`fallback-en.png`、`metrics.json` 和静态子集。用 `metrics.json` 可逐框复查字库选择、缺字、像素边界与 advance。
