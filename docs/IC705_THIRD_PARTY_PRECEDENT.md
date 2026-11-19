# 日版 IC-705 第三方改版先例复核

核查日期：2026-11-15。**公开记录支持「日版 IC-705 曾运行第三方改版」，但未证明有适合日版接收 CW 的入口，或能在机器不开机时完整恢复同一块主板。** 这个先例把主控 Flash 的独立读取从器件规格推进到了同型号案例；不再把等待 Icom 回复当作推进条件。

## 两个 GitHub 仓库

| 来源 | 实际包含 | 对本项目的价值 |
| --- | --- | --- |
| [SQ6EMM 发布仓库](https://github.com/sq6emm/icom-custom-firmware) | MIT 授权的发布工具、差异数据和发布清单，无 Icom 固件。固定提交 `3d30e461d7bcbd39b782c1823764f305639ee9a8`；[清单](https://github.com/sq6emm/icom-custom-firmware/blob/3d30e461d7bcbd39b782c1823764f305639ee9a8/releases.json)给日版和欧版各列一个 `20261113v1`。 | 可核对官方底包、目标地区和功能范围。两个 705 改版均改写引导并声明改变发射范围，不能直接用于只接收的 CW 项目。 |
| [帖子中的 705／9700／905 逆向仓库](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware) | 固件结构文档、Ghidra 辅助脚本、作者的 Flash 记录和解析工具，并非 Icom 源码或可完整重编的 SDK。固定提交 `a91231f64e8afbe34353994786e8276a3b54f1a9`。帖子中另一个 GitHub 仓库对应 IC-7610。 | 可用于交叉核对原厂文件和同型号存储器；不能拿 IC-7610、IC-9700 或 IC-905 的结果代替日版 IC-705 的验证。 |

[发布仓库的测试](https://github.com/sq6emm/icom-custom-firmware/blob/3d30e461d7bcbd39b782c1823764f305639ee9a8/tests/web_patcher.test.mjs)核对文件摘要、长度、合成数据和错误输入；未见针对主板启动、A/B 回退或完整恢复及校准的自动化验收。本轮只读源码和清单，没有运行第三方工具，没有取用补丁数据。

## 开机手动切换 A/B

[作者在论坛第 3 页 #33 的说明](https://mikrofale.cafe/showthread.php?page=3&tid=1296)确认，IC-705 和 IC-9700 的改版保留当前与上一次的主程序，允许开机时手动切换。[发布清单](https://github.com/sq6emm/icom-custom-firmware/blob/3d30e461d7bcbd39b782c1823764f305639ee9a8/releases.json)把 A/B 明确列入 **日版 `705J140.dat` 的 `20261113v1`**；这不是仅针对欧版的 SD 应用功能。对于 IC-705，[发布说明](https://github.com/sq6emm/icom-custom-firmware#before-you-use-it)把另一位置的选择描述为开机时长按电源键，以 LED 闪烁为反馈；不需进入主程序菜单。

这个设计与我们[原厂引导的对照](SAFETY_AND_RECOVERY.md#排除用另一份主程序自动回退)不矛盾：原厂本来就有两处主程序存储位置，但我们未观察到所选位置损坏时自动换位。SQ6EMM 增加的是引导阶段**手动**换位。清单里的“上一份”也不等于永久保存一份原厂镜像；是否在后续更新中保留原厂版须单独验证。公开资料未证明这项切换在未改装的日版 41 系列遇到损坏主程序时已复验，也未说明手动选择是否会在再次重启后保持。

对接收 CW 项目的价值：可以把“原厂主程序可用、CW 主程序异常时从开机阶段选回原厂”列为独立验收。它要求引导本身仍完整、另一份主程序及所需数据仍完好。作者方案首次安装会改写引导，发布说明明确指出中断可能仍需编程器；因此此先例只支持增加主程序回退能力，不能替代首次安装失败时的独立恢复。该公开日版也包含发射范围改动，不直接采用。此节只复核发布资料与既有原厂实验，没有取用补丁或操作电台。

### 原厂 A/B 共用区实测

借用作者的[封装分析](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/a91231f64e8afbe34353994786e8276a3b54f1a9/IC705_DAT_FORMAT.md)和[板上 Flash 记录](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/a91231f64e8afbe34353994786e8276a3b54f1a9/IC705_FLASH_LAYOUT.md)的分层方式：先确认 DAT 的内容，再核对原厂更新器实际写的虚拟 NOR，最后才判断恢复。区界取自[本项目的更新器回放](SAFETY_AND_RECOVERY.md#普通更新会先动哪里)，没有把对方的板上地址直接套到用户的日版。

对 [ICOM 官网来源清单](../research/705j-provenance.json)中的九份日版（1.11、1.20、1.24、1.26、1.27、1.30、1.31、1.32、1.40）校验完整文件的 SHA-256、长度和包内记录，再只读解码对比。九份的 64 KiB 引导与 A 组 **3,932,160 字节（3.75 MiB）的共用区完全相同**；按原厂回放的擦除单位计算，60 个扇区中没有一处不同。已用原厂字库 SHA-256 另行核实该区开头确有共用字库。日版 1.32 相比 1.40 只有 A 组不同；以 1.32 内容为对照的原厂虚拟更新确实没擦写这 60 个扇区。更早的样本仍有 DSP 组变化，1.11 还与 1.40 的 WLAN 组不同；切换主程序位置不会验证或还原这些外围内容。

因此只做接收 CW 时，优先用同一个日版 1.40 作基线，原厂 A 和 CW B **共用同版资源，不改 DSP、WLAN、设置和校准**。两份主程序共用资源是可验证的设计约束，不能据此把任意两个历史版本当成互相独立的整机固件，也不能把 A/B 当作引导损坏时的恢复。

REA 只读复核代表样本的完整文件 SHA-256：1.40 `ev_36f56f7f0d4c1e8632e1d3a16eb4b83bcc97edaf39834735c754edc70b1b02d7`，1.32 `ev_d44fa1efd012b6b5c3f07565e2f5c1b352b9add1b22d8db5f051c16470b552e3`。实际共用区比较由本地解析器完成，结果见 [报告](../.analysis/cw-ab-shared-1115/evidence.json)，SHA-256 `3f9532f8325701244447018b872c985343702e75c233c2b0d69daf8555998ced`。复验命令只输出 JSON，不需要第三方工具或设备：

```powershell
py -3.14 -X utf8 -m tools.audit_705_ab_shared
```

## 真机记录分别支持什么

| 证据 | 判断与边界 |
| --- | --- |
| [论坛第 1 页 #2、#10–11](https://mikrofale.cafe/showthread.php?tid=1296)，[第 2 页 #16、#18–19](https://mikrofale.cafe/showthread.php?page=2&tid=1296) | 2026-11-11，SQ1GQC 的日版首次尝试不成功，随后收到日版专用构建，作者在测试后加入日版。同日另一位用户 SP5CUR 报告自己的日版也能运行，未说明硬件是否改过。两条早期记录都没有文件哈希和主板修订号，也早于清单中 11 月 13 日的构建。 |
| [论坛第 4 页 #49](https://mikrofale.cafe/showthread.php?page=4&tid=1296) 与 [#2](https://mikrofale.cafe/showthread.php?tid=1296) | SQ1GQC 用示波器验证了新加的一项变频器定时功能，说明他看到的不只是开机画面。该台日版以前做过硬件地区改动；这不能当作未改装日版的同条件实证，也没有验证 CW。 |
| [论坛第 1 页 #1](https://mikrofale.cafe/showthread.php?tid=1296) 与 [发布说明](https://github.com/sq6emm/icom-custom-firmware) | 作者明确说开发期间 IC-705 与 IC-9700 各有一次事故需要直接处理 Flash。没交代 IC-705 的地区、主板版本、故障原因或校准恢复结果。发布说明也指出首次安装会改写引导，若该步骤中断，可能需要编程器。A/B 回退依赖改过的引导还能运行，不能拿来证明引导坏了照样能救。 |
| 作者的同型号 Flash 记录（逆向仓库 `IC705_FLASH_LAYOUT.md`）与本地 [维修图核查](SAFETY_AND_RECOVERY.md#日版主程序无法启动时按路径核对恢复证据) | 作者记录了一台 IC-705 的 16 MiB 主控 SPI NOR，报告在板读取不可靠。容量和器件系列与维修图相符；封装、板版不能推到用户的机器。没有公开同版主板两次一致的读取记录、两颗 EEPROM 记录或同板恢复后的校准验收。 |

### SQ6EMM 的外置编程器路线与日版 41 系列

2026-11-15 再读[论坛首帖 #1](https://mikrofale.cafe/showthread.php?tid=1296&pid=5869#pid5869)及当前四页共 49 条帖子。SQ6EMM 说 IC-705、IC-9700 的开发各有一次事故迫使其直接写 Flash。他没有说 IC-705 当时写回整片还是只修了某一区，也没有给出故障前后读回、板号、地区或恢复后的校准记录。日版用户的首次安装不成功、后续日版包运行，是另一组报告，不能当成这次救机，也不能当成 `#41` 救机。线程第 3 页的 `#41` 是帖子编号。

[SQ6EMM 的 IC-705 Flash 文档](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/main/IC705_FLASH_LAYOUT.md#reading--writing-the-flash-directly)具体记录的是：主控 16 MiB `IS25LP128`（SOIC-8）；在板读芯片 ID 返回零、不可靠；文档采用拆下芯片以 3.3 V CH341A 和 `flashrom` 在板外访问，要求读两次且逐字节相同，并把同一颗芯片的原始镜像保留作恢复点。外部编程不依赖故障电台启动。文档的步骤与论坛事故相符，但公开资料没把二者逐步对应，不能声称已经复原了事故时做过的每一步。作者的电台发布页也将[外置编程器恢复](https://github.com/sq6emm/icom-custom-firmware#before-you-use-it)和依赖改版引导仍能运行的 A/B 切换明确区分。

维修图已标出主控 `IC704 / IS25LP128F`，外部路线有同型号依据。[ISSI 数据手册 §8.31 表 8.7](https://www.issi.com/WW/pdf/25LP-WP128F.pdf)给出 LP 型的 JEDEC ID `9D 60 18`，同容量 WP 型是更低电压的另一器件，且该系列有不同封装。不能从 `41` 前缀、相同技适号或同容量推定同一接法。公开的旧板照片和日本样机照片没有把具体板号、器件和 `41` 前缀绑在同一台上；[板版对照](IC705_BOARD_MATCH.md)对此仍无结论。

**能推进的一步：**由有 IC-705 板级维修经验的技术人员确定用户机的主板丝印和主 NOR 完整料号、封装、电压及有效 ID，用独立设备两次读回整片主 NOR、记录影响启动的配置和校验值，并按恢复清单另存原板两颗 EEPROM。若匹配，SQ6EMM 路线就有本机的只读证据；要把它认定为安全回退，还缺同修订板在不能启动时恢复原数据、冷启及保留校准的记录。原厂 DAT 是升级包，不能代替板上完整原始镜像；不拿用户唯一的电台做故障注入。

## 本地只读交叉核验

用项目自己的 [日版／欧版原厂包解析器](../tools/decode_705_main.py)在内存中读取两份官方原件。用整包、引导和解压后主程序共六个 MD5 逐项比对发布方测试常量，全部一致；再直接比较两区的引导与主程序字节。MD5 在这里仅用于对照对方的文件标识，不能作为真实性或签名结论。

| 原厂文件 | 整包 MD5 | 64 KiB 引导 | 解压后 ARM 主程序 | 第三方清单 |
| --- | --- | --- | --- | --- |
| 日版 `705J140.dat` | `b605171288db4a74e0992a8f2afcb1c3` | 与欧版逐字节相同 | 3,558,076 字节，MD5 `c8202dfae07bca21b2d28f6015346863` | 未列 SD 应用、未列 CW |
| 欧版 `705E140.dat` | `2c9c1d7f3fc80ef173e01d841cd1248a` | 与日版逐字节相同 | 3,558,876 字节，MD5 `62fbe39f29bcf0b3cc341b861912047d` | 列有 SD 应用、未列 CW |

两份原厂引导相同，但主程序不同。两项第三方发布共用版本编号，不表示功能也相同。当前清单仅给欧版改版列 SD 应用；这条线索不能用作已知的日版入口，也不能据此断言日版永远没有相应入口。

本地证据 `.analysis/cw-precedent-1115/official-inputs.json`（SHA-256 `c77b877b6f49acde4cc70d1ca6f495ba2f66afba23d8be7bbd767b6bf358d3da`）包含两份原厂文件及其组件的 SHA-256、三份固定提交公开文本的来源与摘要。复验原厂内容不需要网络或第三方工具；从项目根目录运行：

```powershell
@'
from hashlib import md5
from pathlib import Path
from tools.decode_705_main import decode_main

stocks = {}
for region in ("J", "E"):
    raw = Path(f"firmware/705{region}140.dat").read_bytes()
    boot, main, _ = decode_main(raw)
    stocks[region] = boot, main
    print(region, *(md5(data).hexdigest() for data in (raw, boot, main)))
print("same bootstrap:", stocks["J"][0] == stocks["E"][0])
print("same application:", stocks["J"][1] == stocks["E"][1])
'@ | py -3.14 -X utf8 -
```

## GitHub 扩搜：去重后留下的线索

2026-11-15。在 GitHub 仓库名、说明、README、公开 Issue 和可用的代码索引中检查 `IC-705 firmware reverse engineering`、`IC-705 flash recovery`、`705J140.dat`、`GT24C1024` 及新增的两种主板丝印。对两个已知仓库进一步列出公开分支和派生库，用 GitHub API 比较提交，避免把复制的项目当第二份真机证据。

| 具体线索 | 验证结果与用途 |
| --- | --- |
| [OH2LAK 的逆向派生库](https://github.com/OH2LAK/ic705-ic9700-ic905-bring-your-own-firmware) | `main` 指向 `05be9fcda1d353bddfa6f0aeb41df81f7809680d`，落后原仓库 3 次提交，独有提交 0；其中 Flash 文档也是 SQ6EMM 原来的提交，并非另一人复测。 |
| [iu2frl 的逆向派生库](https://github.com/iu2frl/ic705-ic9700-ic905-bring-your-own-firmware)和[发布派生库](https://github.com/iu2frl/icom-custom-firmware) | 两个 `main` 分别与上文固定的原仓库提交完全一致，独有提交各 0。未发现新增的日版入口或独立恢复记录。 |
| [AetherSDR 的 IC-705 接收记录](https://github.com/aethersdr/AetherSDR/issues/6680)、[CW 接收选音修正](https://github.com/aethersdr/AetherSDR/pull/6650)和 [ggmorse](https://github.com/ggerganov/ggmorse) | AetherSDR 有 IC-705 仅接收联网实测记录。其电脑端 CW 解码有跟随电台音调的测试，ggmorse 是 MIT 许可的独立解码器，可作相同录音的外部对照。本轮未运行这套软件，未见它提供 IC-705 机内 CW 入口或固件恢复。 |

在此次可见的 GitHub 结果中，未找到第二个独立的 `705J140` 机内扩展实现、同版完整备份或不开机时恢复并保留校准的记录。普通 CI-V、克隆设置和远程接收项目归为外部工具。空结果不排除未公开或未建立索引的项目。

### 两份实物照片给出不同主板标识

| 来源 | 照片上直接能读到 | 能确定与不能确定的事 |
| --- | --- | --- |
| RadioChief 2020 年 IC-705 拆机：[主板全景](https://radiochief.ru/wp-content/uploads/2020/10/ICOM_IC705_2_1.jpg)、[主 CPU 与 Flash 近照](https://radiochief.ru/wp-content/uploads/2020/10/ICOM_IC705_4_1.jpg) | 主板中央丝印 `B-8984F MAIN`；近照上主 CPU 标 `R7S721001VC`，旁边 Flash 标 `IS25LP128`、`FBLE`，有外露的两排各四条引脚。 | 这块实物有 8 引脚的主控 Flash，和 SQ6EMM 报告的器件系列相符。未找到此样机的明确市场地区、日版批次或独立读回证据。 |
| 日本作者于 2025-02-22 发布的拆机照片：[主板全景](https://yesterdays.jp/wp-content/uploads/2025/02/9329-4-1.jpg) | 主板中央丝印 `B-9913A MAIN-A`；主 CPU 标 `R7S721001VC`。 | 这是不同的实物板号。日本来源与日版研究相关，但照片未把主板与明确的出厂批次标签或限定序列号绑定；不能定为用户主板，也不由较晚的发表日期断言所有后来机器都用该板。 |
| [Icom 日版 1.40 更新页](https://www.icom.co.jp/support/drivers/8603/) | 日版 `#31` 从厂商列出的序列区间起，装过 1.26 或更新后不能使用 1.24 或更早并保持正常音频；1.40 下的蓝牙版本也可随出厂时段为 1.12 或 2.01。 | 有官方批次区分，但 Icom 没在此给出 `#31` 对应的 PCB 丝印；不能把 `B-9913A` 与 `#31` 画等号，也不能以软件版本判同板。 |

验板时优先收集整机地区、主板丝印与具体修订、主控及存储器标识；背标批次和版本信息页只能分组。只报「日版 1.40」或只看到一样的 CPU 都不够。待匹配板的实物照片与 SQ6EMM 的在板读取经验是两份不同性质的证据；前者不证明可稳定读取。

本地取证：`.analysis/github-followup-1115/public-sources.json`（SHA-256 `0c67381176afe8cefa9f9fbc9291cbee79b43f038365e5953cd433990f254667`）保存三个 GitHub 比较的基点及提交差异、照片来源和摘要；另一个比对用文件 `early-wide-2.jpg` 的 SHA-256 为 `ccaca13126c8205b7f86df672e726bc26bd35db3811f2bfa6434bc04273335d4`。所取照片只存本地分析目录，项目只记录对照结果；未执行外部项目代码或连接电台。

## 下一项验收

后续已从公开照片找到日版 `B-8984H`，并确认 `B-9913A` 硬件确实有不同音频芯片；[日版批次与独立测试板筛选](IC705_BOARD_MATCH.md)记录当前证据和验收条件。

优先找能把日版整机批次和实际 PCB 丝印同时对上的公开维修资料，或有来源的独立测试板记录。当前有两种实际板号，缺出厂批次到主板的对应关系；仅有版本信息时先分组，不标为已匹配。本阶段只验来源和板版，不购买、拆开或操作用户的电台。若以后取得独立测试板且获单独授权，先按 [恢复验收表](SAFETY_AND_RECOVERY.md#独立恢复的验收项)核对主控 Flash、两颗 EEPROM 和其他受更新影响的数据范围，要求分两次独立读取、长度和 SHA-256 一致；备份留在本地。即使过了备份这一步，仍需证明该测试板在原厂主程序无法启动时可恢复、可冷启动且保留板级配置和校准。找不到同修订板、读不稳或不能恢复，就停在电脑验收。任何恢复结果也不替代日版专用、保留原厂发射行为的 CW 接入验证。
