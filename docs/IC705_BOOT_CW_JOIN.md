# 日版 1.40：把 CW 回放接到冷启动之后

**日版 1.40 原厂版和 CW 版均已通过电脑虚拟闪存冷启动。** 下文区分在同一块虚拟闪存上的升级试验，以及两个版本各自冷启动的对照。所有实验均不生成 SD 升级包。

## 同一块虚拟闪存从原厂升级到 CW

电脑升级试验的起点是未改的日版 1.40，终点是同样基于日版 1.40 的电脑专用 `.ic705sim`，与从 1.32 升到 1.40 不同。先实际运行原厂引导和程序进入首页，再由电脑测试程序检查包，把 CW 写进**同一块虚拟闪存**的未启动区。切换前用原厂引导检查重启仍读原厂区；提交后再从空应用内存冷启，通过原厂引导读取它刚才写入的 CW 区，继续验证屏幕和解码。两个版本使用同一套合成设置输入；这不测试真实设置迁移。

2026-11-15 **验收通过**：原厂先从 `0x18010000` 开到首页和 `KEYER`，改坏包内主程序一个字节的对照被拒绝，虚拟闪存没有改变。有效包写入的 35 个虚拟扇区读回一致，未改变原厂启动区和共享区。提交前冷启仍从 `0x18010000` 装入并跳到原厂程序；提交后，从 `0x18600000` 装入并实际运行 CW 程序，来宾创建解码线程，原厂音频任务读完 2,827 组音频后 LCD 显示 `CQ`。仍有 `KEYER`；升级前、升级后及退出 CW 的首页逐像素一致。两个完整启动都没有写入持久设置。

对照也确认了原厂会随启动区改变读取资源的位置：例如启动检查读取 `0x18262000` 或 `0x18852000`，模拟器只跟踪其原始读地址。证据：[升级报告](../.analysis/cw-upgrade-1115/evidence.json)，SHA-256 `e0b3974c5c35fad67e81a73a8b3b52ab30b0d8794ae1a4e5e90e0b87551b6b99`；[升级后的解码画面](../.analysis/cw-upgrade-1115/cw_decoded.png)。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.replay_705_cw_upgrade firmware/705J140.dat .analysis/cw-packaged-boot-1115/J140-CW.ic705sim .analysis/cw-upgrade-1115
```

写入由**电脑测试程序**完成；没有把 CW 镜像放进原厂的 SD 升级程序。另一次由原厂更新程序写入虚拟闪存的测试使用的是[原封不动的 J140 官方包](SAFETY_AND_RECOVERY.md#用原厂日版-140-写入-虚拟-nor-并冷启动)。两个试验不能合并成「原厂接受 CW 包」的结论，也不能当成真实机器断电或独立恢复的证明。

### B 读失败时退回原厂 A

在同一块虚拟 NOR 的 A 保留原厂日版 1.40，B 装入现有 CW 电脑镜像。先按上述方法从 B 冷启动并解出 `CQ`，然后让模拟器拒绝读取 B 的主程序头所在页。首次重启仍选 B：原厂引导读不到 B 的头部，在解包前停下，主程序 RAM 仍为空，没有转去 A。

随后只由宿主在虚拟闪存里把启动选择切回 A，B 页保持不可读。原厂引导从 A 解出与官方 DAT 逐字节相同的主程序，显示首页；MENU 仍有 `KEYER`，EXIT 返回首页。首页、KEYER 菜单和退出画面都与安装 CW 前逐像素相同。未修补 B，也未重写 A 或共用区。

这验证了 B 的头部不可读时 A 的隔离和回退结果。开机选择由电脑提供，未实现机身电源键切换，未证明实体机能自动回退或引导本身损坏时可恢复。输出只有 [电脑报告](../.analysis/cw-ab-rollback-1115/evidence.json)（SHA-256 `01d46e64e93e0b83d6b28e793438eb2a0b903a230e7ae6d7ed22bfe48ea11b57`）和画面，包括[回退后的原厂首页](../.analysis/cw-ab-rollback-1115/rollback_home.png)，没有刷机包。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.replay_705_cw_upgrade firmware/705J140.dat .analysis/cw-packaged-boot-1115/J140-CW.ic705sim .analysis/cw-ab-rollback-1115 --rollback-test
```

### 原厂电源键不会改选 A/B

用日版 1.40 的未改引导从复位起跑了 12 组。A 固定为原厂，B 固定为 CW 电脑版；每一组默认选择下的闪存快照不变。只模拟按键由按下变为松开，并在故障对照中单独挡住 B 主程序头所在页的读取。以原厂代码实际读的地址或传给解包程序的来源判断它选了哪边，在解包前停止回放。

