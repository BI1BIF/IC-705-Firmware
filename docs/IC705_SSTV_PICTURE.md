# IC-705 PICTURE 与 SSTV 收发

## RX4-TX4 全模式发射

使用 TX PICTURE 从卡内选图并确认，点 MODE 在六页列表中选择发射模式，返回半屏点 SEND。Robot 36、Robot 72、Martin M1–M4、Scottie S1/S2/DX、SC2-180、PD50/90/120/160/180/240/290、BW 8/12/24、Pasokon P3/P5/P7 均可选。固件从原厂 320×240 预览生成各模式扫描线；选择更大的传输尺寸时，原图细节受预览分辨率限制。相对 TX3 主程序增加 3,488 字节，每次发射继续使用一份 150 KiB 图像快照。[完整波形对照](../.analysis/j140-sstv-rx4-tx4/tx-multimode.json)。

## RX4-TX3 弱信号续画与下方 SEND

SSTV 帧头中的 VIS 指明模式。Robot 36 每行 150 毫秒，整幅 240 行。收到有效帧头后，TX3 用行同步校正时钟，用行号确定交替的色差信号。短暂丢失行同步时，接收器按此前测得的行周期继续推进当前画布。信号恢复后重新对齐同步脉冲，保留前段，缺失的采样仍会显示为缺损。扫完 240 行结束；途中收到另一幅图的有效帧头，可以切换到新帧。进页时已错过帧头的 `MID RX` 仍从第一条识别出的完整行画起，绝对行号未知。这次续画针对有帧头的 Robot 36。

用同一张 SSTV02 山景 JPEG 经 pySSTV 生成 Robot 36，在第 81–104 行分别注入静音、宽带噪声。静音对照中 TX2 重新锁定后只画了 131 行；TX3 两组都只锁定一次，走完 240 行，第 1–78 行与第 109–240 行逐像素等于无损对照。单行反向分隔音、连续三个反向分隔音及连续五行分隔音被替换时，TX3 的整幅像素均与干净对照一致。这些是人为构造的损坏，现场具体损坏的样本待收音记录确认。

原 P 数字位置改为 `SEND`，点一下发送，再点取消；上方只显示接收状态。TX2 将原始手咪按键位也计作忙，单独该位即可在原厂仍报 RX 时阻止按钮。TX3 保留原厂请求过滤和发射判定；真正占用或禁止时分别提示 `TX ACTIVE`、`REMOTE TX`、`TX REQ` 或 `TX INHIB`，便于区分现场原因。

## RX4-TX2 屏幕一键发图

在 SSB、AM 或 FM 下进入 `MENU → PICTURE → SSTV`。点 TX 缩略图，通过 `TX SET → TX Picture` 选择 SD 卡 JPEG 并按 `SET`，在大图的 `MODE` 选 Robot 36 或 Martin M1。按机身 EXIT 回半屏，**点一次右侧的 `PICT TX` 就发一张**。无需连接手咪或按住 PTT。

点按后显示 `STARTING`，电台确认发射后显示 `SENDING`。一帧结束会自动撤销发射请求并回接收。发送中想提前结束，再点同一按钮即可。`TX BUSY` 表示已有其他发射请求或发射状态，`TX TIMEOUT` 表示本次请求等待超时，需要重新点按。

TX2 将本次发送请求并入原厂请求生成器，保留原厂过滤和状态发布。固件只在 DSP 确认发射后输出 PCM，最后两个 DMA 缓冲轮换完成后撤销本次请求。图像、电平和模式选择沿用 TX1。模拟卡、PTT 松开和模拟 DSP 反馈下的两种模式记录在[一键发图验证](../.analysis/j140-sstv-rx4-tx2/tx/evidence.json)。

## RX4-TX1 收发合包

日版 IC-705 1.40 的现场测试版在 RX4 和 CW D6 上加入 Robot 36、Martin M1 发射。解压 ZIP 后，卡内固件路径为 `IC-705/705J140.dat`。发射图片放在 `IC-705/Picture` 内，使用原厂支持的基线 JPEG；首次对照可用[已验证的 320×240 测试图](../.analysis/j140-sstv-rx4-tx1/tx/card/IC-705/Picture/Reverse.jpg)。

