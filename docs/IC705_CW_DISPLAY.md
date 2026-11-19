# 日版 1.40：CW 出字和原厂 MENU 入口对照

2026-11-14。**电脑上已把 CW 录音解出的文字送进原厂 RTTY 页面并绘制出来。也已确认 CW 和 RTTY 使用同一个随模式变化的 MENU 按钮，分别打开 KEYER 和 DECODE。** 这两项使用原厂 J140 的 ARM 指令；未更改 DAT，未访问电台。

## D5 四行译文与绘图优化

2026-11-18。**D4 真机已确认两小窗不再撕裂；上方频谱/S 表和小窗仍掉帧。** 本轮同时完成用户新增的两项要求：移除正文下面两行白色收音诊断；译文满四行时整体上移一行，底行继续写。电脑验收后，已按用户要求直接封装[同一 D5 的日版 1.40 DAT](IC705_CW_RELEASE.md#d5-显示与四行译文测试版)，主程序逐字节一致；未操作电台、未重测升级或开机。

| 项目 | 实际改动 | 验收结果与范围 |
| --- | --- | --- |
| 删除白字 | 删除收音状态和 RAW/TAP/IN/OUT 两行的绘制，底层采音及计数保留。原位置改为正文第 3、4 行。 | 精确绘制调用中已无这些文字；两 bank、空正文/16 字正文对照，每帧少 2 次文字 API 和 45 个诊断字符。 |
| 四行整行上滚 | 原厂比例字宽和字号不变，基线为 y=182/198/214/230。需要第五行时删除完整第一行，其余三行上移，空出的底行接收新字；不逐字符挤走旧正文。 | 填满四行后追加字符、底行继续、连续词、1000 个无空格字符、最窄字符四行 328 字通过。真实原厂字库绘图见下面三张裁图。 |
| HOLD、CLR 与退出 | 冻结显示时后台继续收字，解除后显示最新四行。长按 CLR 清除两份正文；从取样时保存文字版本，阻止清屏前的解码结果随后写回。 | 14 项针对性 ARM 检查通过，包括真实编译 worker 解出 E 后、追加入口及布局执行中的真实长按 CLR 抢占；两种窗口均无旧字回写。 |
| 小窗计算 | 清屏改为对齐的双像素写入，预计算频谱坐标和调色表。保留 D4 缓存清理、屏障及原厂提交。 | 15,000 样本／41 快照与 D4 和独立 Python 参考全部逐像素一致，无越界、共享快照均持锁。40 次重画光栅指令合计 6,617,059→3,687,545（减少 44.27%）。 |
| 小窗刷新 | 普通刷新门限 120→80 ms；关键状态变化仍立即更新，不降低音频取样和解码速率。 | 同 2.12025 秒、2,827 组 CQ，30/60 Hz 外部绘制下实际重画 16→21/26 次；总光栅指令减少 25.59%/6.97%，零丢组、CQ 不变，毫秒回绕也通过。80 ms 是软件门限，不是实体 LCD 帧率。 |

四行演示使用候选的真实 ARM 行布局和日版 1.40 原厂字体/绘制指令，再由离线 OpenVG 光栅模型绘图。图片只裁出左侧正文区域，测试文字是人为填入的数字，不能当成真实来报解码或全机启动截图：

- [四行填满](../.analysis/cw-smooth-1118/text/native-font/01-four-full-rows.png)
- [整行上移，底行开始新字](../.analysis/cw-smooth-1118/text/native-font/02-scrolled-one-row.png)
- [底行继续接收](../.analysis/cw-smooth-1118/text/native-font/03-bottom-row-continues.png)

候选为 `.analysis/cw-smooth-1118/text/CW-TEXT3-PC.ic705sim`，bundle SHA-256 `5ac48137bf83b6149eb76e6c9b4ea661968c453f583c073846f8f2c9a6b8d20d`，main `e96d1ffc67200ebda10321ead42bf6a3546f48b906e9d6197f0ec4747415105f`。TEXT2 曾有 CLR 旧字回写窗口，只作为历史证据，不可交付。C/汇编/像素表的指纹及精确 ELF、BIN、完整静态符号和最终测试均保存在同目录。接收状态分配从 4 KiB 增至 5 KiB，其中新增 824 字节保存 live/held 页面及行位置；原字段偏移和工作线程 4 KiB 栈保留。分配/清零的局部成功、堆失败和线程失败三组检查通过，未借此重新测试全机开机。

**仍有优化空间，不能宣称整机掉帧已经修复。** D4 即使双窗缓存命中，仍逐帧绘制标题、按钮和文字，执行两次合计 140,160 字节的逻辑像素上传；D5 删除诊断字后，这些其余工作和生产完成等待仍保留。满屏窄字比原来的短正文可能增加字形工作。80 ms 候选在上述完整 CQ 片段内省光栅指令，但 60 Hz 的 1000–1999 ms 单秒反而增加 3.67%，不能推广成每秒负载均下降，更不能当作 CPU 百分比或真机 FPS。音频线程同样本指令与 D3/D4 相同，本轮没有改摩尔斯算法。

已独立验证原厂图形 image 的所有权、分配和销毁，可作为下一轮避免重复画整面板的研究入口；共用 target 18 不是私有跨帧缓存。负 pitch、两 bank 像素一致性及失败回退尚未验证，本轮没有合入这项实验，也没有删除 D4 防撕裂的同步。

证据索引：`.analysis/cw-smooth-1118/README.md`。文字为 `text/verification3.json`、`text/REVIEW.md`、`text/native-font/evidence.json`；显示为 `profile/final-inputs.json`、`raster-final-ab.json`、`cadence-final-80.json`、`draw-final-vs-d4.json`；额外的回绕/状态验收为 `final-budget-wrap.json`。维护脚本 `tools/probe_705_cw_session.py` 已支持扩展正文读取；启动回放中固定状态块大小的断言兼容新尺寸，仅语法检查，未执行更新/开机。

复现文字专项用 `python .analysis/cw-smooth-1118/text/verify_text3.py`。复现小窗边界用 `python -m tools.probe_705_cw_scope_budget .analysis/cw-smooth-1118/text/CW-TEXT3-PC.ic705sim <新输出.json> --interval-ms 80`。两者均需现有 `PYTHONPATH=.;.analysis/ic705-emulator/deps`；候选已冻结，避免覆盖历史输出。

## D3 真机反证与 D4 显示路径专项

2026-11-18。D3 真机反馈：两个小窗均肉眼可见撕裂，开启 CW 后上方原厂频谱看起来仍掉帧。不是只在手机照片里出现。提示音和 KEYER 点按的新结果尚未提供；不默认它们已经改善。[现场记录](../.analysis/cw-tear-d3-1118/field-d3.json)。

目前确认了显示实现中的三处差异，不能据此宣称主控无法承担 CW 计算。采音和译码算法本轮均未修改。

| 发现及原厂证据 | D4 修正 | 验证与限制 |
| --- | --- | --- |
| 原厂 CPU 像素上传 `0x201480B8` 在调用 `vgWritePixels` 前逐 32 字节执行 `DCCMVAC`、`DMB`；D3 的 CPU 画布直接上传，缺少对应清理。 | 新画布完成后清理所有覆盖的缓存行，最后 `DSB`，再上传；复用旧画布时不重复清理。 | [原厂指令与精确 ARM 检查](../.analysis/cw-tear-d3-1118/native/REPORT.md)。两 bank×两画布位置，首尾不整行的 691 条缓存行全部覆盖，清理晚于 CPU 最后写入、早于上传。没有实体 cache/GPU 模型，不能认定它已消除全部撕裂。 |
| D3 限制的是主动刷新请求；原厂频谱造成的帧仍调用 CW 绘图，新音频每约 10 ms 改一次缓存键，因而可能每帧都重建小窗。 | 在实际双窗栅格生成处合并普通音频更新，最短 120 ms；代次、收发、音调和配色变化即时重建。音频持续按原速进入、解码。 | [实际重画对照](../.analysis/cw-tear-d3-1118/wave/REVIEW.md)：同一段 2.12 秒 CQ，外部 30/60 Hz 调用下，重建从 63/127 次降至均 16 次；缓存复用时整幅画布逐字节不变。调用频率是测试输入，不是705的实测FPS。 |
| 原厂 RTTY/AUDIO 公共生产阶段有完成等待；原厂 LCD 复制后恢复离屏，交给后续最终等待。D3 另加了一次复制后等待。 | 保留 CW 离屏生产完成及原厂最终完成，仅删除重复的复制后等待。 | [原厂 3,840 条指令核对与双 bank 顺序](../.analysis/cw-tear-d3-1118/commit/REVIEW.md)。最终顺序为生产完成→LCD 复制→恢复离屏→原厂最终完成→VDC 提交→bank 切换。没有修改原厂 bank 管理，也未增加 Vsync 等待。 |

D4 电脑候选为 `.analysis/cw-tear-d3-1118/CW-D4-BUDGET-PC.ic705sim`，bundle SHA-256 `7b39a8efcacbca75e0a8187794ec7e58591bc5de633a7ee31f6c537ac7894413`，main `a0d936a2746213526f2a0e5e0374f97c0199e6cefafc957ccdc3a7554cbb99e4`。标记 `D4 RX`；后续按用户要求已直接封装成[日版 1.40 DAT](IC705_CW_RELEASE.md#d4-显示测试版)，两次静态解包核对主程序一致，未重测升级或开机。源码给非 RTX 的桌面预览保留原缓存规则，避免其不自动行进的原厂时钟冻结画布；该预览兼容修改后的 RTX 包与上述候选逐字节一致。

[四组时钟与 CQ 对照](../.analysis/cw-tear-d3-1118/wave/canvas-throttle-fullcount.json)覆盖 30/60 Hz、零起点/毫秒计数回绕。全部 2,827 组音频进入并消费，零丢组，`fed=212`，译文 `CQ`；普通音频重画间隔至少 120 ms，六种关键状态变化立即生效，时钟回绕不饿死。CPU 小窗指令从 10,259,507→2,640,996 和 20,649,774→2,636,975，约减少 74%/87%；计数覆盖调用窗口内的全部扩展地址，包括较早地址的辅助函数。这是局部指令量，不是整机 CPU 利用率或帧率。旧 `canvas-throttle.json` 只计 scope 入口之后的地址子集，保留原件，不再引用其指令量为全路径。原厂 DMA 路径的[独立接收短回归](../.analysis/cw-tear-d3-1118/d4-budget-cq-smoke.json)也通过 2,827 组并解出 CQ。

交付时尚未量化音频工作线程和整页绘制；后续 D4 真机已确认撕裂消失、掉帧仍在，新的分项测量及 D5 改动见本页开头。局部指令计数不能替代物理 GPU/缓存/总线时间，不能把音频线程总指令误称为纯摩尔斯算法负载。

本轮复用现有工具。REA 6.8.0 会话无打开的目标，Ghidra Provider 缺 `GHIDRA_INSTALL_DIR`；沿用已保存的精确原厂字节及 ARM 执行，未安装或改配置。未重复升级、开机，未访问电台。

复现新增反回归，输出路径须为新文件：

```powershell
$env:PYTHONPATH='.;.analysis/ic705-emulator/deps'
python -m tools.probe_705_cw_scope_budget `
  .analysis/cw-tear-d3-1118/CW-D4-BUDGET-PC.ic705sim `
  .analysis/cw-tear-d3-1118/wave/new-cadence-report.json `
  --baseline .analysis/cw-ui-polish-1118/CW-D3-PC.ic705sim
```

## D2 真机收音通过与 D3 电脑界面修订

2026-11-18，日版 41 系列。用户确认 D2 音频已进入解码器、目前看解码正常。[现场照片](../.analysis/cw-ui-polish-1118/field-d2.png)显示 `D2 RX: AUDIO OK`，四项计数为 667/667/667/668，右侧有波形与频谱，左侧有译文。没有参考正文，不能量化准确率；入队和消费在诊断窗口边界可相差一组，不据此判定重复采音。本轮不改采音源或译码算法。

用户新报告频谱略卡、KEYER 要点几次、CW 软键无提示音、双窗图像撕裂。电脑候选 `.analysis/cw-ui-polish-1118/CW-D3-PC.ic705sim` 的主程序 SHA-256 为 `f8b8950fa905d38205b1e26d741834df0daf929c281ce9124cf3c4dfcf7d9854`，屏上标记为 `D3 RX`。后续按用户要求已将同一镜像静态导出为 [D3 DAT](IC705_CW_RELEASE.md#d3-界面与提示音测试版)，未重测升级或开机，未操作实体机。

| 项目 | 本轮实际改动与对照 | 验收边界 |
| --- | --- | --- |
| 软键提示音 | 有效新按下调用原厂 `0x2007d478(1)`，由原厂提示音序列器和 Beep 设置控制。SET、WPM、翻页、HOLD 只响一次；按住、松手、文本空白、未启用的 TX MEM 和中央空位不额外触发。 | [D2 对照](../.analysis/cw-ui-polish-1118/touch-beep/isolated-baseline.json)、[D3 的 20 组测试](../.analysis/cw-ui-polish-1118/touch-beep/isolated-candidate.json)执行原厂 ARM 触摸处理器及提示音序列器；没有模拟扬声器声压。 |
| 无变化重绘 | 双窗按音频帧、会话代次、收发状态、音调和配色缓存。全历史画布原来重复绘制仍需 222,807 条 ARM 指令，新版重复调用为 103 条、零画布写入；首次绘制反而增加约 1.34%，不能把缓存收益说成整机提速。 | [12 组像素对照](../.analysis/cw-ui-polish-1118/gfx-review/scope-comparison.json)覆盖新音频、复位、配色、音调及模式切换，D2 与 D3 的 RGB565 画布全部相同。 |
| 自动刷新频率 | 音频仍按原速处理，只合并自动显示请求，最短间隔 120 ms；用户操作仍立即请求刷新。同一秒输入从 12 次降至 8 次，时钟回绕也通过。 | [原始 ARM 请求计数](../.analysis/cw-ui-polish-1118/redraw.json)来自受控时钟和音频帧数；不是实体机帧率测量。 |
| 双窗同步 | 用原厂 `vgFinish` 等待离屏绘制完成，再复制到 LCD；复制后等待显示上下文完成，最后恢复原厂离屏上下文。 | 两块显示缓冲的[新版调用顺序](../.analysis/cw-ui-polish-1118/gfx-review/d3-graphics.json)均满足生产者/消费者顺序。[旧版](../.analysis/cw-ui-polish-1118/gfx-review/d2-graphics.json)缺少这两处显式同步；延迟绘图模型中的风险已消除，尚不能证明照片撕裂的唯一根因或真机效果。 |

同一 D3 主程序通过[现场 PTT 条件及接收回归](../.analysis/cw-ui-polish-1118/ptt-receive.json)：前 666 组全部进入和处理，完成后译出 `CQ`；三个独立发射条件仍拒收，解除后恢复。同一版本的[原厂 LCD 六种诊断](../.analysis/cw-ui-polish-1118/lcd/evidence.json)、[调谐/SET/音量/模式](../.analysis/cw-ui-polish-1118/controls/evidence.json)和[TWIN 双缓冲接管](../.analysis/cw-ui-polish-1118/twin/evidence.json)均通过。

另用同一份绘图源码构建隔离 RTX 扩展做[原厂 RF 对照](../.analysis/cw-ui-polish-1118/rf/evidence.json)：开关 CW 都发布 48 次频谱、12 条新瀑布，最长间隔仍为 12/48 个模拟节拍，开启 CW 译出 `CQ`、零丢组，总 LCD 提交 50→67。此项不是从 DAT 启动，也没有板级耗时/缓存模型；其用途是查本轮绘图改动的回归，不能据此宣称真机卡顿消失。

KEYER 的间歇性点按未在电脑稳定复现，未改原厂命中区域或绕过其输入保护。[原厂触摸与提示音服务对照](../.analysis/cw-ui-polish-1118/touch-beep/candidate-native-on/evidence.json)中，KEYER 单击和后续 CW 选择均为 3/3，15 次 CW 按键均有一次正常反馈。真机流畅度、撕裂改善和新增提示音仍须实际验收。电脑验收后另行静态封装 DAT，原厂更新和开机未重测。

## 原厂窗口细节与 MULTI 侧栏

2026-11-16。按 [IC-7300MK2 高级手册 2-12 至 2-15 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300MK2_ENG_Advanced_0.pdf)检查后确认，CW 与 KEYER 共用一个入口；译文字段、连续音频波形、频谱／瀑布、两页底栏、短按 HOLD／长按 CLR、ADJ 三项以及三种速度档与 MK2 的接收操作对应。705 仍显示原有 KEYER 图标，点按进入 KEYER／CW DECODE 选择框；MK2 可以设成点一下直达、按住一秒打开选择框。MK2 手动门限、固定滤波和配色借用主旋钮；当前 705 在屏上调整，主旋钮保留调谐。当前 SET 只含接收配色，当次有效；和文和 TX MEM 发射未纳入接收版。这是按手册对照行为，未移植 MK2 的解码程序。

- **标题和底栏。** 用 705 原厂 RTTY 在 480×272 LCD 的同一幅渐变素材（图件 `0x9a`）；中间亮、两边暗。标题和按键各自按中心点居中，底栏字高、基线、边角及框线按 705 RTTY 调整。长标签 `HOLD/CLR` 用相同字库的较小字级留出两边间距；和文的位置留空。桌面预览同样调用该渐变，不再另画纯色标题。
- **侧栏故障对照。** 实跑日版 1.40 的原厂触摸处理、按键扫描和 LCD 双缓冲提交。原厂 MULTI 把侧栏画在右边 119 像素（从 x=361 起），已交付 RX-TOUCH 的 CW 随后覆盖底部全宽，且侧栏触摸没交给原厂。电脑候选在侧栏开启时只提交左侧 CW，同时把右侧触摸交回原厂。CW 状态下，点原厂 `KEY SPEED` 能选中，屏上返回箭头或首次实体 EXIT 可关闭侧栏并恢复原 CW；第二次实体 EXIT 回首页，底部像素匹配原厂。关闭侧栏后 SET 和 WPM 可操作，QUICK 与 MENU 能正常接管；MENU 像素与直接打开一致。测试是电脑模拟，不能替代真机测试。

[旧版 CW](../.analysis/cw-native-polish-1116/control-final/cw-plain.png)、[新版 CW](../.analysis/cw-native-polish-1116/release-overlay/cw-plain.png)、[MULTI 选中 KEY SPEED](../.analysis/cw-native-polish-1116/release-overlay/cw-multi-key-speed.png)、[旧版遮挡](../.analysis/cw-native-polish-1116/control-final/cw-multi.png)。证据目录下有 `control-final/evidence.json`、`release-overlay/evidence.json` 及 `verify-multi.py`。上述电脑验证使用 `CW-NATIVE-UI-FINAL.ic705sim`；后续从同一镜像生成并验收了 [NATIVE-UI 测试 DAT](IC705_CW_RELEASE.md#native-ui-测试版)。未操作实体设备。

## 音量侧栏与原厂模式选择

2026-11-16 真机反馈：NATIVE-UI 的 MULTI 和主旋钮调频正常，AF/RF/SQL 按键菜单与 TWIN PBT 提示被盖，点顶部 `CW` 无法切换模式。电脑用同一份日版 1.40 原厂 UI 驱动回放，未安装到电台。

- **AF/RF/SQL：** 原厂左下角面板从 x=0 到 117、y=157 到 271。CW 避开这个区域并把对应触摸交回原厂；点 `SQL` 改变原厂选择状态，首次实体 EXIT 关闭侧栏并保留 CW。
- **TWIN PBT：** [旧版绘图记录](../.analysis/cw-field-native-ui-1116/twin-geometry/evidence.json)中，原厂先提交滤波器提示，CW 再提交全宽覆盖。修正后，由原厂按键打开提示，CW 在两块 LCD 缓冲中都避开提示所在的 x=130 到 349、y=153 到 238。将仿真时钟推进到原厂阈值，原厂自行关闭提示，CW 恢复全宽，无需退出或重进。只验收提示和绘图，未验证实体 TWIN 旋转后的滤波数值。
- **模式：** CW 把上半屏触摸和松手交还原厂。顶部 `CW` 打开原厂模式选择，选 SSB 后原厂模式状态改变、CW 面板关闭。同一次回放中主旋钮改频和 CW `SET` 也通过。

[TWIN 提示](../.analysis/cw-field-native-ui-1116/pbt-verified/twin-press.png)、[提示消失后的画面](../.analysis/cw-field-native-ui-1116/pbt-verified/twin-timeout.png)、[AF 触摸画面](../.analysis/cw-field-native-ui-1116/pbt-verified/af-touch.png)、[电脑回放数据](../.analysis/cw-field-native-ui-1116/pbt-verified/evidence.json)。电脑版主程序 SHA-256 `66772408ba1a609af0cb079f97c0fb4fd8a87ec66924ee5566d5ea94ef5a595f`。复现：按原厂 UI 回放设置 `PYTHONPATH`，指定 `IC705_MERGED_PC=.../CW-STOCK-PBT.ic705sim`、`IC705_TWIN_CASE=1` 和 `IC705_CONTROL_ASSERT=1`，运行 `.analysis/cw-field-native-ui-1116/replay-controls.py firmware/705J140.dat <报告路径> --live`。本轮不重测升级和开机，不生成 DAT。

## CW 音频到原厂文字

- 用项目自己生成的 42.9 秒、20 WPM 单声道样本：`CQ CQ DE TEST 705 THIS IS A CW DISPLAY TEST MESSAGE RECEIVED ON THE ORIGINAL SCREEN 73`。样本经原厂录音例程后逐 PCM 样点一致；PC 上的 multimon-ng 自动解码，整句（包括词间空格）一致。没有从参考文本向绘制器填字。
- 把**解码器实际输出**送到原厂 16 字节接收队列。原厂读队列、追加文字、生成行快照，再画出字形。空白到三行的四帧均保存；第三帧后绿字区域从 0 增长至 3,278 个像素（包括抗锯齿），且实际提交的字形与三行逐字一致。最后一帧的 PNG SHA-256 为 `1e109bfdf574ee4a0adbf6449660623d70ffc4122a38380f68370e089ad463c3`。
- 另重新解码之前通过原厂录音例程的 [ARRL 2026-01-06 练习录音](https://www.arrl.org/20-wpm-code-archive)：正文去除空白后 **0/670 字符错误**；末次估速仍将 20 WPM 报成 30 WPM。这段用于评分，展示 PNG 使用上面的自生成文本。

模拟器按原厂手册 [2-13 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_4.pdf)设置接收文字颜色，选择四行区域，试验脚本按词插入换行；文字、属性和字形来自原厂运行结果。截图只复现 RTTY 子画面，保留原厂标题；没有启用真正的 RTTY 接收、发射或日志功能，也没有模拟整个 LCD 硬件。PC 解码结果按行分批注入，尚不证明音频边到边解码、机内负载或自动估速达标。

原厂消费入口 `0x2003C3C0`，追加 `0x2003E108`，快照 `0x20096C14`，页面绘制 `0x201750CC`，行绘制 `0x20174A60`（由 `0x201754C0` 调用）。复核位置见[主程序报告](MAIN_CPU_DECODE.md#rtty-正文的静态入口)和 [REA 记录](REA_ANALYSIS.md#j140-cw-显示与模式菜单)。

## CW 下按 MENU 的入口

Icom 高级手册记录 RTTY 模式的 `MENU → DECODE`。在模拟面板以两处已选择模式的 RAM 为输入，运行原厂 MENU 键扫描和触摸处理，各模式的区别在 J140 的原厂页面上可直接看到：

| 已选模式 | MENU 第 1 页上排第 3 格 | 原厂触摸处理 | 打开的功能 |
| --- | --- | --- | --- |
| CW / CW-R | KEYER | `0x20087990` | KEYER（菜单 13；子画面 `0x0E`） |
| RTTY / RTTY-R | DECODE | `0x20087998` | RTTY DECODE（菜单 14；子画面 `0x0C`） |
| LSB / USB / FM | VOICE | `0x20087988` | 原有页面（菜单 11） |

原厂从 `0x2007D140` 取模式组；菜单状态组装 `0x20092780` 设定图块变体，绘制 `0x2013DA0C` 起按该值选图，触摸 `0x200879E4` 独立按模式选处理器。因此只更换图标或文案不够，新增入口需要同时改绘制和点击路由。第 1 页 CW 的十格均已占用；第 2 页右下角看起来空白，但实测触摸仍报 `0x1B9`，写入 SET 的菜单号 22，不能当作无副作用的空位。

## 可点击的电脑验收版

原厂日版 1.40 的左上角在正常接收时是红色描边 `TX`，发射回报到达后是实心 `TX`。**CW 直接读原厂画图用的发射回报，并检查更早的电键和发射请求。** 验收时看三步：① 按键或收到发射请求，文字保留，右侧连续波形归平，即使图标还没变；② 松键后若发射回报仍在，继续暂停；③ 两边都回到接收后，波形恢复，文字接着追加。[灰色图标对照](IC705_RX_AUDIO.md#用原厂-tx-图标的状态停解码)确认图标即使不变也能正确暂停和恢复。按键到松键的原厂 ARM 画面对照见[音频与界面联动实验](IC705_RX_AUDIO.md#用原厂界面任务绘制-cw-译文和右侧波形)。

可先看电脑回放的三张图：[接收有波形](../.analysis/cw-tx-native-j140-final/01-receiving.png)、[实心 TX 时波形归平](../.analysis/cw-tx-native-j140-final/03-solid-tx.png)、[恢复接收并追加译文](../.analysis/cw-tx-native-j140-final/05-receiving-again.png)。还有一组发射从按键到松键完全发生在两次刷新之间；这段侧音没有进入解码，恢复后第一个点仍解成 `E`。

双击 [Open-IC705-CW-Panel.cmd](../Open-IC705-CW-Panel.cmd)。选 `CW` 或 `CW-R`，按窗口下方的 **MENU**，点屏内左下角 **CW DECODE**。右侧显示连续音频波形，左侧约 2.3 秒开始出字。收到 `CQ TEST 123` 后，可以点 **模拟发射**，左上角原厂 TX 变实心、波形归平、文字保留。点 **模拟接收**，TX 回到描边，最终可看到 `CQ TEST 123 DE IC705`。按面板 **EXIT**（或 `Esc`）回主屏。重新进 MENU 仍可点 **KEYER**；改选 **RTTY** 后，原来的 **DECODE** 和退出路径也仍可用。

- 原厂音频路径、译文、菜单和收发状态现在共享同一个 ARM 仿真实例。音频随窗口计时器进入模拟 DMA，测试代码每 80 个样本解码。收发切换用仿真内的原厂 CI-V 处理器和 DSP 回报。标题和正文由测试 ARM 代码调用原厂字形绘制例程，TX 图标复用原厂绘图路径；原厂任务回放可进一步验证完整绘制。

- 新按钮放在 MENU 第一页的左下空位。对照测试中，原厂对该区域的中心与四角均报空；改动像素限制在按钮内。翻到第二页没有改动。七种模式都通过回放，CW/R 模式仍打开 KEYER，RTTY/R 仍打开 RTTY DECODE，LSB、USB、FM 仍打开 VOICE；离开 CW 模式时停止预览。
- [IC-705 基本手册第 2-1 页](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)标明机身的 EXIT 键；[高级手册第 2-8 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_4.pdf)的 RTTY DECODE 屏内没有 EXIT。原厂日版 1.40 回放确认，按键扫描第 1 组 bit 2 会关闭 RTTY / RTTY-R 的解码页并回主屏。电脑预览用同一个原厂按键输入处理退出，屏内右下角不是退出区。测试未操作电台或改动官方 DAT。
- 已用实际 Tk 窗口的点击事件、按钮和计时器验证同一流程。证据在 `.analysis/cw-live-panel-j140/`：接收有波形、发射时平线、恢复后译文、EXIT 后主屏、原厂功能截图，以及 `panel-evidence.json` 和 `tk-click-check.txt`。
- 面板回归另外把发射请求、原厂收发状态发布和音频处理器回报拆开。在图标仍是描边时，已受理的发射请求就会停止解码并拉平波形；在原厂已报告接收、图标却仍实心时也继续停。四个过渡对照均保留 `CQ TEST 123`，没有接受测试侧音；回报清除后才接着解出 `DE IC705`。证据在 `.analysis/cw-panel-tx-sequence-j140/panel-evidence.json` 和同目录 PNG。
- 另测了发射回报落在两批音频之间的情况：旧预览会把实心 `TX` 和上一帧的波形画在一起。现在电脑面板画波形前也让同一个 ARM 收发判断刷新一次，不需要多送一批音频。测试先保留 `CQ TEST 123` 和非零波形，只送原厂音频处理器的发射回报，不送 PCM；该次绘制就出现实心 `TX` 和平线，原有文字未动。清除回报但仍不送 PCM 时，图标回到描边、预览恢复接收资格，旧波形不会重现。证据在 `.analysis/cw-tx-marker-draw-refresh-j140/panel/panel-evidence.json` 的 `feedback-between-audio-callbacks`。

置信度：对日版 1.40 的离线菜单、原厂文字绘制和同步收发切换高。可点击面板由电脑计时，还由电脑画右侧波形；独立的[原厂 UI 任务回放](IC705_RX_AUDIO.md#用原厂界面任务绘制-cw-译文和右侧波形)另行验证由 ARM 画波形、调用原厂文字绘制，按 EXIT 后回到原厂主屏。完整设备仿真与可刷写包仍未验收。

## 自动估速与锁速

2026-11-15。按 [MK2 和 IC-7110 的操作对照](IC705_CW_MK2_PICTURE.md)重排原厂 480×272 分区：上半保留 705 原厂频率和仪表；下半左侧用原厂绿字显示译文，右侧绘连续解调音频。点标题右侧的 WPM／模式区，或切到底栏第 2 页点 `ADJ`，选择 `AUTO`、`LOCK` 或 `MANUAL`。刚进页面为 `-- WPM / AUTO`，没有有效估速时不能锁定。静音时保持锁定；长按只处理一次；用机身 `EXIT` 离开再进恢复自动。点选择器以外可取消，遮住的原厂菜单按钮不会被误触。

`MANUAL` 从日版 1.40 原厂 `KEY SPEED` 读取报速，不改电键设置。原厂读报速例程 `0x20060448` 和存取前后的两字节缓存 `0x2038024A`，以及 CI-V `14 0C` 字段 `0x203EB126`，对应证据在 `.analysis/cw-key-speed-1115/evidence.json`（遍历 256 个设定值，映射 6–48 WPM，读函数未写应用状态）；REA 已复核该原厂代码窗口 `ev_181086c8b715509f98235db4ce8d2eb2c9156015c93dbb60fc1206dde0c2e634` 的镜像身份。在没有自动训练的情况下，手动 20 WPM 正确解出 `T 0`；外部测试驱动经原厂换算函数改变电键速度后，屏上手动档跟到 27 WPM，读回原厂值保持不变。手动显示给出电键标称速度，实际解码以最近的 10 毫秒点长计算。

同一段约 35 秒的合成来报，从日版 1.40 的模拟音频输入连续送给 ARM 解码器。第一遍始终自动，第二遍在报文中用原厂触摸输入切换。程序向原厂字形接口提交的速度、控制字样和译文均与运行值核对。

| 来报 | 一直 `AUTO` | `AUTO → LOCK → AUTO` |
| --- | --- | --- |
| 20 WPM 起步 | `20 WPM / AUTO` | 点后显示 `20 WPM / LOCK` |
| 安静后变为 24 WPM | 跟到 `24 WPM` | 仍为 `20 WPM`；安静时无新增字符 |
| 回到自动，再收 28 和 12 WPM | 先估成 30，再跟到 12 | 同样先估成 30，再跟到 12 |
| 转写 | 两遍全文逐字一致 | 另验收锁定前已经缓冲的 `E` 只输出一次 |

28 WPM 显示为 30 是 10 毫秒点长量化的偏差。此试验验证按钮确实影响解码使用的点长和自动跟随，尚不说明不规则手键、噪声和弱信号下均能正确估速或译码。证据：`.analysis/cw-mk2-layout-final-1115/speed-evidence.json`。隔离原厂显示任务也实际跑出三档选择器和 `20 WPM / MANUAL`，核对原厂抬头像素、波形和全部 20 张合成帧（19,142 组音频）；中断压力对照 41 对帧一致（9,840 组音频）。详见 `.analysis/cw-mk2-layout-native-1115/evidence.json`、`.analysis/cw-mk2-layout-stress-1115/evidence.json`。可点击面板回归共 19,661 组音频，原有 KEYER 和 RTTY 路径通过。完整冷启动仍是[另一项验收](IC705_BOOT_CW_JOIN.md)。

电脑验收：执行 `Open-IC705-CW-Panel.cmd --speed-demo`，选 `CW → MENU → CW DECODE`。录音约第 5 秒显示 `20 WPM`，点它，选 `LOCK`；约第 10～19 秒来报变快，锁定应保持 20。再次点 WPM 并选 `AUTO` 后，估速重新跟随来报。可直接对照 `02a-speed-chooser.png`、`04-lock-during-24.png` 和 `07-manual-20.png`。

## 原厂底栏、冻结译文和右侧双窗

以 [MK2 高级手册第 2-12 页](https://www.icomeurope.com/wp-content/uploads/2026/02/IC-7300MK2_ENG_Advanced_0.pdf)的 480×272 原图为参照。底栏五格起点为 x=2、98、194、290、386，原厂素材为 93×29 像素、y=241–269。J140 的 RTTY 绘制使用同样位置；复用 705 的原厂图形组件和字库。第 1 页为 `< 1 >`、`HOLD/CLR`、留空、灰色 `TX MEM`、`SET`。点第一格翻页，第 2 页 `ADJ` 可打开[三项接收调节](#adj频率和门限)；两页的 `SET` 均可打开[接收显示配色](#set接收显示配色)。

短按 `HOLD/CLR` 固定译文，短按一次恢复到最新内容；长按约一秒清空译文并解除冻结。应用读取原厂 RTX 计时 `0x20381E08`：原厂 OSTM0 中断 134 每次递增一次；板上时钟证据支持每次约 1 毫秒。独立原厂调度回放实际送入 999 和 1,000 次中断，分别保持译文和清屏；PC 面板另测计数回绕、拖离取消、退出和重进。在冻结期间又处理了 600 个 10 毫秒音频块，原来的 `CQ TEST 123` 仍在屏上，内部已收到 `DE IC705`。清屏不重置收音，后续 `CQ` 正常显示。

右侧 x=291–378 显示约 640 毫秒的连续接收音频。每 8 毫秒保留原始采样的正、负峰值；屏上看得到短音、长音和静音段，但时间拉长后单个载音周期不可分辨。最右侧 x=387–473 的上区显示音频频谱，下区显示最近 33 行瀑布；频带 300–1250 Hz，每 40 毫秒产生一行。两窗使用同一路解调音频。600→900 Hz 对照的峰位分别为 x=414、441，旧轨迹留在下方，发射时两窗清空，不显示侧音。频谱是接收音频，不代替电台的射频频谱或译码门限。

**点划看图验收：**[电脑面板](../.analysis/cw-wave-640/panel/cw-waveform-dash-dot.png)和[由原厂任务绘出的 LCD 帧](../.analysis/cw-wave-640/native/05l-scope-dash-dot.png)都在同一窗画出 20 WPM 的一划、一点和中间静音。输入为 180／60／60 ms；电脑面板实际占 26／7／9 列，原厂任务占 27／6／10 列（8 ms 分箱边界的相位不同）。图形直接来自 PCM，并不读取识别出的点划。底栏、HOLD、TX/RX 和旧瀑布轨迹复验通过；原厂调度 23,148 组模拟 DMA、26 帧，重绘压力 41 对画面逐像素一致、9,840 组无丢。报告和命令见 `.analysis/cw-wave-640/` 及下方复现。尚未测实体机刷新耗时。

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
py -3.14 -X utf8 -m tools.virtual_705_cw_panel firmware/705J140.dat .analysis/cw-wave-640/panel --verify
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-wave-640/native/evidence.json --screen
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-wave-640/stress/evidence.json --stress-screen
```

界面验收以 MK2 确定五格的顺序和右窗的位置，以 705 原厂 RTTY 的素材确定底栏的边框、尺寸和字体。两机原厂按键功能不同：705 [RTTY 原厂手册第 2-7 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_1a.pdf)分别列出 `HOLD` 和 `CLR`，MK2 [CW 原厂手册第 2-12 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300MK2_ENG_Advanced_0.pdf)在一键上区分短按和长按。CW 页沿用 MK2 的操作，原厂 RTTY 页保持原样。左侧留给译文，右侧先显示绿色连续音频，再显示频谱和蓝色瀑布；保留 705 机身 `EXIT`。绿色曲线遵照本项目要求画连续接收音频，MK2 原图画的是信号电平。用 `Open-IC705-CW-Panel.cmd --verify` 可重验按钮和双窗。最新复验通过 19,661 组模拟音频，证据在 `.analysis/cw-user-layout-acceptance-1115/panel-evidence.json`（SHA-256 `1ffff12479eb10386ac10137e1294c41a8284fdcd707bd4dce8f8cae52bbb339`），同目录 `mk2-layout-two-tones.png` 和 `mk2-layout-page-two.png` 可和原厂图直接对照。

原厂调度回放 `--screen` 现在也从实际合成的 LCD 帧测双音瀑布：分两次各送 0.6 秒的 600 Hz 和 900 Hz 模拟音频，经原厂 DMA 与 CW 任务处理；新线在 x=441，旧线仍在下方 x=414，与电脑面板一致。整次通过 21,464 组模拟 DMA、25 帧；每帧核对原厂底栏和连续波形，EXIT 后无 CW 残留。报告在 `.analysis/cw-native-dual-window-1115/evidence.json`（SHA-256 `f3f89dbe1f2ac9d02c08d01e6e810c63c4df79c1a702428ca27661e702e3eeaf`），同目录 `05k-scope-900hz.png` 为双音结果。该回放使用已打开收音的独立来宾，不能当成冷启动后收音或真机通过的证据。

看图验收：[705 原厂 RTTY 底栏](../.analysis/cw-layout-visual-1115/panel/stock-rtty.png) → [705 CW 解码双窗](../.analysis/cw-layout-visual-1115/native/05k-scope-900hz.png)，对照 [7300MK2 原厂 CW](../.analysis/mk2-cw-layout-reference/mk2-cw-decode-original-480x272.png)。新页和 705 原厂 RTTY 保持同一套五格按钮的外框、尺寸和位置，键名和动作按 CW 需要调整；当前证据只覆盖这两台的画面，不把它扩展成 Icom 全系列通用标准。电脑面板和原厂任务回放再次通过（分别 19,661 和 21,464 组模拟 DMA）。两边都能看到音调由 600 Hz 移到 900 Hz，旧轨迹仍留在瀑布下方；[冻结译文时波形仍动](../.analysis/cw-layout-visual-1115/panel/hold-frozen-live-wave.png)。报告见 `.analysis/cw-layout-visual-1115/`。

补充复验：`--verify` 从同一次回放取得 705 原厂 RTTY 底栏，将 CW 两页的按键上下边缘及格间间隔与之逐像素对照，各页选取的像素全部一致；标签和操作仍单独检查。面板 19,661 组模拟 DMA，原厂调度 21,464 组、25 张 LCD 帧均通过。新证据在 `.analysis/cw-layout-acceptance-current/`：[原厂 RTTY](../.analysis/cw-layout-acceptance-current/panel-borders/stock-rtty.png)、[CW 第 1 页和双窗](../.analysis/cw-layout-acceptance-current/panel-borders/mk2-layout-two-tones.png)、[CW 第 2 页](../.analysis/cw-layout-acceptance-current/panel-borders/mk2-layout-page-two.png)、[原厂任务双窗](../.analysis/cw-layout-acceptance-current/native/05k-scope-900hz.png)。另可看[实收录音回放](../.analysis/cw-offair-varc/panel-excerpt-verified/frame-66300.png)；右窗有连续波形与瀑布，译文的呼号内仍有多余空格。这些是电脑验收。

布局验收基准：**705 原厂五格外观 + MK2 CW 按键操作 + 705 机身 EXIT，不加 ACCESS。** [705 基本手册第 5-3 页](https://icomuk.co.uk/files/icom/PDF/productManual/IC-705_ENG_Basic_1.pdf)也有绿色音频示波器和频谱／瀑布；[IC-7110 原厂预览第 2 页](https://icomuk.co.uk/files/icom/PDF/newsFile/IC-7110_pre_EN_A4_web.pdf)展示了 MK2 解码器在 705 风格界面中的排布。CW 解码右侧保留连续的接收音频曲线和独立的音频瀑布，用[正在译码的回放帧](../.analysis/cw-layout-acceptance-current/native/05-receiving-again.png)可同时核对译文、两窗和底栏。此项验收限定为外观和已接通的操作；灰键和真机运行分别记录。

用户看图对照：[同次回放的原厂 RTTY 五格](../.analysis/cw-user-visual-check/panel/stock-rtty.png)和 [CW 解码双窗](../.analysis/cw-user-visual-check/native/05-receiving-again.png)。如果专看波形，用[划、静音和点同窗](../.analysis/cw-user-visual-check/native/05l-scope-dash-dot.png)；如果专看瀑布，用[先后收到 600 和 900 Hz 的画面](../.analysis/cw-user-visual-check/native/05k-scope-900hz.png)。左上原厂红色描边 `TX` 在这几张接收帧上仍可见；实心状态和提前暂停规则见[已验收的收发逻辑](IC705_RX_AUDIO.md#用原厂-tx-图标的状态停解码)。

画面本身保持不变；[四种画布内存位置回放](IC705_CW_MEMORY.md#波形与瀑布不依赖固定画布地址)另外核对了原厂冷启动、两窗拷贝及机身 EXIT。这里的瀑布随 CW 接收音调滚动，原厂用于观察整个频段的主频谱不变。

实收长行对照：[修复前](../.analysis/cw-sideswiper-1115/panel-opening/frame-48450.png)首行按 29 个字符断行，绿色字压到波形标签；[修复后](../.analysis/cw-refine-1115/auto/frame-48450.png)按 J140 原厂字形的实际宽度换行，五键及两窗位置不变。验收还包含 40 个无空格 `W`、46 个窄字 `I`，以及正好需要整词换行的文本。通过字幕绘图层逐像素确认两窗内没有绿色文字；验证由 `--verify` 复现，证据在 `.analysis/cw-refine-1115/panel-verified/`。

直接对照[原厂图像](../.analysis/mk2-cw-layout-reference/mk2-cw-decode-original-480x272.png)、[J140 冻结时的真实渲染](../.analysis/cw-mk2-final-native-1115/05i-hold-while-receiving.png)、[双音瀑布](../.analysis/cw-mk2-final-panel-1115/mk2-layout-two-tones.png)和[底栏第 2 页](../.analysis/cw-mk2-final-panel-1115/mk2-layout-page-two.png)。底栏使用原厂 RTTY 的 3 个图块，以 `0x20148238` 和 `0x20148430` 绘到合成目标；REA 核对两处代码窗口 `ev_6d190d54ec3339134faf151f4920471e50ce3f30c15a20409efc4ce76c167bf5`、`ev_76d4c81670acd338861ffec702508a84f2d4d6ff6aac96a6aa9977daf6cb68b4`。原厂边框的 13,920 个 RGBA 像素逐个和新目标对照一致；底层的原厂「和文」字形在日英四种组合下逐像素相同，CW 页面遵照 MK2 只在日语系统下显示。可复验证据：`.analysis/cw-stock-rtty-softkeys-research/explicit-target18.json`、`.analysis/cw-mk2-final-panel-1115/panel-evidence.json`、`.analysis/cw-mk2-final-native-1115/evidence.json`。原厂调度回放覆盖 23 帧和 19,864 组模拟音频；重绘压力对照 41 对帧一致，9,840 组无丢失（`.analysis/cw-mk2-final-stress-1115/evidence.json`）。

电脑看图或亲手验收：对照 [MK2 原厂图](../.analysis/mk2-cw-layout-reference/mk2-cw-decode-original-480x272.png)、[705 原厂 RTTY](../.analysis/cw-user-visual-check/panel/stock-rtty.png)和 [705 CW 双窗](../.analysis/cw-wabun-1115/native-final/05-receiving-again.png)。双击 [Open-IC705-CW-Panel.cmd](../Open-IC705-CW-Panel.cmd)，进 `CW → MENU → CW DECODE`。左栏显示译文，右边先是连续接收音频，最右侧频谱在上、瀑布在下。按 `HOLD/CLR` 后左栏停住、右窗继续更新，长按约一秒清屏，机身 `EXIT` 返回。两页底栏的外框及格间间隔与 705 原厂 RTTY 逐像素一致；按钮文字和行为参考 MK2。单独看[同窗的一划、一点](../.analysis/cw-wabun-1115/native-final/05l-scope-dash-dot.png)和[先后收到 600 与 900 Hz 的瀑布](../.analysis/cw-wabun-1115/native-final/05k-scope-900hz.png)。面板 [回归记录](../.analysis/cw-wabun-1115/normal/panel-evidence.json)通过 19,661 组模拟音频。

### 和文：日语摩尔斯接收

**当前版本只解国际摩尔斯。** 按用户要求移除了日语摩尔斯的软键、码表和片假名绘制分支。原有「显示语言」「系统语言」仍各自保留。`--verify-languages` 在日／英四种组合下都确认原位置为空，收报途中按空白处不切换或重置译码，照常显示 `CQ`，退出后两个配置值不变。见[四组回归](../.analysis/cw-no-wabun-1115/languages/language-evidence.json)和[日版预览](../.analysis/cw-no-wabun-1115/languages/cw-lang-1-1.png)。下文是旧版记录。

按 [MK2 高级手册第 2-12 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300MK2_ENG_Advanced_0.pdf)，只有「系统语言」为日语时显示此键，与「显示语言」无关。按下后用[日本《無線局運用規則》别表第一号](https://laws.e-gov.go.jp/law/325M50080000017)的和文表解释后续点划，原有译文仍保留。用日版 1.40 的现有字库绘制片假名、合并后的浊音与半浊音。在本试验中，机身 EXIT 结束本次设置；MK2 与原厂 KEYER 共用并保存设置的做法未移植，705 原厂语言和 KEYER 设定均不改。`TX MEM` 暂未接入，范围限接收。

旧版 J140 原厂任务经模拟 DMA 收音，LCD [显示 `イロハ ガ パ 705`](../.analysis/cw-wabun-1115/native-final/07-wabun-native.png)。再次按 `和文` 关闭后再收 `CQ`，[屏幕同时保留两种译文](../.analysis/cw-wabun-1115/native-final/08-wabun-to-latin.png)；两次都读回原厂语言配置不变。该回放连同收发、底栏、波形和瀑布回归共通过 38,258 组模拟 DMA、31 帧。见 [evidence.json](../.analysis/cw-wabun-1115/native-final/evidence.json)；REA 绑定原厂字形函数的输入版本 `ev_8898be7a9acdfeae4fc23490e09b5195a25893ab2ffef803f4ab0c4bb6940fec`。这是当时使用合成音频的证据。

旧版面板曾通过四种显示／系统语言组合、同一 PCM 的欧文与和文对照、混合译文绘制、HOLD 以及 EXIT 复位；见[存档](../.analysis/cw-wabun-1115/panel-final/wabun-evidence.json)。普通欧文冷启动另经 2,827 组模拟音频解出 `CQ` 后返回首页，持久写入为零；见 [启动报告](../.analysis/cw-wabun-1115/cold/startup-current-format.json)。

### SET：接收显示配色

[MK2 高级手册第 2-15 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300MK2_ENG_Advanced_0.pdf)把频谱线、信号波形、接收文字和发射文字的颜色放在 `SET`。705 的试验版只接入前三项，并保留先前已验收的默认配色。双击项目根目录的 `Open-IC705-CW-Panel.cmd`，进入 `CW → MENU → CW DECODE → SET`；点要改的项目，按 `R/G/B` 选择色道，再点标尺的 0 到 255。按 `DEF` 只恢复所选项，按 `SET` 回译文，机身 `EXIT` 回原厂首页。试验版颜色只在当次 CW 会话内有效。标尺直接触摸操作，不需要临时占用 705 调谐旋钮。

[设置页](../.analysis/cw-set-rx-1115/native-final/01-set-rx-colors.png)与[回到译文](../.analysis/cw-set-rx-1115/native-final/01-set-applied.png)是 705 原厂 UI 任务绘出的 LCD 帧。频谱线与波形按各自的颜色绘制，瀑布历史保留原来用颜色区别信号强弱的规则。独立修改三项时，原厂音频任务继续收音，退出与恢复颜色均通过，显示语言、系统语言和 KEYER 速度保持不变。REA 的原厂文字接口字节窗口：`ev_672036bc6ee2413e11de45e39ba1e79df24810e87f3a06bf9b7c4a932ab285a2`；原厂固定色表对照和两个指定 RGBA 值验证 705 的 `0x2014289C` 接受每字符颜色。试验没有修改原厂色表或配置。

报告：`.analysis/cw-set-rx-1115/native-final/evidence.json` 和 `.analysis/cw-set-rx-1115/panel-final/panel-evidence.json`。复跑使用 `tools.probe_705_rtx_audio --screen` 和 `tools.virtual_705_cw_panel --verify`，参数同本页前面的命令。另以开启和关闭原厂内存映射的两套冷启动对照复验，仍解出 `CQ` 并回到原厂首页，12 个 LCD 帧与 5 次两窗像素拷贝一致；见同目录 `cold-compare.json`。该冷启动走的是普通接收页，配色操作由前两项验证。

### ADJ：频率和门限

双击 `Open-IC705-CW-Panel.cmd` 可在电脑上操作常规样本；在 PowerShell 运行 `.\Open-IC705-CW-Panel.cmd --filter-demo` 可用双台样本（有 6 秒静音留给操作）。选 `CW → MENU → CW DECODE → < 1 > → ADJ → FILTER → FIX`。初始白线指向 600 Hz；在 FILTER 打开时点频谱或瀑布可改位置。`THRESH` 在 AUTO 和 FIX 下可切 `AUTO` / `MANUAL`，用 `−`/`+` 调最低门限；屏上数字是目前的测试采样单位。`SPEED` 与上方 WPM 快捷入口共用三档。再次点 `ADJ` 回到第 2 页；机身 `EXIT` 直接回 HOME，并清除这次会话的设置。原厂 MK2 的三项顺序和触屏快捷位置参考[高级手册第 2-14 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300MK2_ENG_Advanced_0.pdf)。`WIDE` 保留旧解码；FIX 触摸选择只改解码目标音调，不改电台频率或 KEYER。

同一段 600 Hz 目标与更强 700 Hz 邻台的混音，经原厂 DMA、解码线程和 LCD 三次回放：`WIDE` 为 `~~~`，`FIX`/固定门限 600 为 `NT T EEIV~B~`，`FIX`/自适应门限 350 完整显示 `CQ TEST 123 DE IC705`／20 WPM。通过 61,440 组模拟 DMA、4,608 个 10 ms 解码块（其中 3,072 个用定频）；每次比较捕获字节与输入，核对原厂 7.030 MHz 和 20 WPM 设置保持不变，并验证 600→750→600 Hz 标线与 EXIT。见 `.analysis/cw-adj-j140-final-1115/` 的 `evidence.json`（SHA-256 `27d4ff5e4102807c48172910bb24fe7c8b97ef46fa34530a9c7c21ce4a082db0`）、`01-wide.png`、`03-filter.png` 和 `06-fixed-decoded.png`。这是原厂代码参与的电脑回放，尚无真机计算开销或无线电实收证据。

### AUTO 跟音与 FIX 对照

运行 `.\Open-IC705-CW-Panel.cmd --track-demo`，按 `CW → MENU → CW DECODE → < 1 > → ADJ → FILTER → AUTO`。开始约有 6 秒供选择。白线先到 600 Hz，译出 `CQ TEST`；约在第二段来报时跟到 900 Hz，译文接成 `CQ TEST DE IC705`，频道始终为 7.030 MHz。`AUTO` 复用已有接收音频频谱，每 40 ms 看一次 300–1250 Hz（50 Hz 频点），短暂缓冲首个音，避免在单个点划的空隙追到邻台。三个档位分别是 `AUTO` 选较强音、`FIX` 由人选择目标、`WIDE` 沿用旧宽带检测。它是参考 MK2 操作的独立实现；没有加载 MK2 固件组件，也没有改变 705 的射频频率、CW Pitch 或 KEYER。

原厂调度的 `--adjust-screen` 回放：纯噪声未选音、未出字；混入较弱邻台和噪声，两段分别在 600、900 Hz 译对，LCD 同时显示译文和白线。对同一组双台输入，`AUTO` 在 700 Hz 译出较强台 `W9XYZ NR 51 CQ DE K8JZZ`，`FIX` 在 600 Hz 译出较弱台 `CQ TEST 123 DE IC705`。共逐字节核对 97,440 组模拟 DMA，无丢失。证据 `.analysis/cw-auto-track-1115/final/evidence.json`（SHA-256 `e3864f4f79aad219ffd0d254d67b966f2b28105e1c7cb72bd3425615cfd2024a`）；冷启动结果与改动前逐字节一致，重绘压力 41 对画面一致，19,661 组电脑面板和三档估速复跑通过。音调改变先有停顿，连续漂移、频率接近、信号时有时无和实际电台接收尚不能据此判定。

自动跟音的独立面板对照：600 Hz 已锁定，模拟发射期间送入 850 Hz，解码器未接受任何块；回到接收先保持静音，旧白线不出现，再送 900 Hz，第一次报文正确显示 `CQ`。证据 `.analysis/cw-auto-track-1115/panel-auto-reset.json`（4,560 组模拟 DMA）。

连续漂移已加到原厂任务的 `--adjust-screen`：同一含噪声的人工来报在约 18 秒内从 600 Hz 平滑升至 800 Hz，无人为调频或额外静音。`FIX 600` 漏掉后半段，`AUTO` 标线依次到达 600、650、700、750、800 Hz，完整显示两遍 `CQ TEST DE IC705`，验证原厂两行字形拼合与 800 Hz 标线。合计 148,960 组模拟 DMA 逐字节一致，无丢组；原厂频率和 KEYER 未改。[显示帧](../.analysis/cw-local-noise-1115/native-specialized/09a-auto-drift.png)，报告 `.analysis/cw-local-noise-1115/native-specialized/evidence.json`（SHA-256 `a5a593df3cb19ab79881bff51c29850fc1213d4bbdb306a85e7408f9877254bf`）。本项验证该人工漂移样本，不能代表所有实收漂移或真机开销。

ARRL 2026-01-06 的 20 WPM 练习录音：以 J140 原厂录音路径以前取得的 8 kHz PCM，直送同一个 ARM 任务的音频队列；47,181 个 10 毫秒块，跟到 750 Hz，按原有去空格口径正文 670 字零错。Windows Unicorn 的整段模拟 DMA 尝试发生宿主访问异常，未通过；这份成绩仅覆盖队列之后的解码路径，不冒充整段原厂链路或无线电实收。报告 `.analysis/cw-auto-track-1115/recordings/arrl-worker.json`，复跑脚本同目录 `arrl-worker.py`（在项目根目录使用 `Get-Content -Raw <脚本> | py -3.14 -X utf8 -`，先设置下节的 `PYTHONPATH`）。

## 复现

从项目根目录执行。使用已有项目 Unicorn、FFmpeg 和 Debian WSL2 解码器；交互面板使用 `py -3.14` 已有的 Tk 和 Pillow。输出在 Git 忽略的目录中。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
$py = '.\.venv\Scripts\python.exe'
& $py -m tools.replay_705_cw_display firmware/705J140.dat .analysis/cw-display-repro `
    --arrl-wav .analysis/cw-recorder-replay/705J140-20.8000.wav `
    --arrl-reference .analysis/cw-baseline/arrl-20260106/260106_20.txt
& $py -m tools.probe_705_cw_menu firmware/705J140.dat .analysis/cw-menu-repro
.\Open-IC705-CW-Panel.cmd --verify
py -3.14 -X utf8 -m tools.virtual_705_cw_panel firmware/705J140.dat .analysis/cw-speed-repro --verify-speed
py -3.14 -X utf8 -m tools.virtual_705_cw_panel firmware/705J140.dat .analysis/cw-layout-repro --verify
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-native-repro/evidence.json --screen
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-adj-repro/evidence.json --adjust-screen
```

两项 ARRL 参数可以一并省略。双击根目录的 `Verify-IC705-CW-Display.cmd` 可重跑自生成样本并打开最终 PNG。实跑目录为 `.analysis/cw-display-j140/` 和 `.analysis/cw-menu-j140/`，分别有 `evidence.json`、逐帧 PNG、文字对照，以及 `stock-menu-evidence.json`、逐模式 MENU PNG。
