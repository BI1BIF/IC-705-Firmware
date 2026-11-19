# 日版 IC-705：DAT 组件归属复核

2026-11-13。对照九个官方 705J DAT 的 A/C/D 载荷与 Icom 各发布页的组件版本。**D 是 WLAN 载荷的强候选，A 与主程序关联，C 与 DSP 有关，但不能只归为 DV DSP。** 本轮重新计算九包的 SHA-256 和各组 MD5，核验 B 的零占位；三个 E 版只用来核对头字段和同版组内容。没有修改原厂文件。

## 九版对照

“变化组”是按各版 MD5 边界对齐后，SHA-256 不同的载荷组。Main CPU 版本与发布版本一致；表中 WLAN 用末段缩写，完整值见下文。没有纳入硬件批次不同的蓝牙版本。
相邻指本项目取得的样本，未取得 1.12，不能进一步确定 1.11→1.20 期间首次出现变化的实际发布版本。

| 日版 | DSP Program | DV DSP | WLAN（末段） | 相对前一行的变化组 |
| --- | --- | --- | --- | --- |
| [1.11](https://www.icom.co.jp/support/drivers/5612/) | 1.09 | 1.02 | 3.11.1.0 | 基线 |
| [1.20](https://www.icom.co.jp/support/drivers/6128/) | 1.10 | 1.02 | 3.17.0.4 | A、C、D |
| [1.24](https://www.icom.co.jp/support/drivers/6192/) | 1.10 | 1.02 | 3.17.0.4 | A |
| [1.26](https://www.icom.co.jp/support/drivers/6435/) | 1.11 | 1.02 | 3.17.0.4 | A、C |
| [1.27](https://www.icom.co.jp/support/drivers/6845/) | 1.11 | 1.02 | 3.17.0.4 | A |
| [1.30](https://www.icom.co.jp/support/drivers/7010/) | 1.12 | 1.10 | 3.17.0.4 | A、C |
| [1.31](https://www.icom.co.jp/support/drivers/7024/) | 1.12 | 1.10 | 3.17.0.4 | A |
| [1.32](https://www.icom.co.jp/support/drivers/7074/) | 1.12 | 1.11 | 3.17.0.4 | A、C |
| [1.40](https://www.icom.co.jp/support/drivers/8603/) | 1.12 | 1.11 | 3.17.0.4 | A |

- **A：确认包含主 CPU 程序。** 八次相邻对照都变，四次只有 A 组变化。三份样本已提取出 A 前段的引导和主程序，且以启动反汇编验证装载，见[主程序报告](MAIN_CPU_DECODE.md)。A 的其余内容未在该实验解码。
- **C：DSP 相关载荷，处理器归属未定。** 1.20→1.24 是阴性对照；1.24→1.26 的两项 DSP 程序版本中，只有 DSP Program 改变，DV DSP 不变；1.31→1.32 则反过来。两次 C 均改变。这个结果修正了仅从后期版本得出的“C 优先归 DV DSP”判断；尚不能判断组内是否含多个处理器的数据，或变化是否由其他关联数据造成。
- **D：WLAN 相关载荷，强候选。** 唯一的变化是 1.11→1.20：公告 WLAN 从 `2.0.0.0_2.2.0.6_3.11.1.0` 变为 `2.0.0.0_2.2.0.7_3.17.0.4`，D 的长度从 549,081 增到 583,010 字节；其后八个日版的 D 逐字节相同。两种 D 的 SHA-256 分别为 `94306f9850c322ea200ef2b952eca8c270fd1424afc2fdeb3e7c854fee3d7d2a` 和 `e59a6a6ba2f91e4d4f7c5920bcf88f39fc66602b34c9f2620bf7e47733bb5e42`。TI 的 [SimpleLink CC3120/CC3220 发布说明](https://software-dl.ti.com/ecs/SIMPLELINK_CC32XX_SDK/4_20_00_07/exports/tools/cc32xx_tools/servicepack-cc3x20/README.html)使用相同形式的 MAC/PHY/NWP 版本号，MAC、PHY 两项和 Icom 后一组相符，NWP 不完全相同。这是器件家族候选，不能据此锁定板上型号或包内格式。

## 能独立核验的头字段

用现有 `layout` 核验所存长度、各组摘要和整包长度。相邻 32 位小端字段的实测值如下；它们出现在每个有效样本中。Icom 没有公布语义，尚未用实际解包结果验证它们代表输出尺寸。

| 所存长度字段 | 相邻字段 | 九个 J 版 | 三个 E 版 |
| --- | --- | --- | --- |
| `0x44`（B1） | `0x48` | 0 | 896 |
| `0x4C`（B2） | `0x50` | 0 | 65,536 |
| `0x54`（C） | `0x58` | 2,097,152 | 2,097,152 |
| `0x5C`（D） | `0x60` | 1.11 为 4,187,352；其余为 4,188,200 | 4,188,200 |

SQ6EMM 的公开研究给出 A 组内部的布局。我们在两份日版、一份 E 版中独立复现：文件 `0x10064` 为编码后的长度头，`0x1006C` 为压缩流；引导解压并跳入 `0x20005000`，主程序向量再跳到 `0x20005060`。这验证 A 前段及主程序，不能外推上表的 B/C/D 解码长度、设备级验签或完整 Flash 分区。

## 复现

```powershell
$py = '.\.venv\Scripts\python.exe'
Get-ChildItem -Path firmware/705J*.dat,firmware/705E*.dat | Sort-Object Name | ForEach-Object {
    $p = $_
    $j = & $py tools/firmware_scan.py layout $p.FullName | ConvertFrom-Json
    if (-not $j.all_records_valid) { throw "Invalid envelope: $($p.Name)" }
    [pscustomobject]@{
        File = $p.Name; SHA256 = $j.sha256
        GroupHashes = ($j.groups.sha256 -join ',')
        SizeNeighbors = ($j.size_pairs.neighbor_value -join ',')
    }
}
```

将 SHA-256 与 [Icom 下载来源清单](../research/705j-provenance.json)比对。REA Windows MCP 用 `inspect_byte_entropy` 独立确认 J111/J120 的 DAT 哈希，Evidence `ev_b9d5a10fd859de80c86c6d4652ab87fba8f7c0acb09458c8d3265d847d6356ab`、`ev_bb8c5f20c39cafcf0a3717db1e674959193af63a411421d9a2b43b4a20edac09`。熵调用用于独立确认输入身份，组件归属依据是字节哈希与公告版本的对照。