1. 选择 SSB、AM 或 FM，打开 `MENU → PICTURE → SSTV`。点半屏右侧 TX 缩略图，进 `TX SET → TX Picture`，选一张图并点 `SET`。
2. 回到 TX 大图，点 `MODE` 选 Robot 36 或 Martin M1。用机身 EXIT 回半屏，点 `PICT TX`。看到 `PTT READY` 后按住机身或话筒 PTT。Robot 36 约 37 秒，Martin M1 约 115 秒。
3. 一帧结束显示 `RELEASE`，松开 PTT 回接收。中途松开会停止，下次点 `PICT TX` 从头发。持续按住只发一帧。图像发送临时选用机内 WLAN 调制通道，原厂保存的输入设置保留。电平沿用 `SET → Connectors → MOD Input → WLAN MOD Level`。该设置的原厂说明见 [Icom 基本手册](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)。

主程序在原厂有效调制输入计算处 `0x20060D28` 选择 WLAN。原厂继续判定发射条件、发布 DSP 控制和选择 SSI0 第二槽。每次 TX DMA 完成，`0x200FFD48` 服务 36 帧。SSTV 在 `0x200FFEB0` 填入该槽的 36 个有符号 16 位采样，沿用原厂全速档增益 10922，随后原厂乘法、双槽交错和缓存清理照常执行。DMA 两个源缓冲为 `0x20400A40` 和 `0x20400B60`，各 288 字节，目的地均为 SSI0 的发送 FIFO `0xE820B018`。日版原厂调制输入枚举可与 [Icom CI-V 手册](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf)对照。

模拟面板从两个 DMA 缓冲的第二槽提取连续音频，独立解码器自动识别并还原 Robot 36（320×240）和 Martin M1（320×256）。另测松 PTT、退出待发页、长按单帧、恢复原调制源、收音重新入队和普通 WLAN 已知音频的逐样本对照。实体 SD 卡及另一台接收机的射频解码留给现场验收。[调制出口数据和回读图](../.analysis/j140-sstv-rx4-tx1/tx/evidence.json)。

## SSTV 发射选图与模式（2026-11-19，电脑原型）

从半屏右侧 TX 缩略图进入大图，点 `TX SET` → `TX Picture`，在原厂浏览器翻看 SD 卡 `IC-705/Picture` 下的 JPEG。`SET` 确认当前图片，机身 `EXIT` 放弃这次浏览。SSTV 大图右侧的 `MODE` 选择 Robot 36 或 Martin M1。回半屏点 `PICT TX`，显示 `PTT READY` 后等待发射状态。未确认照片会提示 `SET PHOTO`。原厂 DV 大图同一位置仍可进入 `BLOCK`。原厂卡图的准备方法见 [Icom Picture Sharing 手册](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_IC-9700_Picture_Tx_ENG_IM_2_20200526.pdf)。

日版 1.40 原厂选图页为菜单 279。`0x200f3a10` 读取当前目录项，`0x200c22c0` 提交预览请求，原厂 JPEG 任务在 `0x2064b584` 输出 320×240 RGB565。确认回调 `0x200c4f5c` 保存文件名，`0x200c231c` 能以已保存的文件名重载。电脑用两张互为镜像的色条 JPEG，确认第二张、再浏览第一张并退出；随后重载的预览和发射快照均逐字节等于第二张。目录缓存、SD 文件服务和 JPEG 任务调度由宿主提供，文件路径、解码像素、画面和按键来自 ARM 执行。

准备发射时复制已确认的 TX 画布。模拟 DSP 已发射状态后，宿主分块取出 ARM 编码的 48 kHz 单声道 PCM。松开 PTT 中止，重新准备后从帧头开始；持续按住只产生一帧。独立软件按 VIS 自动识别并回读两张整图。另外用 Robot 36 行解码器和 Martin M1 像素中心测频，分别核对与已选图像的颜色误差。下表误差为每个 RGB 通道绝对差的平均值，量程 0–255。