| 虚拟闪存状态 | 原厂实测结果 |
| --- | --- |
| 默认 A 或 B，两个位置均可读 | 立即松开、短按、提前一轮松开、持续按住到门槛，均读默认位置。 |
| 默认 A，B 的头不可读 | 短按和持续按住均继续读 A，到达解包入口。 |
| 默认 B，B 的头不可读 | 短按和持续按住均在读 B 时停下；应用 RAM 仍为空，没有转去 A。 |

持续按住 319,488 次轮询时，原厂设置供电保持；提前一轮松开则不设置。轮询次数仅用于模拟器对照，未换算成实体机的按键秒数。REA 单独核对了引导文件摘要（`ev_ed38178b53f69ca1dee4cc9b8cf60c71cb75b8b578e51aff74c173317439e346`），按键和选区结论来自原厂指令回放。可信范围限于该版引导的已模拟复位路径。

SQ6EMM 公布的长按切换属于其自定义引导。上一节已证明在电脑上选到 A 后能启动原厂；这一节排除了把原厂电源键当成该项恢复入口。接下来的恢复验收必须覆盖引导本身无法启动的情况，且能独立恢复原板；A/B 仅覆盖某个主程序出错的情形。

[12 组原始记录](../.analysis/cw-ab-stock-power-key-1115/evidence.json)，SHA-256 `30194d7f38d0213d3bdb5602b44378372d7b1bb9479ec850bb2e35367bdb1df9`。没有输出固件文件。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.replay_705_cw_upgrade firmware/705J140.dat .analysis/cw-packaged-boot-1115/J140-CW.ic705sim .analysis/cw-ab-stock-power-key-1115 --stock-power-key
```

## 虚拟闪存冷启动验收

2026-11-15：从空应用内存和原厂 NOR 复位向量开始，原厂引导自行复制第二段引导、选取并解包虚拟闪存上的压缩程序，再跳到应用向量。同一台模拟 CPU 继续运行到屏幕，不由宿主写入应用代码，也不在进入首页后挂接 CW。早期外设寄存器、电源键、闪存布局和后续外设都是目前这套电脑模型；不据此推断完整实机上电行为。

| 输入 | 原厂引导读出 | 屏幕和操作 |
| --- | --- | --- |
| 未改日版 `705J140.dat` 的原始压缩数据 | 3,558,076 字节，与独立提取的主程序逐字节一致 | VFO A／7.030 MHz／CW，MENU 有 `KEYER`，EXIT 恢复同一首页；与旧对照 8 张画面相同。 |
| 现有电脑专用 `J140-CW.ic705sim` | 3,576,236 字节，与包内主程序逐字节一致 | 进入 `CW Decode`，`CQ`／20 WPM；2,827 组模拟 DMA、212 个完整块。EXIT 恢复同一首页；与旧对照 10 张画面相同。 |
| 选定的虚拟闪存地址缺少主程序头 | 原厂引导读取失败，未进入解包，应用内存仍为空 | 没有进入 UI；排除了测试脚本在失败时补入主程序。 |

原厂引导的实测顺序为 `0x18000000 → 0x20004840 → 0x200044DC → 0x200049B8 → 0x20005000`；读取的主程序区起于 `0x18600000`。REA 复核原厂引导 SHA-256 的证据为 `ev_417d7250ab4f95c1c96a5fa734f2a1acd8170f95363ac60c3071325984572f31`。CW 主程序只在宿主内存里编码成供原厂解包器读取的流，写入虚拟映射；其他资源不被覆盖，原厂 DAT 和电脑镜像均未改。启动过程中保留现有模拟器浮点初始设置与原厂应用地址映射。

用和 CW 版相同的接收设置再跑一次[原厂版](../.analysis/cw-nor-cold-boot/stock-rx-control/startup-current-format.json)，两个首页的 PNG 逐字节相同，包括顶部状态栏。各组均无持久写入。证据：[精简对照](../.analysis/cw-nor-cold-boot/comparison.json)、[原厂启动详报](../.analysis/cw-nor-cold-boot/stock/startup-current-format.json)、[CW 启动详报](../.analysis/cw-nor-cold-boot/cw/startup-current-format.json)、[显示 CQ 的 LCD 帧](../.analysis/cw-nor-cold-boot/cw/boot-cw-decoded.png)。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-current-format --startup-home-probe --no-power-on-check --startup-input close-cw --startup-stock-mmu --startup-from-nor firmware/705J140.dat .analysis/cw-nor-cold-boot/stock
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-cw-image --startup-from-nor .analysis/cw-packaged-boot-1115/J140-CW.ic705sim .analysis/cw-nor-cold-boot/cw
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-current-format --startup-home-probe --no-power-on-check --startup-input close-cw --startup-stock-mmu --startup-cw-rx-ready --startup-from-nor firmware/705J140.dat .analysis/cw-nor-cold-boot/stock-rx-control
```

