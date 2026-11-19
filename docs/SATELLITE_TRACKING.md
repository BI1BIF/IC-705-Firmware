# 日版 IC-705：本机选星、GPS 和双向多普勒补偿

目标是从 **IC-705 本机菜单**选一颗卫星，使用内置 GPS 的位置和 UTC，加上该卫星的轨道数据，预测过境并分别修正下行接收、上行发射频率。收发切换沿用原厂 `SPLIT`：平时听下行，用户按手咪 PTT 时切到上行，松开后回到下行。第一版以 FM 卫星的跨段半双工为目标；按着 PTT 时，同一台 IC-705 不监听下行。

## 跨段收发的证据

| 来源及方法 | 核对结果与边界 |
| --- | --- |
| [Icom 日版产品规格](https://www.icom.co.jp/lineup/products/IC-705/)与《取扱説明書》A7577D-1J-8 纸面 3-1、4-11、20-1 页（PDF 第 25、45、174 页；[手册哈希](../research/SOURCES.md)） | 官方确认日版可在 144 MHz 和 430 MHz 两段收发，VFO A/B 可分别设频率和模式。日文手册把 Split 描述为同频段内的异频操作，用 14 MHz 示例，不能把它作为跨段的官方保证。 |
| JR6BUL 的 [IC-705 操作记录](https://note.com/ukigumo1104/n/nbef1fc4316f4)，2025-12-28；与 [ARISS 的中继资料](https://www.ariss.org/contact-the-iss.html)交叉核对 | 日本操作员记录同一台 IC-705 用 430 MHz 段听 ISS 下行，开启 `SPLIT` 后按 PTT 转到 144 MHz 段上行。上行截图显示 `TX`、`SPLIT`、145.990 MHz 及功率表。是实机操作证据，作者未注明机器地区代码；未测试用户这台日版。 |
| SM0TGU 的 [AMSAT-SM 操作记录](https://www.amsat.se/2021/01/01/working-satellites-with-ic-705-pstrotator-sdr-console/)和 [IC-705 频道表](https://www.amsat.se/2020/11/12/satellite-memory-file-for-ic-705/) | 作者报告单台 IC-705 半双工，PstRotator 可从外部调整收、发两边。频道表也配置了相反方向（如 PO-101 的 430 MHz 段发、144 MHz 段收）；频道配置支持设计判断，不能当作日版两方向的射频实测。 |

频道表复核：读取 [固定提交的 CSV](https://raw.githubusercontent.com/LarsThunberg/SatelliteConfigurationFiles/58a6f9a497767417058fe92a067f12d63f61a58a/IC-705_SatFrqMemGroup_commaseparated.csv)，13,801 字节，SHA-256 `3eee1855f36f20ba7ff8a86871a0dac4cda542b9d7e7a9d61421538f91866861`。用 Python `csv.DictReader` 筛出 `Split=ON`，按 `Frequency`（收）和 `Frequency(2)`（发）所属频段计数：89 条记录中 55 条跨段，27 条为 144 MHz 段发、430 MHz 段收，28 条为反向。包含同一卫星的多条预置，计数是频道数。此表只用于离线核对，不能作为当前卫星频率或在轨状态清单。

## 本机怎么用

1. 在本机打开「卫星跟踪」，从列表选一颗星和对应的转发器。用 NORAD 目录号匹配轨道数据；转发器另存上下行标称频率、各自模式和所需亚音。轨道数据可从 [CelesTrak GP](https://celestrak.org/NORAD/documentation/gp-data-formats.php) 获得，转发器参数核对运营方或 [AMSAT 数据库](https://satdb.amsat.org/)。研究通过 microSD 导入两份数据，不把联网作为使用前提。
2. 内置 GPS 提供观察者经纬度、高度和测位时间（日版手册 12-1、13-20 页）；以 UTC 和该卫星的轨道根数用 SGP4 计算过境、方位、仰角和距离变化。LCD 显示所选卫星、过境时段、定位与轨道数据状态、上下行频率及各自补偿量。GPS 定位本身不会给出所选业余卫星的轨道和转发器参数。
3. 用户确认开始后，接收期间更新两路频率，并核对实际收发角色、频率和 Split 状态。上行不得超出原厂发射范围。初版在 PTT 按住期间保持已设的上行频率，回到接收再继续更新；是否能在发射期间可靠连续微调，单独验证。补偿只负责修正频率，发射由手动 PTT 决定。
4. 卫星落到地平线以下、定位或 UTC 失效、轨道过期或用户手动接管时，停止自动改频并显示原因。若无法确认实际频率和 Split 状态，显示未就绪。退出跟踪后在接收状态恢复进入前的模式、频率和 Split 状态。

## 离线验收与原生门槛

[日版 1.40 原厂回放](IC705_GPS_INPUTS.md)已经验证本机 NMEA 到经纬度、UTC 及各自过期标志的链路。失去定位后，旧经纬度和 3D 状态仍可读取，必须独立检查实时定位及 UTC。原厂 RX 页距离是台站之间的地表距离；跟踪所选卫星需要从轨道和台址另算径向速度。[双 VFO/Split 回放](IC705_VFO_SPLIT.md)已验证 A/B 四组和两个跨段方向的逻辑角色：只有 Split 开启时，`25 01` 的未选频率才是本实验中的 `1C 03` 发射候选。[完整过境回放](IC705_SATELLITE_PASS.md)已串起这两条链路。

- 固定台址重放了 ISS 和 VANGUARD 1 的历史过境，核对仰角、升落时刻和两种跨段角色的上下行偏移。使用合成频率验证基本补偿；线性转发器的通带和反相跟踪另验。
- [PC 选星及状态页](IC705_SATELLITE_PANEL.md)已接入[J140 原厂双路调谐和回读](IC705_PTT_TUNING.md)。两笔之间拒写时停止并保留快照；模拟 PTT 中途触发则冻结，确认接收后才续调最新目标或恢复。原厂模式读写、PTT 完整链路和原生菜单尚需验证。
- [ic705controler](https://github.com/BH6AAP/ic705controler) 的 Android 项目可作为外部流程参考：作者描述了从列表选星、分别调整两路 VFO 和用户转动拨盘时让出控制。机内选星菜单、完整 PTT 状态生产链及真实收发仍需各自验证。