| 模式 | 回读尺寸 | 含帧头时长 | 整图误差 | 末四行误差 |
| --- | --- | ---: | ---: | ---: |
| Robot 36 | 320×240 | 36.910 秒 | 6.66 | 7.02 |
| Martin M1 | 320×256 | 115.200 秒 | 1.40 | 1.39 |

上表保留最初直接从编码器读出的结果。[原型选图画面](../.analysis/sstv-tx-picture/accepted/Reverse-picker.png)、[模式菜单](../.analysis/sstv-tx-picture/accepted/mode-picker.png)、[编码器记录](../.analysis/sstv-tx-picture/accepted/evidence.json)。当前调制输出和复现命令见本页 RX4-TX1 记录。

## RX4 中途接收、行时钟与 SD 保存

收到有效 VIS 时仍按它选模式。没收到 VIS 时，根据连续四个匹配的行周期和同步脉宽选模式，Robot 36 还核对交替出现的色差分隔音。在中途接收时，画面从捕获的第一条完整行画起，半屏可显示 `MID RX`。Martin M1 与 M3、M2 与 M4、黑白 12 与黑白 24 分别共用行时序，所以缺少 VIS 时只能识别到对应的模式组并按较高分辨率的预览高度显示。

Robot 36 用实测的相邻同步间距修正该行的像素采样位置和估计频率。单次同步中断沿用上次周期。回归测试先保留真实 VIS，再把其后的图像采样时钟改为标称值的 98%、99.4%、100.6% 和 102%。验证收满 240 行，以及第 20、60、100、140、180、220 行色条边界的横向位置。已知的一次色差分隔音损坏及短同步断裂继续纳入回归。

收图停下后，点 RX 缩略图进入大图，点 `SAVE/HIST` → `SAVE`。已保存的图从同一个菜单里的 `SSTV 1` 至 `SSTV 8` 打开。文件保存在 SD 卡的 `IC-705/Picture/SSTV0001.BMP` 至 `SSTV0008.BMP`。保存的是 320×240 的机内预览，旧文件保留，槽满会提示 `Album full`。模拟面板使用虚拟文件服务验证按钮、无卡提示、BMP 像素、回读和截断文件保护。实体 SD 卡的写入和断电后回读待验证。

