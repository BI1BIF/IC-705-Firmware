# IC-705 官方固件结构及 REA 分析

记录日期：2026-11-12 至 2026-11-13（中国标准时间）。本报告保留 Icom Global E 系列的首轮结果和 REA 环境说明。用户确认电台为日版，后续以 [705J 日版报告](JAPAN_FIRMWARE.md)为主；E 系列用作文件级只读对照。**最新进展：[日版主程序已解包并反汇编](MAIN_CPU_DECODE.md)，以启动和 GPS 跨版行为验证了装载与函数映射。**

## 来源和校验

Icom Global [产品页](https://www.icomjapan.com/lineup/products/IC-705/)及[历史列表](https://www.icomjapan.com/support/firmware_driver/?business=3&class=&frm_type=Firmware&old=true&open=tab2&product=%7CIC-705+EUR%7CIC-705%7C&type=5)在核查日列出的最新 IC-705 固件为 **1.40，2025-08-21**。历史列表还列出 1.32、1.31、1.30、1.27、1.26、1.24、1.20 等。日本站同日发布的 [1.40](https://www.icom.co.jp/support/drivers/8603/)使用 `705J140.dat`；本轮比较没有混入 J 系列。

| 发布页 | 文件 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| [1.40 · 2025-08-21](https://www.icomjapan.com/support/firmware_driver/4422/) | 705E140.zip | 8,569,218 | `ee4336193485790f8addcb15af79cb92aec701bb70d3734b176af446dde958d7` |
| 同上 | 705E140.dat | 12,279,020 | `132383f8388641d02d0fadaccf9878d01a1960fa77a028328f0eb33dcfbc147b` |
| [1.32 · 2022-12-22](https://www.icomjapan.com/support/firmware_driver/3707/) | 705E132.zip | 8,552,707 | `be32ba183bbf12f6865a33f27d99d597bf69e51e36e7a5eb0c9473aa54e7d8e0` |
| 同上 | 705E132.dat | 12,279,020 | `1b8e5c9e3ec75fafcfa214937bb05dd444716ce73a648cc779827301a0890b26` |
| [1.26 · 2021-07-09](https://www.icomjapan.com/support/firmware_driver/3343/) | 705E126.zip | 8,565,489 | `a86575118bbba927dd39dfe62e841297b12960ececd0a2b4fa0cfaa8e3869f8e` |
| 同上 | 705E126.dat | 12,319,811 | `f9c60ec1617daa9070864441e4e8147b7851ab5f87cc2029007c924d6e372304` |

实际 HTTP 200 下载 URL，取自对应 Icom 官方下载按钮：

- [705E140.zip](https://www.icomjapan.com/api/download.php?post_id=4422&fl=JTJGdXBsb2FkcyUyRnN1cHBvcnQlMkZmaXJtd2FyZV9kcml2ZXIlMkY3MDVFMTQwLnppcA==)
- [705E132.zip](https://www.icomjapan.com/api/download.php?post_id=3707&fl=JTJGdXBsb2FkcyUyRnN1cHBvcnQlMkZmaXJtd2FyZV9kcml2ZXIlMkY3MDVFMTMyLnppcA==)
- [705E126.zip](https://www.icomjapan.com/api/download.php?post_id=3343&fl=JTJGdXBsb2FkcyUyRnN1cHBvcnQlMkZmaXJtd2FyZV9kcml2ZXIlMkY3MDVFMTI2LnppcA==)

Python `zipfile` 读取指定成员并核对 ZIP CRC-32：140=`fa4739a4`，132=`0aa9219a`，126=`34010591`。REA 的 1.40 ZIP 清单独立给出相同 DAT SHA-256，并标明 ZIP 成员未设置加密位。SHA-256 是本次计算的文件标识；官方页面未列出用于独立校验的哈希。

## REA 环境与实际调用

主机为 Windows x64，内核版本 `10.0.26200`。REA 未在 PowerShell 的 PATH；通过现有 Codex 注册所用的 Node 24.22.1 和脚本复用：

```powershell
$reaNode = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$reaCli = Join-Path $env:USERPROFILE '.codex/tools/rea/node_modules/rea-agents/scripts/rea.mjs'
& $reaNode $reaCli --help
& $reaNode $reaCli doctor --json
& $reaNode $reaCli doctor --client codex --json
& $reaNode $reaCli providers --json
```

REA `rea-agents 6.8.0`，技能版本 49。Codex `mcp list` 报告 `rea` 启用，`binary_session` 从当前会话证实服务版本一致、连接状态 `aligned`。Codex 范围的 doctor 健康；全量审计因缺失原生引擎和其他客户端注册而不健康。未运行 setup，未修改全局配置。现场目录 [229 项工具及当前可用性](../research/rea-tool-inventory.tsv) 有 110 项标为可用；“可用”仍不保证存在特定格式的可执行组件。

| 能力 | 本机实测 |
| --- | --- |
| `open_binary` → `inspect_artifact` → `close_binary` | 成功识别并清点 1.40 ZIP；`rea-artifact-graph` v1 识别出一个普通 DAT 成员，架构为空。会话已关闭。 |
| `inspect_byte_entropy` | 成功。DAT 文件熵 7.9969 bit/byte；64 KiB 窗共 188 块。 |
| `inspect_firmware_regions` | 调用返回 `capability_unavailable`，要求 Linux 和绝对路径 `REA_BINWALK_COMMAND`。 |
| `extract_firmware` | 会话目录显示 `unsupported_host`；Windows 不执行。按已验证边界在本地切出四组，见下表。 |
| `open_binary` / `analyze_function`（原生） | 接口存在。Windows Provider 的 ARM Raw 支持实测受限。固件函数本轮由已解包的窄范围 GNU 反汇编确认，未将整份 DAT 当作程序导入。 |
| Ghidra / Hopper / IDA / Kuna | Ghidra 未配置，未发现安装或可用 Java；Hopper 不支持当前 Windows 主机；IDA MCP 未配置且未找到安装；Kuna 未配置。REA 内置归档、熵等能力可用。 |
| GNU objdump | Windows Arm GNU Toolchain 14.2.Rel1（objdump 2.43.1.20241119）可直接读取解包后的 ARM 裸程序。REA CLI 单次指定同一 objdump，先通过自制 ELF 对照，再复核 J140 的复位段分析 ELF。MCP 默认启动 `objdump` 失败；无需为此改 Codex 配置。 |
| 其余本机工具 | 复用 Python 3.12.13；Windows 常见目录和 PATH 未发现 Binwalk、Unblob。 |

本机已有 Debian 13.5 x86-64 WSL2，内核 `6.18.33.2-microsoft-standard-WSL2`，有 `ps`、`prlimit` 和现成的 Docker。Windows 的 Node 启动在 Win32，从 WSL 调用它仍无法使用 Linux Provider。后续已用 Linux Node、Binwalk 和 Unblob 实际跑通两个固件接口，见[复测记录](#wsl2-固件工具实测)。Windows 的 Codex MCP 继续使用现有注册。

[REA Raw Binary](https://github.com/morluto/rea/blob/main/docs/providers/raw-binary.md)与本机 MCP schema 要求给出格式、架构和地址；ARM 路径以 A32 起始。用合成裸 ARM 样本实测，REA 6.8.0 在 Windows 返回 `target_format_unsupported`，报其 Windows Ghidra 路径只接受原生 PE 和明确指定的 raw 6502。独立 Ghidra Raw Binary 可分别指定装载位置与指令状态（如 Thumb），不受该 REA 路径的限制，尚未实跑。本机 REA 诊断要求 Ghidra 12.1.x，见 [REA 安装文档](https://github.com/morluto/rea/blob/main/docs/getting-started/installation.md)。实际主程序的地址和反汇编结果见[主程序报告](MAIN_CPU_DECODE.md)。

## WSL2 固件工具实测

2026-11-13，在现有 Debian WSL2 中用 Linux Node `24.22.1` 运行原安装的 REA `6.8.0` CLI。按 [REA 固件文档](https://github.com/morluto/rea/blob/main/docs/guides/firmware/firmware-analysis.md) 使用 Binwalk `3.1.0`（区段扫描）和 Unblob `26.6.4`（提取）。复用 Windows 安装的 REA JavaScript 包和现有 Docker，只增加项目内解包的 Linux 工具及本地容器镜像；未运行 REA setup、改 Codex MCP 注册或在 Debian 安装系统包。容器离线运行、只读挂入样本。Unblob 将工作区与输出放到 WSL 的 Linux 文件系统；直接写 Windows 挂载盘的对照曾在整理输出权限时失败（`chmod` 返回 `EPERM`），换到 Linux 路径后通过。

| 输入 | REA → Binwalk | REA → Unblob |
| --- | --- | --- |
| 自制 gzip，101 字节 | 偏移 0 正确识别 gzip，长度 101 字节。 | 完整提取 1 个文件、6,400 字节；逐字节相同，SHA-256 `5e1d6bebfa20e463950716abeb9dc5751debcadf3f847bafa923b7406df7db16`。 |
| 日版 `705J140.dat` | 7 个候选（1 个 S-record、6 个 zlib），复核均未通过。 | 0 文件、0 已识别区段；整个输入列为未分类。 |
| 日版 `705J132.dat` | 8 个候选（1 个 S-record、7 个 zlib），复核均未通过。 | 同上。 |
| `705J140.dat` 的 A 组切片 | 5 个候选，均对应整包的同一字节位置（切片偏移加 `0x64`）；无新增候选。 | 0 文件、0 已识别区段。 |

两版的 S-record 候选分别在 `0x16503` 和 `0x2F7F0`；虽然开头有 `S0`，后面的长度字段包含非十六进制字符，首条记录即不成立。Binwalk 的[通用 S-record 签名](https://github.com/ReFirmLabs/binwalk/blob/v3.1.0/src/signatures/srec.rs)本身从短标记 `S0` 起搜。对每个 zlib 候选，从原 DAT 偏移送入标准库 `zlib.decompressobj()`（最多 64 KiB 输入、4 MiB 输出），两版共 13 次均报无效回溯距离或数据校验错误，未得到一个完整的 [RFC 1950](https://www.rfc-editor.org/rfc/rfc1950.html) 流。这些结果只排除了本轮候选作为标准独立组件，无法确定 DAT 内部的编码、压缩或加密状态。已按 MD5 边界提取的 A/C/D 是原始载荷，与通用提取器识别并解码的组件是两回事。

**工具路线。** Windows REA MCP 继续处理 ZIP 和字节证据，通用固件扫描和提取可用现有 WSL2 CLI。Windows 的 Arm GNU objdump 在自制裸样本及日版解包主程序上均能反汇编。同一合成样本在 Linux REA 中报告 Ghidra 未配置，未报 Windows 的目标格式限制（`.analysis/rea-wsl/evidence/rea-linux-arm-smoke.json`）；没有运行 Ghidra。需要图形化分析时，可在现有 WSL2 中配置 Ghidra 与 Java，或用 Windows 上[独立 Ghidra 的 Raw Binary 加载器](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/Base/src/main/java/ghidra/app/util/opinion/BinaryLoader.java)指定已验证映射。

### IC-7300MK2 两版原厂包的提取边界

2026-11-16，在现有 Debian WSL2 上用 REA `extract_firmware` 和 Unblob 26.6.4 分别读取 `7300MK2_102.dat`、`7300MK2_103.dat` 全包；镜像离线、原件只读。两次正常结束，REA 校验所读输入哈希和原件相符，且均报告 **0 个提取文件、0 个识别区段**；1.02 的 8,114,450 字节及 1.03 的 8,115,837 字节全部归为 `unclassified-range`。原始 Unblob 文本的 `Extracted files: 1` 对应报告中的输入自身（一级 `StatReport`，没有子任务），不是解出来的程序；以 REA 输出清单、已发布字节（0）和区段为准。此前 REA/Binwalk 在 1.03 整包提示的六处短签名也已在[包结构记录](IC705_CW_MK2_PICTURE.md#cw已取得两版-mk2-原厂固件)逐项排查，均未成为可验证组件。

这是现有通用提取器未认出 MK2 `DU3` 内部格式，已经在 Linux 运行成功，无需另装 Linux 或改 Windows 的 Codex 注册。不能以这个结果判定 MK2 已加密。待有验证过的解包器、原厂加载器或可读只读镜像，再按确认的架构和装载信息分析主控；DSP 的架构和工具支持另行核对。证据 `.analysis/mk2-rea-extract-1116/rea-unblob-102.json`（`ev_10a8cd0ac67b9180bf290eda4d86f3169ef4a74964e43bff2d20fa57ea177fc7`）、`rea-unblob-103.json`（`ev_cd1bf6cea40c1065fe5f6ade52f44b40d87c918fc769be2b1c576d021617e9fc`）和同目录 `rea-extract.sh`。

### 本机复跑

从项目根目录进入现有 Debian WSL2，以下用到本轮留下的本地工具与镜像。Linux 临时目录使用新路径；结果写入该目录，原始文件不修改。按表把 `input` 替换为其他 DAT 或 A 组切片即可重跑。

```bash
# 从 PowerShell 运行 wsl.exe -d Debian -u root，再在该 shell 执行。
base="$PWD/.analysis/rea-wsl"
modules=/mnt/c/Users/Administrator/.codex/tools/rea/node_modules
node="$base/node/node-v24.22.1-linux-x64/bin/node"
input="$PWD/firmware/705J140.dat"
scratch=$(mktemp -d /tmp/ic705-rea-repro-XXXXXX)
mkdir "$scratch/scan" "$scratch/out"
chmod 0755 "$scratch"
chown 65534:65534 "$scratch/scan"
chown 1000:1000 "$scratch/out"
cp "$input" "$scratch/input.dat"
chmod 0644 "$scratch/input.dat"

env HOME="$scratch/scan" TMPDIR="$scratch/scan" \
  LD_LIBRARY_PATH="$base/binwalk/root/usr/lib/x86_64-linux-gnu" \
  REA_BINWALK_COMMAND="$base/binwalk/root/usr/bin/binwalk3" \
  setpriv --reuid=65534 --regid=65534 --clear-groups --no-new-privs \
  "$node" "$modules/rea-agents/scripts/rea.mjs" \
  inspect-firmware-regions "$scratch/input.dat" --analysis-timeout-ms 30000 --json \
  > "$scratch/scan.json"

docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --memory 2g --pids-limit 100 --read-only --tmpfs /tmp:rw,nosuid,nodev,size=512m --workdir /tmp \
  -e HOME=/tmp -e TMPDIR=/tmp -e REA_UNBLOB_COMMAND=/usr/local/bin/unblob \
  --mount "type=bind,source=$node,target=/opt/rea-node,readonly" \
  --mount "type=bind,source=$modules,target=/opt/node_modules,readonly" \
  --mount "type=bind,source=$scratch/input.dat,target=/data/input/firmware.dat,readonly" \
  --mount "type=bind,source=$scratch/out,target=/data/output" \
  --entrypoint /opt/rea-node ic705-research-unblob:26.6.4 /opt/node_modules/rea-agents/scripts/rea.mjs \
  extract-firmware /data/input/firmware.dat /data/output/result \
  --max-depth 3 --analysis-timeout-ms 35000 --json > "$scratch/extract.json"
printf '%s\n' "$scratch"
```

工具来源：[Node 发布归档](https://nodejs.org/dist/v24.22.1/SHASUMS256.txt)内 Linux x64 压缩包 SHA-256 为 `6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6`；[Kali binwalk3](https://pkg.kali.org/pkg/binwalk3) `3.1.0-0kali5` amd64 从已验签索引核对，deb SHA-256 为 `756cff6d73f56b5c0500fe763b816d26c0f0513a5c37438225b1571389f0e88d`，所需共享库从 Debian 索引核对后解包到同一工具目录。Unblob 镜像以 [ONEKEY 发布的镜像](https://github.com/onekey-sec/unblob/pkgs/container/unblob) amd64 摘要 `sha256:2d99f793513d3830a995755571ceba4d7dfc45edd768df143dfa2c6997cf3a37` 为基础，仅在容器内补入 REA 所需的 `procps`，随后恢复 UID/GID `1000:1000`。构建文件和包清单留在 `.analysis/rea-wsl/`。

证据存于 `.analysis/rea-wsl/evidence/`。gzip 的 REA 证据分别为扫描 `ev_d933896653f1066dd25d9536cf8edbf688d3ba61084a23f2400973e77ee36b3d`、提取 `ev_40d36cf38c82c7ebe9b31f3617dc52813b68f3d6a018cd500676d50f6649441d`；J140 分别为 `ev_4c935fd7c047656a39d53271e1fea82fca357b20496a71f2a35899714df4bb6d`、`ev_78b8626ff96743c8a19ab435f06978f55a0fb36ea702397e6033e65156843b64`。J132、A 组及签名逐项复核见相应的 `rea-binwalk-*.json`、`rea-unblob-*.json` 和 `verify-binwalk-candidates.json`。两份 DAT 及 A 组输入 SHA-256 与[日版原始记录](JAPAN_FIRMWARE.md)一致。

## DAT 容器和提取结果

三个样本均以 `44 00 77 55` 开头；头部推定为 `[0, 0x64)`，依据是此后四个 MD5 边界都能同时闭合。头部 `0x04` 有 ASCII 版本样字段：1.26 的 `4.04`、1.32 的 `4.47`、1.40 的 `4.52`。这些值不等于公告中的固件版本，其字段语义尚未验证。头部 `0x38/0x44/0x4C/0x54/0x5C` 的 32 位小端字段给出五个长度，分别为 A、B 的两个候选子范围、C、D；A/B/C/D 各自紧跟 16 字节原始 MD5。三个版本均有 `40 75` 两字节尾标；含义未验证。

以下是 1.40 在 `firmware/705E140-carved/` 下的实际切片。偏移左闭右开；文件只包含对应的原始字节，不含紧随其后的 MD5。

| 切片 | 范围 | 原始 MD5（与计算一致） | SHA-256 |
| --- | --- | --- | --- |
| group-A.bin | `[0x64,0x9C0064)` | `99ec59e23905c4972152389f4617a208` | `21a1c24e29cd29357c13b7accdd250c7f71de1ee6ab82e77900bdaef73b54125` |
| group-B.bin | `[0x9C0074,0x9C4E52)` | `0c8e539d7cc30e63370b4c5f3bafd5ba` | `67262dcb94b8e65a528627326cf53959fa9ea163e86b3ee33a456b0dfa0deaf5` |
| group-C.bin | `[0x9C4E62,0xB27768)` | `3c8237b44d3753707f0d3fb3df94364a` | `d82fec3ece3bb097378e59d1f9a19ea93e5a8f033a6a41209c00292ec09ff6f5` |
| group-D.bin | `[0xB27778,0xBB5CDA)` | `091041ff8d28df45c2d56b3b9670114d` | `e59a6a6ba2f91e4d4f7c5920bcf88f39fc66602b34c9f2620bf7e47733bb5e42` |

B 组的 `0x9C041F` 是头部长度给出的子边界候选；已证实的是整组共享摘要，不是两个独立镜像。1.26 C 组的长度较后两版多 `0x9F57`，所以 D 组偏移随之后移；D 的内容哈希仍相同。

## 比较和逆向边界

- **1.32 → 1.40**：同为 12,279,020 字节；同偏移 4,246,933 字节不同。内容变化只在头部、A 组及 A 的摘要；B/C/D 完全一致。发布页列出的主 CPU 版本从 1.32 变 1.40，公开 DSP/FPGA/DV DSP 版本未变。A 内已有经[解包验证的主程序](MAIN_CPU_DECODE.md)，其余子组件尚未逐项归属。
- **1.26 → 1.40**：同偏移的重叠区有 6,517,122 字节不同，1.26 多 40,791 字节。按各版布局重新对齐后，B、D 一致，A、C 不同。DSP Program 与 DV DSP 公告版本也不同，尚不能把 C 唯一归属到某个处理器。
- 1.40 原始 DAT 的扫描未命中所查 ELF/ZIP/gzip/xz/zstd/PNG/uImage/DTB/SquashFS 等标识。某些 64 KiB 窗熵为 8.0000，同时相距 256 的字节全相等（例如 `0x210000`）。外层 ZIP 确认压缩；A 组主程序确认有逐字节编码及 LZSS，其他组的表示仍待核验。
- 以 A 组起点对齐划分 156 个 64 KiB 窗：1.32 与 1.40 有 74 窗完全相同，这 74 窗在 1.26 也相同。1.40 有 6 个完整的 256 字节周期窗，内容彼此一致，且 1.32 对应窗相同；下一轮可先缩小到变化区和周期边界两侧。
- 原始字节 `0x950D6A` 的单个 `RTTY` 无可复核的引用，不能用于定位 UI 或解码器。解包后已验证 ARM/Thumb 代码、向量、入口、装载地址和 GPS 距离格式化函数，并找到 RTTY 资源引用。Icom 日版手册确认整机包含 CMSIS-RTOS RTX 和 FreeType，见[架构报告](HARDWARE.md)，库的使用位置尚未验证。
- 三个主 CPU 镜像已由各自的 DAT 单独恢复，不需旧版，确认这部分不是差分。其它分组及完整 Flash 覆盖尚未核实。完整性和设备恢复见 [恢复评估](SAFETY_AND_RECOVERY.md)。

## 日版及跨机型续测

日版基线为 [705J140](JAPAN_FIRMWARE.md)。已追加 705J111 并校验日版组布局；另用现有 REA MCP 的 ZIP 归档和字节熵接口复核 IC-905 和 IC-9700 各一个代表版本。两次归档会话均已关闭。证据编号、原始 ZIP/DAT 哈希、首段 MD5、切分点和错位对照见[跨机型报告](CROSS_MODEL_FORMAT.md)。Windows Provider 能力与固件函数分析条件没有变化。

此前用 REA 熵接口复核 [尾段 25,640 字节的重复地标](TAIL_RECORD_ANALYSIS.md)，未确认该尾段内有字库或可执行组件。另用归档和 `inspect_pe_resources` 接口核对 [CS-705 两版官方软件](CS705_MENU_REFERENCE.md)及其 x86 PE32 程序；程序内的菜单键和帮助主题已定位。PC 程序仅作外部对照。

[设置字段续测](CS705_SETTINGS_MAP.md)用 REA 核验两份官方 ICF 的外层 ZIP，并打开 CS-705 1.30 的 x86 PE。当前 Windows MCP 的 objdump 和深度 Provider 不能反汇编该 PE；已在现有 Debian WSL2 中用本地解包的 GNU objdump 核对四个设置字段。此结论只涉及 PC 程序及设置文件；12 个 DAT 的明文对照均未定位这些字段。

[九个日版的组件对照](FIRMWARE_COMPONENTS.md)将 A 与主 CPU、D 与 WLAN 联系起来，并用相邻更新的反例排除将 C 单独归给 DV DSP 的简化判断。Windows REA MCP 独立核对了 1.11、1.20 输入 SHA-256；头字段和组归属用实际字节与官方版本表交叉核验。

## 主程序解包与实际函数

本地只读解包器已从 705J132、705J140、705E140 提取主 CPU 镜像。Windows REA MCP 复核两个日版的输出 SHA-256；REA CLI 对 J140 的复位段成功反汇编。引导及 GPS 距离显示的调用链由 GNU objdump 结合两版字节、资源表和官方公告核对，已建立 `0x20005000` 的运行地址映射。GPS 距离缓冲和 RTTY 标题都能追到共用的文字绘制入口。详见[提取哈希、地址与复现](MAIN_CPU_DECODE.md)。C/D 内部及固件运行时完整性仍未验证。

[J140 原厂语言行仿真](IC705_EMULATION.md#日版-140原厂菜单行像素)由现有 Windows REA MCP 复核提取的原厂字体字节，GNU objdump 核对 A32/Thumb 边界，Windows Unicorn 执行原厂绘图代码。本轮已经输出两项语言设置和对应选项值，未依赖 WSL，也无需为此调整 REA 配置。

[J140 原厂显示设置整页](IC705_EMULATION.md#日版-140显示设置整页画面)复用同一环境，REA 核验主程序页函数字节，原厂列表和绘制函数在 Windows Unicorn 运行，已补足显示设置所需的 Flash 位图映射。`1/6` 和 `6/6` 的五个参考帧可逐字节复现。没有修改 REA 配置或接入实体电台。

沿已验证的 A 组解码继续提取出两份 TrueType，确认先前 25,640 字节的地标是小字体的完整长度记录。Windows REA MCP 复核两份字体 SHA-256，Python `cmap` 与 Windows WPF 独立核对原厂菜单字形。两版「显示语言」到字库的路径、哈希及复现命令见[字库报告](IC705_LANGUAGE_FONT.md)。

### J140 原厂设置导航

[原厂设置导航重放](IC705_EMULATION.md#日版-140原厂设置导航重放)继续复用 Windows REA MCP。`inspect_byte_entropy` 返回的 256 字节窗口用于独立核对解包后主程序的原始字节。行为证据另由 GNU objdump 的反汇编和 Windows Unicorn 的执行轨迹提供。未使用 Linux 提取 Provider，也未改动配置。

| 字节窗口 | REA 证据编号 |
| --- | --- |
| 事件分派 | `ev_8fbfa84fbac2227c668b2d8f100cfe92015d1dc7ed2cae480ef6aee91bdc373f` |
| 翻页和选行回调 | `ev_232eee5847e3943d67395b902d9fd846bf0a0464a6742ddda02ffb1df92c7c5c` |
| 返回回调 | `ev_c5b4194703c08f649f2f3171156986ea648574713318fa18b52e9cfafbc4067a` |
| UI 更新 | `ev_9aecdafeff28680a29b056b5557e14052fb1b1bbd5696113b0b8bae310f7a588` |

### J140 触摸坐标与语言提交

Windows REA MCP `inspect_byte_entropy` 在相同主程序哈希上复核四个 256 字节窗口。对应行为由 GNU objdump 和 [Unicorn 坐标重放](IC705_EMULATION.md#日版-140用鼠标操作原厂设置)证实。

| 入口 | REA 证据编号 |
| --- | --- |
| `0x20107418`，矩形命中 | `ev_5cecb86ad7d1393e15f5416236559035ccb15594628532957729c84bb96b7a4f` |
| `0x201083B0`，按页面选择触区表 | `ev_12ab01aa77e7853ba7c00ffd1c2b80611569b372ea240678881d562bb8496f7e` |
| `0x20108550`，解析坐标样本 | `ev_6c37bd9beac6bd90fb307d8d82a9fea4a30d6a07d8c70528207210ca89a6d0e7` |
| `0x201088F4`，触区映射为固件事件 | `ev_a1e205b6cb0175f8a27568d70fb2d65684ccd1a0521bdd31f292db13b1952be1` |

### J140 主屏与 MENU

在原有 Windows REA MCP 上用 `inspect_byte_entropy` 复核下列入口起始的 256 字节；输入为解包后的 `main.bin`，SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`。功能命名来自 ARM 反汇编及[按键、坐标和绘制的动态回放](IC705_EMULATION.md#日版-140原厂主屏与-menu)，不是从熵推断。

| 入口 | REA 证据编号 |
| --- | --- |
| `0x2007F010`，按键扫描 | `ev_5760c609472ed4418308cdcfcc22e2105b74bd269a6fe77faf59f6d4f890eb41` |
| `0x200872E8`，打开 `MENU` | `ev_f1f73ac1c98c3f19e9f5d8971e7093114bf136fe6097c97b1858b3fd4c3730a7` |
| `0x20087340`，选择 `SET` | `ev_148e47609409bb967cb242778421bd4dc51738a3ecfb133a2ca429c5799e8dae` |
| `0x2013C5E8`，画面分派 | `ev_836638584d042565c78c4a65abf6abdd1ddc950f84102371281942e93b56db01` |
| `0x2013D82C`，菜单格绘制 | `ev_a322c88a55256d989692eaf7aa4c1abae28d0a49391bc73cf52a05769f2a5664` |

### J140 单行简体实验

复用 Windows REA MCP 的 `inspect_byte_entropy`，对同一 `main.bin` 哈希复核每个地址起始的 256 字节。路径、字形和画面由 [原厂面板动态实验](IC705_ZH_NATIVE.md)验证。

| 入口 | REA 证据编号 |
| --- | --- |
| `0x202F0DFC`，显示语言记录 | `ev_6f9546643e7069952ab656fe5ed43c88c8f386ae90b37983df408c63030f2fe4` |
| `0x20144CAC`，原厂转换器 | `ev_00b9a64d290bd7e91b8b3fa574d30c67753520da2bff76b8b9ffc200c1b1705e` |
| `0x20146ABC`，绘制路径的转换返回点 | `ev_0c2fc7370b0d8824a6fd6cf0cb807bf5f3753a2ed7e106258948cb2237c9820e` |
| `0x201450F4`，选择字体实例 | `ev_e985173642487b10f24bfd61ecb4a10451607b39d39405639377c78e6cc9b93a` |
| `0x20197410`，内存字体初始化 | `ev_3b44f4e02e716470c1ab0dc046c67d9c5dd614d97e4b5fede40f87bcf5bae7e8` |
| `0x20197A90`，绘制 16 位字符缓冲 | `ev_10e1a85e94f111eb4ed1ec43f45460d8621eae2bd9f856ac499eca78602ed4fe` |

### J140 显示设置第一页简体实验

继续使用 Windows REA MCP `inspect_byte_entropy` 复核 J140 主程序 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9` 的指定文件偏移（运行地址减 `0x20005000`）。亮度和选项值的语义由 objdump 和 Unicorn 离线运行确认；[对照报告](IC705_ZH_DISPLAY_PAGE.md)记录实际像素和偏好写入。

| 入口或文件 | REA 证据编号 |
| --- | --- |
| `0x20061C64`，亮度读取入口 | `ev_82acf5abd6e7b03c4561f9c0014e9281834ea685b9f6670dd86f05f7577ac11e` |
| `0x200ACE04`，亮度数据进入列表 | `ev_0518d82755d059995e4cc2b12bde9443a5f2d58e18ebc306e762c1acd814341a` |
| `0x200ACD20`，枚举值进入列表 | `ev_5f863f2bb812eabb188ee73d7a985694ccec09df20ca998060e5a44df97f6fb6` |
| `0x201451A0`，识别临时字体槽 | `ev_32165525596e6ca7317a583ddfe85f8e40a95883371de1bbafc1dfdb23e27c55` |
| 新的简体 TrueType 子集 | `ev_8e860ea7a0d4e4661f96bf7fb4efd4923bb1e62314ac60fc0ff8f3ac6ccd78ff` |

### J140 亮度编辑器与 ARM 词表实验

Windows REA MCP 对主程序继续用 `inspect_byte_entropy` 复核相关字节。GNU objdump 和 [62 帧离线实验](IC705_ZH_ARM.md)核对分派和绘制语义。

| 入口 | REA 证据编号 |
| --- | --- |
| `0x20159854`，亮度编辑器绘制 | `ev_19b881a6e8fc8518badd8d37f1044e7a7ac79b70b8b76fbb208ceaf629db2ed8` |
| `0x200A24E4`，设置选项列表构建入口 | `ev_5386af9570dc08d5d13fcdcdd81590a69aa2050dca40e04dd0cf10fcbdcd3cf3` |

## C 交叉编译对照

2026-11-13，用现有 Arm GNU Toolchain `14.2.Rel1`（GCC `14.2.1`，GNU objdump `2.43.1.20241119`）把[独立 C 函数](../samples/arm-compile.c)按 `-mcpu=cortex-a9` 分别编译链接成 A32 和 Thumb ELF。GNU `readelf` 确认两个文件都是小端 ELF32 / ARMv7-A。REA 6.8.0 调用 objdump，均识别出 `toolchain_smoke` 中的左移、加 7 和返回；输出未截断，前后文件哈希不变。

| 样本 | ELF 入口 | SHA-256 | REA Evidence |
| --- | --- | --- | --- |
| A32 | `0x8000` | `d475d4aeb928f61574c14857844e1df198b22a2208aca0c7e1a42a14396843c3` | `ev_bf7a469df5014ed62e72b9c0bfb422d482de614fd4aee882ab3ffb62c1b1fef0` |
| Thumb | `0x8001`（实际指令起点 `0x8000`） | `6201979b6554bcd08cb07c8a2dffa3f8bffc7b0e7d0f4f1a0ad6f738399d2988` | `ev_aaa32dda5a186ad8325deaca3f2d785f8913ce77fc01bf20f7a53f664fca2490` |

入口来自对照样本的链接结果，与 IC-705 地址无关。编译选项也是对照设置，不能用来判断原厂调用约定或浮点 ABI。本次没有执行 ELF；实测只证明本机能构建和分析自己的 ARM 代码。完整输出在 `.analysis/arm-compile/`，见[复现命令](../samples/README.md#c-交叉编译对照)。

## 复核

运行 [README](../README.md) 中的 `layout`、`scan`、`compare`、`strings`。本机 `.analysis/` 保存了诊断和实验 JSON，包括 1.40 ZIP Evidence `ev_6c7f4476ac5ec3569abc69f07518196dbb50ea29aa4c24eec07fec9a917033e4`、熵 Evidence `ev_7bf112661cece81a589482ed67010ee57ee235d17cc73006cec0741113cc022a` 及合成 ARM 样本 Evidence `ev_0404abe3a44a8b103febfd5c79c0077bcc6882086ced271acf3728503b309f3b`。GNU objdump 验证命令见[样本说明](../samples/README.md)。

在项目根目录运行以下 PowerShell 命令可复现切片，固件输入只读，输出放在新目录，不覆盖现有切片。其他已验证的 J/E 版本使用相应文件名与新输出目录。对比 A 组可直接在两个 DAT 上运行 `compare-groups --block 0x10000`；切片可用 `scan --block 0x10000` 检查周期。

```powershell
@'
from pathlib import Path
from tools.firmware_scan import layout

data = Path("firmware/705J140.dat").read_bytes()
report = layout(data)
if not report["all_records_valid"]:
    raise SystemExit("Invalid payload MD5 or placeholder")
out = Path("firmware/705J140-carved-repro")
out.mkdir()
for group in report["groups"]:
    if not group["bytes"]:
        continue
    with (out / f'group-{group["name"]}.bin').open("xb") as target:
        target.write(data[group["offset"]:group["end_exclusive"]])
'@ | .\.venv\Scripts\python.exe -
Get-ChildItem firmware/705J140-carved-repro/*.bin | Get-FileHash -Algorithm SHA256
```

## J140 六页显示设置与时间设置对照

这次使用现有 Windows REA MCP 对已提取的 `705J140/main.bin` 运行 `inspect_byte_entropy`。选取列表绘制例程 `0x201549B4` 对应文件偏移 `0x14F9B4`，长 256 字节。返回证据 `ev_80c122f5d120c74f787a28a2e5083d3e02b59f91ed8855f210dc371847797ec5`；主程序 SHA-256 与原厂回放一致：`d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`。该检查只核对文件身份和区间；选项、回显与语言切换均来自原厂 ARM 在 Unicorn 内执行。

`open_binary(format="raw-binary", architecture="arm", entry_point="0x20005000", provider_id="ghidra")` 返回 `capability_unavailable`。本会话未配置 `GHIDRA_INSTALL_DIR`；此外，当前 REA 的 Windows Ghidra 适配器只接收本机 PE 与显式裸 6502，这不是对 Ghidra 本身的格式判断。无需改动配置或安装软件即可完成本轮回放；若后续要做更广的交叉引用，可用独立 Ghidra Raw Binary 导入，或在[已有 Debian WSL2](#wsl2-固件工具实测)上先核实对应 Provider 对 ARM 的支持。

[六页复现与结果](IC705_ZH_CATALOG.md)记录了菜单 67、68、69、70 和通用选项菜单 286 的触摸、项目 ID、原厂偏好及画面对照。

## 开机图片与字体加载对照

### 字库入口连续回放

Windows REA MCP 用 `inspect_byte_entropy` 核对 J140 `main.bin` 的身份与两个 256 字节窗口：资源入口（文件偏移 `0xFF90C`，证据 `ev_0db1d1a782007b5d898a8e858a3d779f585d7767221093297dbe4b687f781257`）、MTU2 通道 4 例程（偏移 `0xD5C`，证据 `ev_9378b6cbcbb205fae007f9df692f7542f2e88e24e3a367ecafc11a0a41d76924`）。两窗均绑定主程序 SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`。A32 指令用已安装的 GNU objdump 核对；实际访存和四次写表来自[原厂 ARM 在 Unicorn 内执行](IC705_SD_RESOURCES.md#j140从函数入口连续写表并用写出的字库绘制)，不是从熵或地址推断出来的。

2026-11-13。现有 Windows REA MCP 的 `inspect_byte_entropy` 复核两个日版主程序的全文件哈希和开机图片调用附近的 256 字节窗口。

| 样本 | 文件偏移 | Evidence |
| --- | --- | --- |
| J132 | `0xF0A08` | `ev_8dd430eb69404b226f78e4ac7de161987b785fa344dd3ba6f7c5b7bba5254cef` |
| J140 | `0xF3F98` | `ev_60cfcf3c9d361a5d29535f355c1532e6e4ab8e9a387d4bb6d1e4f65c85002f50` |

完整 JSON 在 `.analysis/stock-resource-paths/`。文件证据用于确认输入身份；A32 调用由现有 GNU objdump 复核，实际状态变化由 Unicorn 回放确认。参见[原厂开机图片与字体报告](IC705_SD_RESOURCES.md)和[RTTY 从 GPIO 到正文](MAIN_CPU_DECODE.md#rtty-从五位符号到正文)。本轮没有安装工具或修改 REA 配置。

## 日版接收音频复核

2026-11-13。复用现有 Windows REA MCP 的 `inspect_byte_entropy`，复核两份已解包主程序和每个入口的 256 字节窗口。运行地址减 `0x20005000` 即文件偏移。功能语义由 GNU objdump 与[原厂 ARM 回放](IC705_RX_AUDIO.md)验证。

| 日版／入口 | 文件偏移 | REA Evidence |
| --- | --- | --- |
| J132 SSIF0 DMA 消费 `0x200FC658` | `0xF7658` | `ev_0e9a25113980e83b4effa5e974e0250343eecba382fbe7733e78c379790ff6f3` |
| J132 录音 PCM 消费 `0x2010C7C8` | `0x1077C8` | `ev_46d9224452343cce2a8acaa480ae0964c46c571baf46bfd507491709b8be0ab8` |
| J140 SSIF0 DMA 消费 `0x200FFC70` | `0xFAC70` | `ev_05c5feda4b460e7eaa0dcfb5a7b1d293f8996804507c981c3f3a9ad95f839652` |
| J140 录音 PCM 消费 `0x2010FE04` | `0x10AE04` | `ev_87ac703e989b30126338d68c1c6de90af5748fd4a7be8247afe7b242252ac28f` |
| J132 预录 PCM 入队 `0x2010C230` | `0x107230` | `ev_a73fe7165798d51de4aa7c3bc9b0c2fa8d544b693c700abda26a7d137a45da55` |
| J140 预录 PCM 入队 `0x2010F86C` | `0x10A86C` | `ev_a67d6b153cc0ddac4250bd95496b582315743839e0fc883fc2787b56ec1777a5` |
| J132 PCM 6:1 抽样 `0x2010C418` | `0x107418` | `ev_764bdf119ca104a763f70ada9113c823c0e101e0f2062fab7a1070486618eecf` |
| J140 PCM 6:1 抽样 `0x2010FA54` | `0x10AA54` | `ev_21b8f4c5fe03013e6dc74db0da4deb0a573545df4235a531533388a27185e392` |

新增两个入队窗口的完整 MCP 响应在 `.analysis/cw-recorder-replay/rea-prerecord.json`。用原厂 ARM 函数对两版各回放 470.816 秒，并做延迟消费反例；[游标、PCM 哈希和时序结果](IC705_RX_AUDIO.md#cw-长录音与延迟读取对照)来自 Unicorn。没有变更 REA 安装、Provider 或 WSL 配置。

两个抽样例程的完整响应在 `.analysis/sstv-robot36-v1/rea-decimation.json`。[Robot 36 回放](IC705_SSTV_REPLAY.md)验证了原厂逐点抽样和混叠；REA 证据用于复核镜像和入口区间。

## J140 语言保存与重载

2026-11-13，继续复用 Windows REA MCP `inspect_byte_entropy`。以下文件窗口的主程序 SHA-256 均为 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`。REA 复核输入和区间；GNU objdump 和 [Unicorn 回放](IC705_LANGUAGE_PERSISTENCE.md)验证实际代码与行为。证据包已导出到本机 `.analysis/j140-language-persistence/rea-evidence.json`，未改动 REA 或 WSL 配置。

| J140 内容 | 文件偏移（长度） | REA Evidence |
| --- | --- | --- |
| 设置读取、比较与同步保存 `0x2004E73C` | `0x4973C`（1024） | `ev_ac23226862de25c9b146dd2a3edb8e0db79bc412bf0796d319eef0ccadcc2558` |
| 显示和系统语言的状态打包 `0x20095E8C` | `0x90E8C`（256） | `ev_cc9b1d66a410ab85bda921367a87fc7858ce99d90173691489a993d76147253e` |
| 显示与系统语言选项记录 `0x202F0DFC` | `0x2EBDFC`（256） | `ev_5d2f2866a63abc68cc0859ff5871dcb58a22f9fca26b535e4f71a3d970ac25f8` |

### J140 独立显示语言试验

在相同主程序上另用 Windows REA MCP 核对共享日英选项表 `0x202ED520`（文件 `0x2E8520`，`ev_883851678b252176de9643434c39e1957e5ee27b6077b3cf6e95620f788502bd`）和原厂语言函数 `0x2009F520`（文件 `0x9A520`，`ev_79fd8e20c8b9310c981868f617c33674783aec801c4965952b147ebff9fe9a2c`）。GNU objdump 与[实际触摸和存取重放](IC705_ZH_THIRD_LANGUAGE.md)验证行为。完整 REA 证据在 `.analysis/ic705-emulator/j140-third-language/rea-evidence.json`；此试验不需要更改 Windows 或 WSL 的 Provider。

中文导航补充：Windows REA MCP 复核主菜单渲染区 `0x2013D82C`（4,096 字节，`ev_8709292cc14bcd018cbc595ada551e092fa2e51a0db2ab45bd6540903ad03eed`）与字形索引函数 `0x2025B668`（256 字节，`ev_504be425c98777f46347f12706b5725627dff293136ad37e05f800fac168e4b3`），证据包在 `.analysis/ic705-emulator/j140-zh-navigation/rea-evidence.json`。该步骤锁定字节范围；[A32 调用及图形回放](IC705_ZH_THIRD_LANGUAGE.md)另验证菜单标题、图块和缺字行为。

字体资源回放补充：REA 对同一 J140 主程序核对资源入口 `0x2010490C`（`ev_e8439f4c411f29e6b9725f18b141bfb1094caf2631d72c4cc3a867c257ec2490`）、字体槽初始化 `0x20145244`（`ev_5407d7d148f59d76bb358ce0e31abc4778b40cf0086e9b02537c72bf039ee938`）及 FreeType 内存字体入口 `0x2025D1BC`（`ev_6e2bcb6ac0a11bd04f29cffe09f64a65356007b7cb15ba6fba775f096994ae17`）。原厂 ARM 的实际访存、参数和绘制由[独立回放](IC705_SD_RESOURCES.md#j140从字库发现到首条测试菜单绘制)验证；本地证据包为 `.analysis/ic705-emulator/j140-font-boot/rea-evidence.json`。

资源函数入口继续核对：Windows REA MCP 以同一 SHA-256 镜像记录 DMA 设置例程 `0x201048F4`（`ev_82e83088d157f95abb536025514cdeff3c0b605db9c2a6af2d04ae9a136f7d8d`）、两处时钟辅助例程 `0x20367B00`、`0x20005AC0`，以及 Thumb 标签比较 `0x202C9068`（`ev_21aa20d0a4826c97cae4ffcd62475bcfa71c6a7dd6b000561aaa08e4c1790bae`）。新证据包 `.analysis/ic705-emulator/j140-font-resource-entry/rea-evidence.json`。寄存器身份见上游资料；[写入顺序及标签对照](IC705_SD_RESOURCES.md#j140资源函数入口与标签分支)由反汇编和 Unicorn 验证。无需更改 REA 或 WSL 配置。

### J140 转换前的菜单文案

2026-11-14，Windows REA MCP `inspect_byte_entropy` 核对同一 J140 主程序的原厂取字函数 `0x2014B390`（`ev_ce2f737b4651caf76c0c5543e5c031edd2e9b31198c0cbb84766a285112067df`）、显示/系统语言记录 `0x202F0DFC`（`ev_b7f55fb5448ba05a2bb27c6f0b14dc55472414bd4d60ef4c3b18bcf9e268e188`）、字符转换入口 `0x20144CAC`（`ev_55e657440b85dd3f3a2a34e324617a7a1d2bac3fe2c83731572c83be69e9b902`）及映射表 `0x202FCDC4`（`ev_a7fe9abdc5ff354ba69904f8e89b6871965ef5065312db936a4fb39ac704872c`）。字节窗口由 REA 记录；[原厂取字、解码与设置回放](IC705_ZH_SOURCE_WORD.md)另用 Arm GNU 工具与 Unicorn 验证。证据包在 `.analysis/ic705-emulator/j140-menu-word/rea-evidence.json`。

### J140 菜单资源与设置文件导入

Windows REA MCP 对同一主程序记录以下字节范围。[独立原厂 ARM 回放](IC705_ZH_RESOURCE_ORIGIN.md)验证运行时读写，未改 REA 或 WSL 配置。

| 位置 | REA Evidence |
| --- | --- |
| 弹窗标题读取 `0x20154AA0` | `ev_7bf9c51236a5039676c53d9664720f5c84c56345366cb14374be4b039a7a9026` |
| 选项表读取 `0x20153B9C` | `ev_c7130f145cd3f3fa77b194fae30f1e3de5649c887caacb78b96b8a689498460c` |
| 早期启动复制和清零 `0x200052C8` | `ev_1df81db7af800dedd88ac96c52fce4ba18fe14b39e1ceec5db8c11b2fe661f84` |
| 文件任务分发 `0x20071C8C` | `ev_be9d83d9e837da003ff1426d49fed171104a14f2f4a5550995d3f143c5dd54e5` |
| ICF 原厂解析例程 `0x20068454` | `ev_a11424da7fcbe41ba3afe0a8c7ef675d125cc511b885e713a51bc0730d756879` |

本地证据包：`.analysis/ic705-emulator/j140-menu-resource-origin/rea-evidence.json`。

### J140 GPS 距离文字与绘制

Windows REA MCP 核对原厂距离格式化 `0x2021710C`（`ev_899898623dc6d841ab087bce0f3f23ecf2e1671245880378f95428000ce28cbb`）、标签与数值共用绘制函数 `0x20189500`（`ev_ce077f2839657729755e1b03bbe72449aa9cb200b09396cb715eab26562a5adf`）、差异重画 `0x2018A8D0`（`ev_c4e5a901cd85688dd05f0464cef1b7810443e12defa64467f2806a2755d29ce6`）及日英标签记录 `0x2032AFBC`（`ev_b218b3e21e93a2610ffa153f4d18f25e62ee17b8f3eb83d35dc349873c6cfd8c`）。证据包在 `.analysis/ic705-emulator/j140-gps-distance/rea-evidence.json`。实际输入、原厂绘制参数和像素结果由[独立回放](IC705_ZH_GPS_DISTANCE.md)验证。

### J140 GPS 输入与距离缓存

Windows REA MCP 的 `inspect_byte_entropy` 复核同一主程序哈希及三处原厂窗口。偏移是虚拟地址减 `0x20005000`。原始字节统计不验证指令语义；[GPS 输入回放](IC705_GPS_INPUTS.md)另用 GNU objdump 和 Unicorn 验证调用和行为。

| 原厂窗口起点、长度 | REA Evidence |
| --- | --- |
| `0x20073D00`、`0x400`：距离写入 | `ev_3913251c2eb015c897270c3f12f3200504568f71e10935cedc4f2404c4ef77cf` |
| `0x20212B00`、`0x400`：读取坐标和 UTC | `ev_ce08b357990ab502e9c2d2be5029f693dc6c8b5b94fa6033a3207dc2301a8a7b` |
| `0x20213400`、`0x200`：定位及 UTC 过期 | `ev_e705eaf89b4d92908f7fb1cb3f264591b08d7e303f7a04eb99530f6251175c56` |

本地证据包：`.analysis/ic705-emulator/j140-gps-inputs/rea-windows.json`。复用现有 Windows 工具，未安装软件或更改 REA 配置。

### J140 CI-V 与 VFO/Split

2026-11-14。Windows REA MCP `inspect_byte_entropy` 复核主程序哈希和下列字节窗口；偏移等于运行地址减 `0x20005000`。GNU objdump 验证命令分派表与调用；[原厂 ARM 回放](IC705_VFO_SPLIT.md)证实四种状态、发射候选及面板副频文本。复用 Windows 工具，无需修改配置或切换 WSL。

| 窗口起点、长度 | REA Evidence |
| --- | --- |
| `0x20029F00`、`0x400`：收帧路径 | `ev_a5590d275fa8173bed59c87952a69b58d5d29547f2f41c8dab06358034d0f4fe` |
| `0x2001B988`、`0x200`：命令邮箱 | `ev_5f06a569f78a0aad7c384ba8a6a0375f9b34bc5bfed41c692a93216a0f532208` |
| `0x200280D4`、`0x100`：`25` 频率回读 | `ev_8dc5c74d7d760ce308ead814a17f967ec7c39b83c895a797acd074c2b1afc143` |
| `0x20026604`、`0x100`：`1C 03` 发射候选回读 | `ev_d12a19820ffb1d7eab5587abf2b1a2ff43816e892ba58653459609132c5cb27c` |
| `0x20094AB0`、`0x100`：面板副频入口 | `ev_49e79c8ba75d373d678010dadd3d44429c5eb1b3f3439d1f023511f15b3388da` |
| `0x20103914`、`0x100`：Split 设置 | `ev_d8a46b0d7692fa0f904dc3322f1e7dd56cc0420c67e6afa5175155f3fcfb5107` |

本机证据包：`.analysis/ic705-emulator/j140-vfo-split/rea-evidence.json`。

### J140 卫星过境回放的原厂字节证据

Windows REA MCP 的 `inspect_byte_entropy` 复核 `main.bin` SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`。每处窗口为 256 字节；这是样本身份及字节范围证据。[过境回放](IC705_SATELLITE_PASS.md)由 Unicorn 验证原厂输入输出；轨道算法与补偿是桌面实现，无需 Linux Provider。

| 运行地址 / 文件偏移 | REA Evidence |
| --- | --- |
| `0x20212B20` / 2153248，坐标和 UTC 字段读取 | `ev_400aefd30238dc42400dbecbcd544a26678f3f204959028a0e14b641401a031d` |
| `0x20213480` / 2155648，定位和 UTC 过期入口 | `ev_a33026c8cf80063486810a2863a5cf1dc3ffff168955ce4bfba2d1bf5cf9dcb3` |
| `0x20026604` / 136708，发射候选回读 | `ev_d12a19820ffb1d7eab5587abf2b1a2ff43816e892ba58653459609132c5cb27c` |

本机证据包：`.analysis/satellite-pass/rea-evidence.json`。

### J140 PTT 与双 VFO 调谐

Windows REA MCP `inspect_byte_entropy` 复核同一份 J140 主程序 SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`。下表各窗口长 `0x400`；文件偏移为运行地址减 `0x20005000`。GNU Arm objdump 复核调用和分支，Unicorn 以原厂代码验证[受控回放](IC705_PTT_TUNING.md)。REA 字节窗口本身不证明执行路径；没有使用 Linux 提取 Provider。

| 原厂窗口起点 | REA Evidence |
| --- | --- |
| `0x200234A0`：频率设置分派 | `ev_eb81e59ccd26327ceba58fc4215b681112d7b011c826934964ffd755ea953122` |
| `0x2001CC04`：BCD 解析与频率分类 | `ev_c7f935bf54f279ac8640cf93fee8b0d1a76361e949e39ffdab99f73cdc4d2878` |
| `0x20098B50`：初始化调谐范围 | `ev_bc4061569abf66ae13dc0a5e647558b0da0da2ab4307e86d40f96929a6709bb9` |
| `0x200225E4`、`0x2007F4E0`：CI-V 请求 | `ev_4637b30234197aa0b375a0f1e6c690d66d491b09c85ef68ff729984ab03b74bf`、`ev_b8ff72818b4e9ebc9b542b09070fcc279c7f045b3225bee5e49fa4e2c2214ce4` |
| `0x2010B948`：采样手咪输入 | `ev_29caabd328df697ba700baf5a32db960c8a03746f0ffb589af7cbdc0b06c9b2d` |
| `0x20109E74`、`0x2010A084`：状态任务及其写点 | `ev_8a4e2f9b268220e2017c10ed1f30a7404e72e4dce577d62a376124401844c109`、`ev_942c2a8b6b16bc3e87a1bd751eb6f7d7344a5330dd400a867240b24be95082fb` |

本机证据包：`.analysis/ic705-emulator/j140-ptt-tune/rea-evidence.json`。

### J140 应用入口核查

Windows REA MCP `inspect_byte_entropy` 复核已提取的原厂 `705J140/main.bin`。文件 SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`。文件偏移 `0x6CC8C` 起 268 字节（文件分发表）对应 `ev_10050418c7f378f099cd56a262ba3cc5bf988d70157765a12ddf949cb638145d`；偏移 `0x34F2B4` 起 576 字节（内置目录路径一部分）对应 `ev_66177667c66cbedf4f153b13278dfcc5faf54b2c3609cd92cec5e84813f1b53c`。REA 此处只核对字节与来源，调用关系由 GNU Arm objdump 和 [Unicorn 原厂回放](IC705_APP_ENTRY.md)确认。未打开持久反汇编会话。证据包：`.analysis/ic705-emulator/j140-native-decision-baseline/rea-evidence.json`。

## J140 CW 显示与模式菜单

Windows REA MCP 核对 J140 主程序 SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`，固定三个原始文件窗口：

| 调查位置 | 文件偏移与长度 | REA 证据 |
| --- | --- | --- |
| 原厂 RTTY 页面入口 | `0x1700CC`，256 字节 | `ev_1195501132e6c2bee02d7316e5ae01e580bb70a63900656a95467d8004636506` |
| RTTY 正文颜色与行绘制邻域 | `0x16FA04`，256 字节 | `ev_20e63883a537e1d7331eddcf4c85a2bb41661de765305d16bf33488be4cea37f` |
| 原厂 MENU 状态组装入口 | `0x8D780`，256 字节 | `ev_ec751552683c3dcdb482253894972428a383b1895351017de5c653ae6e8106c8` |

REA 确认镜像及字节范围；由现有 GNU objdump 核对 A32 指令，通过 Unicorn 实跑按键、触摸、文字队列和绘制。见 [CW 显示与菜单对照](IC705_CW_DISPLAY.md)。未改环境配置。
