# CS-705 菜单与帮助主题：日版固件的外部对照

2026-11-13。从 Icom 日本站取得 [CS-705 1.21](https://www.icom.co.jp/support/drivers/7075/)（2022-12-22，对应固件 1.32）和 [CS-705 1.30](https://www.icom.co.jp/support/drivers/8597/)（2025-08-21，对应固件 1.40）。[日版固件 1.40 公告](https://www.icom.co.jp/support/drivers/8603/)列出了两项设置的选项变化。用这两个 PC 发行包做语义对照，具体下载 URL、ZIP 和成员大小、CRC32、SHA-256 见 [来源清单](../research/cs-705-provenance.json)。Icom ZIP、程序及帮助只留在本地。

## 验证到的设置

从两个 ZIP 的 `ISc(` 型 InstallShield CAB 分别提取 `CS705.exe`、日文和英文 CHM 帮助。REA `inspect_pe_resources` 识别出两个 `CS705.exe` 都是 x86 PE32（machine `0x014C`）；各完整枚举 57 个 PE 资源。目标标签均在普通 `.data` 节，未落入 REA 列出的 PE 资源负载。脚本按 PE 节表读原始文件范围，定位同一条记录中的标签与菜单键，再核对键到 CHM 主题文件的映射。每个键在两版都能对应两处 CP932 日文标签、一处英文标签和一个主题编号。

| 设置 | CS-705 键 / 主题 | 1.21 → 1.30 的帮助差异 |
| --- | --- | --- |
| デジタルレピータセット / Digital Repeater Set | `CL_Common_Digital_RPT_Set` / `55938.htm` | 增加 `ON(GW)`；该选项将 R2 设为网关呼号。 |
| レピータモニタータイマー / Repeater Monitor Timer (Japan) | `CL_Common_RepeaterMonitorTimer` / `65708.htm` | 原有 10、20、30 分钟；新增 60 分钟。日文帮助注明仅日版设备显示。 |
| 表示言語 / Display Language | `CL_Common_DispLang` / `54960.htm` | 日、英各自的主题文件在两个版本逐字节一致，用作稳定对照。 |

主题比对只读取 HTML 文本：日文按 CP932、英文按 CP1252 严格解码，去掉 HTML 标记后比较。两种语言对变更项的解释一致，主题 SHA-256 已写入清单。标签和主题编号原本就存在，真正可跟踪的变化是**新增选项**。例如 1.30 英文标签的 PE 文件偏移为 `0x3B6DE4`、`0x3B80A7`、`0x3BEA9F`，各自的主题映射在 `0x3DB61A`、`0x3DD275`、`0x3DB67C`。它们是 Windows 程序的偏移。

将三组日英标签（UTF-8、UTF-16LE/BE、CP932）和三个 ASCII 键在 `705J132.dat`、`705J140.dat` 上逐字节搜索，均无命中。后续用 x86 指令和官方 ICF 确认了 [四个 PC 设置字段](CS705_SETTINGS_MAP.md)，包括两个新增选项的数值。原始 DAT 没有命中对应的明文表示；日版电台内的资源编码、字库和 LCD 绘制路径仍未确认。

## 工具和复现

REA MCP 6.8.0 `open_binary` + `inspect_artifact` 验证两个官方 ZIP，归档会话已关闭；`inspect_pe_resources` 对提取的 PE 做静态复核，无须加载程序。ZIP 的成员和 PE 的资源清单保存在 `.analysis/rea-zip-cs-705-v{1.21,1.30}.json` 及 `.analysis/cs-705/{1.21,1.30}/rea-pe-resources.json`。

| CS-705 | ZIP Evidence | PE 资源 Evidence |
| --- | --- | --- |
| 1.21 | `ev_398eacc0a04f14230c72c43b3cefecaa1ff4aeb5186dcd5c3f51505e7bf36156` | `ev_3223d5476ad1c0d33b9d49286705c324c8a596b6678f1524e4ef4634f1ef320d` |
| 1.30 | `ev_776a6aa2ff434ea08c2a7ed0084db4a992c69bbd92ac65615b572e02f1a622ac` | `ev_33b9c539f6a87441050a2e7e5567686cddedb33d5fd7d137d795325e8e2e552e` |

现有 Debian WSL2 未安装 Unshield、7-Zip。使用 `apt-get download` 下载 Debian trixie amd64 包，与本机 APT 索引中的 SHA-256 核对后用 `dpkg-deb -x` 解到被忽略的 `.analysis/`；未安装系统包，也未改 REA 或 WSL 配置。实际只从 ZIP 读取 `data1.cab`、`data1.hdr`、`data2.cab`，Unshield 各列出 22 个成员，按名单提取上述三个文件。没有运行 Icom 安装器、程序或 HTML 帮助查看器。

| Debian 包 | 版本 | SHA-256 |
| --- | --- | --- |
| [unshield](https://packages.debian.org/trixie/unshield) | `1.5.1-1+b2` | `1924071101e8f3aa7e2588c3f585436573138c7f65355c4e25f29c47b6c73231` |
| [libunshield0](https://packages.debian.org/trixie/libunshield0) | `1.5.1-1+b2` | `97b411fb339223d108a87b11f49a424cc960a710eab25e5be00add63bbf7d8b4` |
| [7zip](https://packages.debian.org/trixie/7zip) | `25.01+dfsg-1~deb13u2` | `b2cb210bee3be6a10230b38b8645d71846d19364b157f44fd08e1a54cae1652f` |

在已具备 `unshield`、`7z` 的 Linux/WSL 中可从项目根目录复现；示例将 ZIP 展开到本地证据目录，再按名单提取 CAB 内容：

```sh
for ver in 1.21 1.30; do
    digits=$(printf '%s' "$ver" | tr -d '.')
    dst=".analysis/cs-705/$ver"
    python3 -m zipfile -e "firmware/comparators/CS-705-v$ver.zip" "$dst/zip"
    cab="$dst/zip/Cs705_ver$digits/data1.cab"
    unshield l "$cab"
    unshield -d "$dst/extracted" -g DefaultComponent x "$cab" CS705.exe CS705_JPN.chm CS705_ENG.chm
    for lang in JPN ENG; do
        mkdir -p "$dst/topics/$lang"
        for topic in 55938.htm 65708.htm 54960.htm; do
            7z x -so "$dst/extracted/DefaultComponent/CS705_$lang.chm" "$topic" > "$dst/topics/$lang/$topic"
        done
    done
done
```

在 PowerShell 执行探针，JSON 只记录偏移、帮助主题、哈希和 DAT 精确匹配情况：

```powershell
.\.venv\Scripts\python.exe -m tools.probe_cs705_menu `
    .analysis/cs-705/1.21/extracted/DefaultComponent/CS705.exe `
    .analysis/cs-705/1.30/extracted/DefaultComponent/CS705.exe `
    --firmware firmware/705J132.dat --firmware firmware/705J140.dat |
    Set-Content -Encoding UTF8 .analysis/cs-705/menu-reference.json
```
