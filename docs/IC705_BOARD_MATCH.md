# 日版 IC-705：批次辨认与独立测试板筛选

核查：2026-11-15。**找到一台有明确日版来源的 `B-8984H MAIN` 实物，也确认另一块 `B-9913A MAIN-A` 换了音频芯片。** Icom 日版更新页给出了音频兼容批次，但现有公开证据不能把该批次直接对应到 `B-9913A`，也没有足够证据确认用户手里的主板。这里的结果用于筛选独立测试板，不属于备份、恢复或刷写验收。

## 看得见的硬件差异

| 样本 | 本轮查到的证据 | 判定 |
| --- | --- | --- |
| 2020 年末购买、自述为日本国内规格的个人样机 | [作者记录](https://ameblo.jp/hdmbe117/entry-12653790269.html)同页的[全景](https://stat.ameba.jp/user_images/20210131/23/hdmbe117/cb/37/p/o0800060014889629092.png)可读 `B-8984H MAIN`；[近照](https://stat.ameba.jp/user_images/20210131/23/hdmbe117/12/3d/p/o0800059414889641326.png)是同一 CPU 标记的电路，CPU 左侧两颗芯片可辨 `4951A`。[AKM 数据手册](https://www.allelcoelec.com/datasheets.5c/AK4951AEN.pdf)第 103 页确认该顶标。 | 对这台公开样机是日版、板号为 H、使用早期音频器件的判断可信度较高；原文未提供把该板和 `#31` 绑定的背标或维修单。 |
| 2020 年 RadioChief 的另一块板 | [板号全景](https://radiochief.ru/wp-content/uploads/2020/10/ICOM_IC705_2_1.jpg)为 `B-8984F MAIN`；[音频芯片近照](https://radiochief.ru/wp-content/uploads/2020/10/ICOM_IC705_3_1.jpg)同样有两颗 `4951A`；[Flash 近照](https://radiochief.ru/wp-content/uploads/2020/10/ICOM_IC705_4_1.jpg)可读 `IS25LP128`。 | 实物可确认是 F，市场和批次未确认。F、H 的可见音频芯片相同，板号仍然不同。 |
| 2025 年 2 月日本作者发表的另一块主板 | [作者记录](https://yesterdays.jp/ic-705-usb-c/)的[原尺寸照片](https://yesterdays.jp/wp-content/uploads/2025/02/9329-4-1.jpg)同一张可读 `B-9913A MAIN-A`、`R7S721001VC` 和两颗 `AC3105I`；[TI 器件标记](https://www.ti.com/quality-reliability-packaging-download/ja-jp/report?opn=TLV320AIC3105IRHBT)确认 `AC3105I` 对应 `TLV320AIC3105`。CPU 旁可见八脚存储芯片，照片上 `IS25LP` 可辨，但余下料号有遮挡，不能用照片确认容量或完整料号。 | 该板与 F、H 的音频芯片确实不同；作者发表时间不等于出厂时间。未见这台整机的批次背标、两颗 EEPROM 标记或恢复记录。 |
| Icom 2021 年 5 月出口版维修补页 | [原厂维修手册的公开副本](https://www.passion-radio.com/index.php?controller=attachment&id_attachment=787)，PDF 第 24、26、28 页将不同出口批次对应到 `B-8984I/J/K`；第 41、49 页的 `MAIN UNIT (2/8)` 分别标出 `AK4951AEN`、`TLV320AIC3105`，后者明确适用 `#32/#33/#36/#37`。 | 官方图纸证实出口版有音频电路换型，且同一种音频芯片可以装在不同板号上。图纸没有给日版 `#31` 的对应关系，也不能据以把 `B-8984K` 当成 `B-9913A`。 |

另外核对了 [日版《规格变更通知》](https://www.icom.co.jp/support/manual/5441/) 的 18 页目录和可提取文字。它说明各版用户功能与菜单变化，没有找到制造批次到主板的表。2023 年的[另一组拆机实拍](https://teeart.blog107.fc2.com/blog-entry-809.html)只能读出 `B-8984`，尾字被遮挡；未计为新的板号证据。

## 原厂包实测：相同引导不等于可以回退

[Icom 日本 2021 年 7 月 9 日发布的 1.26](https://www.icom.co.jp/support/drivers/6435/)首次在本次核实的版本里明确说明：日版 `#31` 从 `31001001` 起，已安装 1.26 或更新版本的设备若退到 1.24 或更早，音频将不正常。[日版 1.40 下载页](https://www.icom.co.jp/support/drivers/8603/)仍保留同一条说明。这个条件能用机身标贴筛出明确受该提示约束的机器。它不提供板号；不在明示范围内也不代表已证明可安全回退。1.40 页列出两个出厂蓝牙版本，不能将其当成音频芯片版号。

只在内存中解析了三份原厂日版 DAT，四组记录检查全部通过。三份 **65,536 字节引导逐字节相同**，SHA-256 `8c55e7f49477985f994e79d83b111048ace533bfacce70a62ef80a6543d732db`。1.24 到 1.26 变化的是 A（主程序所在）和 C（已有对照关联 DSP Program）；B 仍空，D 内容相同。原厂版本表对应为 DSP Program `1.10 → 1.11`。这是可重现的版本差异，尚未定位日版音频芯片选择逻辑，也没有证明兼容变化来自 A 或 C 中的某一项。

| 日版原件 | 解压后主程序字节数 | 文件来源 |
| --- | ---: | --- |
| `705J124.dat` | 3,570,044 | [Icom 1.24](https://www.icom.co.jp/support/drivers/6192/) |
| `705J126.dat` | 3,575,800 | [Icom 1.26](https://www.icom.co.jp/support/drivers/6435/) |
| `705J140.dat` | 3,558,076 | [Icom 1.40](https://www.icom.co.jp/support/drivers/8603/) |

复验：根目录使用已有解析器，只读取原件并计算摘要，不保存可执行镜像。

```powershell
@'
from hashlib import sha256
from pathlib import Path
from tools.decode_705_main import decode_main
from tools.firmware_scan import layout

bootstraps = []
for version in (124, 126, 140):
    raw = Path(f"firmware/705J{version}.dat").read_bytes()
    boot, main, _ = decode_main(raw)
    bootstraps.append(boot)
    groups = layout(raw)["groups"]
    print(version, sha256(boot).hexdigest(), len(main),
          [(g["name"], g["sha256"]) for g in groups])
assert bootstraps[0] == bootstraps[1] == bootstraps[2]
'@ | py -3.14 -X utf8 -
```

## 用于验收的两步

1. **用户机器分组已完成。**电池仓背标照片明确为 IC-705，序列前缀 `41`，日本技适号 `002-200086`。[Icom 技适目录](https://www.icom.co.jp/support/personal/giteki/)将该号列为 2021 年 3 月认证；此日期不用于推定单机生产日期。[日本经销商](https://www.chutoku.com/shopdetail/000000006170/)确实用 `#41` 区分在售版本，与前缀相符。项目筛选记为「日版，41 系列」。只记前缀和技适号，完整序列号、条码及原照片不进项目。预期中的 `31` 前缀与实机不同，[Icom 日版 1.40](https://www.icom.co.jp/support/drivers/8603/)的降级说明只明示 `#31`，未看到对 `#41` 的公开兼容结论；不要把数字上的大小关系当作公告涵盖 `#41` 的证据，也不要用本机做降级试验。
2. **按「日版、41 前缀、`002-200086`」筛独立候选。**同机需有可遮盖尾号的背标或维修记录、清楚的主板丝印、音频芯片标记、NOR 和两颗 EEPROM 的料号及板位。当前公开照片和维修资料尚未把 `#41` 与 `B-9913A` 或某个 `B-8984` 修订绑定；经销商页面仅证实零售称呼，并未证明板号。没有板件记录时，同组测试机只能作为候选，结果只适用于验过的那块板。需要记录软件基线时，用日版说明书印刷页 16-1 的 `SET → その他 → 本体情報 → バージョン情報` 查看实际固件、DSP 和蓝牙版本；这些显示值不直接认定主板修订。

当前未确认同修订测试板，没有可交付刷机包。下一道验收是独立测试板的原板备份与[断开原厂主程序后的独立恢复](SAFETY_AND_RECOVERY.md#独立恢复的验收项)；这与电脑上已验证的 CW 接收和冷启动分开判断。未经另行授权，本记录不涉及购买、读取实体存储、拆机或写入。

取证文件均留在本地：`.analysis/japan-board-match-1115/stock-version-compare.json`（SHA-256 `abbb9742d761bff22ebb114173566a26b57fd384fea4a880f43d66cb183ee498`）、同目录 `photo-survey.json`（`99cf85763f4245a9016e1aa41bb5cb3191fbb3ceb07f3bbcb6779227f0120319`，含原图 URL 和哈希）及 `jpn-2021-silk.png`、`later-codec-bottom.png`（从原图取局部，最近邻放大）。`B-9913A` 原图 SHA-256 `d5d06a1a2c9cbc31c358d2e757232f140d3099b7d2720ba2535cfea83f18b052`，已列入[上一轮照片清单](IC705_THIRD_PARTY_PRECEDENT.md#两份实物照片给出不同主板标识)。
