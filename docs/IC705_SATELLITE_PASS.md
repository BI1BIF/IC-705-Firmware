# 日版 1.40：离线选星与整次卫星过境回放

2026-11-14。PC 已跑通「从离线列表选星 → 用日版 1.40 原厂 GPS 例程取得经纬度和 UTC → 预测升起、最高点和落下 → 根据原厂 Split 回读计算双向多普勒」。两个历史案例均从地平线以下开始和结束。分别让原厂定位和 UTC 过期时，下一次计算立即不再给出频率；数据重新有效后恢复。实验不连接电台，不向电台发指令，不修改原厂包。

| 回放（UTC） | 几何升起 | 最高点（仰角） | 几何落下 | 与 Skyfield 最大时差 | 两路目标频率最大差 |
| --- | --- | --- | --- | --- | --- |
| ISS，2014-01-23 | 11:14:17.324 | 11:19:17.862（19.165°） | 11:24:17.792 | 0.060 s | 1 Hz |
| VANGUARD 1，2000-06-28 | 12:40:12.441 | 12:49:40.362（31.936°） | 13:06:53.613 | 0.123 s | 1 Hz |

60 和 116 个采样点分别核对；每 20 秒采样，并补测升落边界两侧与最高点附近。最大仰角差分别约 0.00070° 和 0.00116°，径向速度最大差约 0.279 和 0.529 m/s。表中小数是程序输出，差值衡量两个模型的一致性；没有与真实卫星遥测或射频对照。几何地平线用 0°，未计地形、天线或折射。

## 原厂输入、频率角色及失效对照

- [离线样本](../samples/satellite-pass.json)用 NORAD 字符串选择两个历史对象。ISS 轨道和观察点取自 [Skyfield 文档](https://rhodesmill.org/skyfield/earth-satellites.html)，VANGUARD 1 取自 [Vallado 论文及验证包](https://celestrak.org/publications/AIAA/2006-6753/)中的 `SGP4-VER.TLE` 和 `tcppver.out`。台址是 Bluffton, Ohio（40.8939°N、83.8917°W），椭球高度由样本固定为 0 m。TLE 行号、目录号与校验和先验证；距历元超过 7 日是本工具的拒绝策略。没有查询当前轨道或转发器。
- 合成 RMC 与 ZDA 逐字节输入[原厂 J140 GPS](IC705_GPS_INPUTS.md)。程序从原厂 getter 取坐标、两位年份和秒级 UTC；在历史样本内解释为 2000–2099 年。两种过期试验均只把对应倒计时置零，再跑原厂过期函数；定位过期时旧坐标仍在，UTC 过期时定位仍有效。两次都不生成频率，重喂有效 NMEA 后恢复原有结果。未验证实际计时节拍、高度基准、并发更新时的一致读法。
- 读取[原厂 VFO/Split 回放](IC705_VFO_SPLIT.md)的 `03` / `25 00` 接收频率、`0F` Split 和 `1C 03` 发射候选，两套角色分别计算。VFO 使用合成的 145.900 和 436.850 MHz，**不是这两颗卫星的转发器参数**。Split 关闭、模拟非接收状态或几何地平线以下都无新目标。非接收状态在计算器入口注入，尚未由原厂 PTT 状态机产生。

以 ISS 回放的两个边界内采样为例，表中是拟议的地面频率修正：

| 原厂 Split 角色 | 11:14:19 UTC，接近：RX / TX | 11:24:15 UTC，远离：RX / TX |
| --- | ---: | ---: |
| 145 MHz 段接收、430 MHz 段发射候选 | +3015 / −9028 Hz | −3017 / +9032 Hz |
| 430 MHz 段接收、145 MHz 段发射候选 | +9028 / −3015 Hz | −9032 / +3017 Hz |

轨道核心使用 SGP4；桌面实现用 WGS84 台址、恒星时旋转和中心差分算径向速度，Skyfield 独立算地平线事件和径向速度，两者共用 SGP4 核心。另用 Vallado 的独立发布向量核对该核心。近似中 UTC 代替 UT1、不建模极移。距离缩短时 RX 调高、TX 预补偿调低；距离增加时反向。VANGUARD 1 的另一个低仰角样本在落下前仍接近，单元测试固定了这个反例；不能根据升落或仰角变化决定补偿正负。

[REA](REA_ANALYSIS.md#j140-卫星过境回放的原厂字节证据)锁定主程序和输入例程窗口；Unicorn 在 PC 分别执行未修改的原厂 ARM 片段。轨道预测、状态门控和补偿是桌面代码。置信度高，限上述回放条件；原生选星页面、真机调谐和跨段发射均待验证。

## 复现

在项目根目录用 Python 3.14；Unicorn 已安装时跳过第一行。生成结果须用新文件名。首次安装依赖后，计算过程可断网运行。

```powershell
py -3.14 -m pip install --only-binary=:all: --target .analysis/ic705-emulator/deps unicorn==2.1.4
py -3.14 -m pip install --only-binary=:all: --target .analysis/satellite-pass/deps -r requirements-satellite.txt
$env:PYTHONPATH = @((Resolve-Path .analysis/ic705-emulator/deps).Path, (Resolve-Path .analysis/satellite-pass/deps).Path) -join [IO.Path]::PathSeparator
py -3.14 -X utf8 -m tools.replay_705_satellite_pass --list
py -3.14 -X utf8 -m tools.replay_705_satellite_pass firmware/705J140.dat .analysis/satellite-pass/iss-local.json --satellite 25544
py -3.14 -X utf8 -m tools.replay_705_satellite_pass firmware/705J140.dat .analysis/satellite-pass/vanguard-local.json --satellite 00005
py -3.14 -X utf8 -m unittest discover -s tests
```

工具先核对原厂 DAT 和解包主程序 SHA-256。JSON 留在忽略目录，记录每条 NMEA、原厂状态、CI-V 回读、目标频率、参考数据和控制样本。验收阈值为时刻 1 秒、仰角 0.01°、斜距 100 m、径向速度 2 m/s 和频率 3 Hz。原 GPS 工具重跑的 JSON 与之前的基线逐字节相同；项目 41 项测试通过，涵盖 Vallado 位置/速度向量、选星、坏 TLE、过期和掠过地平线。

本机证据目录为 `.analysis/satellite-pass/`，其中 `iss-pass.png` 是 ISS 仰角和其中一组跨段补偿的曲线。两次独立生成的 ISS JSON 逐字节一致：

| 文件 | SHA-256 |
| --- | --- |
| `iss-release.json` / `iss-release-repeat.json` | `d20e74234473b58a0c91ff40f57a447526b3c68549f7dad2e48ee4b0586eb4ac` |
| `vanguard-release.json` | `1a2623c6fb6f31311aa7afb602ff0962e56a7386e7bc71d913ecd4e4c0bf99b9` |

[PC 选星及状态页](IC705_SATELLITE_PANEL.md)现已接入回放，使用虚拟 VFO 验证了预览、启用、PTT 冻结、松开恢复、手动接管和退出恢复。原生固件接入独立验收。
