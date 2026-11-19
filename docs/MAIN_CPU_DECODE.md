# 日版 IC-705 主程序：提取、启动映射与 GPS 代码对照

2026-11-13。本地官方 `705J140.dat`、`705J132.dat` 均已提取并反汇编主 CPU 程序。两个样本的启动代码把主程序映射到 `0x20005000`，A32 复位入口为 `0x20005060`。沿 `GPS Position` 页面表和调用链找到 1.40 的距离单位改动，并追到 RTTY 标题也使用的文字绘制入口。现有 Windows 工具足以复现本报告；不需要新的固件样本或 Linux 主机。

后续已在 PC 上用[仿真脚本](IC705_EMULATION.md)运行两版原厂距离格式化、菜单行代码和部分启动路径。下文的反汇编证据与动态结果可独立复核。

## 原先的卡点与提取证据

本次查阅了 Icom 日本的 [1.40](https://www.icom.co.jp/support/drivers/8603/) 和 [1.32](https://www.icom.co.jp/support/drivers/7074/) 公告，以及 SQ6EMM 的[公开格式研究](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/6adfab19d58e64f3362d72e8fd7d41dbd47a8eee/IC705_DAT_FORMAT.md)。Icom 公告标明地区、主 CPU 版本和功能变化；第三方研究解释了 A 组内部的逐字节编码与 LZSS 压缩。按该文档独立编写[只读提取脚本](../tools/decode_705_main.py)，未运行第三方项目代码。输入身份见[日版来源清单](../research/705j-provenance.json)与 [E 版记录](REA_ANALYSIS.md#来源和校验)。

先用 DAT 长度、分组 MD5 和尾标复核封装。A 组从文件偏移 `0x64` 开始，前 `0x10000` 字节还原为引导镜像，内有 45,068 字节的 `FF` 尾部填充。接着读出 `0x10064` 处的小端长度头，压缩流始于 `0x1006C`。过去对原始 DAT 和 A 组做的向量、明文和通用格式扫描看不到这段解包后的代码；仅更换反汇编基址不能还原它。三份样本的引导镜像逐字节相同，65,536 字节，SHA-256 `8c55e7f49477985f994e79d83b111048ace533bfacce70a62ef80a6543d732db`。

| 官方输入 | 压缩流所存字节 / 未消费的 FF | 主程序字节数 | 主程序 SHA-256 |
| --- | ---: | ---: | --- |
| 日版 `705J140.dat` | 2,071,676 / 2 | 3,558,076 | `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9` |
| 日版 `705J132.dat` | 2,072,380 / 0 | 3,636,768 | `e2367bf67ec7969ef42cf74a4d0da22d3b75b825377c223ccc131f1ba217617f` |
| 欧洲版 `705E140.dat`（地区对照） | 2,071,976 / 1 | 3,558,876 | `3df33f33de9b2754a86cc61608334e61364e409f5a8ce905f0fac0e42afd3b3c` |

输出长度与各自的头字段一致。三份镜像的向量结构一致，但内部构建标识分别含 `SX4075 V4.52-J00`、`SX4075 V4.47-J00` 和 `SX4075 V4.52-E00`。三个主程序均可由各自的 DAT 单独恢复，无需上一版，因此这个主 CPU 组件不是增量补丁；其余载荷、设备专属数据、完整 Flash 布局未由本实验覆盖。

## 从启动代码验证装载地址

以下地址由解包后的引导镜像和主程序交叉验证，可信度高（静态证据）。文件偏移与运行地址的关系只适用于**已解包镜像**；解压后的地址不能直接减一个常数换算成原始 DAT 偏移。

| 环节 | 观察 |
| --- | --- |
| 第一段引导 | `bootstrap.bin` 的 `+0x00` 按 `0x18000000` 映射。`0x18000104` 调用复制函数 `0x1800004C`；该函数从 `0x18004000` 复制 `0x9BC` 字节到 `0x20004000`，随后经 `0x18000144` 转到 `0x20004840`。 |
| 解压目标 | `0x20004630` 从常量池取出目的地址 `0x20005000`，读取所选输入头的 `+4` 作为输出长度、从 `+8` 取流，跳到 LZSS 子程序 `0x200044DC`。子程序有 `0xFEE` 初始游标、低位优先标志和 12 位回溯索引。|
| 移交控制 | `0x200049A8` 至 `0x200049B0` 设置向量基址寄存器；在 `0x20004974` 处再次把 `0x20005000` 读入 `r0`，最后于 `0x200049B8` 执行 `bx r0`。 |
| 主程序 | `main.bin` 偏移 0 对应 `0x20005000`。八条 A32 `ldr pc` 从紧接的地址表跳转；首项为 `0x20005060`。复位代码使用 CP15，设置栈并调用子程序。J140 在 `0x200050B4/0x200050B8` 调用 `0x2011C028/0x20124E90`；GPS 调用链也实证主程序混用 A32 和 Thumb。 |

这验证了引导与主程序的代码边界和装载位置。没有观察实机冷启动，也没有从这些地址推断启动绑带、更新验签或独立恢复路径。

## 第一条原厂功能链：GPS 距离显示

Icom 1.40 公告称，GPS Position 等页面把以米显示的上限从 1 km 调到 10 km。本次从两版页面表出发找到同一个格式化路径；名称是研究标注，无原厂符号表。

| 证据 | 1.32（J132） | 1.40（J140） |
| --- | --- | --- |
| 页面表记录地址；标识字同为 `0x0101002C` | `0x20300798` | `0x202EC840` |
| 同一记录内 `GPS POSITION` / `GPS Position` 字符串地址 | `0x2036A650` / `0x20369218` | `0x20356E18` / `0x203559E0` |
| 表内第一个指针指向的函数 | `0x200B1F3C` | `0x200B34B0` |
| 页面函数分支之一 | `0x200B1FB8 → 0x200B146C` | `0x200B352C → 0x200B29D0` |
| 上述分支调用距离格式化器 | `0x200B17A0 → 0x20212350` | `0x200B2D10 → 0x2021710C` |
| 公制近距判断 | `0x202123A4` 把 `9995` 放入 `r11`；`0x202123BC` 比较 | `0x20217178` 从 `0x20217494` 取 `99995`；`0x2021717C` 比较 |
| 在结果缓冲内写单位 | `0x202124A4` 写 `m`；`0x20212648` 引用 `0x202126AC` 的 `km` | `0x20217264` 写 `m`；`0x2021743C` 引用 `0x202174A8` 的 `km` |

核对了调用参数与分支。格式化器取 `r1` 的距离、`r0` 的输出缓冲及 `r3` 的单位选择，调用者也传入允许近距单位的标志。有效数据、公制且允许近距时，`r1` 以 0.1 m 为单位。近距分支加 5 后除以 10，按整米显示；`9995` 和 `99995` 是舍入边界，分别避免把接近切换点的数值显示为 `1000m`、`10000m`。两版的无符号除法函数（J132 `0x202DCDF8`、J140 `0x202C8D2C`）由 A32 `BLX` 进入 Thumb；函数的 44 个字节逐字节一致。与公告一致的离线分支推演：500 m 两版都写 `m`；5 km 在 J132 写 `km`、在 J140 写 `m`；12 km 两版都写 `km`。这些输出已在[原厂函数仿真](IC705_EMULATION.md#原厂菜单行和-gps-函数的动态证据)中复现，尚未验证屏幕像素。

## 从距离字段到原厂文字绘制

GPS 格式化器把文本写入页面状态块 `+0x3A`。两版均有另一组代码比较这个字段与上一份状态的 7 个字节；需要重绘时，把地址及长度送往文字绘制。用 RTTY 标题作独立对照：它先读取资源指针和 11 字节长度，再调用同一个绘制入口。这里识别的是显示调用，不是 RTTY 解调器。

| 证据 | 1.32（J132） | 1.40（J140） |
| --- | --- | --- |
| 页面状态块；距离文本地址 | `0x204BAC18`；`0x204BAC52` | `0x204BACB8`；`0x204BACF2` |
| 状态比较后的绘制调用 | `0x20186F14 → 0x2018594C` | `0x2018AAC8 → 0x20189500` |
| 把距离缓冲地址放入 `r2`、长度放入 `r3` 后，调用共用文字入口 | `0x20185A2C → 0x2013EF7C` | `0x201895E0 → 0x20142698` |
| RTTY 标题也传入指针和长度，调用该入口 | `0x201717D0 → 0x2013EF7C` | `0x201751EC → 0x20142698` |
| 同一链的字节到 16 位字符转换 | `0x20141590`，调用 `0x201DAA84` | `0x20144CAC`，调用 `0x201DED50` |

在 J140 中，文字入口经 `0x20146970` 到达字符转换和字形绘制逻辑。转换子程序有 ASCII、半角假名及 Shift-JIS 型双字节分支。主程序内的诊断字符串含 `TxtRender_FT2_Init` 和 `TxtRender_FT2_LoadGlyphData`；初始化函数 `0x20196D50` 在调用失败时引用前者。同一绘制链的 `0x20198B60` 设置字形原点及混合模式，再以字形数和索引数组调用图形后端；`0x1122`、`0x1104`、`0x2001` 及参数次序与 [Khronos OpenVG 1.1](https://registry.khronos.org/OpenVG/specs/openvg-1.1.pdf)一致。J132 对应图形段是 `0x20194894`。这是主 CPU 内使用 FreeType 文字后端及 OpenVG 字形接口的静态证据。[字库文件、装载和简体字覆盖](IC705_LANGUAGE_FONT.md)已另行验证；LCD 帧缓冲和图像绘制路径仍待确认。

[J140 距离续测](IC705_ZH_GPS_DISTANCE.md)已从模拟记录执行原厂页面准备和距离格式化，并用原厂重画路径验证 9,999.4/9,999.5 米的文字与像素。续测已验证[距离缓存 `0x203D9E30` 写入及 GPS/UTC 数据源](IC705_GPS_INPUTS.md)，以及独立的 [VFO/Split 原厂入口和回读](IC705_VFO_SPLIT.md)。

## 其它可追的资源

| 资源 | J140 字符串地址 → 引用槽 | J132 字符串地址 → 引用槽 | 边界 |
| --- | --- | --- | --- |
| `Display Language` | `0x2035B828 → 0x202F0E20` | `0x2036F034 → 0x20304D50` | 同一记录含日文标签；显示语言、系统语言共用选项表，见下文。 |
| `RTTY Decode` | `0x20358860 → 0x202ED744` | `0x2036C098 → 0x2030169C` | USB(B) 设置标签，不能拿它当解调函数。 |
| `RTTY DECODE` | `0x203643DC → 0x2031ABA0` | `0x20377908 → 0x2032E774` | 已追到实际标题绘制和下方[正文入口](#rtty-正文的静态入口)。 |

「显示语言」与「系统语言」各有英文、日文标签和不同的状态地址字段，但引用同一张选项表（J140 `0x202ED520`，J132 `0x20301478`）。两版的四个表项依次为 `English`、`Japanese`、`英語`、`日本語`，即同一对选项的两套文字。这个观察可用于追踪语言选择与设置生效；四个字符串不代表有四种语言，也不证明可追加第三种语言。详见[汉化报告](LOCALIZATION_ZH_CN.md#第一页验证显示语言)。

用「表示言語」验证文字转换器。静态复算 `0x201DED50`（J140）及 `0x201DAA84`（J132）对应的索引和跳过区间：双字节尾字节 `0x40–0x7E`、`0x80–0xFC` 分别走 63、125 项一行的表。两张表的 J140 地址为 `0x20331124` / `0x20331D12`，J132 为 `0x20344A7C` / `0x2034566A`。两版均把 `955C 8EA6 8CBE 8CEA` 转为 `U+8868 U+793A U+8A00 U+8A9E`，与独立的 Python CP932 解码一致。[续测](IC705_LANGUAGE_FONT.md)确认「表」对应大字体字形 3136，并独立取得轮廓。此结果只覆盖已追到的菜单路径。

## RTTY 正文的静态入口

顺着同一个 `RTTY DECODE` 页面绘制函数越过标题，已识别**每行 83 字节的正文缓冲及重绘调用**。上游单比特接收、五位符号转换和缓冲写入已由下节的双版回放确认。

| 证据 | J140 | J132 |
| --- | --- | --- |
| 当前页面快照／用于比较的副本 | `0x204BD240`／`0x204C037C` | `0x204BD1A0`／`0x204C02DC` |
| 复制第 `i` 行的 83 字节；另复制 42 字节属性 | `0x201753B4–0x201753FC` | `0x20171998–0x201719E0` |
| 按 NUL 或 83 字节取长度；比较上次绘制的正文和属性 | `0x20175418`、`0x20175448`、`0x2017545C` | `0x201719FC`、`0x20171A2C`、`0x20171A40` |
| 把行文本、属性、长度交给行绘制器，再进入原有文字路径 | `0x201754C0 → 0x20174A60 → 0x2014289C` | `0x20171AA4 → 0x20171044 → 0x2013F180` |

正文字节取自当前快照 `+83×i`，属性取自 `+0x298+42×i`；42 字节可容纳 83 个四位属性，渲染前确实逐项拆出低／高半字节。行绘制器将正文的 CR/LF 在临时副本中换成空格。J140 `0x201752F4–0x201753AC` 根据页面样式遍历 4 或 8 行，属于渲染布局。快照地址取自函数常量池，交叉引用以双版 A32 指令验证。

## RTTY 从五位符号到正文

2026-11-13，确认两版主 CPU 从 GPIO 接收已判决的一位电平，再组装五位码和检查停止位。按 [RZ/A1H 端口映射](https://kernel.googlesource.com/pub/scm/linux/kernel/git/mchehab/linux-media/+/7fafb54c7d390e9b273a1d7d377e38d9c408046e/Documentation/devicetree/bindings/pinctrl/renesas,rza1-pinctrl.txt)和[读取引脚的驱动定义](https://android.googlesource.com/kernel/common/+/beeebffc807531f69445356180238500f56951cc/drivers/pinctrl/renesas/pinctrl-rza1.c)，`0xFCFE3200` 对应端口 0 输入寄存器 PPR0；固件提取第 5 位。两版用相同的字母／数字对照表，`27` 和 `31` 切换列，队列写索引在 16 个位置循环。

| 数据流 | 日版 1.32 | 日版 1.40 |
| --- | --- | --- |
| GPIO 采样入口 → 拼五位码、校验停止位 | `0x20115218` → `0x20115050` | `0x20118854` → `0x2011868C` |
| 五位码和有效标志（连续 RAM 字节） | `0x204986CB`、`0x204986CC` | `0x2049876B`、`0x2049876C` |
| 原厂转换入口，字母／数字表 | `0x20115408`、`0x2031FBB0` | `0x20118A44`、`0x2030BCA8` |
| 转换后存字节／更新索引 | `0x201154B4`／`0x201154C4` | `0x20118AF0`／`0x20118B00` |
| 通道 0 的 16 字节队列（控制块 `+0x30E`） | `0x203E1DB6` | `0x203E1E3E` |
| 消费队列 → 正文环形缓冲写入 | `0x2003B1D4` → `0x2003CF1C` | `0x2003C3C0` → `0x2003E108` |
| 复制正文和字符属性到绘制快照 | `0x20095764` → `0x204BD1A0` | `0x20096C14` → `0x204BD240` |

[回放脚本](../tools/probe_705_resource_paths.py)先调用原厂初始化和视口计算，验证正文尚无目标字符串。接着在虚拟 GPIO 输入合成起始位、数据位和停止位。原厂逻辑从十帧电平中完成数字／字母切换并生成八个字符；另给一帧错误停止位，原厂记录帧错且不入队。消费索引从 0 变为 8，原厂快照第 1 行第 1 列出现 `3CQ TEST`，八个四位属性都为 2。未预置符号、正文队列或绘制缓冲；本回放没有模拟物理时钟和中断，用合成视口宽度和零初始化字宽，不测排版或最终 LCD 像素。

这给 CW、FT8 的原厂文字显示提供可复现的对照。Icom [维修图](https://www.passion-radio.com/index.php?controller=attachment&id_attachment=787) 2021 年 5 月增补，PDF 第 41、45 页：`RTD` 从 IF DSP IC202 的 A10（`DATA8` 引脚）经 R219 连到主 CPU IC701 的 AA9（`P0_5`）。线路与原厂例程相符，确认这一路传的是单比特流。DSP 内部滤波和判决实现未核实。图纸副本的 SHA-256 为 `c1d9ff22383058aef6c51af697eb5e05b6e91ade109ed43005a557ff5166792a`。

同一维修图第 41、47 页另显示 `USB_AF` 到 USB codec IC1191（PCM2901E）的模拟输入，USB 数据线从 codec 接出。这给外部音频原型提供了明确路径，也说明不能把 PC 上能录 USB Audio 当成主 CPU 已有 PCM 缓冲的证据。**下一步沿原厂录音和 WLAN 音频各追一条数据链，找实际交给主 CPU 的 PCM，或确认走独立器件。** USB(B) 解码数据与日志分流未回放；SSTV 图像另见[原厂图片处理对照](IC705_SD_RESOURCES.md)。

## 复现

在项目根目录运行。提取命令要求输出目录不存在。脚本只读输入，写出 `bootstrap.bin`、`main.bin` 和 `manifest.json`；不会输出 DAT。产物留在 Git 忽略的 `.analysis/`。

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -m tools.decode_705_main firmware/705J140.dat .analysis/main-decode/repro-J140
& $py -m tools.decode_705_main firmware/705J132.dat .analysis/main-decode/repro-J132
& $py -m unittest discover -s tests -v

$boot = '.analysis/main-decode/repro-J140/bootstrap.bin'
$j140 = '.analysis/main-decode/repro-J140/main.bin'
$j132 = '.analysis/main-decode/repro-J132/main.bin'
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x18000000 --start-address=0x18000000 --stop-address=0x1800014C $boot
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20000000 --start-address=0x200044DC --stop-address=0x200049BC $boot
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x20005000 --stop-address=0x200050DC $j140
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x200B29D0 --stop-address=0x200B355C $j140
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x2021710C --stop-address=0x202174AC $j140
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x20212350 --stop-address=0x202126B0 $j132
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x2018AA70 --stop-address=0x2018AAE0 $j140
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x201751BC --stop-address=0x201751F0 $j140
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x20186EBC --stop-address=0x20186F2C $j132
arm-none-eabi-objdump -D -b binary -m arm --adjust-vma=0x20005000 --start-address=0x201717A0 --stop-address=0x201717D4 $j132
```

`objdump -D` 也会把常量池当指令打印；本报告按代码分支和引用把它们识别为数据。看 Thumb 除法时显式使用 `-M force-thumb`，从表述的地址读 44 字节。页表或字符串可直接在 `main.bin` 按 `地址 - 0x20005000` 读取。

REA MCP `inspect_byte_entropy` 复核两个日版解包产物的全文件 SHA-256。J140 Evidence `ev_fd1ee1f350df7859c447eb3723fa6b91ff802e49fba0967e5daecc6d257a7ae1`；J132 `ev_4de7dc028cd237cb53cc925b2d1c6035b13fae4ccebd3bc413680c77b2c8083e`。REA 6.8.0 CLI 用现有 GNU objdump 对 J140 复位段作定点复核：把 `main.bin` 的 `[0x60, 0xDC)` 按原字节包装为分析 ELF，地址 `0x20005060`，A32 指令和尾部常量池分别标注；回转成裸字节后哈希相同。证据 `ev_c62a2c2e9ee31d32306168e52e5ee07de6ef5663a9227539b2cfa861a5cf3274`，原始 JSON 在 `.analysis/main-decode/705J140/rea-reset-mapped.json`。MCP 进程的默认 `objdump` 启动失败，CLI 使用单次环境变量指向现有 Arm GNU 工具，没有改配置。REA 这里调用的是同一个 GNU 后端，不能算第二个反汇编器。需要进一步作交叉引用、反编译时，可用独立 Ghidra 以小端 ARMv7-A Raw Binary 分析 `main.bin`，基址 `0x20005000`、入口 `0x20005060`；该 Ghidra 路径尚未实跑。