本节验证的是虚拟闪存已有固件后的启动。后续也已验证原厂更新程序读取未改官方包并从写后闪存启动；详情见[安装证据](SAFETY_AND_RECOVERY.md#用原厂日版-140-写入-虚拟-nor-并冷启动)。

## 打包镜像启动验收

- 产物：本地 [J140-CW.ic705sim](../.analysis/cw-packaged-boot-1115/J140-CW.ic705sim)，6,895,682 字节，SHA-256 `705e6b0041fbbbdb4752cadd834483b1d99b04d43594017efc81d16c1a5b7ece`。两次编译打包逐字节相同；修改包内主程序一个字节而保留原清单，加载时会拒绝。打包只读取官方 `705J140.dat`，不覆盖输入。
- 变更边界：校验原厂主程序 SHA-256 和五条原指令，只改这五个跳转，再附上同一套 CW 代码。REA 独立核对原厂主程序 SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`，证据 `ev_d40457f62540b996bef572dc801319b7e19f13e4ab2e3759b8f9f973a812d36f`。电脑启动代码区是本次仿真约定，未证明可在实体电台部署。
- [打包启动报告](../.analysis/cw-packaged-boot-1115/run/startup-current-format.json)记录原厂引导片段 `0x20004848`、主 CPU 复位入口 `0x20005060`、原厂地址映射保持开启、来宾写入 CW 状态指针、来宾工作线程实际执行。测试脚本没有开机后写入 CW 代码或用宿主跳转替代新增分支。
- [原厂未改对照](../.analysis/cw-packaged-boot-1115/stock-control/startup-current-format.json)只显示原厂 KEYER。打包版保留 KEYER，进入 `CW DECODE` 后逐组核对 2,827 组模拟 DMA 音频，处理 212 个完整块，LCD 画出 [CQ 与右侧波形和瀑布](../.analysis/cw-packaged-boot-1115/run/boot-cw-decoded.png)。机身 EXIT 返回与进入前逐字节相同的首页。和[旧的宿主挂接对照](../.analysis/cw-packaged-boot-1115/attachment-control/startup-current-format.json)相比，保存的 10 张 PNG 全部逐字节一致。
- 画布有五次像素提交，EXIT 时原厂 UI 归还其 22,104 字节分配块。整个空闲清单在前后仍有 824 字节净差，未将画布归还扩展为所有内存分配均恢复的结论。模拟保存只留在内存中。
- 边界：电脑预装已解包的主程序，借助已建模的外设和合成 EEPROM 记录启动。没有从实物 NOR 解包这个镜像，没有测真实副 CPU、电台功耗、物理接收或独立恢复。

复用检查：`samples/cw-arm.c` 是同一套译码逻辑；打包和旧回放共用 `probe_705_cw_session.build`、原厂任务的绘制函数、启动回放、PCM 校验和画布审计。日版源文件哈希直接引用解包器的定义，避免再维护副本。仍有一处有意保留的重复：可点面板用 Python 画底色和边框，ARM 原厂任务也画同样的背景。快预览与启动验证用途不同，背景有改动时以 ARM 提交的 LCD 帧为验收证据。

界面对照：用户的参考图对应[日语系统下的 CW 界面验收帧](../.analysis/cw-style-current/native/05-receiving-again.png)，正文为 `CQ TEST 123 DE IC705`。打包启动图和同一镜像的 HOME 比较，上面 140 行逐像素一致；和[未改原厂日版 HOME](../.analysis/cw-packaged-boot-1115/stock-control/boot-home-after-close.png)比，顶部状态栏也逐像素一致。上方的无线相关图标属于原厂界面，由模拟启动状态决定，不能据图认定联网。CW 版式仍以参考图的译文、波形、频谱／瀑布和五键为准；`和文` 跟随原厂系统语言为日语的条件。后续如需相同状态的截图，调整电脑仿真的输入，不从 CW 页面硬盖原厂状态栏。

在项目目录用既有 ARM GCC、Python 和 Unicorn 复跑（打包输出需为新文件）：

```powershell
$env:PYTHONPATH = ".analysis/ic705-emulator/deps"
py -3.14 -X utf8 -m tools.build_705_cw_sim firmware/705J140.dat .analysis/cw-recheck/J140-CW.ic705sim
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-cw-image .analysis/cw-recheck/J140-CW.ic705sim .analysis/cw-recheck/run
```

**上电到原厂 CW 首页与 KEYER 已通过。** 从未改的日版 1.40 连续启动后，原厂自行从读取到的设置恢复 `VFO A / 7.030 MHz / CW`，用机身 MENU 打开带 `KEYER` 的原厂第一页，再按 EXIT 回到逐字节相同的首页。该阶段不加载 CW 扩展。旧 [WX-00 对照](IC705_SD_RESOURCES.md#冷启动后用机身-menu-和-exit-导航)在同一版脚本仍给出逐字节相同的报告。合成存储中的擦除值造成 WX 显示，不能把它当作日版机默认行为。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-current-format --startup-home-probe --no-power-on-check --startup-input close-cw firmware/705J140.dat .analysis/ic705-emulator/j140-cold-cw-home-1115
```

通过三处模拟 EEPROM 输入把有效位、Weather 状态和 MENU 页恢复到本试验所需值：`0x3D3C0+11` 读 `00` 允许原厂取 CW 模式、`0x3D440+10` 读 `00` 清除以 `0x203EBC2C` 为来源的 WX 状态、`0x3BBC0+0` 读 `00` 选择 MENU 第一页。只清有效位的独立回放能显示 CW 并把 7.030 MHz 带入频率缓存，但 LCD 仍为 `WX-00`，见 `j140-bitclear-vfo-r2-1115/memory.json` 和 `boot-home-after-close.png`。只改前两处时，原厂模式查询已返回 `1`，但无效的 `FF` 标签页令 KEYER 分支未执行。加入第三处后，原厂运行 `0x2009280C`，LCD 确认画出 `KEYER`；菜单第 1503 周期送屏，EXIT 后第 2426 周期送屏，返回帧与无警告 CW 首页的 RGB565 哈希同为 `b167f7e769fc8162b69c2a6a6e681fd980deed0263acdda01118ac022cf0a06e`。持久写入 0。

证据目录 `.analysis/ic705-emulator/j140-cold-cw-home-1115/`：`boot-home-after-close.png`、`boot-stock-menu.png`、`boot-home-after-exit.png`、`startup-current-format.json`（SHA-256 `b4d01e800c144f0511231b2b527832d17ae1febabce79a1b88128103b40211c9`）。REA 对应镜像字节窗口：`ev_ea52a307d3af5da8cb32187327a3175f231cd2ffc3007212be3b603642865ba2`（切换 VFO）、`ev_97dc65f3e0957a78a59e88cf79b256be6f63ecda73e9d95d32ea36dcf522cf85`（MENU 模式分派）。本次原厂音频门的读回仍为 `0`，下一道验收是用原厂外设输入让它自然打开，再接解码和 LCD。

| 观察点 | 已知证据 | 接续验收 |
| --- | --- | --- |
| 首次原厂 HOME | 启动例程在 `0x2007AE04` 调用 `0x200964BC` 更新画面，随后在 `0x2007AE0C` 等待倒计时。隔离回放已看到原厂 `0x20095F78` 写入首页编号 `0x204BAB5D`。 | 记录第一次首页编号的原厂写指令，保留同一实例的 UI 任务句柄 `0x20380CC4`；以原厂翻屏后的 RGB565 帧和请求字段 `0x20380C8C` 归零为准，不以截图外观或页号单独当通过。 |
| 主循环 | 原厂正常分支 `0x2007B970 → 0x200D4E1C`；在 `0x200D4E3C` 设置首轮标志，`0x200D4EC4` 此后等到两次计时通知或首轮标志，主任务 `0x200D5114` 再调用 `0x200964BC`。 | 沿原厂调用进入主循环；保留 `0x20381E90` 当前任务、任务栈、异常向量和已经建立的图形及存储状态。首次 HOME 的验收独立于 CW 扩展，即使硬件事件调度先看到主循环入口再到 LCD 确认，也可先停留在原厂模式直到确认。 |
| MENU、触屏、EXIT | `0x200D4F54 → 0x2007F104`；触屏经 `0x201085FC → 0x20108550` 读来宾侧接收缓冲 `0x203E1F23`（按下状态 `0`，后接大端 X、Y；松开 `01 00 00 00 00`）。`0x2007F164 → 0x2007F010` 每次扫描一个键组；首字节 `0x203E1F1C`，MENU 为组 0 位 3，EXIT 为组 1 位 2。 | 初次接续可以在 `0x200D4F54` 的模拟输入边界提供按键和触屏字节，按键按下、释放各保持至少七个无触摸扫描轮次。原厂应自行选 MENU（`0x200927A4`）和首菜单（`0x200927D0`），再点 `(80,247)`；不写页号、不直接调用菜单处理函数。实体 EXIT 后帧应恢复原厂 HOME。上游外设接收包是否完整仿真另记。 |
| 收音与任务 | 应用通知由 IRQ 154（`MTU2+0x22C` 比较标志）发出，原厂软件中断 0 切换任务。IRQ 159 的 SSIF0 回调 `0x200FFC70` 读 `0xE82000E4`；位 0 表示通道运行，位 6 表示有 DMA 完成，位 7 选择缓冲。`0x200D4F74 → 0x20110384 → 0x2010FE04` 原厂取音，`0x2010FEAC` 的 `SP+8` 有六枚有效 PCM 样本。 | 无输入时给运行状态 `0x01`；有输入时把每批 72 个交错 32 位值写入 `0x20400800` 或 `0x20400920`，再分别给 `0xC1` / `0x41` 并送 IRQ 159。记录读写游标、主任务取到的 PCM 和新解码任务处理结果。检查原厂是否自行满足音频门 `0x2038026C`；隔离回放是直接设为 1，不能把它当冷启动已确认。 |

接续实现宜复用 [CW 编译与状态读取](../tools/probe_705_cw_session.py)的 `build(..., rtx=True)`、`read_session()` 与[原厂调度专项回放](../tools/probe_705_rtx_audio.py)中的扩展安装，而不复用后者的整个 `probe()`。后者会新建 CPU、入口栈、SVC 及显示映射，并预置音频门、VFO；冷启动已通过模拟 EEPROM 输入传入 VFO 记录，应只据原厂解出的模式决定能否打开 CW。首次冷启动 HOME 应在未挂接扩展的路径中先独立验收。

音频门有可观察的原厂写入点。主任务 `0x200D5090 → 0x200623F0 → 0x20062120` 传入声道索引 0；通常分支 `R5=0` 时，`0x200622D8` 向 `0x2038026C` 写入 `1 & ~(R7 >> 1)`。当收音门在冷启动回放中保持关闭时，先跟踪 `0x20062168 → 0x200CAE30` 的返回值和 `0x20062294 → 0x20117DC8` 的分支条件。这里确认的是指令和数据写入地点，尚无同一冷启动回放自行打开音频门的证据。采音检查点 `0x200D4F74` 早于本轮音频门更新，所以不应用第一轮取音证明门错误。

冷启动补充对照在上一个输入被原厂读取后才送下一组。10 组六采样点的 PCM 均经模拟 SSIF0 中断进入主任务，在 `0x2010FEAC` 按顺序逐字节一致；原厂收音门仍是 `0`。门控轨迹显示 `0x200CAE30` 返回 `1`，`0x20061528` 返回 `0`，随后替代条件读取值同为 `0`。门控与 PCM 到达是两个独立检查，不能以成功收到样本认定 CW 已解码。临时对照驱动 `.analysis/ic705-emulator/trace-j140-cold-audio-1115.py`，报告 `.analysis/ic705-emulator/j140-cold-audio-paced-1115/startup-current-format.json`（SHA-256 `d607437aa331cfc87224ffb7788e15b593592d3febe572bb137c55b9a4d5565e`）。本对照未挂接 CW 或更改门控。

**门控分支已定位。** 原厂连续启动的 18 次主循环观察中，`0x2006153C` 收到 `0x2002F13C` 的返回 `0`，因而没有走到 `0x2006154C` 对 `0x2010ACBC` 的调用。前者检查的 `0x203E84C0=0xF7` 对通道 0 已匹配，`0x203806F4=0x13` 的位 6 未置；后者所读的 `0x203809A1=0x40` 的位 6 已置，不能把这个镜像当作缺项。替代路径 `0x203806FC` 仍为零，两个原厂门写入点 `0x200622C8`/`0x200622D8` 记录到的值都为零。临时驱动 `.analysis/ic705-emulator/trace-j140-cold-gate-1115.py`，报告 `.analysis/ic705-emulator/j140-cold-gate-1115/startup-current-format.json`（SHA-256 `c87551fc6a428ee6d75630b7a55bd8d28d96a7635d1a74735f85a74e561bc3cf`，`audio_decisions`）。REA 校对的是字节窗口版本：`ev_feef4bd1d9225a7df3d3ba12ca524596dbcc991a77364dd6d253085f08919ec5`、`ev_08e8e51e22c52bfdc2311c58bb77097ab7cd4af2939ce3c68376a7dd907356bf`、`ev_b7550306a9a319d5a32d88c2da1078f16746e49e63a226389b44c147b66ca8f9`；分支证据来自 ARM 回放和 GNU 反汇编。

独立 CI-V 来宾回放（`.analysis/ic705-emulator/trace-j140-civ-sql-1115.py`）中，`15 01` 回复 `E0 A4 15 01 00 FD`，经原厂 `0x200254A0` 调用同一个 `0x20061528`；`15 05` 和 `14 03` 没有走该函数。[IC-705 原厂 CI-V 指南](https://www.icomjapan.com/support/manual/3064/)定义 `15 01` 为静噪状态，`1C 02` 为 XFC（发射频率监听）。实跑 `1C 02` 回复 `E0 A4 1C 02 00 FD`，命中读 `0x203806F4` 位 6 的原厂 `0x200265F0`。因此这个位和监听状态有关，不能为了让仿真出字而把它当普通接收使能。下一次分别观察正常 RX 开静噪及替代门 `0x203806FC` 的来源；即使电脑能画出 CW 页，也仍单独判定冷启动收音。

**已确认冷启动收音的两个外部输入。** CI‑V `14 03`（静噪电平）实跑经过 `0x20025290` 读 `0x203EB11B`；`14 02`（RF 增益）经过另一入口 `0x20025284`。冷启动从模拟 EEPROM `0x1CCC0` 的 32 字节记录取第 18 号字节（从 0 起），旧夹具填了 `0xFF`，原厂把它当作最大静噪；18 次观察均走进 `0x200B4758` 门限比较，替代条件为 0。只把模拟 GPIO `0xFCFE3210` 位 13 设为高（手咪 PTT 松开）后，原厂 `0x203809C4` 位 0 由 1 变 0，静噪仍关闭；再把模拟 EEPROM 此处改为静噪最小值 `0`，原厂替代条件和音频门都打开。主循环 `0x200D508C → 0x200B47D0 → 0x200B45F0` 在 `0x200B47B8` 更新有变化的替代条件，随后的 `0x200622D8` 实际写入收音门为 `1`。未直接写来宾静噪、PTT 状态或音频门。两组只读报告 `.analysis/ic705-emulator/j140-cold-rx-ptt-1115/startup-current-format.json`（`b46d10f237a829ad84e96493c8a523ffb34e001dcd374a97ad08d2c5c7e27c41`）和 `j140-cold-rx-both-confirm-1115/startup-current-format.json`（`a18ac36ce3bb609ad4004775c202b5e4fff319f9975692a1189006575d811b2b`），驱动 `.analysis/ic705-emulator/trace-j140-rx-squelch-source-1115.py`。REA 校对 J140 字节窗口 `ev_3f65fb041745ad3f55e9baf9f4d42ca930a2ba4f41083edd1f2d52bc92f8e3de`。以上报告未送入待解码音频。

**原厂图形调用修正。** 连续启动后原厂 RTX 成功创建了 CW 任务（句柄 `0x20499BD8`）。第一次画 `CW DECODE` 按钮时，来宾停在读 OpenVG 当前颜色的函数：入口误用了 Thumb `0x202632A4`（`sub sp,#20`），跳过 `0x202632A0` 保存 LR 的指令，所以调用返回到 `0x0`。额外给绘图栈 16 KiB 仍在同一处失败；寄存器与栈记录在 `.analysis/ic705-emulator/j140-cold-cw-attach-1115-vg.log`。扩展入口和电脑所用的图形适配入口均已校正，避免电脑回放继续把错误入口当成图形接口。

仅在原厂主任务上进入接续时，临时保留同一 CPU 的完整寄存器上下文和任务所有者。在来宾测试 RAM 放入扩展状态（`0x21001000`，4 KiB）、ARM 代码（`0x21008000`，16 KiB；载入后只读可执行）和双窗 RGB565 画布（`0x2100C000`，映射 24 KiB，使用 22,080 字节）。通过真实 Thumb 入口 `0x202D48C1` 创建解码任务：描述符在 `0x21001704`，包含 `<4I` 的 `cw_rtx_worker, 0xE8, 1, 0x1000`；校验结果句柄不是主/UI 任务，且 `handle+2` 的优先级为 `0xE9`，记录句柄到 `0x21001700`。调用结束恢复来宾寄存器，不重置任务内存；若发生意外抢占或留下软件中断，停止该次验收并记录原因。不要用会把系统栈设到通用 `SP` 的 `emulate_705.call()` 接管当前任务。

只在模拟器改变指令流，不改固件文件：挂接前读取并核对原厂四字节 `0x2007F10C` (`3a2502eb`)、`0x2007F1A4` (`d2f8ffeb`)、`0x2010FEAC` (`0040a0e3`) 和 `0x2013D4A8` (`30039fe5`)。第一处允许 CW 遮罩在真正触摸判定前拦截点按，免得误触隐藏菜单；最后一处是原厂 UI 合成帧到送屏前的扩展入口，之后仍用原厂显示提交。`make_surface(..., initialize=False)` 仍重设图形环境及字体状态，不能在活的冷启动实例上直接复用；冷启动验收应记录原来模拟 LCD 的实际 RGB565 缓冲内容。

**连续启动已画出首帧，尚未通过退出和收音。** 修正图形入口后，由原厂 Vsync 提交 CW 页，读取来宾 LCD 缓冲确认右下两窗和平线已出现。进入页时的同一次按压原来会误触第一软键；现在在释放前由 CW 消费。修正后重跑在第 2607 周期确认默认页 1，RGB565 SHA-256 `0edc9ac482dd182b896e18822ca4c854c88a4f1b644b14fc2699855a44b5b4a2`，见 `.analysis/ic705-emulator/j140-cold-cw-first-page-1115/{boot-cw.png,cw-first-frame.json}`。上半屏仍为 MENU；该次保留原厂收音门，CW 样本数仍为 0；EXIT 验收前停在仿真尚未覆盖的 SCIF 寄存器写 `0x20123260 → 0xE800800C`，未认定这是真机故障。独立回放增加了进入键持续按住三个扫描轮次的回归验收，并通过 19,864 组模拟音频、23 帧（`.analysis/cw-opening-press-check-1115/evidence.json`，SHA-256 `a0706f2bff222891dbee387c5152f212a9d429c9cdbe2d6c73823509cc40e3fc`）。绘图入口的 REA 原字节证据 `ev_82046cb3f033a33425b6e4c00c90bc43bafe7c797dc6440ed45c5e6b229053d2`。

**界面接续现已通过。** CW 入口沿原厂 RTTY 使用的路径 `0x200801E4 → 0x200EFE64(0)` 关闭菜单格，原厂自行更新上半屏。电脑侧将触屏和机身键样本移到 `0x2007F104`，即原厂触屏函数之前：CW 截住底栏触摸时，仍按时提供机身键样本。仿真仅接收 `0xE800800C` 的单字节 SCIF2 发送写入，不伪造对端回报（Renesas RZ/A1H 手册 §14.3.4；REA `ev_0272b5c300812075a361e8d190f1ab3ea54b86d319dffe5e3cb14c076461423b` 校对写入例程）。第 2278 周期，原厂提交 CW 首帧，自动断言上方 140 行和原厂 VFO 首页逐字节相同、底部变化、软键在第 1 页。原厂在第 3383 周期识别 EXIT，关闭 CW 后第 4726 周期送出与进入前完全相同的首页（RGB565 `b167f7e769fc8162b69c2a6a6e681fd980deed0263acdda01118ac022cf0a06e`），没有持久写入。关闭扩展的原厂对照报告 SHA-256 仍是 `b4d01e800c144f0511231b2b527832d17ae1febabce79a1b88128103b40211c9`；独立收音、发射暂停与显示回归通过（`.analysis/cw-stock-menu-close-1115/evidence.json`）。冷启动报告 `.analysis/ic705-emulator/j140-cold-cw-official-run-1115/startup-current-format.json`（SHA-256 `54a7c8d1738052770433eaf18a318cd7c6d0aadeadcc552d7aa9e082233dd77c`），同目录 `boot-cw.png` 为实际送屏帧。音频门与输入给 CW 的组数仍为 0。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-current-format --startup-home-probe --no-power-on-check --startup-input close-cw --startup-cw-decode firmware/705J140.dat .analysis/ic705-emulator/j140-cold-cw-verify
```

同一命令加 `--startup-cw-rx-ready`（换一个输出目录），即使用 PTT 松开和最低静噪的模拟输入。原厂在第 2285 周期提交 CW 页，第 3390 周期识别 EXIT，返回原来的首页。该轮读取音频门为 `1`、持久写入为 `0`，不送测试音。记录 `.analysis/ic705-emulator/j140-cold-rx-ready-authoritative-1115/startup-current-format.json`，SHA-256 `8886678109c89e1830be46568457ad5ce1e61dcd304812b9abedf981007d96ba`。

**同一次冷启动已经显示 `CQ`。** 2026-11-15 的连续实验先打开 `CW DECODE`，再经模拟 DMA 给原厂音频任务送入 600 Hz、20 WPM 的合成来报。以原厂取音位置逐字节校对（原厂读完前最多积压六组），没有跳过原厂调度、改写收音门、人工填译文或设置页号。短版本的末尾静音不足，192 块已送达但自动估速未出字；给足静音后，处理 212 个完整 10 ms 块，屏幕在第 7622 周期显示 `CQ` 和 20 WPM，右侧瀑布可见原信号。机身 EXIT 后首页和进入前逐像素相同。原厂提出的 38 次 VFO/设置保存只在模拟器的临时内存接收，无真实设备、储存写入或配置备份；未模拟 EEPROM 写时钟和写后读回。副 CPU 的实物应答仍未验证。先导实验 `.analysis/ic705-emulator/j140-cold-rx-cq-letter-gap-1115/` 有 `boot-cw-decoded.png` 和 `startup-current-format.json`（`d53ae32fbbbcd4d7016e264814cf31a73c10965b1c73d8ba0438edbf22e300eb`）。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-current-format --startup-home-probe --no-power-on-check --startup-input close-cw --startup-cw-decode --startup-cw-rx-test firmware/705J140.dat .analysis/ic705-emulator/j140-cold-rx-cq-verify
```

正式命令复跑 `.analysis/ic705-emulator/j140-cold-rx-cq-final-1115/`：校对 2,827 组原厂 DMA、正文区 113 个绿色像素；译文 LCD 帧 SHA-256 `6f65d05b799dc79f819c8c63af1dad496a64ed4ba71f9d11b2c8c8183c960ce9`（和先导相同），报告 SHA-256 `9e34e6dfd1c6a4e92e067e5c072f8b107caf1d7b05c3a1a8e802dc119be85aee`。新参数关闭时的旧界面报告与本次改动前逐字节相同（`54a7c8d1738052770433eaf18a318cd7c6d0aadeadcc552d7aa9e082233dd77c`）。

2026-11-15：[同一来宾的挂接函数](../tools/attach_705_cw_replay.py)已在原厂调度器实跑。它验证原厂指令、主任务和界面任务身份，保存 CPU 上下文，以当前来宾栈执行原厂任务创建，再恢复寄存器；没有在创建时抢占或产生额外调度请求。独立回放验证了新任务实际被原厂调度，收音和绘屏回归为 19,142 组模拟 DMA、1,427 次解码处理；`--cw` 也通过音频任务的抢占及退页重进。该回放仍使用隔离环境，没有把其画面当作从上电提交的首页。证据：`.analysis/cw-boot-attach-20261115/evidence.json` 与 `audio.json`。REA 复核主程序输入处理窗口和时钟初检窗口的版本身份：`ev_0bef5f022993c532aa7069ea10c6e9686fa5f448fe77674604827ba49ebfd52c`、`ev_b196d81787f196e4688e97b4650dd011522088ce17d6d4f76613e64671fa57a8`；执行和控制流结论来自 ARM 回放和反汇编。

REA MCP 在主循环窗口 `file[0xCFE1C, 0xD0128)` 复核了镜像身份（`ev_77621d39443de0118a317736377f819f5259f36cc2c69e3fecdb9793afc75ca2`）；指令和流程判断来自 GNU ARM 反汇编，可按原始窗口重查（下载及解包见[主程序记录](MAIN_CPU_DECODE.md)）：

```powershell
arm-none-eabi-objdump -b binary -m arm -EL -D --adjust-vma=0x20005000 --start-address=0x200D4E1C --stop-address=0x200D5120 .analysis/main-decode/705J140/main.bin
arm-none-eabi-objdump -b binary -m arm -EL -D --adjust-vma=0x20005000 --start-address=0x2007F010 --stop-address=0x2007F1B0 .analysis/main-decode/705J140/main.bin
arm-none-eabi-objdump -b binary -m arm -EL -D --adjust-vma=0x20005000 --start-address=0x200FFC70 --stop-address=0x200FFD48 .analysis/main-decode/705J140/main.bin
```
