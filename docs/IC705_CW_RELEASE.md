# 日版 IC-705：CW 真机交付门槛

更新：2026-11-18。项目现在只推进接收 CW，译码限国际摩尔斯，移除 CW 专用的「和文」，原厂显示语言和系统语言照旧。当前入口试验：`CW / CW-R → MENU → 原厂 KEYER 图标 → KEYER / CW DECODE`。左侧显示译文，标题显示估速，右侧按 IC-7300MK2 的布局依次显示连续的解调音频波形、音频频谱和瀑布。底栏沿用日版 705 原厂 RTTY 按钮的外观，原和文键位留空，短按 `HOLD/CLR` 冻结或恢复译文，长按清空；`TX MEM` 仍为灰字。按机身 EXIT 回主屏。SSTV、FT8、卫星跟踪和整机汉化暂缓。

| 门槛 | 当前证据 | 完成标准 |
| --- | --- | --- |
| 1. ARM 收音频并解码 | [录音关闭回放](IC705_RX_AUDIO.md#录音关闭时的-cw-音频取样)输出完整的 `CQ TEST 123`；已覆盖原厂 CI-V 收发切换与模拟手咪输入。[CW/CW-R 与三档 Break-in 的六组回放](IC705_RX_AUDIO.md#cw-电键和自动转回接收)均不解码模拟侧音，回到接收立刻送入的首字正常。调用由电脑测试脚本调度。 | 验证实体电键到 DSP 的输入时序。覆盖弱信号、手键、邻台干扰、变速，量化误码、首字延迟和实际耗时。 |
| 2. 原厂程序接入 | [电脑面板](IC705_CW_DISPLAY.md#可点击的电脑验收版)已复验 EXIT、KEYER、RTTY DECODE。[原厂 UI 任务专项验收](IC705_RX_AUDIO.md#用原厂界面任务绘制-cw-译文和右侧波形)通过译文、连续波形、TX 暂停、RX 恢复与 EXIT；[新增 CW 绘制压力回放](IC705_RX_AUDIO.md#cw-新图层的重绘压力对照)有 41 对一致帧，9,840 组音频无丢失。未找到 [日版原厂扩展入口](IC705_APP_ENTRY.md)。 | 证明原厂日版有可部署的、能正常调用和退出的扩展路径；在授权测试条件下核对真实 LCD、CPU 和内存预算。 |
| 3. 日版更新与独立恢复 | [Icom 日版 1.40 公告](https://www.icom.co.jp/support/drivers/8603/)说明的是正常启动后的 SD 更新、配置和记忆备份；[SQ6EMM 先例复核](IC705_THIRD_PARTY_PRECEDENT.md)确认第三方方案改写引导、改变发射范围；作者报告开发时有 IC-705 需要直接处理 Flash。该方案未证明引导异常时也能回退。 | 独立核对匹配目标日版的主板修订与测试板，再取得可复验的完整备份及不依赖正常启动的同板恢复证据；核对原有收发行为和校准。不等待官方回复。 |
| 4. 真机验收 | [D2](#d2-收音修正测试版)真机已有音频、波形和译文；D4 真机已无双窗撕裂。[D5](#d5-显示与四行译文测试版)用户反馈整体正常、掉帧略有改善但仍轻微存在。[本轮内测审核](IC705_CW_D5_AUDIT.md)确认默认选音覆盖、长静默后干扰误字两项解码缺口。 | 尚无实体 FPS、成套长时/组合验收及独立参考正文；HOLD/CLR、提示音、KEYER 没有新增逐项真机记录。先处理审核缺口，不重复升级/开机。41 系列独立恢复仍未验证。 |

## D6 黑屏唤醒测试版

2026-11-18。按用户新指示将同一已验证的 RX3 导出为日版 1.40 DAT，**不重测升级和开机**。文件 [705J140-CW-WAKE-D6-TEST.dat](../.analysis/cw-reacquire-1118/delivery-d6/705J140-CW-WAKE-D6-TEST.dat)，**12,259,086 字节**，SHA-256 `c50899d0931a81d46b145f21e30c876344effa428491e50961511e1ee7869b41`。系统仍显示 **1.40**，没有屏上 D6 标记，以文件名和摘要辨认。

默认选音保持 D5 **WIDE**，未加入失败的 AUTO/FIX 默认方案。[唤醒修复](IC705_CW_BACKLIGHT.md)让新触摸先走原厂唤醒，首击及恢复中不误按后台按钮；保留上轮电脑通过的 AUTO 长静默规则，仅手选 AUTO 时使用。该规则不能算默认音调覆盖已经解决；[两次默认方案的独立失败](IC705_CW_RX_REACQUIRE.md)继续保留。

直接使用 `CW-RX3-WAKE2-PC.ic705sim`，bundle SHA-256 `e5aed9437d46df0835fe9350f6ec9eac027cdae03ed653b6e433d104bce71c88`；没有重新编译。DAT 落盘解包得到与已验证镜像逐字节相同的 main `8a5aa8c6083fb49dc6889871357dcd4cdb98eb7bda70d384c0f00f321d9c4aa6`。原厂包头/版本、64 KiB 引导、B/C/D 外围段及尾部保持，全部记录校验有效。上轮 17 手势、30 状态、15 原厂 UI、22 整合及 25 AUTO 控制没有重复运行。

真机只需重点确认：电池超时后点下方和上方均唤醒；首击不执行 SET/HOLD/CLR；恢复完成后的新一次触摸正常、调频和译文继续。实体背光及实际恢复耗时、轻微掉帧和日版 41 系列独立恢复仍有原有边界。没有访问电台，下列 D5 文件及全部历史快照保持不变。

[交付说明](../.analysis/cw-reacquire-1118/delivery-d6/README.md) · [静态封装核验](../.analysis/cw-reacquire-1118/delivery-d6/verification.json) · [独立复核 PASS](../.analysis/cw-reacquire-1118/delivery-d6/INDEPENDENT_REVIEW.md) · [独立复核数据](../.analysis/cw-reacquire-1118/delivery-d6/independent-review.json) · [SHA256SUMS](../.analysis/cw-reacquire-1118/delivery-d6/SHA256SUMS.txt)。父目录 `acceptance-partial.json` 保留打包前快照，当前交付以 `delivery-d6/` 为准。复现用 `.analysis/cw-reacquire-1118/export-wake-dat.py`，只调用静态封装，不调用更新/开机，拒绝覆盖已有交付。

## D5 显示与四行译文测试版

**交付后的用户反馈及审核（2026-11-18）：** 用户确认目前测试正常、掉帧稍有改善、仍稍有掉帧，整体无明显大问题。[综合内测审核](IC705_CW_D5_AUDIT.md)对同一 D5 做了只读代码及定向机器码检查，发现默认 WIDE 音调覆盖与 AUTO 长静默后误报两项缺口；未发现新的内存/退出竞态、侧栏遮挡或错误封装。没有修改下述交付快照或生成新包；本轮没有重测升级和开机，也没有操作电台。

2026-11-18。按用户要求封装已经验收的 D5，**不重测升级和开机**。交付 [705J140-CW-UI-D5-TEST.dat](../.analysis/cw-smooth-1118/delivery/705J140-CW-UI-D5-TEST.dat)，**12,259,086 字节**，SHA-256 `0021d61f937dbfb05ca4c63b42c95404e5dc637e9f26b849dd0e87221c3e1f54`。系统仍显示 `1.40`；这版已按要求删除两行白诊断字，**没有 D5 RX 标记**，以文件名/摘要、无白字及四行滚动确认。这是项目测试版，非 Icom 官方发布。

直接使用 `.analysis/cw-smooth-1118/text/CW-TEXT3-PC.ic705sim`，bundle SHA-256 `5ac48137bf83b6149eb76e6c9b4ea661968c453f583c073846f8f2c9a6b8d20d`，没有重新编译固件。静态解包主程序与已验收电脑版逐字节一致，main SHA-256 `e96d1ffc67200ebda10321ead42bf6a3546f48b906e9d6197f0ec4747415105f`。原包头/版本、64 KiB 引导、B/C/D 外围段及尾部保留，全部记录校验有效；主程序压缩流 2,251,246 字节。PowerShell 另算 DAT 摘要一致，固件及交付目录被 Git 忽略。

本版包含[小窗计算优化、80 ms 普通刷新、去诊断白字与四行整行上滚](IC705_CW_DISPLAY.md#d5-四行译文与绘图优化)，另保留 D4 缓存/提交处理，并修复 CLR 抢占时旧字回写。真机重点是同接收设置下对比上方频谱/S 表与双窗流畅度、四行滚动及 HOLD/CLR；电脑局部指令减少不能替代实体 FPS。D4 双窗撕裂已通过，不重新当成未确认；留意本版无回退即可。

[交付说明](../.analysis/cw-smooth-1118/delivery/README.md)、[落盘静态核验](../.analysis/cw-smooth-1118/delivery/verification.json)、[独立复核](../.analysis/cw-smooth-1118/delivery/independent-review.json)、[SHA256SUMS](../.analysis/cw-smooth-1118/delivery/SHA256SUMS.txt)。复现为现有 `PYTHONPATH=.;.analysis/ic705-emulator/deps` 下运行 `.analysis/cw-smooth-1118/export-dat.py`，固定的 delivery 输出目录须尚不存在。导出器核对冻结的 bundle/main、C/汇编/像素表以及 14 份证据指纹，只在当前进程允许这一个候选；不改共享配置，不调用更新或启动仿真。打包前 acceptance 保持历史快照，当前交付见 delivery 报告。未操作电台，未新增手动 A/B 或独立恢复机制。

## D4 显示测试版

2026-11-18，按用户要求直接封装已通过电脑专项的 D4，不重测升级和开机。交付 [705J140-CW-UI-D4-TEST.dat](../.analysis/cw-tear-d3-1118/delivery/705J140-CW-UI-D4-TEST.dat)，**12,259,086 字节**，SHA-256 `12fabbc5ba5e77e99da71b909dc24c8d9735ca366ab16a2449a2fcf110bd8243`。系统仍显示 `1.40`，CW 页左下标记 **`D4 RX`**。这是项目测试版，非 Icom 官方发布。

直接使用 `.analysis/cw-tear-d3-1118/CW-D4-BUDGET-PC.ic705sim`，bundle SHA-256 `7b39a8efcacbca75e0a8187794ec7e58591bc5de633a7ee31f6c537ac7894413`；本次没有重新编译固件。DAT 落盘后及独立复核均解出与已验收电脑版逐字节相同的主程序 `a0d936a2746213526f2a0e5e0374f97c0199e6cefafc957ccdc3a7554cbb99e4`。原包头/版本、64 KiB 引导、B/C/D 外围段与尾部保留，各记录校验有效；主程序压缩流为 2,250,594 字节。PowerShell 独立计算的 DAT SHA-256 一致。

本版包括[实际双窗重画节流、CPU 像素缓存交接及原厂完成等待对照](IC705_CW_DISPLAY.md#d3-真机反证与-d4-显示路径专项)。采音与译码算法不变。本次真机只重点比较开启 CW 前后上方频谱的卡顿，以及两个小窗肉眼可见的撕裂；电脑局部指令减少不代表已经测得实体机帧率。KEYER 新真机结果仍待反馈。

[交付说明](../.analysis/cw-tear-d3-1118/delivery/README.md)、[静态核验](../.analysis/cw-tear-d3-1118/delivery/verification.json)、[独立复核](../.analysis/cw-tear-d3-1118/delivery/independent-review.json)、[SHA256SUMS](../.analysis/cw-tear-d3-1118/delivery/SHA256SUMS.txt)。复现：设置既有 `PYTHONPATH=.;.analysis/ic705-emulator/deps`，运行 `.analysis/cw-tear-d3-1118/export-dat.py`，输出目录必须不存在；随后运行同目录 `review-delivery.py` 作独立静态复核。导出器固定 D4 bundle/main 和七项既有证据摘要，仅调用 `pack_cw_dat`，未调用更新或开机。打包前 `acceptance.json` 保持历史快照，当前交付以 `delivery/verification.json` 为准。未新增手动 A/B 或恢复机制，未访问电台。

## D3 界面与提示音测试版

**后续真机结果：双窗肉眼可见撕裂仍在，开启 CW 后上方频谱仍有掉帧观感。** D3 的电脑检查不能代替实际显示验收；提示音和 KEYER 的新增结果尚未提供。后续已按原厂 CPU 像素交接和显示顺序制作 D4 电脑候选，并另行交付[同一 D4 的 DAT](#d4-显示测试版)；原 D3 文件及导出快照保持不变。

2026-11-18，用户要求把已经验证的同一份 D3 镜像导出，已通过的升级和开机不重测。交付 [705J140-CW-UI-D3-TEST.dat](../.analysis/cw-ui-polish-1118/delivery/705J140-CW-UI-D3-TEST.dat)，**12,259,086 字节**，SHA-256 `427ada79e2ed71d74ce973ce17f393bbab47ea825440377ab9f76676b0781056`。系统版本仍为 `1.40`，CW 页左下标记 **`D3 RX`**。这是本项目的测试包，非 Icom 官方发布。

DAT 直接封装 `.analysis/cw-ui-polish-1118/CW-D3-PC.ic705sim`，没有重新编译或改动样本。PC 包 SHA-256 `fd0b0cbc0d49d149717e8863532ad1195ade938b71b74c8bf1ba822a100b05cd`；DAT 落盘后重新解包，主程序与电脑版逐字节相同，SHA-256 `f8b8950fa905d38205b1e26d741834df0daf929c281ce9124cf3c4dfcf7d9854`。完整包长、包头版本、64 KiB 原厂引导及 B/C/D 外围段保持不变，各段校验有效。主程序压缩流为 2,250,514 字节，通过已有封装器的空白容量及往返核对；PowerShell 独立计算的 DAT 摘要一致。

改动和电脑验收见 [D3 界面记录](IC705_CW_DISPLAY.md#d2-真机收音通过与-d3-电脑界面修订)：恢复有效 CW 软键的原厂提示音、缓存未变化双窗、合并自动重绘请求、加入原厂绘图完成同步。采音路径和解码算法沿用已在 D2 真机通过的版本。KEYER 间歇失灵未在电脑复现，没有改其原厂命中框或绕过输入保护。后续真机已确认卡顿和撕裂仍在，提示音及KEYER新结果未提供，不计为已修好。

[落盘静态核验](../.analysis/cw-ui-polish-1118/delivery/verification.json)、[SHA256SUMS](../.analysis/cw-ui-polish-1118/delivery/SHA256SUMS.txt)、[本次验收说明](../.analysis/cw-ui-polish-1118/delivery/README.md)。复现：项目根目录设置既有 `PYTHONPATH=.;.analysis/ic705-emulator/deps`，运行 `.analysis/cw-ui-polish-1118/export-dat.py`，目标目录必须不存在。该脚本严格固定 D3 PC 包与主程序摘要，只调用 `pack_cw_dat`，未调用原厂更新、启动仿真或实体设备；不更改生产工具中的旧允许列表。`acceptance.json` 是导出前的电脑验收快照，保持原件供交付记录引用。未新增手动 A/B 或恢复机制，日版 41 系列独立恢复仍未验证。

## D2 收音修正测试版

2026-11-16。[705J140-CW-RX-DIAG-D2-TEST.dat](../.analysis/cw-rx-ptt-d2-1116/delivery/705J140-CW-RX-DIAG-D2-TEST.dat)，12,259,086 字节，SHA-256 `35bd5a86443667a40be96aa4bcfee9de3cc3665e61cbc4109a62a2f4d91eab54`。主程序 SHA-256 `f147753bb0969ae6b718563600bddd700794e511a529576b1be15d92855ddbd5`。系统页仍为 `1.40`，CW 页左下 `D2 RX` 区分版本。仅修改 CW 对原始 PTT 的接收过滤和诊断标签，保留原厂引导和收发行为。未新增手动 A/B 或独立恢复机制。

同一份 DAT 经运行于 D1 虚拟 A 槽的原厂程序预检，写入 B 和选择记录，再从写出的虚拟 NOR 冷启动；核对全 NOR 内容，原厂引导、在用槽和共用区未改。测试模拟 P2_13 输入，由原厂扫描维护原始 PTT 位，电脑未改 CW 诊断计数。原厂仍报告接收，实际送入 2,827 组模拟音频、零丢组，波形起伏 19 行，LCD 显示 `CQ` 和 `D2 RX: AUDIO OK`，诊断窗口四项均为 672。SET、AUTO/WPM 和实体 EXIT 通过。电脑另测 CI-V 发射请求、DSP 发射反馈、本机键控仍阻止 CW 收样。

[同包结果](../.analysis/cw-rx-ptt-d2-1116/delivery/verification.json)、[电脑 LCD 截图](../.analysis/cw-rx-ptt-d2-1116/delivery/cw_decoded.png)、[PTT 回放](../.analysis/cw-rx-ptt-d2-1116/field-ptt.json)、[六种诊断](../.analysis/cw-rx-ptt-d2-1116/lcd-replay/evidence.json)。复现使用 `.analysis/cw-rx-ptt-d2-1116/export-verified.py`、原厂 J140、D1 DAT、D2 电脑版及项目现有 Unicorn 环境；脚本只测试虚拟硬件，通过后落盘并再次核对摘要和主程序。2026-11-18 用户已确认 D2 真机收音和解码，目前无参考正文用于量化正确率；日版 41 系列独立恢复仍未验证。

## D1 收音诊断测试版

2026-11-16。日版 IC-705 1.40 的 [705J140-CW-RX-DIAG-D1-TEST.dat](../.analysis/cw-rx-diagnostics-1116/delivery/705J140-CW-RX-DIAG-D1-TEST.dat)，12,259,086 字节，SHA-256 `46fa525bd1e96dcc437bd4de1bc9db9b75ee62339298754a3687efe046daee0a`。主程序 SHA-256 `b2b14076c313c6fc86dbbf3747ec988e5f39b2f68c65d04b6e7425b642b015f0`。系统信息页仍显示 `1.40`；进入 CW DECODE 后看到 `D1 RX` 才能区分这版。保留原厂引导；未新增手动 A/B。用途是日版真机接收诊断，尚未确认日版 41 系列的独立恢复能力。

同一主程序的电脑回放验证了 [六种收音诊断状态](IC705_RX_AUDIO.md#d1-屏幕收音诊断)、TWIN PBT、AF/RF/SQL、顶部模式选择、主旋钮调频和 MULTI。用同一 DAT 在电脑上从 NATIVE-UI 运行中的虚拟 B 槽升级；原厂更新器只写 A 和选择记录，保留引导、在用槽及共用区。重启后原厂任务接收 2,827 组模拟 PCM，零丢组，波形起伏 19 行， LCD 译出 `CQ`，SET、AUTO/WPM 和实体 EXIT 均通过。文件从仿真通过的字节落盘，再读回核对哈希和主程序。

补充用同一 DAT 冷启动后，按模拟 PCM 的时长推进原厂毫秒计时。最后一个有信号的诊断窗口 `RAW/TAP/IN/OUT` 都是 `672`，没有拒收，原厂 LCD 同时显示 `AUDIO OK` 和 `CQ`。[冷启动诊断截图](../.analysis/cw-rx-diagnostics-1116/cold-timing/cw_decoded.png)、[计时验证](../.analysis/cw-rx-diagnostics-1116/cold-timing/verification.json)、[LCD 六组测试](../.analysis/cw-rx-diagnostics-1116/lcd/evidence.json)、[界面测试](../.analysis/cw-rx-diagnostics-1116/controls/evidence.json)、[MULTI](../.analysis/cw-rx-diagnostics-1116/multi/evidence.json)、[DAT 更新及启动记录](../.analysis/cw-rx-diagnostics-1116/delivery/verification.json)。仿真使用已建模硬件；尚未在实体电台验收。

## NATIVE-UI 测试版

2026-11-16，日版 1.40，接替 RX-TOUCH。交付 [705J140-CW-NATIVE-UI-TEST.dat](../.analysis/cw-native-polish-1116/delivery/705J140-CW-NATIVE-UI-TEST.dat)，12,259,086 字节；SHA-256 `b44f8141b10eaa032ddf3b7733ee70e0bf1b86ea05cc1afe9c049926543d5f52`。解包主程序摘要 `b7e58ad1bbedc0f047b6b08bb048a3d2eb6a0c2b3cca4dcb3c782746fbac22f4`，与[原厂布局及 MULTI 双缓冲验收](IC705_CW_DISPLAY.md#原厂窗口细节与-multi-侧栏)用的最终镜像完全一致。DAT 落盘后用 PowerShell 与独立解包复核，保留原厂包头、版本、64 KiB 引导和外围段。没有新增手动 A/B。

同一 DAT 从电脑上运行在 B 的 KEYER 版出发，原厂更新器仅验写 A 和选择记录，并请求重启。全部虚拟 NOR 读回符合预期；保留引导、B 和共享区。从这份实际写出的 NOR 冷启动后，SET、AUTO/WPM 分别开关成功；原厂录音许可未打开，2,827 组模拟音频零丢组，波形起伏 19 行、显示 `CQ`，实体 EXIT 回首页。验收未操作电台，未覆盖真实射频与板级时序，也未证明日版 41 系列的独立恢复。

[同包证据](../.analysis/cw-native-polish-1116/delivery/verification.json)、[冷启动译文画面](../.analysis/cw-native-polish-1116/delivery/cw_decoded.png)。复现使用 `.analysis/cw-native-polish-1116/export-verified.py`、原有 Unicorn 依赖与原件，脚本拒绝覆盖现有交付。版本页仍显示 `1.40`；现场用 DAT 文件名及摘要辨认，屏上对照居中文字和 MULTI 侧栏。

本版的真机对照：MULTI 不被遮挡、主旋钮可调频；AF/RF/SQL 与 TWIN PBT 原厂提示仍被覆盖，CW 页内不能点顶部模式切换。这三项修正已合入上面的 D1 测试版。打开 CW 页时原厂录音有 CW，但 CW 解码波形仍平；[收音验收仍未通过](IC705_RX_AUDIO.md#cw-页录音有声解码波形仍平)。

## QSB 版真机退回

2026-11-15，日版 41 系列。用户确认 CW 底栏原「和文」位置为空白，说明运行的是移除和文后的版本系列；未读回实体机摘要，不能据此鉴定具体镜像。用户所测候选为 `705J140-CW-QSB-TEST.dat`。

- **原厂回归：** `SET` 的标题、页码 `1/4`、分类图标和选中框均在，分类名缺失。`GROUP SELECT` 的标题、行号和 `CALL CH` 仍可见，仅凭照片无法确定组名原先是否非空。用户已确认：正常关机再开机后，不进入解码页、首页底部无功能面板，原厂菜单仍缺字。用户补充，缺字与菜单出现 `CW DECODE` 入口的状态相关。故障无需打开解码页，因此先查新增入口和不同首页布局，不能只查解码页退出。
- **CW 真机功能：** 首页声音及调谐正常；进 CW 后扬声器仍有声、波形无可见活动、软键无反应。转旋钮后用实体 `EXIT` 回首页，实际频率未变；不是单纯 CW 页频率数字没刷新。扬声器有声不能证明解码器收到了音频。
- **电脑隔离：** 在安装包主程序的触摸专项中，全零空闲触摸记录使软键不响应，明确的松手记录使软键恢复。独立的原厂任务回放也复现了这一点：全零空闲时软键无响应、原厂实际频率停在 `7,030,000 Hz`。恢复正常松手后，同一次回放软键可用，频率变到 `7,030,320 Hz`。全零阶段仍有 28 个波形帧并解出 `CQ`，所以这个实验没有复现真机的静止波形；也未证实真机触摸记录实际为全零。
- **电脑菜单对照：** 上述回放恢复正常松手后，经实体键路径退出 CW，再进入原厂日文 `SET`，四项分类名称都进入模拟绘图。这个结果未复现实体机丢字；模拟使用模型化的绘图后端，不能代替真机对原厂菜单的验收。[回放记录](../.analysis/cw-field-triage-1115/handoff/evidence.json)，SHA-256 `2d3e4793b9ef31a65a520d70a07c13b7aa111ba8a63b0de4340501989020793b`。
- **对照照片中的状态：** 保留原厂小频谱，比较「从未进 CW → SET」与「模拟触摸未松手 → 实体 EXIT 关闭 CW → 首页无 CW 面板 → SET」。日文与英文分别跑一次；各自四行的像素在前后完全相同。英文为 `Tone Control/TBW`、`Function`、`My Station`、`DV Set`。此对照是在原厂任务回放中加载当前 CW 源码构建，英文由既有显示语言设置入场，仅用模型化绘图；没有刷包或重跑整机升级。[英语记录](../.analysis/cw-field-triage-1115/stock-set-en/evidence.json)、[日语记录](../.analysis/cw-field-triage-1115/stock-set/evidence.json)，[离线诊断入口](../.analysis/cw-field-triage-1115/stock-set-compare.py)。

#### 无需进入解码页：菜单入口绘制对照

从交付 DAT 离线解出主程序，并与官方 J140、电脑包和当前源码构建逐字节比对。交付 DAT 的主程序 SHA-256 为 `9e1c7fcaed3ea6763a2d6291705eb95578cdfa6a2c1b21d06fe10ee8a02c86b9`；源码按实际构建选项编译后与其新增代码段相同。原厂主程序范围内只有五处跳转不同，菜单文字表和原厂绘制函数本身无直接改写。[来源核对](../.analysis/cw-field-triage-1115/candidate-provenance.json)。用 REA 核对了原厂绘制段的文件窗口（`ev_fd34cdcc76e6a607866d687515b1f6a57a2db56aa5ff6b238a6edf7a390998db`），用 GNU 反汇编定位原厂帧结束处理的 `vgFinish` 调用 `0x2013D4C8`。实验使用当前源码的离线调度版本与原厂主程序，未运行实际板载显示外设。

| 电脑对照：从首页直接进 MENU，再进 SET，未点击解码 | MENU 的 CW 入口 | 原厂结束 MENU 帧时的目标 | 英文 SET 第一页四行 |
| --- | --- | --- | --- |
| [现有绘制逻辑](../.analysis/cw-field-triage-1115/entry-checked-on/evidence.json) | 有 | 显示缓冲（试验中分别切到 1、0） | 全部正常 |
| [仅跳过入口绘制](../.analysis/cw-field-triage-1115/entry-checked-off/evidence.json) | 无 | 原厂离屏目标 18 | 全部正常 |
| [保留入口，画完恢复原目标](../.analysis/cw-field-triage-1115/entry-checked-restore/evidence.json) | 有，MENU 像素与现有逻辑相同 | 原厂离屏目标 18 | 全部正常，与两组逐像素相同 |

**确认的差异是绘图目标被留下来；真机缺字的因果关系仍未证实。** 仿真把两套显示缓冲合为同一虚拟 LCD，并将 `vgFinish` 建模为空操作，未覆盖真实的绘制同步与缓冲提交。实验只在临时编译中恢复目标；未改生产源码、未生成 DAT。仍暂停试刷，不恢复出厂，也无需重复重启。[复现脚本](../.analysis/cw-field-triage-1115/menu-entry-compare.py)。

#### 入口随原厂菜单一次送屏

沿原厂 ARM 菜单调用跟踪，`0x2013C9F0` 调用网格绘制 `0x2013D82C`；返回到 `0x2013C9F4` 时，原厂仍在离屏画布 18，尚未做 LCD 像素搬运。此后原厂向显示缓冲整屏送出一次 480×272。REA 核对官方 J140 的同一代码位置（`ev_3b3468748e2c1839f04f22ebc99fec300261ac4d5732caf0903634bcb214c9f6`）；[原厂顺序与像素搬运记录](../.analysis/cw-field-triage-1115/native-grid-trace.json)。

电脑候选移除了原厂合成完成后单独补画解码入口的分支，改为在原厂送屏前、仍处于同一张菜单画布时绘制。入口不另选前台显示缓冲、不另送一块画面。第一次改动的第 2 页虽未再次画按钮，仍带着缓存的第 1 页旧像素；加上只清理自己留下的矩形后，翻页时外观和触摸均正常。解码页内部绘图没有改动。

在同一个原厂调度回放里用实际菜单点击，比较有/无早期入口两个版本。英语 CW、日语 CW、英语 USB 共 **18 组成对截图通过**：CW 第 1 页唯一差异限于按钮的 141×37 像素；第 2 页无残影，点击同一位置不进解码；英文、日文的原厂 SET 四行和退出首页均逐像素相同；USB 所有对照页一致。CW 两种显示语言均能点新入口进入解码页，再以实体 EXIT 回首页。菜单每帧只有原厂一次整屏搬运，原厂的帧结束目标不变。[像素核对](../.analysis/cw-field-triage-1115/native-grid-final.json)、[原厂 MENU 与候选的时序](../.analysis/cw-field-triage-1115/grid-final-candidate-en/evidence.json)、[候选 MENU 截图](../.analysis/cw-field-triage-1115/grid-final-candidate-en/01-menu-without-opening-cw.png)、[随后进入原厂 SET 的截图](../.analysis/cw-field-triage-1115/grid-final-candidate-en/04-original-set.png)。

复现：项目根目录下设 `PYTHONPATH=.analysis/ic705-emulator/deps;.`，运行 `py -3.14 -X utf8 .analysis/cw-field-triage-1115/native-grid-entry.py firmware/705J140.dat <输出目录>/evidence.json --live`。候选加环境变量 `IC705_GRID_CANDIDATE=1`；日文加 `IC705_GRID_LANG=ja`；USB 加 `IC705_GRID_USB=1`。六组保存为本报告链接的名称后运行 `check-native-grid.py` 做成对像素断言。候选只编译进临时目录，由模拟器接入原厂主程序，未改交付 DAT 或生产源码。真机缺字仍未复现；下一项要对照真实前后显示缓冲及同步时序，也仍需保留独立恢复门槛。

#### 双缓冲与菜单字形的跟踪

从 QSB 版 DAT 离线提取并核对主程序摘要，这次在电脑客体内**直接执行该版原始帧钩子及其绘制机器码**；输入和音频仍由既有隔离任务提供，没有进入 CW 解码页。两个 LCD 缓冲独立存像素，对应 `0x208AE000` 和 `0x208EDC00`。实际执行原厂 ARM 送屏：`0x2012D914` 写 GR2 地址寄存器 `0xFCFF770C`，`0x2013D520` 后轮换下一帧索引。普通显示行回调不会清除请求或换掉当前可见帧；模拟 Vsync 清掉 `GR2_UPDATE` 后，原厂回调及 RTX 自行把请求从 `2` 清至 `0`。REA 核对送屏代码窗口 `ev_7c421df61260f5188103729221ebb100cd87749ddba9a71a1e88f0f912d2793e`。Renesas VDC5 手册 §35.2.1 说明寄存器更新时机；OpenVG 1.1 §4.3 的 `vgFinish` 仅等待当前上下文，原厂显示与离屏有各自的 `eglCreateContext` 调用（`0x201948F4` 和 `0x20194F50`）。

英文、日文各从两种缓冲起步，分别保留旧入口、保留入口并在电脑模型恢复原厂绘图目标、跳过入口绘制。**12 组对照、84 次 LCD 提交通过。** 旧入口在 MENU 帧额外送一次 141×37 的按钮区域，随后 `vgFinish` 对着 LCD 而非离屏画布；两次送屏仍写入同一个后备缓冲，没有写进正显示的另一块。进入原厂 SET 时，标题、页码与四行名称都先绘制到离屏画布 18，再由同一笔 480×272 搬运和同一次 Vsync 显示。按显示语言分组，两个缓冲、三种入口处理的 SET 截图逐字节相同；英文四行分别有 `626 / 276 / 398 / 221` 个目标颜色的像素，日文为 `1005 / 451 / 423 / 312`。在该模型里，**“选错前后缓冲”本身不能解释只少字、不少图标的现象**。

新线索：SET 标题、页码使用的字体对象与四行名称不同；英文四行共用一个对象，日文各行分别使用对象。旧 `CW DECODE` 入口在两次 MENU 重绘中各创建并销毁一个临时字体；两帧合计还创建并销毁 4 个画笔、10 条字形路径，关闭入口后这批操作消失。原厂图标的 41 次图像创建和清理两组相同。该回放用软件绘图代替 `eglMakeCurrent` 和实际 OpenVG 执行，故不能证明驱动在硬件上同步了销毁操作，或缓存／队列如何复用这些对象。**真机缺字仍未复现，不能把对象销毁当成已证实的根因。** 下一关在同一原厂回放里保持入口可见，取消入口的临时字形对象，同时追踪原厂 SET 行字形在 GPU 提交前是否仍有有效的路径和目标，区分绘图对象生命周期与显示缓冲本身。

[汇总 JSON](../.analysis/cw-field-triage-1115/display-bank-summary.json) SHA-256 `da6f2bb095cf1c2f1cbabce06bea0b0e7867b053461502b44313f027bd6cfd84`；[英语原始轨迹](../.analysis/cw-field-triage-1115/lcd-en-1-late/evidence.json)、[英语 SET](../.analysis/cw-field-triage-1115/lcd-en-1-late/set.png)、[日语 SET](../.analysis/cw-field-triage-1115/lcd-ja-1-late/set.png)。复用既有依赖路径，从根目录运行 `py -3.14 -X utf8 .analysis/cw-field-triage-1115/display-banks.py firmware/705J140.dat .analysis/cw-field-triage-1115/lcd-<en|ja>-<0|1>-<late|restore|off>/evidence.json --live`。三项对应 `IC705_BANK_LANG`、`IC705_BANK_START`、`IC705_BANK_ARM`，再运行同目录 `check-display-banks.py`。只读使用旧 DAT；无新打包、不重跑更新或冷启动、不连接电台。

#### 保留入口外观并追踪 SET 四行

**电脑版只替换入口文字的绘制。** 从既有 QSB 对照截图取得 105×22 的 RGB565 像素，替代旧入口每帧调用的动态字形绘制。按钮底框、点击区域、画布和提交顺序保持原样。英语和日语的菜单截图转回 16 位 RGB565 后，与旧入口逐像素相同。两次重画中，旧版入口创建并销毁的 2 个字体、4 个画笔、10 条路径全部消失；原厂各 41 次图像创建和销毁完全一致。这个替换只接入电脑回放，没有修改 DAT 或生产源码。

**四行均进入原厂绘图命令，参数和字形完整。** 电脑实际执行 `vgDrawGlyphs` 包装函数 `0x20263CA4`、原厂命令分发（组 10、命令 78）及参数还原，到 `0x202AB6E6` 的七个参数与入口逐项相同。每个可见字符的字形编号及轮廓、画笔、坐标、画布在旧入口与位图入口之间完全一致。再以实际回放已登记的字形构造驱动表，运行原厂逐字检查，四行均通过到 `0x202AB7B8`。英语、日语各从两套 LCD 缓冲开始，旧入口和位图入口共 **8 组、32 条 SET 分类行命令**；每个 SET 帧先在离屏画布 18 绘制，随后只提交一次整屏。同一语言的 SET 输出逐字节相同。

**故意缺一个字形，原厂校验会丢掉整行。** 对照只从电脑模拟的驱动登记表移除英语第二行的首字形 `F`，保留送到驱动的八个字形编号及轮廓。原厂指令走到 `0x202AB840`，对索引 0 报 `0x1001`；整行 `Function` 从 276 个文字像素变为 0，其他三行、标题、选中框和图标逐像素不变。因此，命令完整也不能排除驱动登记失败。旧版和位图版在正常回放都没有这类错误；电脑仍以软件绘制，原厂登记表、上下文切换与实际 GPU 排队没有完整仿真，**不能把此对照当成真机根因**。下一关应在同一场 MENU → SET 回放实际运行原厂字体登记和销毁，以及上下文切换后的首次绘图，记录字形/画笔能否在真实驱动的数据结构中查到；之后再追硬件提交。

[验收汇总](../.analysis/cw-field-triage-1115/set-glyph-queue-summary.json)；[英语位图入口](../.analysis/cw-field-triage-1115/queue-en-1-sprite/menu.png)、[英语 SET](../.analysis/cw-field-triage-1115/queue-en-1-sprite/set.png)、[日语 SET 轨迹](../.analysis/cw-field-triage-1115/queue-ja-1-sprite/evidence.json)、[故意漏字的轨迹](../.analysis/cw-field-triage-1115/queue-validate-1/evidence.json)和[截图](../.analysis/cw-field-triage-1115/queue-validate-1/set.png)。复用上一节命令，运行 `IC705_BANK_ARM=late|sprite` 的四组语言和缓冲搭配，保存到 `queue-<en|ja>-<0|1>-<late|sprite>/evidence.json`；英语从缓冲 1 起、`sprite` 再以 `IC705_BANK_MISSING_GLYPH=0|1` 分别保存到 `queue-validate-0/1` 两个目录，然后运行 [验收脚本](../.analysis/cw-field-triage-1115/check-set-glyph-queue.py)。没有打包、刷机、重测升级或开机。

#### 原厂驱动复现 SET 缺字并验证画布切换

**电脑复现了真机照片中的英文 SET 故障。** 旧按钮和仅改成位图的按钮都能让四行文字在第一帧彻底消失；标题 `SET`、`1/4`、图标、选中框的像素保持原样。关闭按钮绘制作为对照，或保留按钮并在菜单帧结束前调用原厂函数切回离屏画布 18，四行全部恢复，按钮外观也不变。旧按钮与对应的恢复组、位图按钮与对应的恢复组，分别保持相同的 LCD 拷贝次数和区域。

| MENU 入口处理 | 英文 SET 分类名称（两块 LCD 缓冲分别起步） | 日文 SET 分类名称与驱动错误 |
|---|---|---|
| 旧按钮补画 | 0/4 行；四行都报 `0x1000` | 4/4 行；仍有字体／画笔清理错误 |
| 仅把按钮文字换成位图 | 0/4 行；四行都报 `0x1000` | 4/4 行；仍有字体／画笔清理错误 |
| 关闭补画（对照） | 4/4 行，无错误 | 4/4 行，无错误 |
| 旧按钮或位图按钮，补画后切回离屏画布 | 两版均 4/4 行，无错误 | 两版均 4/4 行，无错误 |

**丢字发生在原厂驱动查找字体的时候，早于逐字检查及 GPU 提交。** 旧入口在 `0x2036DCD0` 前把画布切到显示上下文，并在这张画布结束帧。进入 SET 时，首先在错误的上下文销毁离屏字体和两个画笔（调用返回地址 `0x20198318 / 0x20198328 / 0x20198338`），三条都报 `0x1000`。随后新字体及画笔确实创建成功，但只登记在显示上下文。第一条 SET 文字命令是标题，用在离屏上下文已登记的对象，因此标题和页码都显示。第一条分类名称 `Tone Control/TBW` 和其余三行回到离屏画布后，画笔绑定在 `0x202A25A0` 失败，整行绘制在字体查找分支 `0x202AB720` 被拒；原厂命令和送屏都仍执行。日文发生同样的前置清理错误，但四条实际绘制命令分别使用切回离屏后重新登记的字体和画笔，因而本次没掉字。上一轮故意漏单个字形得到的 `0x1001` 是另一条拒绝路径，本轮复现的是字体及画笔句柄在当前画布不可见。

**验证边界。** 用原厂 `0x202A4240` 建立两个独立驱动上下文；原厂显示初始化里的两次 EGL 创建均传空共享参数（`0x201948F4 / 0x20194F50`）。实际执行原厂字体／画笔／路径的登记、解绑和销毁、`vgGetPaint`、字形检查及绘制准备。另一个 ARM 实例以 MENU → SET 回放捕捉到的参数运行原厂驱动；当前上下文由客体实际进入 `eglMakeCurrent` 时传的句柄决定，板级 EGL 表面、运行时内存分配、锁及最终像素仍由电脑建模。恢复组由实验跳板实际调用原厂离屏选择函数 `0x201951AC`，不直接改字形表或首条绘图命令。健康组的可见字符所引用的轮廓在应用释放原路径句柄后仍有驱动引用，返回画笔与预期颜色一致。共 **20 组回放、80 条分类命令，预期故障组拒绝 16 条**。该证据定位了可重复的电脑故障链；尚未做真机修正或验证。

[20 组验收摘要](../.analysis/cw-field-triage-1115/native-vg-context-summary.json)、[旧入口缺字截图](../.analysis/cw-field-triage-1115/context-en-1-late/set.png)、[保留位图按钮并切回画布的 SET 截图](../.analysis/cw-field-triage-1115/context-en-1-sprite-restore/set.png)、[原厂驱动轨迹](../.analysis/cw-field-triage-1115/context-en-1-late/evidence.json)。复用 `display-banks.py` 命令，加 `IC705_BANK_NATIVE_OBJECTS=1`，运行语言 `IC705_BANK_LANG=en|ja`、缓冲 `IC705_BANK_START=0|1`、入口 `IC705_BANK_ARM=late|sprite|off|restore|sprite-restore` 的组合，输出到 `context-<语言>-<缓冲>-<入口>/evidence.json`；最后运行 [验收脚本](../.analysis/cw-field-triage-1115/check-native-vg-contexts.py)。改用下节的合并入口后，这组旧入口故障用作回归对照。

## 复用原厂 KEYER 做成 MK2 式单入口

用户改定单入口，不继续修改 QSB 的独立按钮。原厂日版 1.40 实跑七种模式，同一个菜单格 `(240,77)` 由原厂命中测试得到 `0x1B2`，再按模式分派。两种 CW 经回调 `0x20087990` 调用原厂 `0x200801E4(13)`，RTTY 和 USB 分别保持原厂功能 14 和 11。新试验只接 CW 的回调，关闭旧入口的额外绘图及触摸逻辑；MENU 图标本身仍由原厂绘制并显示 `KEYER`。

**确实复用了 705 的原厂选择框。** KEYER 的 `EDIT/SET` 原先调用 `0x200CD628(12, 0xffff)` 打开选单，`0x200CDC20` 生成绘图数据，`0x200CD9B4` 接收原厂命中的行，原厂在触摸释放后调用该行的动作。实验只在模拟 RAM 临时借用原厂表项填入两行及一个选择回调，关框时归还。选 `KEYER` 执行原厂 `0x200801E4(13)`，原厂 `EDIT/SET` 也仍有原来的三项。选 `CW DECODE` 关闭原厂选择框，启动现有 705 接收解码会话，未另写一套菜单绘图或触摸。实体 EXIT 在模拟器内可取消选择框，也可从解码退出。没有移植 MK2 二进制代码。

**电脑验收。** 隔离 RTX 回放在 CW／英文和 CW-R／日文分别通过 20 个画面检查：原厂 MENU 一次送屏，旧独立入口位置不再响应；两项选择、原厂 KEYER/EDIT/SET、取消、解码 SET、速度选项、旋钮从 `7,030,000` 调至 `7,030,320 Hz`、波形与译文 `CQ`，以及退出后原厂 SET 页面四行文字。RTTY、USB 同位置仍进原厂功能。只送入模拟触摸、机身键、旋钮和 PCM；LCD 像素由软件模拟。此轮未将新选择框接入双缓冲原厂字体驱动试验，也未核对全屏瀑布。Windows 当前 REA MCP 能识别原始 ARM 文件，提供者不支持其深度读取；以已有 ARM 工具和运行轨迹核对，无需改配置。

[选择框截图](../.analysis/cw-mk2-merged-1115/CW-en/02-picker.png)、[原厂 KEYER](../.analysis/cw-mk2-merged-1115/CW-en/03-stock-keyer.png)、[CW 解出 CQ](../.analysis/cw-mk2-merged-1115/CW-en/13-cq.png)、[退出后的原厂 SET](../.analysis/cw-mk2-merged-1115/CW-en/16-stock-set.png)。[实验脚本](../.analysis/cw-mk2-merged-1115/merged-entry.py) 在现有 `probe_705_rtx_audio --live` 上复用原厂任务及外设夹具。复跑示例：

```powershell
$env:PYTHONPATH='.;.analysis/ic705-emulator/deps'
$env:IC705_MERGE_MODE='CW'; $env:IC705_MERGE_LANG='en'
py -3.14 -X utf8 .analysis/cw-mk2-merged-1115/merged-entry.py firmware/705J140.dat .analysis/cw-mk2-merged-1115/recheck/evidence.json --live
```

下一关是在原厂选择框内分配独立的测试表项，结合两块 LCD 缓冲的原厂驱动检查和全屏瀑布入口测试。此次所有改动只在离线实验中生效，未修改正式构建源码、DAT 或电台。

## 单入口的日版 1.40 构建

新版编入 `MENU → KEYER → KEYER / CW DECODE`。705 原厂选择器保留全部 277 条描述，只新增选择框和两条选择项，不再临时覆盖原厂 `EDIT/SET`。原厂图标仍显示 `KEYER`。旧的独立按钮及其触摸区域在此构建中停用；CW 页绘完以后交回原厂离屏画布。从原厂频谱或其他下半屏应用选择 CW 时，先调用原厂的关闭程序，避免原厂应用仍占着下半屏导致 CW 立即退出。

桌面回放通过普通 CW／英文和 CW-R／日文的两项选择、原厂 KEYER 与 EDIT/SET、物理 EXIT、CW SET 和 AUTO、旋钮调频、波形和 `CQ`。在两块 LCD 缓冲上用原厂 ARM 字形和画笔逻辑验收：英文和日文直接进原厂 SET，以及实际打开 CW、退出之后再进 SET，首帧四行都有字。使用 `MENU → SCOPE → EXPD/SET` 确认原厂展开旗标和 LCD 上移缩小的频率读数，再从 MENU 走两条分支。原厂字形对象和命令在模拟器中执行，外设和最终图形输出仍由电脑建模。

原厂更新器已接受该候选 DAT，把主程序写入虚拟 NOR 的另一启动区，并请求重启。仅从它实际写出的虚拟 NOR 冷启动，验明主程序 SHA-256 `1be7f473e2329f61537adf9d496d7dc2e9de1b48eceb9bf0bd8d89170aba0f70`；没有从宿主加载 CW 程序。冷启动后从原厂 KEYER 进入选择器，选 CW，2,827 组模拟 PCM 在 LCD 译出 `CQ`，用机身 EXIT 回到同一原厂首页。引导、原用区、共享区及其他固件均保持原样。只验证了新候选包，未重跑历史包。

[日版 1.40 测试 DAT](../.analysis/cw-mk2-merged-1115/delivery/705J140-CW-KEYER-TEST.dat)（12,259,086 字节）已从通过同包更新的候选重建，保存前后 SHA-256 均为 `da596f0ba9d201165a90f51816018f960280633b9f665cf3f27ffc023407e8da`。证据：[更新与冷启动](../.analysis/cw-mk2-merged-1115/update-trial/evidence.json)、[CQ 实际屏幕帧](../.analysis/cw-mk2-merged-1115/update-trial/cw_decoded.png)、[展开频谱及两条分支](../.analysis/cw-mk2-merged-1115/final-native-scope/result.json)、[原厂 SET 首帧](../.analysis/cw-mk2-merged-1115/final-native-scope/set.png)。`native-en-0-0`、`native-en-1-1`、`native-ja-0-0`、`native-ja-1-1` 目录各有双缓冲日志。`.ic705sim` 仅供电脑加载，DAT 也只完成了电脑验收。未接触真机；保留原厂 1.40 版本和引导，并无手动 A/B。日版 41 独立恢复未验证。

```powershell
$env:PYTHONPATH='.;.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.build_705_cw_sim firmware/705J140.dat .analysis/recheck/705J140-CW-KEYER.ic705sim --merged-entry
py -3.14 -X utf8 -m tools.replay_705_cw_dat firmware/705J140.dat .analysis/recheck/705J140-CW-KEYER.ic705sim .analysis/recheck/update --dat-output .analysis/recheck/705J140-CW-KEYER-TEST.dat
```

## RX-FIX 候选同包仿真验收

2026-11-16，日版 1.40 研究候选：`.analysis/cw-field-fix-1116/delivery/705J140-CW-RX-FIX-TEST.dat`，12,259,086 字节，SHA-256 `5865dff6d3158f25787716ce2c85557dc6b7dbe6e9052b0eaa49f9743ecb8f88`。主程序 SHA-256 `b8bd2504f788b584765930ea1b9b8414d1f50a18dc0a020a09dadbb08cfd56d1` 与音频及触摸对照完全一致；保留日版 1.40 原厂包头版本，无手动 A/B 功能。改动为读取原厂实时选择框状态、补充触摸松手处理，以及让 CW 接收不再依赖录音服务状态；[真机观察和电脑故障对照](IC705_RX_AUDIO.md#原厂-audio-有波形后定位-cw-收音与软键)。

本次用**已交付的 KEYER 版在 B 运行**作为虚拟起点，不重跑它的安装。用该版原有更新器验包并写入 A，擦写范围实际只有 A 和选择记录，整片读回均与预期字节一致；保留了原厂引导、先前的 B 和共享数据。更新器请求重启后，从这同一份虚拟闪存冷启动；启动前应用 RAM 为空，由原厂引导从 A 加载并校对主程序，原厂任务收到模拟接收音频，LCD 显示 `CQ`，实体 `EXIT` 回到首页。落盘的 DAT 哈希与这次实际送进仿真的包一致。证据 `.analysis/cw-field-fix-1116/update-from-keyer/{evidence.json,cw_decoded.png}`。

补充验收用已落盘的两份 DAT 重建 NOR，快照 SHA-256 与原厂更新器上次写成的完整快照一致；本次不运行更新器。分别在新增 CW 音频桥读取每组 PCM 时置入内部录音状态 `0`、`2`，回到原厂录音代码前恢复原值。两组均走原厂引导、DMA、原厂调度和 LCD，2,827 组逐样本一致，零丢组，音频窗占 19 行、显示 `CQ`，实体 EXIT 回首页。与原先状态 `1` 的验收在 `CQ` 帧逐像素一致。证据 `.analysis/cw-field-fix-1116/cold-record-gate-{0,2}/evidence.json`。这里验证的是录音状态对 CW 的依赖是否已消除；没有模拟真机产生这两个状态的原因。

这是一份通过电脑验收的候选；真实音频取样、触控时序与板级独立恢复仍未验证。电脑中有两个存放主程序的位置，不等于日版 41 系列有可用的手动回滚入口。本轮没有操作真机。

```powershell
$env:PYTHONPATH = '.;.analysis/ic705-emulator/deps'
$p = '.analysis/cw-field-fix-1116'
py -3.14 -X utf8 -m tools.replay_705_cw_dat firmware/705J140.dat "$p/705J140-CW-FIELD-FIX.ic705sim" "$p/repro-from-keyer" --previous-keyer .analysis/cw-mk2-merged-1115/delivery/705J140-CW-KEYER-TEST.dat
py -3.14 -X utf8 -m tools.probe_705_cw_cold_record_gate firmware/705J140.dat `
    .analysis/cw-mk2-merged-1115/delivery/705J140-CW-KEYER-TEST.dat "$p/delivery/705J140-CW-RX-FIX-TEST.dat" `
    "$p/705J140-CW-FIELD-FIX.ic705sim" "$p/update-from-keyer/evidence.json" "$p/repro-gate-0" 0
```

## RX-TOUCH 修订版

2026-11-16，日版 1.40。除承接 RX-FIX 的独立收音路径与首次打开修正外，新版只让 CW 将原厂发布的 `9999,9999` 松手报告交回原厂并解除按住状态。不改固件包头 `1.40`、原厂引导、共享区或 TX 判断。旧 KEYER 和 RX-FIX 对该原厂报告均从第一下开始整排软键无效；新主程序的真实 ARM 输入处理、原厂 LCD 提交、SET、AUTO/WPM、翻页、HOLD/CLR、旋钮、EXIT 和 QUICK 已通过同一 UI 回放。[软键 A/B、原厂松手来源和完整 UI 证据](IC705_RX_AUDIO.md#原厂松手坐标导致-cw-软键从第一下就失灵)。

候选 DAT SHA-256 `f84a9f2566d1c30a7f38ce108b9bb542ef97b6d7737ab3e03765d07d40433ad6`，12,259,086 字节；主程序 `6834c70d441b206b63aa9725681415e4bb58c4d9fe8d8c586d50453e3c1ed3d1`。同一个候选已用运行在 B 的 KEYER 版原厂更新器写入 A，原厂要求重启；保留引导、B 和共享区，独立重建的虚拟闪存逐字节一致（SHA-256 `805cc4b9531306b8ac615be43e41d62e367ea8276b76399c82def80134f395c9`）。从这份虚拟闪存冷启动，在原厂录音许可一直关闭时，收到 2,827 组模拟音频、零丢组，波形覆盖 19 行，显示 `CQ`，机身 EXIT 回首页。证据 `.analysis/cw-touch-native-release-1116/cold-stock-sql-control/{evidence.json,cw_decoded.png}`。没有连接真机；日版 41 系列独立恢复没有得到确认。

交付文件 `.analysis/cw-touch-native-release-1116/delivery/705J140-CW-RX-TOUCH-TEST.dat`；保存后重核 DAT 哈希，清单 `delivery/verification.json`。原厂版本页仍显示 `1.40`，不能作为识别测试包的依据。

**同一轮电脑验收通过。** 直接读取上次原厂更新器写成的虚拟 NOR 并逐字节核对，不重复更新。冷启动一进 CW 即开始回放原厂格式的触摸报告；四个不同 LCD 提交分别确认 SET 打开、关闭，AUTO/WPM 打开、关闭。随后显示 `CQ`，波形有 19 行起伏，2,827 组模拟音频零丢组；模拟机身 EXIT 回到相同首页，没有持久化设置写入。模拟器通过原厂任务、触摸读者和 LCD 翻页完成，无宿主替换主程序或强制重画。证据 `integrated-before-audio/{evidence.json,cw_decoded.png}`。上次把软键排在译文结束之后的较长分支停在原厂 SCIF4 发送寄存器 `0xE800900C`（原厂 `0x20014A18`）。本次把软键和收音放在同一场并先操作软键，译出后即退出；不据此声称已经模拟串口、真实收音或长期运行。串口地址见 [R7S72100 设备树](https://github.com/torvalds/linux/blob/master/arch/arm/boot/dts/renesas/r7s72100.dtsi) 和 [Renesas 硬件手册](https://www.renesas.com/en/document/mah/rza1h-group-rza1m-group-users-manual-hardware)第 14 章。

仅复用上次写好的快照（输出目录 `integrated-before-audio` 应为空缺，避免覆盖证据）：

```powershell
$env:PYTHONPATH = '.;.analysis/ic705-emulator/deps'
py -3.14 -X utf8 .analysis/cw-touch-native-release-1116/integrated-before-audio.py
```

对同一包的复现（不覆盖已有文件）：

```powershell
$env:PYTHONPATH = '.;.analysis/ic705-emulator/deps'
$p = '.analysis/cw-touch-native-release-1116'
py -3.14 -X utf8 -m tools.replay_705_cw_dat firmware/705J140.dat "$p/705J140-CW-NATIVE-TOUCH.ic705sim" "$p/repro" --previous-keyer .analysis/cw-mk2-merged-1115/delivery/705J140-CW-KEYER-TEST.dat
```

## 单机条件下的交付判定

用户只有一台日版 `41` 系列，找不到同修订替代测试机。把电脑升级验收定为一条完整链：**拟交付的同一个文件 → 日版原厂 SD 更新程序检查并写入 → 仅用写入后的虚拟闪存冷启动 → 打开 CW DECODE、译出接收音频、正常退出。** 隔离试验中可以模拟外设和文件读取，但不能由电脑安装器替原厂更新程序写入，再将两项结果合并当作通过。

旧的 `.ic705sim` 是电脑专用格式，原厂更新器在读文件头时就拒绝它（`.analysis/cw-release-header-1115/stock-vs-pc.json`）。此前的两项试验分别用的是官方 DAT 和 `.ic705sim`，不能拼作一条完整链。新的 [CW DAT 仿真](#同一-cw-dat-的-rza1-仿真)已补齐这项电脑验收。

真机仍需能在正常菜单无法进入时恢复，且设置备份不能代替原板恢复。相同电脑链已通过，不再重复冷启动或录音验收来代替实体机缺失的证据。

2026-11-15，在本项目的真机结果出来前，按这一范围重新核对 [Icom 日版更新公告](https://www.icom.co.jp/support/drivers/8603/)、[发布方 GitHub](https://github.com/sq6emm/icom-custom-firmware)的清单、Issue 和[论坛](https://mikrofale.cafe/showthread.php?tid=1296)当时的 4 页共 49 条正文。GitHub 当时为提交 `3d30e461d7bcbd39b782c1823764f305639ee9a8`，日版仅 `20261113v1`，开放及关闭 Issue 均为零。论坛有日版运行报告：一台明确曾做硬件改动，另一台的硬件状态和批次都未说明。这些帖子早于当时的公开构建；第 3 页的 `#41` 是楼层号，不是硬件批次。公开构建改动引导和发射范围；当时未发现符合本项目条件的第三方 CW 安装先例，只核对发布说明，没有下载或执行第三方补丁。证据：`.analysis/cw-japan-install-evidence-1115/summary.json`，SHA-256 `601f47ed14eb645786b3c0d3d8bf638a3371bad3bc925dfe869300121e0bc46b`。

### 同一 CW DAT 的 RZ/A1 仿真

2026-11-15，**由运行日版 1.40 的原厂程序安装 CW DAT，再从实际写成的虚拟闪存重启并显示 `CQ`／20 WPM，整条链已通过。** 参照 [SQ6EMM 的容器格式](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/main/IC705_DAT_FORMAT.md)，只在内存重建同长度的日版容器，复用已验收的 CW 主程序。独立解包确认 64 KiB 原厂引导、文件头、外围组件和尾标均与官方底包相同。没有采用 SQ6EMM 的 A/B 引导或其发射范围补丁。

| 验收点 | 实测结果 |
| --- | --- |
| 同版本原厂验包 | 未修改的日版 1.40 原厂更新器识别文件头，核对主控 A 组的容器校验，通过并选中主控更新；原厂写入任务返回 `0`。 |
| 实际写入范围 | 写入待用的 B 启动位置和启动选择记录，共擦除 36 个扇区、编程 2,244,112 字节（其中 16 字节是选择记录）。引导、原在用 A 位置和共用资源区均为 **0 擦除、0 页编程**。另观察到一次 Flash 状态寄存器写请求。完整 16 MiB 虚拟闪存与独立解包预期逐字节相同。 |
| 冷启动及 LCD | 原厂发出看门狗复位请求；仿真用写任务交出的同一份虚拟闪存与空应用 RAM 重启。原厂引导选 B，解出和候选包相同的完整 CW 主程序。未由宿主注入 CW 代码。从 2,827 组模拟 DMA 收音后，LCD 实际画出 `CQ`，EXIT 回到原厂首页。 |

执行的是 RZ/A1 的 Cortex-A9 指令及这条路径需要的模拟外设（包括文件接口、SPI NOR、任务应答、复位、音频和 LCD），不等于完整电路、物理 SD 卡通讯或全板计时仿真。只验证了初始引导和共用资源均为原厂 J140 的条件。没有接触电台，也没有留下 DAT 或 NOR 镜像文件。

本地 [JSON 记录](../.analysis/cw-stock-dat-1115/evidence.json)和 [LCD 截图](../.analysis/cw-stock-dat-1115/cw_decoded.png)。内存 DAT 12,259,086 字节，SHA-256 `c512cc0916f4a99f563a63a13f6052b9e01bc44712719d7badb4c62f0626c545`；证据 JSON SHA-256 `57329d50886ea8ae97caf5e72c7d1d797a7acf150aef7db93ed8b07fb7853716`。

2026-11-15，按用户指示只复用打包函数，将完全一致的内容另存为本地 [705J140-CW-TEST.dat](../.analysis/cw-dat-delivery-1115/705J140-CW-TEST.dat)。写出前核对仿真记录与候选的 SHA-256，落盘后用 Python 读回比对，并用 PowerShell `Get-FileHash` 再核对同一摘要。没有重跑仿真，文件被 Git 忽略，打包时未连接电台。真机后来已看到 CW 入口，见下节。恢复进度见 [SQ6EMM 路线与 41 系列](IC705_THIRD_PARTY_PRECEDENT.md#sq6emm-的外置编程器路线与日版-41-系列)。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.replay_705_cw_dat firmware/705J140.dat .analysis/cw-packaged-boot-1115/J140-CW.ic705sim .analysis/cw-stock-dat-repro
```

### 日版 41 系列已显示 CW 入口

2026-11-15，用户报告自行尝试刷入后正常开机：普通 CW、全屏瀑布打开时，机身 `MENU` 第 1 页有 `KEYER`，左下留空，触摸空位无反应；回到主界面按机身 `EXIT` 退出全屏瀑布，再开菜单，出现 `CW DECODE`。这个标签是 CW 主程序新增的，排除了仍在运行未改原厂 1.40 的解释。真机随后进入 CW 页，按实体 `EXIT` 可回主界面。未单独读回真机 Flash，不据此判断真机启动槽或已安装字节的摘要。可对照[电脑菜单帧](../.analysis/cw-packaged-boot-1115/run/boot-stock-menu.png)。

- **本包使用原厂引导。** REA（`ev_45ccc47d2132340ed1c7b5e2d462016bb6a1d4792b4c3e6c0f79d5e21324bd61`）独立核对了交付 DAT 摘要。重新解包，核对主程序与电脑验收源逐字节一致，5 个 CW 跳转及标签都在。DAT 头部、64 KiB 引导和主程序版本字段均保持原厂值。这不是 SQ6EMM 的开机手动 A/B 版。仿真里的两个位置是原厂内部的主程序存储位置，无需进入手动引导，也不保证可手动回退。后续构建宜在界面增加独立标记（如 `CW TEST 02`），保留原厂更新比较所依赖的版本字段。
- **入口受当前界面状态限制。** [绘制判断](../samples/cw-j140-lab.c#L915)要求常规第 1 页的菜单状态、无子页面且画布可用；[触摸判断](../samples/cw-j140-lab.c#L305)同样要求常规菜单状态和对应位置未被原厂按钮命中。真机观察到退出全屏瀑布后入口恢复；尚未采集全屏时具体哪一个条件不满足。电脑验收没有覆盖全屏瀑布，也没有跑实体 SD 卡文件列表。

早期[局部取证 JSON](../.analysis/cw-hardware-menu-triage-1115/evidence.json)保留原厂空位和模拟初始化故障的对照；这些替代解释已不适用于“退出全屏后可见”的实测。

#### CW 页软键及波形未通过

用户报告 `SET` 等底栏按钮、右上 `AUTO/WPM` 都没有可见反应，观察波形未见输入活动；实体 `EXIT` 正常。仅凭静止画面还不能断定接收音频没有送进来，也不能断定每个软键都没有改变内部状态。`TX MEM` 是灰色占位，未计入故障。

对交付 DAT 中的**同一主程序**做了两组输入专项对照，调用原厂触摸轮询，没有改包或重跑升级。提供明确松手样本时，`SET` 开关、`AUTO/WPM`、`< 1 >` 都改变各自状态；把松手间隔替换成全零样本时，CW 页仍可打开，但后续触摸全被当成还没有松手，所有上述状态保持不变，实体 `EXIT` 两组都正常。两组 CW 软键均未走原厂普通触摸事件分派。这个模拟复现了与实机相同的**软键症状**，但尚未确认实体机实际发出全零样本；此探针也没跑屏幕提交或音频。旧专项在每次操作后主动请求完整 HOME 重画，所以不能据其图像排除真机页面没刷新。原厂轮询代码区间由 REA 核对（`ev_2bcfb3f24eb3d90b6d39a44212590b6059437b9503d3fd14f9090f03e570b017`）。

[输入对照证据](../.analysis/cw-hardware-menu-triage-1115/touch-controls.json)；离线复现：

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_cw_touch firmware/705J140.dat .analysis/cw-dat-delivery-1115/705J140-CW-TEST.dat .analysis/cw-packaged-boot-1115/J140-CW.ic705sim
```

真机追记：点 `SET` 后轻转主旋钮，用户未见频率改变。用户照片也证实原厂 `MENU` 和 `QUICK MENU` 能在背景打开，却被 CW 面板挡住下半。打开 CW 时还观察到原厂频谱偶尔卡顿，未量化。照片证明屏幕并非始终停止更新，不能区分软键事件是否丢失，也不能判断音频在哪里中断。

#### CW 遮挡原厂菜单已在电脑修正

原厂输入轮询的对照重现了旧 DAT 进入 `MENU` 和 `QUICK MENU` 后仍保留 CW 的问题。修正后的电脑版在 `MENU`、`FUNCTION`、`QUICK`、`EXIT` 上释放 CW 页面，原厂分派的四个目标画面均不变；原厂弹窗已出现时，CW 主动停止绘图并把触摸交回原厂。既有调度专项随后跑完 38,258 组模拟音频、31 帧，`SET`、和文、波形/音频频谱和退出回归通过。该专项仍会在其需要截图时明确请求重画，不能当作真实触摸、旋钮、收音和提交在同一次自由运行中都已验证。

本轮专项记录为 `.analysis/cw-hardware-menu-triage-1115/navigation-controls.json`（上述输入命令加 `--check-navigation`）及 `.analysis/cw-hardware-navigation-1115/panel/evidence.json`。逐帧的 ARM 指令计数中位数 790,860（31 个探针帧，含退出），只说明 CW 绘图有值得量化的开销，不能换算成真机帧率或断定卡顿根因。下一项参考[初代 7300 的同场仿真](IC705_CW_MK2_PICTURE.md#两个初代-7300-项目可以复用什么)：由原厂任务自主提交帧，连续验证触摸、旋钮和接收音频，再以开/关 CW 对照频谱更新。没有生成新 DAT 或操作真机。

#### 电脑连续操作验收

复现了 `SET` 内部已经打开但画面一直不动，以及退出后旧画面残留。修复后由 CW 通知原厂显示任务刷新：按键和退出立即通知，接收波形最多每八个 10 ms 音频块追加一次画面更新。另用原厂合成器真正的弹窗状态区分 `QUICK` 与 `M.SCOPE`。软件 LCD 的重叠画布解析也修正了，以免把旧菜单误当成 VFO 图块。

| 验收点 | 同一轮原厂任务回放 |
| --- | --- |
| 进入、软键和退出 | 从原厂 HOME 通过 `MENU → CW DECODE` 打开；`SET` 可以开关，点 `AUTO/WPM` 能打开速度菜单，收报后点 `LOCK` 可锁定估速；实体 EXIT 清除 CW，原厂 `QUICK` 单独回归。 |
| 调谐与原厂频谱刻度 | CW 关和开各送相同旋钮动作，VFO 从 `7.030.00` 调到 `7.030.32 MHz`；在相对第 2、4、6、8 次主循环都提交四次相同频率变化，同帧保有原厂迷你频谱刻度。 |
| 收音、波形与译文 | 3,280 组接收 DMA 样本逐字节吻合，无丢组；28 幅不同的波形图，最大垂直跨度 18 像素，LCD 输出 `CQ`。素材为 20 WPM，本轮原厂任务回放的实验解码器最终估为 17 WPM；估速精度另验。 |

脚本从既有板初始化状态开始，送触摸样本、旋钮计数、定时中断、接收音频和 LCD 完成信号；原厂任务自行决定刷帧和提交，不由脚本写屏幕更新标志或调用 CW 绘制。环境未模拟完整外围，略过与验证无关的循环末段；这里的主循环次数不是物理毫秒。该次试验只送频谱刻度的调谐变化，动态射频见下一节。移除和文后，上表各项通过[回归](../.analysis/cw-no-wabun-1115/live/evidence.json)。未重复升级和开机，未生成新 DAT 或连接电台。

证据：[JSON](../.analysis/cw-live-1115/acceptance/evidence.json)、[SET](../.analysis/cw-live-1115/acceptance/04-set.png)、[速度选单](../.analysis/cw-live-1115/acceptance/05-speed.png)、[译出 CQ](../.analysis/cw-live-1115/acceptance/08-cq.png)、[退出覆盖后的原厂 QUICK](../.analysis/cw-live-1115/acceptance/10-stock-quick.png)。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-live-1115/acceptance/evidence.json --live
```

#### 原厂射频频谱和瀑布开关 CW 对照

两组在相同的 7.030 MHz、原厂迷你频谱布局下，先用原厂射频数据预热，再送相同的 48 帧动态射频和一段 `CQ` 音频。原厂收帧与发布的 475 个点逐帧一致，LCD 分开统计射频频谱、瀑布最上行及瀑布区域的实际像素变化。下方 CW 的音频波形和蓝色小窗不计入射频指标。

| 电脑回放结果 | CW 关 | CW 开 |
| --- | ---: | ---: |
| 原厂发布并显示的射频频谱变化 | 48/48 | 48/48 |
| 原厂射频瀑布实际新增行 | 12 | 12 |
| 相邻更新的最长间隔（频谱／瀑布，模拟循环） | 12／48 | 12／48 |
| LCD 总提交（含 CW 或其他内容的额外刷新） | 50 | 78 |

模拟的射频块和解调音频经原厂 IRQ 159 进入各自接收路径。用原厂配置开启瀑布，在模拟器补足本地频谱订阅；原厂代码处理历史数据、绘制带颜色的行并提交 LCD，脚本不请求强制重画。两组音频都完整有序，开启时显示 `CQ`，关闭时无译文。瀑布在本组原厂设置下平均每 4 帧频谱滚一行；两组起始相位不同，以每组新增行之间的间隔比较。 **这项试验排除了本次负载下漏掉频谱或瀑布更新；同时证实 CW 增加整屏提交。** 模拟器允许每步运行至约定位置，不模拟实体板上的总线耗时、显示压力或物理采集时限，因此真机卡顿原因仍未定位。后续先给 CW 专用重绘计较真实的开销，再决定是否合并提交。无新 DAT，未操作真机。

[报告 JSON](../.analysis/cw-rf-live-1115/acceptance/evidence.json) · [CW 关闭画面](../.analysis/cw-rf-live-1115/acceptance/01-rf-cw-off.png) · [CW 开启并解出 CQ](../.analysis/cw-rf-live-1115/acceptance/04-rf-cw-on.png)

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-rf-live-1115/acceptance/evidence.json --rf-scope
```

### 保留原厂引导的安装核查

2026-11-15。**原厂 SD 更新可以在特定条件下保留引导；未找到日版 1.40 向接收 CW 开放、并保证只换主程序的安装入口。** [Icom 的日版 1.40 公告](https://www.icom.co.jp/support/drivers/8603/)只说明普通 SD 固件更新及有偿代更新。[CS-705](https://www.icom.co.jp/support/manual/5070/)和[日版 CI-V 资料](https://www.icom.co.jp/support/manual/5068/)没有提供机内第三方组件安装入口。[SQ6EMM 日版发布](https://github.com/sq6emm/icom-custom-firmware)说明其 A/B 构建首次会改写引导。其欧版清单列出的 SD 应用不能作为未改日版的入口。

在电脑上用**未经修改的官方 DAT**，让日版原厂预检、任务和模拟 SPI 写入跑完。已安装位置放原厂 1.40，待写位置放原厂 1.32；按既有夹具给预检提供 1.32 版本报告，原厂实际选择主控 A 组，两次都正常返回。引导和共用数据初始与 J140 完全一致。这次逐区统计的是**实际擦除和页编程请求**，即使同一内容被先擦再写，也不会误算成没动。

| 原厂写入方向 | 引导、原在用主程序、共用资源区 | 写入位置 | 启动选择记录 |
| --- | --- | --- | --- |
| A → B | 全部 **0 擦除、0 页编程字节** | 擦除 81 个扇区，编程 5,274,864 字节 | 擦除 1 个扇区，编程 16 字节 |
| B → A | 全部 **0 擦除、0 页编程字节** | 擦除 81 个扇区，编程 5,274,864 字节 | 擦除 1 个扇区，未编程 |

两组仍各发出一次主 Flash 状态寄存器写命令，阵列统计不涵盖实体机全部外围数据、设置和校准。[前一轮的原厂对照](SAFETY_AND_RECOVERY.md#共享引导被擦除时两份完好的主程序都无法启动)已经表明：引导内容有差异时，同一个官方 J140 文件可以让更新器擦除它。因此，保留引导是这两组条件下的观察结果，不能当作更新入口的保护承诺。更不能把官方包通过算成 CW 候选通过。此轮没有重做 CW 译码、生成候选更新包或操作机器。

[逐区报告](../.analysis/j140-stock-write-scope-1115/evidence.json)，SHA-256 `e7e5ef183227f8a7317a4ca56ed7fd285350ae83b0f9e1288dd939338698b663`。REA 核对官方底包全量 SHA-256（`ev_212201f84c2beaee990f882fa4ff910e7d9e35da1adb1b839aae55665cbfec57`），写入范围来自原厂指令及模拟 SPI 事务。复现可沿用 [原厂双向回放命令](SAFETY_AND_RECOVERY.md#原厂写入中断后的两向冷启动)，用新输出路径，查看 `power_cuts` 里两种方向的 `observed_write_scope`。

这项原厂对照之后已完成同包仿真，见上节。真机交付仍需目标同修订的独立恢复证据。

### 日版 1.40 原厂包主程序空间实测

**CW 主程序放得下。** 按原厂格式压缩后的原版主程序为 2,071,676 字节，已在虚拟闪存冷启动的 CW 版为 2,243,907 字节，增加 172,231 字节。我用 `tools.decode_705_main` 只读解出官方 `705J140.dat` 的 A 段并核对 SHA-256；从原压缩流结束处向后扫描，实测连续空白有 361,340 字节。CW 版长度取自已经冷启动成功的虚拟闪存记录；同时核对电脑包和其中主程序的 SHA-256。加上头部并向上取整到模拟试验使用的 64 KiB 写入单位，距原厂下一处已有数据还剩 **139,264 字节**。原始数据与计算结果见 `.analysis/cw-dat-capacity-1115/evidence.json`。

当时的空间测量没有生成候选 DAT。随后用相同的压缩主程序通过了[同一 CW DAT 的 RZ/A1 仿真](#同一-cw-dat-的-rza1-仿真)。目标日版在无法开机时的恢复路径仍待验证。

## 本轮实跑结果

[定频与门限专项](CW_BASELINE.md#定频滤波门限与强邻台)已在仿真 ARM 比较同一音频：两个相隔 100/200 Hz 的强邻台合成样本从 16/16 错降为零，ARRL 录音保持 0/670。随后在 [J140 的 ADJ 页](IC705_CW_DISPLAY.md#adj频率和门限)通过 61,440 组模拟的原厂 DMA 输入，按 `FIX` 和自适应门限完整显示 `CQ TEST 123 DE IC705`，电台频率和原厂 KEYER 未改。NW6V 直键须调高门限才达原宽带成绩，同频仍无法分离；实收和真机开销尚未核对。

[自动跟音](IC705_CW_DISPLAY.md#auto-跟音与-fix-对照)已走通原厂 DMA、解码线程和屏幕。两个有噪声的合成来报由 600 Hz 转为 900 Hz，逐字一致；同一 600/700 Hz 双台混音可在 `AUTO` 抄强台、`FIX` 抄指定弱台。此项验证了参考 MK2 的接收功能；日版可部署入口和独立恢复的结论不变。

[40 米 SSN 实收与冷启动 `0`](CW_BASELINE.md#冷启识别-0-与侧摆键实收)：同一录音经电脑中的 705 原厂音频任务和屏幕回放，`FIX 640` 与[细化后的 `AUTO`](CW_BASELINE.md#自动选音细化)均抄对评分窗 34 字及全部空格；旧版 `AUTO` 错一字。CW 译文实收长行及宽字换行已按原厂字体通过边界回归。冷启 `0/5` 在三档正确，单音 `T/E` 的歧义仍在。原厂[维修条款与核对单](IC705_REPAIR_INQUIRY.md)单独跟踪第三方固件是否受理、是否有官方安装途径和能否恢复原板及校准；尚无可刷写文件。

[连续开机回放](IC705_BOOT_CW_JOIN.md)已从模拟 EEPROM 恢复 `VFO A / 7.030 MHz / CW`，关闭合成副 CPU 警告，沿原厂菜单进 `CW DECODE`，经模拟 DMA 读入音频并在 LCD 显示 `CQ`／20 WPM，再按机身 EXIT 回到字节相同的 HOME。手咪模拟输入松开、静噪为最低时原厂自行开放收音。此项为电脑回放，不证明副 CPU 实物响应、真实电台接收或固件部署能力。

[侧摆手键连续回放](CW_BASELINE.md#快手键区分速度估错与短停顿合并)修正一次错误重估，把 AUTO 的总体错误从 67 降至 46／81 字；MANUAL 24 WPM 为 14／81。仍有一段快报 AUTO 无法可靠译出，另有 5–10 ms 停顿被合并的边界。底栏、波形和瀑布与收发切换仍按原电脑面板的回归条件核对。

[快报恢复专项](CW_BASELINE.md#错把多字连成一字后的自动恢复)将同一段手键演示录音的 AUTO 错字继续降到 26／81，末段从 41 降至 21／41 字；每轮 103,375 组原厂模拟音频无丢失，电脑面板与三种速度回归通过。快报和极短停顿仍有缺口，未进入真机交付。

[波形点划验收](IC705_CW_DISPLAY.md#原厂底栏冻结译文和右侧双窗)把接收音频窗口加长到约 640 ms；20 WPM 的一划、一点和静音能同时看见。原厂程序参与回放 23,148 组模拟 DMA，41 对压力帧逐像素一致；从冷启动仍解出 `CQ` 并可退出。[两份手键对照](CW_BASELINE.md#极短停顿与两份手键对照录音)表明现阶段应优先改善估速；继续压短停顿没有稳定提升实录表现，未更改检测器。布局与速度成绩均为电脑证据，日版安装与独立恢复各自仍未验证。

[自动估速修正](CW_BASELINE.md#自动估速防止长点拖慢和短点翻倍)让同一收音路径的手键错字由 26→18／81、8→2／68；第二段多余空格由 5 增至 8。ARRL、弱信号、邻台、变速和电脑冷启动结果保持。尚未验证真实机器运行负载、官方安全安装入口和原板恢复；没有生成可刷写固件。

[分词复验](CW_BASELINE.md#速度重估和长字间隔的分词)用同一日版收音路径将 F6UIG 多余空格从 8 降到 1，已有正确的词间空格和 2／68 字符错误不变；第 4 课练习音频的多余空格从 39 降到 10。弱台、变速、ARRL、NW6V 与日版电脑的冷启动、显示和退出均复跑。此项只改善接收译文，交付门槛 2 和 3 的证据不变。

[原厂内存映射下的完整电脑回放](IC705_CW_MEMORY.md#原厂地址映射下运行-cw)通过：在原厂分配的 14,464 字节私有块中由仿真宿主装入 14,400 字节 CW 代码与只读数据。原厂内存映射保持开启，2,827 组模拟音频解出 `CQ`，12 张 LCD 帧与对照逐张一致，机身 EXIT 归还画布并回到原厂首页。此结果解决电脑上原厂映射兼容问题。真实无线电的复位仍没有经验证的代码装载入口，[Icom 日版渠道复核](IC705_REPAIR_INQUIRY.md#官方咨询渠道复核)也未发现可公开核实的安全安装或同板恢复承诺。尚无可刷写文件。

[右侧双窗的四种画布位置](IC705_CW_MEMORY.md#波形与瀑布不依赖固定画布地址)在同一原厂内存映射下各通过 12 帧像素对照和 5 次拷贝，并确认 EXIT 归还画布。此项关闭电脑回放的对齐问题；不计为真机刷新或安装验收。

[SET 的三项接收配色](IC705_CW_DISPLAY.md#set接收显示配色)按 MK2 的项目分工加入日版回放，沿用 J140 原厂文字接口。原厂任务在配色页继续接收，恢复默认和机身 EXIT 验收通过；试验色彩只保存在会话内存。没有新增刷写路径。

旧版曾[实现并测试和文](IC705_CW_DISPLAY.md#和文日语摩尔斯接收)，当前源码已按用户要求去掉该键和译码，只保留国际摩尔斯。四组日英显示／系统语言组合的[电脑回归](../.analysis/cw-no-wabun-1115/languages/language-evidence.json)均显示 `CQ` 并保留原厂语言配置。`TX MEM` 仍保持灰字。

[原厂调度器回放](IC705_RX_AUDIO.md#用原厂界面任务绘制-cw-译文和右侧波形)已从原厂主任务选出的 HOME 开始，按 MENU 让原厂自行选页并绘制，再点原厂图形接口绘出的 `CW DECODE`。复验 18,354 组模拟音频，发射期间暂停，发射回报一清除就继续收音，EXIT 回主屏。电脑仍提供调度检查点和显示完成通知；这项证据不能替代从上电开始的整条连续回放。

[MK2 风格的布局与速度选择](IC705_CW_DISPLAY.md#自动估速与锁速)已用同一段 35 秒来报验证：24 WPM 时，自动跟到 24，锁定保持 20；回到自动后能重新跟随。手动档按原厂 KEYER 报速在尚无训练时正确解出 `T 0`，并跟随原厂设定从 20 变到 27 WPM；读回原厂设定未改。长按去抖和机身 EXIT 通过。

[原厂更新器写入前检查](SAFETY_AND_RECOVERY.md#日版-140-的原厂写入前检查)逐项通过未改动官方包的文件头尾和 A、C、D 三组摘要检查；[首个引导扇区对照](SAFETY_AND_RECOVERY.md#原厂更新器怎样处理首个引导扇区)验证相同时跳过写入。另在[原厂更新任务的独立回放](SAFETY_AND_RECOVERY.md#原厂更新任务在-flash-状态配置前停止)中，到首次 Flash 状态配置之前停止，全程没有执行 Flash 写入。仍没有验证签名机制、完整备份或独立恢复。

新增[日版恢复路径对照](SAFETY_AND_RECOVERY.md#日版主程序无法启动时按路径核对恢复证据)：所查主板的原机 microSD 卡槽与主控 ROM 开机读取的引脚不同，不能据此从原机卡槽恢复损坏的主程序。原厂强制全复位恢复的是设置。独立 SPI 读取仅有器件级证据；下一道门槛是同板版可重读的完整备份，以及主程序不能运行时恢复原板、重新开机并保留板级数据的实证。

[维修图逐线复核](SAFETY_AND_RECOVERY.md#维修图核实主控时钟两套-flash-与日版适用范围)排除 `CP706` 是调试口，确认所查 Wi‑Fi 模块有独立 4 MiB Flash，且公开板版表不能将用户的日版匹配到具体主板。下一份可解除恢复门槛的证据是同版原板的独立恢复记录，或厂商同等证明。已写好[可转发的维修核对单](IC705_REPAIR_INQUIRY.md)，未发送；它不能替代日版安装入口验收。

[两个启动位置轮流损坏的只读对照](SAFETY_AND_RECOVERY.md#排除用另一份主程序自动回退)：被选中的日版 J140 或 J132 主程序不可读、仅剩开头或头部全擦除时，原厂引导都未改选另一份完好的程序。不能将两个启动地址或菜单降级计作应急回退。安装仍需要可复验的原厂接入路径；独立恢复仍需同板版的恢复证据。两者都未通过。

[日版 1.40 原厂更新的首个改写请求](SAFETY_AND_RECOVERY.md#普通更新会先动哪里)：有差异时可以先动首个引导扇区；主程序会比较未在运行的那份；共享 A 组尾段也在改写范围内。八组电脑回放均未执行状态配置或写入。备份不能只存一份主程序，原板完整存储和校准仍需实证。此结果不证明更新器接受扩展，也不证明 SD 卡能救回无法启动的电台。

| 样本 | 转写 | 末段估速 |
| --- | --- | --- |
| 12 WPM / 500 Hz，20 WPM / 600 Hz，28 WPM / 750 Hz | 三个合成样本逐字符一致（含空格） | 12、20、30 WPM |
| 20 WPM / 600 Hz，合成标记段标称 6 dB 白噪声 | 逐字符一致 | 20 WPM |
| 纯静音与一份合成纯噪声 | 两者均无输出 | 无 |
| J140 原厂录音路径，合成 86 字符（含空格） | 零错字，解码器实际输出经原厂队列绘出三行 | 20 WPM |
| J140 原厂录音路径，ARRL 2026-01-06 练习录音 | 约 7 分 49 秒，去空白的参考正文 670 字符零错误 | 17.14 WPM（标称 20） |

新增[独立 ARM 质量诊断](CW_BASELINE.md#arm-解码器中途变速首字和人工直键)：在词间重新估速后，两组 12/28 WPM 大幅变速对照分别由 13/34、11/34 降到零错字，另一段不同文字也通过。匀速、有噪样本和 ARRL 670 字符保持原有成绩。人工直键在该版为 50/282；词内突变和自动档冷启单独一划仍无通过证据。该诊断直接跑 ARM 解码器；另通过原厂独立调度器的 19,142 组音频对照。证据 `.analysis/cw-adaptive-20261114/quality-final/evidence.json` 与 `rtx/evidence.json`。

后续[短间隔手键对照](CW_BASELINE.md#缩短直键字母分隔门槛)将同一发报者样本的错误从 50 降到 20／282。短间隔专项从 8 降到零／22，ARRL 正文保持零／670，噪声、变速和 AUTO/LOCK 回归通过。仍需其他真人发报和无线电实收样本；不能用一份手键录音证明普遍可靠。

[两次 40 米实收通联验收](CW_BASELINE.md#40-米通联实收验收)已加入。有一组片段把自适应最低门限调高后达到 1／120 字符编辑错误（不计空格），另一组在同设置仍有 47／61。J140 电脑面板已从同一实收片段显示两个呼号，但呼号内仍有多余空格；自动门限、实际信噪比和电键型号没有验收。曾试过的宽带纯度限制会挡住指定弱台，已撤回。门限改进需同时通过实收、强弱邻台和低音量回归；安装和恢复交付门槛不变。

[局部噪声门限](CW_BASELINE.md#局部噪声门限与空格评分)已进入电脑试验版。相同低门限下，两次通联分别由 36 降至 19 错（61 字）、64 降至 34 错（120 字），第 7 课背景误字 67 降至 35；100 Hz 强邻台、弱台、ARRL 和 NW6V 回归通过。原厂 J140 收音与显示的专项复跑包含同一发报音调 600→800 Hz 连续漂移，`AUTO` 完整抄出两遍报文，`FIX` 漏收。呼号空格仍未通过，背景仍有误字，不能将电脑结果写成真机性能或刷写验收。

[按发报节奏分词](CW_BASELINE.md#按发报节奏分词)使实收呼号短片的多余空格从 6 降到 2，较完整的第 7 课评分窗从 61 降到 11，同时少了 3 个应有空格；字符错数不变。独立意大利桨键录音的两段呼号和词间空格全对，原厂接收任务、模拟发射后恢复及三档速度复验通过。词内换速、弱实收、冷启孤立 `T/0`、实际硬件成本及安装与恢复仍各自待验证。

上述表格是上次整链基线，证据在 `.analysis/cw-arm-j140-final/evidence.json`；`rtty-frame-3.png` 用原厂 RTTY 绘图子画面。合成样本首次出字约 1.76–3.39 秒，旧基线测试机器码含常量共 1,252 字节，仿真最高约 7,837 条 ARM 指令／10 ms 输入块。新版变速对照代码 1,660 字节、仿真最高 8,900 条；状态仍为 88 字节、每块输入仍为 160 字节。指令计数不能当作真机周期、耗时或系统占用。长录音是练习播报，实收弱信号、全程估速和失锁后重新同步未验收。

[重绘压力回放](IC705_RX_AUDIO.md#cw-新图层的重绘压力对照)已在原厂界面任务内验证新增图层和收音并行。[底栏和右侧双窗](IC705_CW_DISPLAY.md#原厂底栏冻结译文和右侧双窗)已扩展到同源频谱/瀑布；新版画布占 22,080 字节，电脑统计不能推断真机性能。[引导回放](SAFETY_AND_RECOVERY.md#原厂引导选择主程序的受控回放)没有看到自动回退；[后续启动回放](SAFETY_AND_RECOVERY.md#启动时实际使用的板上数据)证实正常启动会读两颗 EEPROM。交付依[独立恢复验收表](SAFETY_AND_RECOVERY.md#独立恢复的验收项)取证；完整备份和无需主程序启动的恢复尚未验证。

## 短衰落实录与日版 1.40 测试包

2026-11-15。[留出实录](CW_BASELINE.md#短衰落修复和独立录音验收)有 20 个可核对字符，合计编辑错误 17→12；80 米弱应答原先漏掉的 `C` 重新出现，但整段仍有漏抄和错字。7.405 MHz 30 秒无来报对照误字 3→2，两份其他对照保持 0。另以当前构建重放原厂音频调度和 RF 频谱：开关 CW 后均提交 48 次频谱、12 行新瀑布；这是模拟节拍，不能替代实体机帧率。

本机专项证据在 `.analysis/cw-fade-1115/`：`panel-final-fox-b/`、`panel-final-shootout-a/`、`panel-final-commons/`、`panel-final-7405/` 及 `final-rf-scope.json`。独立录音和原厂固件均不入库。

短衰落修复的实测设置：在 `CW DECODE` 页点右侧频谱窗口，选择 `AUTO` 选音；右上角自动速度同样保持 `AUTO`，门限保持自动。默认宽带 `WIDE` 或固定 `FIX` 选音不使用本次的弱音接续。纯音 `CQ` 用于验证冷启动后的收音到 LCD 链路；弱音实录另做专项。

实际导出 [705J140-CW-QSB-TEST.dat](../.analysis/cw-fade-1115/delivery/705J140-CW-QSB-TEST.dat)，12,259,086 字节，SHA-256 `10cd23ffcc579006d832bccfc3e35ef0405f3b2ba0bc59e0f15aac246a4925a4`。原厂日版 1.40 更新程序读取这组字节，写入虚拟备用 B 和选择记录并请求复位。将整个 16 MiB 虚拟 NOR 与独立解包的预期逐字节比对通过；原厂引导、正在运行的 A 和共享区未擦写。用同一写入结果从空应用 RAM 冷启动，主程序摘要 `9e1c7fcaed3ea6763a2d6291705eb95578cdfa6a2c1b21d06fe10ee8a02c86b9`，无宿主挂接。原厂收音任务送入 2,827 组模拟 DMA，LCD 显示 `CQ`；实体 EXIT 的模拟按键返回逐像素相同的原厂首页，保留 KEYER。启动至验收共记录 38 个提交帧；验收器为音频回放增大了 VDC50 和字形日志容量，未放开寄存器合法性、NOR 或画面断言。

[验收 JSON](../.analysis/cw-fade-1115/stock-dat/evidence.json)和 [LCD 截图](../.analysis/cw-fade-1115/stock-dat/cw_decoded.png)来自同一次运行。文件只在整链通过后写出，落盘摘要与送入原厂更新器的字节一致。保留原厂版本值 `1.40`，仍无开机手动 A/B，也未证明 41 系列真机无法开机时可以独立恢复。本次未连接或刷写实体机；只标为实验测试包。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps;.'
$d = '.analysis/cw-fade-1115'
py -3.14 -X utf8 -m tools.build_705_cw_sim firmware/705J140.dat "$d/repro.ic705sim"
py -3.14 -X utf8 -m tools.replay_705_cw_dat firmware/705J140.dat "$d/repro.ic705sim" "$d/repro-evidence" --dat-output "$d/repro-delivery/705J140-CW-QSB-TEST.dat"
```

复现需使用相同工具链与原厂输入，脚本只接受锁定摘要的构建，输出路径须不存在。落盘 DAT 和电脑镜像均不入库。

## 复现

用现有 ARM GNU 工具链、Unicorn 与官方日版 1.40 原文件，在项目根目录运行：

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.verify_705_cw_arm firmware/705J140.dat .analysis/cw-arm-repro `
    --arrl-wav .analysis/cw-recorder-replay/705J140-20.8000.wav `
    --arrl-reference .analysis/cw-baseline/arrl-20260106/260106_20.txt
```

输出目录须为新目录；两项 ARRL 参数可一起省略。测试只读官方 DAT。原厂音频回放、ARM 解码及原厂绘图分别运行，WAV 和译文由测试驱动转交。测试 ELF 不包含原厂更新包结构，不能用电台刷写。
