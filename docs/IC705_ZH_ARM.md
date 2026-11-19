# 日版 1.40：用模拟器内的 ARM 代码加载中文词表

启动器现已升级为[六页显示设置与时间设置](IC705_ZH_CATALOG.md)。本页保存 62 帧的第一版对照和复现命令。

2026-11-13，Windows x64。双击 [Open-IC705-ARM-Preview.cmd](../Open-IC705-ARM-Preview.cmd)，走 `MENU → SET → セット 2/4 → ディスプレイ設定`。可查看第 1 页，以及背光编辑、两种屏幕保护的选项和 `[POWER]` 熄屏选项。已有的[中文预览](../Open-IC705-Chinese-Preview.cmd)保留作为 Python 对照。

这次用现有 Arm GNU Toolchain 为 Cortex-A9 编译了一个 1,036 字节的 C/汇编模块。宿主只映射代码、16 条 UTF-16 词表和已有的静态 TTF，并在四个已核对的渲染位置写入 **模拟 RAM 内**的跳转。`ChineseLabel` 的 Python 替换钩子没有实例化。中文匹配、文字长度、字库选择与还原均在模拟 ARM 上执行；ARM 初始化函数调用原厂 `0x20197410` 打开内存字库。原厂仍决定触摸命中、设置值、文字宽度和绘制位置。原厂模式和编辑器路径见 [REA 证据](REA_ANALYSIS.md#j140-亮度编辑器与-arm-词表实验)；控制含义对照 [Icom 基础手册](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)。

| 验证 | 结果 |
| --- | --- |
| 背光编辑 | 原厂菜单 `286`、项目 `0x8C`，绘制模式 `15` 经 `0x20159854`。从受控初值 49% 点「＋／－」显示 `49 → 50 → 49%`。再切换自动与手动、返回列表；两种实现的模拟 RAM 写入和值一致。自动模式无环境光输入，回到手动后读到 0%，不能据此判断真机恢复策略。 |
| 屏幕保护、熄屏选项 | 用原厂选项页选择电池 5 分钟、外部供电 60 分钟和「开启」，返回后在相应行显示。验证了电源选择页以及两个保护时间页的已译选项与页码。 |
| 语言及像素 | 62 帧 ARM 中文与 Python 中文 PNG 逐字节一致；空词表 ARM 和原厂对照也逐字节一致。有效词表有 168 次配对的文字／字库切换与还原，空词表为零。相对原厂，10 帧是目标列表、9 帧是目标子页、6 帧是原有的「显示语言」，其余 37 帧相同。英语切换仍由原厂处理，「系统语言」选择页及偏好保持原样。 |

两次独立编译的模块逐字节一致（SHA-256 `3c19862b07da9607284d33f7ce9aa8d328c35fb6966746b00d79245f0c7e6c16`）。Windows Tk 的首页和定时选项页与回放像素一致；原版面板的 25 帧基准与 JSON 不变，36 项项目测试通过。

四处跳转只存在于模拟器每次创建的 RAM 中。模块与词表尚无原厂持久加载入口，不具备第三语言选项，也没有验证整机冷启动。未生成可刷写文件，未访问电台；原厂 DAT 的 SHA-256 仍是 `2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45`。

## 复现

复用 [J140 字库](IC705_ZH_DISPLAY_PAGE.md#复跑)和本机 `arm-none-eabi-gcc`、`objcopy`、`nm`。执行目录为项目根目录：

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
$root = '.analysis/ic705-emulator'
$font = '.analysis/zh-cn-preview/display-page/IC705LabSC-Regular.ttf'
py -3.14 -X utf8 -m tools.virtual_705_panel firmware/705J140.dat --display-check --panel-replay "$root/j140-stock-flow"
py -3.14 -X utf8 -m tools.virtual_705_panel firmware/705J140.dat --display-check --panel-replay "$root/j140-zh-flow" --zh-font $font
py -3.14 -X utf8 -m tools.virtual_705_panel firmware/705J140.dat --display-check --panel-replay "$root/j140-arm-flow" --zh-font $font --arm-zh "$root/display-arm-build"
@'
from pathlib import Path
from tools.arm_705_display import build
from tools.virtual_705_panel import load, touch_replay
root = Path(".analysis/ic705-emulator")
font = Path(".analysis/zh-cn-preview/display-page/IC705LabSC-Regular.ttf").read_bytes()
touch_replay(load(Path("firmware/705J140.dat").read_bytes()), root/"j140-empty-arm-flow",
             front_panel=True, zh_font=font, display_check=True,
             arm_build=build(root/"display-arm-build-control"), arm_table=bytes(4))
'@ | py -3.14 -X utf8 -
py -3.14 -X utf8 -m tools.compare_705_display_preview "$root/j140-stock-flow" "$root/j140-zh-flow" --arm "$root/j140-arm-flow" --empty-table "$root/j140-empty-arm-flow"
```

查看 ARM 输出目录的 `brightness-plus.png`、`external-picker-next.png`、`power-on.png`、`english-display-page1.png` 和 `trace.json`。

## 首轮盘点

从同一套原厂重放中已经盘点到第 2–5 页的 16 条设置。先按下面的覆盖点补齐选项；当前画面只证明这些值出现过，不能当成完整选项表。

| 页面 | 原厂重放中实际出现的覆盖点 |
| --- | --- |
| 2/6 | 接收 LED、仪表峰值保持、存储名称、组名称弹出；观察到共用 `OFF`。 |
| 3/6 | 接收呼号、位置指示、位置显示和显示时间；除了开关，还出现 `5秒`，应单独校验数字和单位。 |
| 4/6 | 自动应答位置、接收图像指示、DV 接收背光、发射呼号显示；观察到共用 `OFF`。 |
| 5/6 | 滚动速度、开机消息、开机检查、显示单位；观察到枚举 `遅い`，显示单位是下一层菜单。 |
| 6/6 | 沿用「显示语言」实验；「系统语言」继续作为独立的回归对照。 |

这些选项和第二设置组的结果见[六页回放](IC705_ZH_CATALOG.md)。原厂资源表或初始化调用方能否承接模块仍是独立问题。
