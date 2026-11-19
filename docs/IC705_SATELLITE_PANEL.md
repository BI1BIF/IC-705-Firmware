# IC-705 卫星跟踪：PC 选星与控制流程

双击项目根目录的 [Open-IC705-Satellite.cmd](../Open-IC705-Satellite.cmd)。Windows 选星页现在默认使用**日版 1.40 原厂 ARM 调谐和回读**，通过 Unicorn 在电脑来宾内存内运行。现有工作区已生成两份历史回放，并有本地日版 `705J140.dat` 和 Unicorn；新检出项目的复现方式见下方。

1. 选 ISS 或 VANGUARD 1，再选 A/B 收发方向。窗内时间都是历史 UTC，频率来自合成的跨段测试样本。拖动时间条或点「播放回放」。启用前，建议 RX/TX 可以变化，当前 VFO 保持原样。
2. 点「启用补偿」。在地平线下等待，进入可见范围后才调谐。勾上「模拟按住 PTT」，时间条与建议值继续变化，A/B 冻结。只有请求解除、原厂状态回读是接收、且定位与 UTC 有效时，才会继续采用当前最新采样。
3. 点「手动接管」后可点「手动 +1 kHz」。时间往前走也不会覆盖手动频率。点「退出并恢复」或关闭窗口，恢复进入时的 A/B、所选 VFO、Split 和桌面的模式标签。若 PTT 请求还在、状态仍为发射或状态未知，等确认接收再恢复。
4. 「模拟操作与失效注入」可以分别让定位或 UTC 失效、调谐被拒或读回不同。选择「第二路被原厂拒绝」时，第一笔会写入，第二笔由原厂校验拒绝；界面保留部分生效的读数，停止跟踪，保存原快照供退出恢复。选择「两路之间按下 PTT」时，第一笔完成后冻结；取消「模拟按住 PTT」仍不会改频，直到取消「模拟发射状态输入」，让原厂状态读端返回接收。若先点了退出，就只恢复快照。

## 证据和边界

界面直接读[两份 J140 历史过境](IC705_SATELLITE_PASS.md)：原厂 GPS/UTC、过境高度、两种 Split 角色的目标频率及分别过期的测试样本。启动核对回放标识、本地 DAT 和主程序 SHA-256。后端复用[原厂 ARM 调谐实验](IC705_PTT_TUNING.md)：使用原厂 A/B 选择、Split、频率设置与读回函数。写每一路前检查请求和收发状态，写后读回该路、另一路和发射候选，再决定下一步。第二路拒绝使用 300 MHz 接收分类反例，由原厂代码返回 `FA`。PTT 试验只把独立请求和合成状态信号送入桌面控制器及来宾 RAM；原厂程序读取状态，但没有执行完整 PTT 转换。

| 观察 | Windows 验收 |
| --- | --- |
| 预览与选星 | ISS 显示建议值，无调谐；切换 VANGUARD 1 验证反方向。 |
| 第二路被拒绝 | A、B 两方向均实测 `FB → FA`。首笔保留、第二路不变；继续时间轴不写频，退出恢复完整快照。 |
| 第一笔后出现 PTT | 两方向都只执行第一笔。请求松开但状态仍为发射时，保持部分生效的读数；B 方向确认接收后直接应用当前采样，A 方向先请求退出后仅恢复快照。 |
| 定位与 UTC 独立失效 | 各自单独失效都无目标写入，恢复有效后继续。落到地平线下也停止补偿。 |
| 手动接管及退出 | 手动值保留至退出；退出和关闭窗口能恢复初始频率、所选 VFO、Split 和桌面模式标签。 |
| 回读不一致 | 原厂接受但读回与期望不符时停更；恢复失败没有丢快照。状态未知也不能触发恢复。 |

原厂后端通过 32 个 Tk 检查点，桌面纯模拟后端通过 20 个检查点，项目测试 49 项通过。例如 VANGUARD 1 的 B 方向：2000-06-28 12:40:40 UTC 第一笔后，A/B 为 145.500000 / 436.856853 MHz；推进至 12:41:20、请求松开但状态仍为发射，读数不变。确认接收后才写入该时刻的 145.897829 / 436.856500 MHz（两笔均为 `FB`）。ISS 的 A 方向在同类中断下请求退出，确认接收后只恢复进入前的 145.500000 / 433.500000 MHz。逐笔记录见本机 `.analysis/satellite-panel/j140-arm/trace.json`，两次独立回放的 SHA-256 均为 `0e836a094f77297cbc6509bd4e0e05827bf1b4ef915d8515a4e61a10bc19359b`，截图在 `.analysis/satellite-panel/j140-arm-repeat/`。

原厂代码执行的是频率、A/B、Split 和状态读端；模式仅为桌面标签，菜单界面也仍是 Tk。没有串口、网口或射频传输路径，不生成固件。下一次应优先验证原厂接收模式的设置和回读是否能与 A/B 各自绑定并恢复，再挑选原生菜单切入点。

## 复跑

如果已有默认 JSON，直接启动窗口。否则按[过境回放依赖设置](IC705_SATELLITE_PASS.md#复现)准备环境，再从项目根目录生成这两个文件：

```powershell
py -3.14 -X utf8 -m tools.replay_705_satellite_pass firmware/705J140.dat .analysis/satellite-pass/iss-release.json --satellite 25544
py -3.14 -X utf8 -m tools.replay_705_satellite_pass firmware/705J140.dat .analysis/satellite-pass/vanguard-release.json --satellite 00005
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.virtual_705_satellite
```

如只想预览已有 JSON，可加 `--virtual`，这时不需要 DAT 或 Unicorn。下列检查驱动实际 Tk 控件。输出目录必须是新的；需要窗口截图时可加 `--screenshots`（Pillow）。

```powershell
py -3.14 -X utf8 -m tools.check_705_satellite_panel .analysis/satellite-panel/recheck --arm
py -3.14 -X utf8 -m unittest discover -s tests -p test_satellite_panel.py
```

