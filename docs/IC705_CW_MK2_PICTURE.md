# IC‑7300MK2 的 CW 对照与 IC‑705 Picture 复用

更新：2026-11-16。当前只推进机内 CW；SSTV 和整机汉化保留已有研究。

## 原厂先例：IC-7110 把 MK2 解码器放进 705 风格界面

[Icom 日本公告](https://www.icom.co.jp/news/8997/)明确称 IC-7110 是 IC-7100 的后继型号；[Icom UK](https://icomuk.co.uk/Unveiled-Tokyo-Ham-Fair-2026-Introducing-the-New-Icom-IC-7110/2/5662/)称其采用 IC-705 风格界面。[IC-7110 原厂预览手册](https://icomuk.co.uk/files/icom/PDF/newsFile/IC-7110_pre_EN_A4_web.pdf)第 2 页明确写明沿用 IC-7300MK2 的 CW 解码器，原厂图上左侧是译文，右边先是绿色信号振幅波形，再是蓝色频谱/瀑布，另显示解码速度。Icom 已证明功能能跨机型复用；无法据此判定两个型号使用同一份二进制，也不能据此判定 IC-705 的兼容性。截至 2026-11-16 复查仍未找到 IC-7110 官方公开固件；[11 月 15 日的大阪活动](https://www.icom.co.jp/news/9073/)被 Icom 称为上市前演示，[11 月 11 日公告](https://www.icom.co.jp/news/9074/)列出 12 月 5 日实机展示。现阶段用 IC-7110 原厂资料作界面参考，用 IC-7300MK2 官方包作二进制对照。

| 原厂做法 | 日版 705 首版取舍 |
| --- | --- |
| MK2 在 CW 模式的 `MENU → KEYER/DECODE → CW DECODE`；还可设置短按直达、长按选择。 | [705 单入口实验](IC705_CW_RELEASE.md#复用原厂-keyer-做成-mk2-式单入口)沿用 CW/CW-R 的原厂 `KEYER` 图标及原厂选择框，短点先选择 KEYER 或 CW DECODE，仍用机身 `EXIT`。 |
| 原厂上半保留电台主屏，解码标题居中且右侧显示模式和 WPM。下半左侧绿色接收译文，右侧绿色连续信号振幅曲线，旁边是独立的频谱和瀑布。 | 以原厂 480×272 分区作为参考；左栏为绿色译文，右侧用同一接收 PCM 产生[连续波形和音频频谱/瀑布](IC705_CW_DISPLAY.md#原厂底栏冻结译文和右侧双窗)。MK2 的绿色线是信号电平，705 此处显示用户要求的连续有符号音频；用真实频率样本验证两列。 |
| MK2 在 `ADJ → SPEED` 或点速度区域时调整 `AUTO`、`LOCK`、`MANUAL`。`AUTO` 跟随来报；`LOCK` 保持有效估速；`MANUAL` 用电键的 `KEY SPEED`。`FILTER` 和 `THRESH` 是独立调整项。 | 电脑已验收[三档速度和原厂测速联动](IC705_CW_DISPLAY.md#自动估速与锁速)、[定频和门限](IC705_CW_DISPLAY.md#adj频率和门限)，以及[自动跟音](IC705_CW_DISPLAY.md#auto-跟音与-fix-对照)。默认 `WIDE` 仍保留旧检测；速度 `MANUAL` 读 705 的电键报速，不改 KEYER。 |
| MK2 下排有翻页、`HOLD/CLR`（短按冻结/继续显示、长按清屏）、日语系统下的 `和文`、`TX MEM`、`SET`。正文还区分本机发出的电码。 | 复用 705 原厂 RTTY 按钮素材；保留冻结、清屏、翻页、速度调整、[SET 接收配色](IC705_CW_DISPLAY.md#set接收显示配色)和机身 EXIT。`TX MEM` 保持灰字。按用户要求不移植和文，第 1 页原位置留空。 |

原厂 480×272 截图来自英文高级手册第 2-12 页内嵌图，保存在本地忽略目录 `.analysis/mk2-cw-layout-reference/mk2-cw-decode-original-480x272.png`（SHA-256 `7f781ab7b9c578b9f8651ebc9a53cd3153c4d8a489f301f896c90b6c8db72912`）。可对照 `.analysis/cw-mk2-layout-final-1115/02a-speed-chooser.png`。前者为 Icom 原图，后者为日版 1.40 仿真结果。

## 原厂解码可借鉴什么

**原厂收音的边界（2026-11-16）。** 由 Icom 基本手册能确认 MK2 的 DSP 解码；高级手册给出随最强信号或固定在 CW 中心的窄带选择，以及独立的电平门限和速度设置。结合接收音调与 APF 分别可设，可以推断解码器处理的是 DSP 内部的音频频段信号。尚未从程序确认从哪个滤波器前后取样、实际采样率、是否已经过静音或增益处理，也未识别主 CPU 收到的是字符还是别的事件。没有证据把 MK2 的输入等同于 705 的交信录音、扬声器或 USB Audio。

[原厂日版 1.02（2025-11-13）](https://www.icom.co.jp/support/drivers/8693/)与[日版 1.03（2026-09-04）](https://www.icom.co.jp/support/drivers/9010/)都列 DSP Program 1.01、DSP Data 1.00；这一对样本没有可直接用的 DSP 版本差。Windows REA 补看 1.03 的 `0x636B00` 附近（`ev_a470bde5465a1df2efa1f576913a864a0ac3f3fb8ba0a458851c0b49ed4dce5e`），仍没有验证到可反汇编的 DSP 载荷。两个包从 `0x04` 起的 28 字节有不同 ASCII 头部内容，不能据此划分组件。常见可执行/压缩签名未给出可信的组件边界；高熵不能判断是否加密。现阶段先在已解包的日版 705 验证原厂接收链：[RTTY 频谱使用独立于交信录音的采样槽](IC705_RX_AUDIO.md#扬声器有声但-cw-波形平调度和原厂取样分开排查)，但已测 RTTY 消费者不会在 CW 模式读取该槽，尚不能作为直接移植点。

[MK2 基本手册](https://icomuk.co.uk/files/icom/PDF/productManual/IC-7300MK2_ENG_Basic_0.pdf)第 i 页确认 CW 由 DSP 解码；[高级手册](https://www.icomeurope.com/wp-content/uploads/2026/02/IC-7300MK2_ENG_Advanced_0.pdf)第 2-14 页能核实三个独立的控制：`FILTER AUTO` 跟随最强信号，`FIX` 把目标固定在接收中心；`THRESH` 决定什么强度算有点划，能自动或手动；`SPEED` 自动估速、锁定估速，或使用电键设置。公开资料未给出滤波细节、自动门限公式、点划／停顿判定、重新捕获规则或源码。不能从手册把任何一种常见算法认作原厂实现。IC-7110 沿用 MK2 的解码功能只证明厂商做了跨机型复用，不能证明 705 可加载同一段代码。

日版 705 的实验版已经有对应的三类控制，默认仍为 `FILTER WIDE`。电脑回放表明接收效果受输入影响：ARRL 20 WPM 练习正文 0/670；两段独立手键回放以不同样本计得 2/68、18/81（不计空格）。来源、条件及历史版本详见[基线实测](CW_BASELINE.md#速度重估和长字间隔的分词)。[公开的 MK2 实收体验](https://www.fbnews.jp/202602/impression01/index.html)记录一次良好接收下的准确 `CQ`，没有和 705 用同一份录音或统计可比较的误字率；Icom 的[规格页](https://www.icomjapan.com/lineup/products/IC-7300MK2/)也提示准确度受接收条件影响。现阶段不能按“原厂更稳”排出两个解码器的名次。

现版 705 已用相同录音在电脑面板回放三种滤波档，三个都是 705 自己的解码器。按已转写的字母数字评分；自动和定频都用自动门限，最低门限 350，速度都用 `AUTO`。这一对照复用已有录音和评分窗，结论只覆盖这些输入。

| 音频 | 宽带（当前默认） | 自动选音 | 手动定频 |
| --- | ---: | ---: | ---: |
| [SSN 40 米实收](../.analysis/cw-mk2-filter-reference-1115/ssn/evidence.json) | 63/63 | 1/63 | 0/63（640 Hz） |
| [F6UIG 手键演示](../.analysis/cw-mk2-filter-reference-1115/f6uig/evidence.json) | 1/68 | 2/68 | 2/68（700 Hz） |
| [VARC 第 7 课实收](../.analysis/cw-mk2-filter-reference-1115/varc/evidence.json) | 47/49 | 9/49 | 10/49（580 Hz） |

VARC 前 30 秒的已标注背景窗，没有目标来报；宽带、自动选音、定频分别误报 22、28、20 个字符。自动选音明显改善两份实收的正文，但这三份录音不足以支持直接改默认，尤其是自动档增加的背景误字。下一项优先区分“没有目标来报”与“附近有弱 CW”，用独立录音验证抑制误报时不会把弱台一起滤掉。九次回放均通过音频队列、译文追踪和 EXIT 检查，官方 DAT 未改。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat .analysis/cw-sideswiper-1115/ssn40.wav samples/cw-ssn40-continuous.json .analysis/cw-mk2-filter-reference-1115/ssn-replay --modes WIDE AUTO FIX --pitch 640
```

先以稳定性衡量是否值得改默认值。用现有电脑回放在同一组真录音上比较 `WIDE` 和 `FILTER AUTO + THRESH AUTO`，把 `FIX` 作为已知目标频率的对照。下一轮需要用未参与调参的样本统计弱台邻近强台时是否串台、无来报时的误字、手键误字及停顿后恢复。能减错且不牺牲弱台或增加误报才改默认值。若能取得原厂 MK2 的同输入试验，再比较译文；Icom 不通过 USB 输出 CW 译文，原厂结果可录屏留档。继续搜原厂代码时，仅在找到可验证的 DSP 组件和 705 接口对应关系后考虑移植。未更换解码器或改动 DAT。

## CW：已取得两版 MK2 原厂固件

**原厂入口是一个图标、两条分支。** 英文基本手册 PDF 第 40 页和高级手册印刷页 2-7、2-11～2-15 对照：切到 CW，按机身 `MENU`，点同一个 `KEYER/DECODE` 图标，再从选择框进 `KEYER`（电键／预存报文）或 `CW DECODE`（完整译码画面）。菜单可设为短点直达 KEYER，或短点直达 DECODE；两种直达都能长按约 1 秒叫出选择框。KEYER 的 `EDIT/SET → KEYER DECODE SET` 也有译文显示开关，日语系统下还能切换和文译码；与 CW 页的和文开关是同一项。两页共享部分设置，但使用不同画面。

| 在 MK2 的 `CW DECODE` 画面 | 操作 |
| --- | --- |
| 日常收报 | 左栏显示译文；右侧是幅度、音频频谱和瀑布。`HOLD/CLR` 点按暂停或继续显示，按住约 1 秒清屏。 |
| 调接收条件 | `<1>` 翻页 → `ADJ`：`SPEED` 选自动估速、锁定当前估速或使用电键报速；`FILTER` 选自动或定频；`THRESH` 选自动或手动，手动时主旋钮调门限。 |
| 调外观 | `SET` 改频谱、幅度线和文字颜色；选一个 RGB 通道后，主旋钮调数值。主旋钮在这些明确的调整操作中有专门用途。 |
| 调用存储报文 | 原厂另有会发报的 `TX MEM`；705 当前实验只做接收，保留灰字。 |

旧日版 QSB 包使用独立的 `MENU → CW DECODE` 入口；现按用户要求停止修补该入口。新的[电脑试验](IC705_CW_RELEASE.md#复用原厂-keyer-做成-mk2-式单入口)只复用 705 的原厂 KEYER 按钮和两项选择框，保留两条分支及原厂 KEYER 的 EDIT/SET。一级图标仍写 `KEYER`，二级选择框标题为 `KEYER/DECODE`；短按直达、长按选择的可选设置未做。当前复用的是操作以及 705 的现成实现，MK2 自身的 CW 程序及 DSP 不在此对照中。

Icom 的 [MK2 产品说明](https://www.icomjapan.com/lineup/products/IC-7300MK2/)、[高级手册](https://www.icomeurope.com/wp-content/uploads/2026/02/IC-7300MK2_ENG_Advanced_0.pdf)第 2-12～2-14 页及[日文说明书](https://www.icom.co.jp/support/manual/8689/)核对了以上操作。MK2 解码主画面没有 `ACCESS` 或屏内退出键；[基本手册](https://www.icomeurope.com/wp-content/uploads/2026/02/IC-7300MK2_ENG_IM_Basic_1.pdf)第 12 页定义机身 `EXIT`，但没有确认从 MK2 解码主画面按一次的落点。705 保留已实跑确认的机身 `EXIT` 直接回 HOME。官方 [CI‑V 参考手册](https://icomuk.co.uk/files/icom/PDF/productAdditionalFile/IC-7300MK2_ENG_CI-V_0.pdf)的 `1A 05 02 64` 对应 `KEYER/DECODE` 键的启动偏好；可作寻找菜单分派的独立线索，该命令本身不调用 CW 解码。

**原厂把解码放在 DSP。** MK2 基本手册第 i 页说明 DSP 解码接收和发射的 CW。Icom 提交的 [MK2 内部照片](https://fccid.io/AFJ453000/Internal-Photos/Internal-Photos-8742518.pdf)第 1 页 Main Bottom 中央的器件旋转 180° 可读 Analog Devices 和 `SHARC`；具体型号模糊。原厂 705 维修图可核对 `ADSP-21478BBCZ`，也是 SHARC。两机属于同一 DSP 家族，但还没有 DSP 具体型号、程序片段和通信协议能互相对照。照片 Main Top 可见 `TRION` FPGA，和 [705 维修图](HARDWARE.md)中的 Cyclone 10 LP 不同。照片 SHA-256 `51b52630a87432ddd5cbc308c124fe02593172f4021e31cbeb7b57aa1c2d6ccc`。[IC-7110 的 Icom FCC 申请](https://fccid.io/AFJ455900)列明内部照片与用户手册分别受到短期保密，当前清单的预期公开日为 2027-03-06；原理图和物料清单属长期保密。暂不能靠它确定相同芯片或直接复用原厂代码。

| Icom 来源 | ZIP：字节数 / SHA‑256 | DAT：字节数 / SHA‑256 |
| --- | --- | --- |
| [1.02，2025-11-13](https://www.icomjapan.com/support/firmware_driver/4493/)；官方下载 API post `4493` | 6,590,439 / `51a843bd0d79d8e5f3e5085dfb624897b625a7944ab25da0ce9ea65e2d3c99d7` | 8,114,450 / `a3c4b3a31593b8c69f7cfd85073a1e29ec2e2b2198e9cced957211cad249e020` |
| [1.03，2026-09-04](https://www.icomjapan.com/support/firmware_driver/4742/)；官方下载 API post `4742` | 6,590,782 / `cc112a9711b34f8a7cc505049e0ef0f4453dafb6d2bc0fc1bcabc98e915ce42f` | 8,115,837 / `96306d3c746792a77ea4efdf7745edd86eeb5df6779d2e145629679f55ad942f` |

来源页下载按钮指向 `/api/download.php?post_id=…&fl=…`。ZIP 和唯一 DAT 成员原样放在被 Git 忽略的 `firmware/`。两个 DAT 以 `44 55 33 00` 开头；`0x20` 和 `0x30` 的两个长度候选之和在两版均距总长 `0x33A`，但这不能确定真实边界。IC‑705 的解析器不能直接用；裸包搜索两种常见字符编码均未找到 `CW DECODE`、`KEY SPEED` 或 `RTTY DECODE`。这不表示功能缺失。

REA Windows `inspect_byte_entropy` 绑定 1.03 哈希（`ev_67cab6f76d992e56f0ba8d45c77452f99471c4f35ab9e5f426fed5c30a132671`）；Windows 的固件区段接口仍需要 Linux Provider。复用已有 Debian WSL2 执行 REA/Binwalk 3.1.0，1.03 给出六个签名候选（`.analysis/rea-mk2-103-regions.json`，`ev_2f44f110615cb6c9db3d43c5bdc77b06e51e1259b8db0debedf7cb5dac40e3be`）：两处 zlib 实际解码失败；S-record 候选在第一个字节计数就不符合十六进制格式；另外三处 GPG 短签名没有得到结构或验证证据，不能作为签名存在的依据。没有确认可反汇编的 MK2 主程序或 DSP 组件。包头、哈希和搜索结果置信度高；字段语义和组件归属未知。

**新增二进制对照：**截至 2026-11-15，[日本官方最新版本](https://www.icom.co.jp/support/drivers/9010/)和国际站均为 1.03；按日本站官方链接重新获取 [1.02](https://www.icom.co.jp/support/drivers/8693/) 和 1.03，确认两版 ZIP 和内部 DAT 分别与本地国际站副本逐字节一致。原厂版本表中 Main CPU 从 1.02 到 1.03、FPGA 从 1.01 到 1.02，DSP 程序/数据版本均不变。按两个包的 `0x20` 头字段作为比较界标，前面抽样 1,589 个 4 KiB 窗口，49 个唯一匹配都在原位置；后面抽样 390 个，216 个唯一匹配都在 1.03 中前移 5 字节，另有 2 个多重匹配。从文件末尾减去 `0x30` 候选长度，两版位置正好相差 5 字节，跨过该位置的精确相同字节区长 **897,453 字节**，为 `[0x637101,0x7122AE)` 和 `[0x6370FC,0x7122A9)`，两者 SHA-256 为 `014ac57f8bbbe80d11f25e056bfadef374ae94c80ab26f3923143ab1eba2835c`。这是真实的包内对齐线索，不能把这一段认作 DSP 或 CW；稳定区跨过倒算位置，所以也不能把倒算位置直接称为组件边界。可复现报告 `.analysis/705-mk2-operation-and-binary.json`（SHA-256 `f9bf612b8a159b59f638be5cbe6e1e1508bc8b0b168bc08400ebb1d24e1ff9fc`）。下一次需要同一个边界假设在两版都能通过结构或校验验证，再定位运行代码和实际调用。

**705 的首个可验收目标已通过**：有原文的 CW 录音 → 日版 J140 录音例程 → PC 解码器 → 原厂 RTTY 正文和绘制。见 [四帧结果与 CW/RTTY 菜单对照](IC705_CW_DISPLAY.md)。可借鉴 MK2 的自动估速与界面，MK2 未解包不阻塞本项。

### 两个初代 7300 项目可以复用什么

| 参考 | 实际覆盖 | 对 J140 的用法 |
| --- | --- | --- |
| [jeskko/ic7300-homebrew](https://github.com/jeskko/ic7300-homebrew) 的 [QEMU 验收](https://github.com/jeskko/ic7300-homebrew/blob/master/qemu-machine/README.md)和 [SDK](https://github.com/jeskko/ic7300-homebrew/blob/master/sdk/README.md) | 初代 IC-7300 1.42 的原厂程序；作者在同一次仿真验证触摸、实体键、主旋钮、频谱和接收音频。SDK 双缓冲，应用主动归还 UI 线程；退出时归还屏幕、输入和音频。作者明确尚未在实体机运行。 | 复用外设测试思路：从外围输入送入触摸/旋钮/收音，等原厂提交屏幕更新，保留同一会话里的原厂频谱。不同机型的固件地址、外围数据和更新包各自验证。 |
| [zarthur/ic-7300_firmware](https://github.com/zarthur/ic-7300_firmware) 的 [包结构](https://github.com/zarthur/ic-7300_firmware/blob/main/research/container.md)与离线回放 | 初代 IC-7300 1.40–1.42。四段逐个校验；提供 FT8 录音精确对照，公开重建要求与原厂镜像逐字节一致。未提供 MK2 CW 实现。 | 复用“阳性对照、逐段验证、同一采样记录可重复回放”的方法，不把初代解析器当 MK2 解析器。 |

**实际用包对照。** 从 [Icom 初代 1.42](https://www.icomjapan.com/support/firmware_driver/4102/) 下载 `7300_142.dat` 放到 Git 忽略目录。按初代项目记录核对：文件头 `33 77 66 55`，四个载荷的长度与摘要覆盖整个文件，四个 MD5 全部匹配。两份保留的 MK2 DAT 均为 `44 55 33 00`（`DU3`），未通过同一布局检查；不能用初代解包结果推断 MK2 主程序或 DSP。初代 DAT 为 3,954,089 字节，SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`；官方 ZIP 为 2,868,098 字节，SHA-256 `6b4a5910555c5736ecacd954a88ee5df8afd996a8a89aa4888e85b1cc533606e`。

两份 MK2 在开头 256 KiB 中最长的同位置相同段为 `[0xB420, 0x2418C)`，共 101,740 字节；和既有的包尾对齐区可以分别用作后续边界假设的对照。`0x24` 的值恰好等于 `0x28` 与 `0x2C` 两个值的和，两版都成立；三个值的用途仍未验证。上述比较只识别文件结构，不等于已经提取或反汇编 CW DSP。证据 `.analysis/cw-mk2-public-control-1115/evidence.json`；复现（不运行两个仓库的代码）：

```powershell
py -3.14 -X utf8 -m tools.probe_7300_family .analysis/cw-mk2-public-control-1115/7300_142.dat firmware/7300MK2_102.dat firmware/7300MK2_103.dat
```

对现有真机故障，优先借用第一个项目的仿真验收方法，在 705 上同时验证 `SET` 与 `AUTO/WPM` 的可见变化、主旋钮、接收来报和原厂频谱刷新。继续只读拆解 MK2 可用来核对它的 DSP 接口和弱信号行为；直接移植原厂解码器仍缺可验证的 DSP 载荷与两机接口，不能替代对 705 自己的 UI 和接收路径的验证。

### 用 GitHub 的逆向方法验证 MK2 载荷边界

2026-11-16。沿用 [zarthur 的整包长度核算和原厂版本对照](https://github.com/zarthur/ic-7300_firmware/blob/2a29126a4608b17d043a7a183c8a88e186352088/research/container.md)。[jeskko 的协议研究](https://github.com/jeskko/ic7300-homebrew/blob/84fb65b457f00bddcf5fb3d044e9f29dad3be48b/notes/dsp-protocol.md)提供下一段的验收方法：先按器件启动记录恢复实际装载地址，再把接收缓冲、命令分派和主控端的读写互相对照。初代的 TI 启动格式、地址和串口协议不套到 MK2 的 SHARC。关于分段编码的具体对照采用 [SQ6EMM 公布的 IC-705 只读格式](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/a91231f64e8afbe34353994786e8276a3b54f1a9/IC705_DAT_FORMAT.md)。

**MK2 的两段存储范围已得到交叉支持。** 两版均可从 `0x38` 起用包头 `0x20`、`0x30` 两个长度覆盖载荷：每段后 256 字节，再有一份 256 字节和最后两字节，恰好覆盖文件全长。第二段从下列偏移开始，其相对偏移 `+1` 起有连续 **897,453 字节**两版相同，正好解释旧扫描中 `-5` 字节的对齐位移；它不是倒算得出的 `文件长度 − 0x30 处的值`。Windows REA 复核两个分界窗口（`ev_3daba8ee599de069f3a9fb6464df7f6311d72e7e501782e30ad654c5bcdd7364`、`ev_e58b0e0b9b64cb95f7922b109e9fb43d361643e138ac2392f89032aa2ebf5853`）。这里只确认结构候选；256 字节的用途与两个大段内的组件归属仍未知。

| 版本 | 第一段（起点、长度） | 第二段（起点、长度） |
| --- | --- | --- |
| MK2 1.02 | `0x38`, `0x636FC8` | `0x637100`, `0x185E10` |
| MK2 1.03 | `0x38`, `0x636FC3` | `0x6370FB`, `0x186380` |

**用四份 IC-7760 原厂包做独立对照。** [1.01](https://www.icom.co.jp/support/drivers/8059/)、[1.12](https://www.icom.co.jp/support/drivers/8402/)、[1.14](https://www.icomjapan.com/support/firmware_driver/4515/) 与 [1.15](https://www.icom.co.jp/support/drivers/8753/) 使用另一种 `DDDV` 包头。按 `0x70` 头部、八个交替的长度字段和同样的 256 字节间隔，也能完整核算四个文件。1.12→1.14 原厂版本表只变更三项 CPU，只有第 1、2、4 段变化；第 3、5–8 段逐字节全同。1.14→1.15 的 DSP 版本保持不变，仍有五段的存储字节不同；其中第 7、8 段都只有首字节改变。这说明对齐、计算完整范围和对照版本必须一起做，不能用“这段变了／没变”给 MK2 命名，也不能把两机的区段编号当成同一组件。

**读码边界。** 按 SQ6EMM 的格式解释，705J140 的 DSP 相关存储段完整消费 1,452,294 字节，得到 2,097,152 字节，输出 SHA-256 是 `0bf7c9921e3c603dda92a7cac2f688a100f39084fd4fe115efcf82d454fdadf4`；未给输出里的各部分命名。同一方法在 MK2 第二段的 1.02 留下未消费字节，在 1.03 解码超出声明尺寸；两者均判失败。另按 705 的 64 KiB 启动区模型测试 MK2 第一段：705 恢复出 45,068 字节的连续擦除尾部，且与既有 `bootstrap.bin` 哈希一致；两版 MK2 都只有人为设定的最后一个 `FF`，未复现 705 的结构。这两个阴性结果不能外推为整个 MK2 都不用某种压缩，不能把输出当反汇编输入，也不能据此断定签名或加密。

下一项验收：在 MK2 自身找到能独立复核的载荷格式或装载记录。优先从第一段找主控的启动/加载结构，判据是两个版本都能得到自洽的入口和地址；再沿主控发送的 DSP 配置及返回缓冲查 `CW/FILTER/THRESH`。只有两端吻合后才认定取样点或结果格式。705 原厂 AUDIO 动而 CW 平只能作为本机下游的排查线索。

复现如下。输入只读；完整 DAT 校验、分段 SHA-256 与差异集中在 `.analysis/mk2-dsp-1116/payload-boundaries.json`，报告 SHA-256 `dea1cb16650064bd8c481bbb9d2b2208a5d86e96ff35ec4c1d824f4a4749d386`。已验证完整／截断的合成包、原厂包的分段对齐，以及两个 705 解码阳性对照。没有生成测试 DAT。

```powershell
python -m tools.probe_icom_payload_boundaries --ic705-control firmware/705J140.dat `
  firmware/7300MK2_102.dat firmware/7300MK2_103.dat `
  .analysis/mk2-dsp-1116/7760_101.dat .analysis/mk2-dsp-1116/7760_112.dat `
  .analysis/mk2-dsp-1116/7760_114.dat .analysis/mk2-dsp-1116/7760_115.dat
```

### 第一段与主控载荷的交叉证据

2026-11-16。两版 MK2 第一段相对偏移 `0xF87` 起的 983 字节，在 `+4352` 完整重复；在 `+2176` 则有且仅有 57 个字节翻转最高位，位置间隔正好 17 字节。这个精确指纹在 MK2 第二段没有出现。在五版 IC-7760 的第 1、2、4 段都出现，在其余五段均未匹配。两个机型各自的窗口内容不同，匹配的是这种记录规律。REA 把两版 MK2 的检查窗口绑定到原厂包 SHA-256（`ev_fdd860bef9805d0b94fba45ebeae95dc362598139cdf011a2f45a5cc6be4f0b7`、`ev_14b8b7d871bae947da9393723aaf81b9c082668811a694bb2b78a120e2328188`）。17 字节与一类 LZSS 记录长度相容，但未见有效的解码流，不能据此识别算法或断定校验形式。

补取 [Icom IC-7760 1.13](https://www.icomjapan.com/support/firmware_driver/4392/)，DAT SHA-256 `4a379add9bd4c4ba7f4156d89206b033461c48ec1ecc78f8dd79733a86e204fa`。官方 ZIP SHA-256 `d06014edbc68c660c4288b039bd467c52974ab1fbe74e80a94f0b88dc4b04ba1`，来源是该发布页的下载按钮。按官方版本表独立比较：

| IC-7760 版本 | 原厂版本表中改变的组件 | 实际改变的存储段 |
| --- | --- | --- |
| [1.12](https://www.icom.co.jp/support/drivers/8402/) → 1.13 | Main CPU、Sub CPU、RF CPU | 1、2、4 |
| 1.13 → [1.14](https://www.icomjapan.com/support/firmware_driver/4515/) | Main CPU、Sub CPU | 1、2 |
| 1.14 → [1.15](https://www.icom.co.jp/support/drivers/8753/) | Main CPU、RF FPGA | 1、5、6、7、8；7 和 8 仅改变首字节 |

三次差分较强支持 IC-7760 的第 1、2、4 段分别与 Main、Sub、RF CPU 相关。对 MK2 的推断范围仅为：**第一段是两段中更有证据支持的主控候选**，仍可能有内嵌资源或其他组件。没有证据给出程序或 CW 子段的地址。

只读扫描两段的原样字节，找包含七个有效入口槽的常见小端 A32 启动表，两版 MK2 都没有命中。初代 7300 1.42 的原样主控段和已解出的 705J140 引导均命中开头，首个跳转目标均为 `0x1800008C`。这个阴性结果排除了把这两段原样按同族启动表加载的做法，未排除不同架构、不同入口表或先解包再映射。FCC 照片本轮下载未成功；CPU 具体型号仍不根据初代推定。

复现结果 `.analysis/mk2-main-1116/cpu-records.json`，SHA-256 `60054d21777ea2943407c70102cc58a823b28dcc4b2056d504da3200adb9d881`。`python -m unittest discover -s tests -p 'test_probe_icom_cpu_record.py'` 两项通过。命令：

```powershell
python -m tools.probe_icom_cpu_record `
  --original-7300 .analysis/cw-mk2-public-control-1115/7300_142.dat `
  --mapped-705-boot .analysis/main-decode/705J140/bootstrap.bin `
  firmware/7300MK2_102.dat firmware/7300MK2_103.dat `
  .analysis/mk2-dsp-1116/7760_101.dat .analysis/mk2-dsp-1116/7760_112.dat `
  .analysis/mk2-main-1116/7760_113.dat .analysis/mk2-dsp-1116/7760_114.dat `
  .analysis/mk2-dsp-1116/7760_115.dat
```

后续优先用这组已归类的 CPU 数据验证公开的压缩／装载格式；至少需要两个独立 CPU 样本还原完整且入口自洽，才能把结果交给反汇编。若没有这种验证或公开可用的原厂加载器／已解包镜像，不能靠猜地址进入 CW 追踪。未修改原厂文件、未打包、未连接电台。

### 两版第一段解包与原厂加载器核查

2026-11-16。**MK2 原厂 1.02 与 1.03 均未通过第一段解包和启动入口验收。** 仅处理 `0x38` 开始、分别为 6,516,680 / 6,516,675 字节的存储段，排除其后的 256 字节块。把 `0xFC0000`（16,515,072 字节）作为待验证的输出长度；尚未证实它确实是输出长度。两版官方 ZIP 各仅一个 DAT，成员 CRC-32 (`ab261c03` / `ac50cb44`) 通过且与本地 DAT 字节一致。

先用 [zarthur 公开的初代 7300 解码方案及参考哈希](https://github.com/zarthur/ic-7300_firmware/blob/2a29126a4608b17d043a7a183c8a88e186352088/research/targets.json)核验初代 IC-7300 1.42：4 个组件 MD5 均通过，读 1,676,645 字节解出 3,738,392 字节，输出 SHA-256 与项目独立参考一致；引导的首个跳转目标为 `0x1800008C`，解包应用开头跳 `0x20005050`。日版 IC-705 1.40 按 [SQ6EMM 的公开格式](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/a91231f64e8afbe34353994786e8276a3b54f1a9/IC705_DAT_FORMAT.md)解出 3,558,076 字节，与本项目已知主程序 SHA-256 一致，引导首个跳转目标也是 `0x1800008C`。对照的地址不用于给 MK2 定址。

| 第一段试验 | MK2 1.02 | MK2 1.03 |
| --- | --- | --- |
| 按初代 7300 从段首解，允许截短最后一个 LZSS 引用 | 剩 1,857,719 字节未读；输出全段无 A32 启动表候选 | 剩 1,787,737 字节未读；同样无候选 |
| 先用原样公布的 IC-705 段解释，再用初代 7300 LZSS | 剩 1,833,083 字节未读，输出无候选 | 剩 1,822,581 字节未读，输出无候选 |
| IC-705 严格结束规则，从段首分别试原样与 IC-705 解释后的字节 | 两条路径均在末个引用超出预期长度 | 同左 |
| 两种旧格式在 64 KiB 边界的内嵌长度头 | 原样及 IC-705 解释后均不合理 | 同左 |
| zlib / gzip / raw DEFLATE / XZ / bzip2，各查七个有依据的起点 | 0/35 通过 | 0/35 通过 |

初代解法能输出 16,515,072 字节是因为试验要求在该长度截停；与原厂正对照不同，既没有可信的下一个记录解释，也没有启动向量。17 字节指纹也不是可直接代入的初代压缩记录：把翻转位位置当固定组标志时，两版两个窗口各有 57/57 个非零字节，而固定 17 字节的这类组必须是八个双字节引用、标志为零。只能排除这个**直接解释**，仍不能识别实际格式、CPU 架构或签名。REA Windows 给两份输入绑定 SHA-256；段首两块 4 KiB 的熵均约 7.91–7.96，只作数据特征，不判定加密。

**替代入口：已查 GitHub 默认分支和原厂下载渠道。** [jeskko 的原厂引导分析](https://github.com/jeskko/ic7300-homebrew/blob/84fb65b457f00bddcf5fb3d044e9f29dad3be48b/notes/base-loader.md)与 [SDK loader](https://github.com/jeskko/ic7300-homebrew/blob/84fb65b457f00bddcf5fb3d044e9f29dad3be48b/sdk/loader/README.md)都指向初代 IC-7300；仓库的 EEPROM 测试文件也不是 MK2 主程序。zarthur 的登记表仅列初代 1.40–1.42；SQ6EMM 的[解码仓库](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware)和[补丁发布仓库](https://github.com/sq6emm/icom-custom-firmware)没有受验证的 MK2 镜像。Icom [产品支持清单](https://www.icomjapan.com/lineup/products/IC-7300MK2/)公开的电脑软件是 USB 驱动及 RS-BA1 控制软件，[日方有偿更新](https://www.icom.co.jp/support/drivers/paid_service.html)是寄机服务，[高级手册 §11](https://www.icomeurope.com/wp-content/uploads/2026/02/IC-7300MK2_ENG_Advanced_0.pdf)只给使用者 SD 更新并在异常时送修的途径。查到的公开渠道没有可核实的 MK2 原厂加载器或已解包镜像。

**下一个验收点：**取得来源、机型和版本可核验的原厂 MK2 加载器，或经授权的未修改 MK2 主控只读镜像。先用启动代码和有效映射确定实际入口、主控/DSP 的固件加载位置，再从 `CW DECODE` 入口跟到 DSP 模式设置和返回接收函数，区分主控拿到的是 PCM、点划事件、译文还是多类数据。1.02→1.03 的 DSP Program / Data 版本未变，不能靠这两版的差分当作 CW 实现变化。未得到这些证据前保留 MK2 界面参照，暂停从该段猜 DSP 音频接线，不回头重复原厂更新或开机，不打包、不刷机。

证据（本地忽略目录）：`.analysis/mk2-load-1116/first-payload.json`（SHA-256 `75aec4a0f46ab2bc654145f089b7b61c3198714c4338b4a8b7e2589a152c3b13`）、`public-loader-audit.json`、`rea-entropy.json`。相关 10 个单测通过。复现只读，两版的 ZIP 放在 DAT 同目录：

```powershell
python -m tools.probe_mk2_first_payload `
  --original-7300 .analysis/cw-mk2-public-control-1115/7300_142.dat `
  --ic705-control firmware/705J140.dat `
  firmware/7300MK2_102.dat firmware/7300MK2_103.dat
```

**跨机型原样字节对照。** Windows REA 针对两版重合区各分析 220 个窗口，整段均为高熵（1.02 证据 `ev_72dd75078b4bb0936964c0dbb0157bdbc38c9d19f72af73d00d4299b0889cacb`；1.03 `ev_3ef8f8c9e03df1410a4bb4f31973c6a14cf044d2f71b944b8b548602faca5bc1`）。另从日版 705 已解包主程序和 [DSP 相关 C 组](FIRMWARE_COMPONENTS.md)抽样，在两版 MK2 裸包和共同区均未找到原样字节；同一个 705 已解包主程序在它自己的裸包里也搜不到，解包后的日版 1.32 则能搜到。在已经知道能解包的正对照上即可重现这类假阴性，所以高熵和零命中都不能排除共用代码，也不能支持把整段拿来移植。日版 705 已确定能取到接收音频，继续以它为实际接入路径，对照 MK2 操作独立实现。

| J140 来源及窗口 | 抽样数 | 解包后 J132 主程序命中 | J140 自己的 DAT 命中 | 两个 MK2 DAT（各自）及共同区命中 |
| --- | ---: | ---: | ---: | ---: |
| 解包主程序，32 / 64 字节 | 654 / 312 | 362 / 112 | 0 / 0 | 0 / 0 |
| 裸包 C 组，32 / 64 字节 | 337 / 337 | 0 / 0 | 337 / 337 | 0 / 0 |

报告 `.analysis/705-mk2-plaintext-controls.json`，SHA-256 `1de1f097f398862027062cbecb6fc7364b175115f049cd0d37dfa3430f365cf5`。待取得 MK2 已确认的 DSP 载荷和通信接口，才把移植作为另一个可验收方向；无需守在旧的裸包字符串搜索上等待。

### 705 上先验证固定速度能否帮忙

参考 MK2 的 `MANUAL`，用同一个 705 ARM 解码器做临时先验设速对照：从首块就给定等效点长，关闭速度修正，其他处理与 `AUTO` 相同。这模拟手动给定速度的核心效果，**不等于**已经实现 MK2 先自动、再锁定的交互，也没有调动 705 的电键设置。三种来报速度每种都单独回放冷启 `E / T / 5 / 0`，另外用同一段 NW6V 人工直键计分。

| 试验档 | 15／20／25 WPM 各正确几项（各 4 项） | NW6V 错字（282 字） |
| --- | --- | ---: |
| AUTO | 2 / 2 / 2 | 50 |
| 固定 15 WPM | 4 / 4 / 2 | 257 |
| 固定 20 WPM | 4 / 4 / 4 | 108 |
| 固定 25 WPM（10 ms 时间量化后约 24） | 4 / 4 / 4 | 46 |

20 WPM 单独 `T` 在 `AUTO` 中误译为 `E`（580 ms），正确设速后译为 `T`（300 ms，自首个音起）；`0` 也从 `5` 改为正确。手键固定 20 明显恶化，固定 25 在同一录音里仅改善 4 字；这些是预先列出的三个档，不足以证明固定档对手键普遍有益。默认仍用 `AUTO`，保留 `LOCK` 给对方报速稳定的场景。WPM 显示和切换已另行验收，手键误码仍单独跟踪。

本机复跑：设置 `$env:PYTHONPATH = '.analysis/ic705-emulator/deps'`，执行 `py -3.14 -X utf8 .analysis/mk2-fixed-speed-research/compare.py`。报告同目录 `evidence.json`（SHA-256 `99e8be96c075a884e2b89b7ccdcda4b00c547b40b37613deea865fc0deb797b1`），标记试验 ARM 代码与录音哈希，没有进入 705 UI、写入电台或生成固件包。

## SSTV：原厂 Picture 页面已找到并回放四个入口

[Icom 图像共享手册](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_IC-9700_Picture_Tx_ENG_IM_2_20200526.pdf)确认收发预览、选图、历史、microSD 和 DV Fast Data；[IC‑705 1.40 更新说明](https://www.icomjapan.com/support/firmware_driver/4422/)确认接收百分比和已收图块显示。J140 主程序表项与原厂 ARM 例程可在 PC 上互相核对。以下四个入口在新建的模拟内存上实际返回，原厂各自写入了正确的页状态；没有模拟导航、图像帧缓冲或触发收发。REA 字节范围证据：`ev_0e66ab4898e7cf58cf633c5d5f8deebc89c1ae1ed7d68c2899c64253b9f8b69e`（标题）和 `ev_8f4f8bd6c8f2bf5a1051c9a9e50dae6400aa446475395e0f37ce9add4bd82d09`（页面表）。

| 原厂页面 | J140 表项 | 原厂入口 | 实际写入页号 |
| --- | --- | --- | --- |
| RX PICTURE | `0x202ECB60` | `0x200B3A14` | `0x37` |
| RX PICTURE HISTORY | `0x202ECB78` | `0x200B3B6C` | `0x38` |
| TX PICTURE | `0x202ECB90` | `0x200B3BB0` | `0x39` |
| TX/RX PICTURE VIEW | `0x202EBC60` | `0x200B3EE4` | `0x3A` |

**入口放 `PICTURE` 里，收发仍走独立的模拟音频路径。** 建议将菜单分为 `DV 图片` 和 `SSTV`，或在现有 Picture 页面放一个 `SSTV` 子入口，允许从合适的模拟模式进入。DV 图片传输的是数字数据块；常规 SSTV 则把图像变成音频音调，短波通常经 SSB，特定 VHF/UHF 用例可用 FM。不能把 SSTV 接到 `TX ALL` 或套用 DV 图块重传、呼号、图片质量参数。Picture 的画布、选图和完成图查看是复用候选；接收百分比应由 SSTV 已解码行数生成，历史和保存格式单独验证。原厂 1.40 的文件管理中还找到 `\PICTURE\Private\Rx\RxHistNNN.dat`，因此首版不应把 SSTV 图直接塞进 DV 历史文件。

先把[已有 Robot 36 回放](IC705_SSTV_REPLAY.md)解出的同一张测试图送进原厂图像绘制入口，核对首尾行、方向、颜色和屏幕输出；然后再测逐行更新与保存。发图放在第二阶段：先在电脑把测试图编码为 WAV，经独立解码器回读；选图和预览可沿用 Picture，机内模拟音频输出与发射控制仍需单独验证。本阶段只读，不访问电台或发射。

## 复现

从项目根目录运行，先按 [主程序解包](MAIN_CPU_DECODE.md)生成 J140 `main.bin`。下列脚本校验三个输入哈希，再跑四个原厂入口；结果在 `.analysis/705-picture-mk2.json`。WSL 扫描可按 [已有 REA 流程](REA_ANALYSIS.md#wsl2-固件工具实测)只替换输入路径。

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
py -3.14 -X utf8 -m tools.probe_705_picture_mk2 .analysis/main-decode/705J140/main.bin firmware/7300MK2_102.dat firmware/7300MK2_103.dat |
    Set-Content -Encoding utf8 .analysis/705-picture-mk2.json
py -3.14 -X utf8 -m tools.probe_705_picture_mk2 .analysis/main-decode/705J140/main.bin firmware/7300MK2_102.dat firmware/7300MK2_103.dat `
    --j140-dat firmware/705J140.dat --j132-main .analysis/main-decode/705J132/main.bin |
    Set-Content -Encoding utf8 .analysis/705-mk2-plaintext-controls.json
```