构建入口 `tools/build_705_cw_sstv_rx.py --late-join`。交付证据目录 `.analysis/j140-sstv-rx4/`，其中 `rx3-lines.json` 增加了时钟偏差对照，`multimode.json` 与 `mid-frame.json` 分别记录完整帧和去除帧头后的模式回放，`verification.json` 记录保存与历史。行时序识别可与 [Robot36 Android](https://github.com/xdsopl/robot36) 对照，跨行时钟校正可与 [F4JTV/sstv_decoder](https://github.com/F4JTV/sstv_decoder) 对照。

## RX3 多模式接收

日版 IC-705 1.40 的 `705J140-CW-D6-SSTV-RX3-MULTI.zip` 放在 `.analysis/j140-sstv-rx3-multi/`。ZIP 内路径为 `IC-705/705J140.dat`。进入 MENU → PICTURE → SSTV 后根据 VIS 自动选择接收模式。

| 系列 | 模式 |
| --- | --- |
| Robot 彩色 | 36、72 |
| Martin | M1、M2、M3、M4 |
| Scottie | S1、S2、DX |
| PD | 50、90、120、160、180、240、290 |
| Wraase | SC2-180 |
| 黑白 | BW 8、12、24 |
| Pasokon | P3、P5、P7 |

用 [Robot36 Android](https://github.com/xdsopl/robot36) 核对 VIS 模式、色彩通道和同步结构，使用 [pySSTV](https://github.com/dnet/pySSTV) 的发射时序生成测试音频。PD50、Robot 72、黑白 12 和 Martin M3/M4 使用单独的测试编码表和 pySSTV 基类。新增解码支持逐行 RGB、跨两行共享色差的 PD、逐行 YCrCb 及黑白。Scottie 在蓝、红通道之间重同步。高分辨率源图按 320×240 在机内预览，大图元数据报源尺寸。

Robot 36 对短暂断裂的行同步使用预期 150 ms 行时钟，在下一条完整同步脉冲时重新对齐。单个不明确的色差分隔音可按当前行奇偶继续。整段行同步不可用显示 SYNC，确认色差顺序反转或连续损坏显示 COLOR。对照 RX2 在模拟损坏位置停在 2 个源行，RX3 在同样的输入下完成 240 行。真机上是否由同类损坏引起，待现场复测。

构建使用 `tools/build_705_cw_sstv_rx.py --basic`。23 种整帧码型回放使用 `tools/probe_705_sstv_multimode.py`。另回归 CW D6、原厂双槽引导、半屏放大与返回、Robot 36 和已录制的 Martin M1。证据分别保存在交付目录的 `multimode.json`、`rx3-lines.json`、`verification.json` 和 `boot-slots.json`。

## RX2 低电平接收与现场诊断

用户反馈 RX1 在 FM 下始终显示 SSTV AUTO。用已交付 RX1 的 ARM 代码回放同一段 Robot 36 的前三秒，将输入 PCM 峰值设为 300、700、1500 时，输入块全部处理而帧头均未锁定。3000、15000 均能锁定并画 12 行。原估频器取 16 位样本的高 8 位，低电平时的量化误差和能量门限影响判频。

RX2 在候收时根据 48 ms 的原始峰值调整估频器输入倍率，锁定后保持，超出范围的块立即恢复原倍率。半屏下方显示的 P 数字始终是缩放前的 PCM 峰值（每 512 块约 0.38 秒更新）；NO PCM 表示本次进页还没收到采样，QUEUE 表示已收到但尚未处理，P 0 表示已处理的测量窗全零。另一个按钮可显示 GAP（本次进页发生过丢块）、PARITY、VIS 编号或 LOST。诊断提示仍为只读。原始 PCM 峰值 300、700、1500 都已锁定；700 的整图完整 240 行，静音未锁定。现场 FM 取音、真实信号幅度和帧头质量尚待测。

交付目录 `.analysis/j140-cw-sstv-rx2-field/`；证据 `pcm-levels.json`、`verification.json`、`boot-slots.json`；RX1 对照在 `.analysis/j140-cw-sstv-rx1/pcm-levels.json`。构建选项为 `--diagnostics`，幅度回放工具为 `tools/probe_705_sstv_rx_levels.py`。

## 日版 1.40 合并接收测试包

2026-11-18 打包原 CW D6 和 SSTV RX1。交付目录 `.analysis/j140-cw-sstv-rx1/`。ZIP 只含 `IC-705/705J140.dat`，适用于日版 IC-705。DAT 长 12,259,086 字节，SHA-256 为 `a05d5968e28babd1a162872ba02d8d233be4949cd49cbfefc69a7999f4834692`。原厂版本显示仍为 1.40。构建入口为 `tools/build_705_cw_sstv_rx.py`。

从交付 DAT 解出的主程序已在 ARM 模拟器上验证。原厂调度器分别创建 CW 和 SSTV 线程；Robot 36 完成 240 行，共 50,880 个六采样块，零丢块。完整 Robot 36 后接收 Martin M1、Robot 36 第 17 行中断后接收 Martin M1 均完成 256 个源行，两次成图一致。CW 经同一采音入口处理 2,827 块，译文为 CQ。SSTV 半屏显示 RX ONLY，两个发送触区均未进入原厂 DV 发送处理。内存不足显示 RX unavailable，退出后再次进入可恢复，离页释放画布。两个模拟 NOR 槽都经原厂引导解压到同一主程序，A 组共享数据与原厂逐字节相同。证据为交付目录的 `verification.json`、`boot-slots.json`、`heap-reentry.json`。

待真机确认：从完整 VIS 开头分别收 Robot 36、Martin M1，检查半屏和大图之间切换时扫描进度，退出后在 CW 模式从 KEYER 打开 CW DECODE。合包尚无真机写入、接收和故障恢复记录。

2026-11-18。此功能线从日版原厂 1.40 开始，独立于 CW D5。第一版选用 Robot 36，接收和发送的参考分辨率均为 320×240。原厂负责触控、画布和视图绘制，新增的音频处理负责识别 SSTV 信号、生成扫描行和编码音频。

## 双模式自动接收（2026-11-18）

日版 1.40 模拟器的 ARM 解码器读取 7 位 VIS 和偶校验，识别 Robot 36（8）和 Martin M1（44）。进页半屏显示 SSTV AUTO，锁定后显示模式名，收完保留成图并监听下一帧。中途失步时半屏恢复 AUTO。点 RX 打开大图后，右侧显示实际模式和源图尺寸。

| 同一会话的输入 | 结果 |
| --- | --- |
| 完整的 Robot 36，再播放独立项目的 Martin M1 录音 | 依次解出 240、256 行。共处理 206,624 个原厂音频块，零丢块 |
| Robot 36 第 17 行截断，插入 0.6 秒静音，再播放同一段 M1 | 第二次识别成功，M1 的完整 RGB565 画布与上一组逐字节相同 |
| M1 第 80 行点 RX 放大，第 160 行按 EXIT 返回 | 切换前后计数一致，随后接收完整。256 个源扫描行映射到 240 行 LCD，最后 16 个源行的画布写入单独检查 |
| 校验错误的 VIS 8、校验正确但未支持的 VIS 12 | 保留已完成的图像，未产生新锁定 |

M1 回放使用 colaclanth/sstv 自带的 `examples/m1.ogg` 和 `m1.png`。ARM 大图与缩放后的独立参考图之间 RGB 通道平均绝对误差为 20.24/255。输入经过单声道混合及重采样，送入模拟的原厂 48 kHz 音频链。两段切页测试在测试程序调度下运行 ARM 工作任务，另用原厂 RTX 调度器回归了 Robot 36。实机性能和弱信号容限待测。

[M1 半屏接收到第 160 行](../.analysis/sstv-auto-rx/complete-then-m1-160.png) · [M1 完整大图](../.analysis/sstv-auto-rx/complete-then-m1-detail.png) · [双模式数据](../.analysis/sstv-auto-rx/evidence.json)

## 半屏与大图操作路径（2026-11-18）

选择 MENU → PICTURE → SSTV 后打开原厂半屏 PICTURE（菜单 21）。RX 在左侧 160×120 缩略图里自上而下更新，每解出一对 Robot 36 扫描行就可显示一行缩略图。点击 RX 打开 320×240 的 RX PICTURE（菜单 274）。大图按 EXIT 返回半屏，半屏再按 EXIT 才结束这次接收。空图也能点开和返回。点击 TX 图片区时，无卡条件下出现原厂缺卡提示，EXIT 可关闭提示并继续留在半屏。

同一份录音第 60、120、180、240 行各从一个视图切到另一个视图，核对切换前后的行数、已绘出的色卡、剩余黑区以及半屏的 TX 和按键区域。原厂缩略图和大图读取同一份 ARM 解码画布。信号经 50,880 个音频块解出 240 行，队列丢块为 0。模拟器补全了原厂缩放所用的 OpenVG 像素读取。独立原厂 RTX 回放核对相同的最终画布。动图按操作节点选帧，播放速度不代表真机刷新率。带卡选图、SSTV 发射和真机运行另行验收。

[切页动图](../.analysis/sstv-panel-rx/panel-navigation.gif) · [第 120 行半屏](../.analysis/sstv-panel-rx/half-120.png) · [同一时刻大图](../.analysis/sstv-panel-rx/rx-120.png) · [ARM 回放数据](../.analysis/sstv-panel-rx/evidence.json) · [原厂与 DV 对照](../.analysis/sstv-panel-rx/stock-comparison/evidence.json)

## 此前直接进入大图的 ARM 接收验收（2026-11-18）

日版 1.40 模拟器回放 48 kHz 色卡音频，经原厂音频链降采样到 8 kHz。新增 ARM 任务从每块 6 个样本中检测 VIS 8、恢复行同步和交替色差，把像素写入独立的 320×240 RGB565 画布。原厂 RX PICTURE 绘制该画布。

| 回放 | 实测结果 |
| --- | --- |
| 从 MENU 进入 SSTV，分段查看画面 | 60、120、180、240 行截图依次通过核对，尚未接收的区域保持黑色。最终 RGB 通道平均绝对误差为 5.04/255。该回放由测试程序定期调用 ARM 工作任务 |
| 中途按机身 EXIT 并重新进入 | 第 17 行退出时队列中还有 3 块。退出后继续送入 8 块，旧会话的计数和画面均未继续更新。重新进入后完整接收 50,880 块、解出 240 行，丢块为 0。原厂 DV 图像缓冲区保持完整 |
| 独立验证原厂 RTX 调度 | 从已选中 SSTV 的会话开始，原厂调度器通过音频事件运行解码线程 8,480 次。50,880 块全部处理，队列峰值 6 块，最终画布与界面回放逐字节相同 |
| 队列过载对照 | 暂停消费，向 32 块队列送入 40 块，实际记录丢失 8 块，解码器进入失步状态 |

本轮使用模拟器分配的约 160 KiB 地址空间，另配 4 KiB 线程栈。真机的内存余量、连续运行耗时和实际射频录音仍待验证。当前支持单张 Robot 36，收完或失步后需要退出并重新进入。

[最终画面](../.analysis/sstv-arm-rx/rx-240.png) · [两次回放及过载对照数据](../.analysis/sstv-arm-rx/evidence.json) · [ARM 解码器](../samples/sstv-j140-rx.c) · [音频和绘图接点](../samples/sstv-j140-rx.s)

## 早期界面和电脑端编解码验收

| 项目 | 输入及操作 | 本轮结果 |
| --- | --- | --- |
| 同一个 PICTURE 图标 | 在 ARM 模拟器按机身 MENU，点第二页，再点左下角 PICTURE | 打开原厂样式的 DV / SSTV 选择器。直接按机身 EXIT 可取消 |
| DV | 点第一项，与独立的原厂镜像执行同样导航后比较 | 回到原厂 PICTURE。菜单号、文字和整帧 PNG 一致。对照范围到第一页 |
| SSTV | 点第二项 | 原厂 RX PICTURE 打开。实测菜单号 274、页面状态 0x36。旧记录里的隔离表项不能直接当作 MENU 实际导航结果。机身 EXIT 返回主画面 |
| 接收 | 同一份 J140 原厂 ARM 录音链路回放的 8 kHz 单声道 PCM | 新增电脑端参考解码器检测 VIS 8、行同步和交替色差，每两行送入模拟电台一次。四次重绘分别覆盖 60、120、180、240 行。每次都核对 76,800 个可见像素，含未接收的黑色区域 |
| 信号对照 | 比较原色卡，另测单音、损坏帧头和中途丢同步 | 8 kHz 干净回放的 RGB 平均绝对误差 2.38/255。单音和擦除奇偶校验位各产出 0 行。删除第 13 行同步后只返回前 12 行 |
| 编码 | 从 320×240 图片文件生成 48 kHz 单声道 WAV | 色卡输出和[已用独立 QSSTV 验证的音频](IC705_SSTV_REPLAY.md)逐字节相同。电脑参考解码器回读 240 行，平均误差 2.67/255 |
| 发图选择器 | 在原厂 PICTURE 页点 TX 图片区 | 无卡环境得到原厂的缺卡提示。带卡选图、取出原厂已解码的预览像素仍待验证 |

![PICTURE 选择器](../.analysis/sstv-picture-start/accepted/chooser.png)

![原厂 RX PICTURE 上的 Robot 36 结果](../.analysis/sstv-picture-start/accepted/sstv-rx.png)

截图由原厂 ARM 绘图程序和电脑 OpenVG 模型共同生成。当前画布右侧仍显示 DV 的呼号、尺寸、质量和 HISTORY 等控件。SSTV 的行数、模式、保存及 TX 控件尚待接入。

## 早期界面回放的实现边界

新增 A32 选择器回调在模拟器专用内存执行，沿用 CW 已验证的两行描述符和延迟回调机制。默认 CW 描述符的 20,194 字节与 D5 对应区完全相同。SSTV 选择不会切换电台 RF 模式，模拟器没有执行发射。

RX PICTURE 的正常绘制读取 153,600 字节 RGB565。实验由宿主将新解出的行写入模拟缓冲区并请求重绘，原厂程序完成 320×240 绘图和 480×272 最终合成。电脑字体分配器已在本次回放中避开旧位置与该缓冲区的重叠。实机上 DV、SD 任务和 SSTV 对缓冲区的占用、接管及恢复仍待验证。

## 多模式调研（2026-11-18）

现有 `valid_vis()` 将收到的帧头与固定编号 8 逐位比对，`decode_rows()` 在一幅图完成或失步时返回。`encode` 固定调用 `robot36()`。目前电脑端可自动起收一幅 Robot 36，尚无连续守候、多模式分派或 TX 模式选择。这里只记录调研，不改变已验收的收发范围。

| 参考项目 | 对本项目的用途 |
| --- | --- |
| [xdsopl/robot36](https://github.com/xdsopl/robot36) | 实时接收体验和独立解码对照，覆盖 Robot、Martin、Scottie 和 PD 等模式 |
| [colaclanth/sstv 的解码器](https://github.com/colaclanth/sstv/blob/master/sstv/decode.py) | `_decode_vis()` 读模式位、检查偶校验，再由 `VIS_MAP` 选择解码方法。可用来核对通用帧头检测 |
| [dnet/pySSTV 的彩色编码器](https://github.com/dnet/pySSTV/blob/master/pysstv/color.py) | 可为 Martin M1、Scottie S1、Robot 36 和 PD120 等分别生成独立 WAV。各模式有不同的扫描时序、通道顺序及图像尺寸 |

建议 RX 默认 AUTO，识别后显示模式名。遇到缺失帧头可提供手动指定模式，后续以单独的行同步测试核实中途接收效果。TX 的模式列表仅展示已经通过独立回读的编码器。PD120 的源图为 640×496，原厂 320×240 画布需单独处理预览缩放。这些都是后续设计。

## 下一项验收

1. 真机从 SD 卡选择同一张 JPEG，在第二台接收机上分别解出 Robot 36 和 Martin M1，核对颜色、方向和图底。再验证中途松开 PTT 后恢复收音。
2. RX4 的现场项目仍是完整收图行对齐、中段起收，以及实体卡保存后重启回读。

## 复现

ARM 回放需要带有 clang、lld 和 LLVM 二进制工具的工具链。在项目根目录执行，按本地安装位置调整编译器路径。

```powershell
$env:PYTHONPATH='.;.analysis/sstv-deps;.analysis/ic705-emulator/deps'
$cc="$env:USERPROFILE/.codex/ndi-android-toolchain/sdk/ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
& .venv/Scripts/python.exe -m tools.build_705_cw_sstv_rx .analysis/rx4-tx1-rebuild --clang $cc --tx
$r='.analysis/sstv-robot36-v1'
& .venv/Scripts/python.exe -m tools.probe_705_sstv_arm firmware/705J140.dat "$r/robot36.wav" "$r/reference.ppm" .analysis/sstv-auto-rx --clang $cc --martin .analysis/sstv-colaclanth/examples/m1.ogg
```

从项目根目录运行。输入录音可按[录音回放记录](IC705_SSTV_REPLAY.md)重建。编码与解码命令要求输出文件尚不存在。

```powershell
$env:PYTHONPATH='.;.analysis/sstv-deps;.analysis/ic705-emulator/deps'
$d='.analysis/sstv-picture-start'
$r='.analysis/sstv-robot36-v1'
& .venv/Scripts/python.exe -m tools.probe_705_sstv_picture firmware/705J140.dat "$r/guest/705J140-robot36.wav" "$d/accepted"
& .venv/Scripts/python.exe -m tools.sstv_robot36 encode "$r/reference.ppm" "$d/my-tx.wav"
& .venv/Scripts/python.exe -m tools.sstv_robot36 decode "$d/my-tx.wav" "$d/my-rx.png"
```

界面、取消、接收退出和四次像素比较见 `.analysis/sstv-picture-start/accepted/evidence.json`。音频对照及 CW 默认表复核见同目录 `codec.json`，复核脚本为 `.analysis/sstv-picture-start/verify.py`。
