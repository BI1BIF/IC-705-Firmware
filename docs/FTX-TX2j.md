# FT8 / FT4 · TX2j · 2026-11-20

[固件转换页 · Firmware converter](https://bi1bif.github.io/IC-705-Firmware/) · [操作演示 · Simulator GIF](images/ftx-tx2j.gif)

日版 IC-705 1.40。本次公开版合入 FT8／FT4 收发，并包含原有 CW D6 和 SSTV RX4-TX4。转换页使用原厂 DAT 生成目标固件。TX2j 输出的 SHA-256 为 `8dcb44ae45c02d963d4eba6c9feca23d97f1e90b1f0409f75366de7d467c3c68`。

This build adds FT8/FT4 to the Japanese IC-705 1.40 CW D6 and SSTV RX4-TX4 firmware. The converter checks the original DAT and verifies its output against the digest above.

| 操作 | 中文 | English |
| --- | --- | --- |
| 进入 / Open | 点原厂模式键 → FT8/4 → FT8 或 FT4。FT8 每隙 15 秒，FT4 每隙 7.5 秒。频率和 S 表保留在上方。 | Tap the stock mode button → FT8/4 → FT8 or FT4. Slot lengths are 15 s and 7.5 s respectively. |
| 收听 / Listen | 十行列表按接收顺序显示。上页看较早报文，下页返回较新报文。「仅看 CQ」筛选呼叫。地名按呼号前缀估计，有本台位置和对台网格时可显示距离。 | Browse older or newer decodes and filter for CQ. Country or region is inferred from the call. Distance uses the local position and the other station’s grid. |
| 设置 / Set up | 在菜单选择 GPS 或机内时钟授时。使用机内时钟时核对日期、时间和 UTC 偏移。在本台设置核对呼号、网格和发射音频频率。 | Select GPS or the internal clock. For the latter, check date, time and UTC offset. Check your call, grid and TX audio frequency. |
| 通联 / Work a station | 点「呼叫 CQ」或选中收到的报文后点「应答」，预览报文再点发送。页面区分等待时隙与正在发射。自动选台决定答谁，自动通联控制后续报文编序。 | Call CQ or select a decoded station and reply. Review the message and queue it for transmission. The screen distinguishes queued from on air. Caller selection and exchange sequencing have separate controls. |
| 日志 / Log | 已确认对台并发完结束语后，记录追加到 SD 卡 `IC-705/FTLOG.ADI`。FT8／FT4 共用 ADIF 3.1.6 文件，可从 FT 菜单查看。 | After a confirmed exchange and completed final transmission, the radio appends a QSO to the shared ADIF log. Open the FT menu to view it. |

## 验证与已知现象 · Validation and field observations

用户已在早期 FT 测试版上确认实机接收和发射。下表为最终 TX2j 的本地回放结果。实体转轮在 FT 页面中的手感，以及 ESP32 遥控同时使用时的偶发停更，仍待真机核对。

Reception and transmission were observed on hardware with earlier FT builds. The results below are local TX2j replays. Dial response and intermittent stalls with a connected ESP32 remote still need on-radio testing.

| 回放 / Replay | FT8 | FT4 |
| --- | --- | --- |
| 常规内存 / Normal memory | 连续 6 隙，每隙 13 条 / 13 decodes in each of 6 slots | 连续 8 隙，每隙 12 条 / 12 in each of 8 slots |
| 低内存 / Reduced memory | 13 × 6 | 11 × 8 |
| 遥控 CI-V 轮询 / Remote polling | 单独回放 13 × 6；多项测试并跑时一隙为 12 条 / 13 × 6 in isolation, one slot with 12 under parallel test load | 12 × 8 |

TX2j 调整了收听页顶栏对齐。列表内容没有变化时，每帧文字绘制由六次降到一次。在两种内存档，31 份弱信号或噪声录音和 12 份带时频偏移录音的结果均与 TX2i 一致。`No RX audio` 表示约两秒没有收到机内音频回调，`RX paused` 表示当前模式或电台收发状态暂停接收。

TX2j centers the header labels and reduces text draws on stable list frames from six to one. Both memory profiles matched TX2i on 31 weak-signal/noise recordings and 12 time/frequency-offset recordings. The screen reports missing RX audio callbacks after about two seconds and distinguishes a receiver paused by radio state.

## 源码 · Source

- [机内模块 / On-radio modules](../samples/ftx/) · [J140 构建 / Firmware builder](../tools/build_705_ftx_rx.py) · [连续接收回放 / Continuous receive replay](../tools/verify_705_ftx_rx.py)
- 解码使用 [kgoba/ft8_lib](https://github.com/kgoba/ft8_lib)，旗标使用 [flag-icons](https://github.com/lipis/flag-icons)，国家或地区映射参考 [FT8CN](https://github.com/N0BOY/FT8CN)。中文和拉丁文字形来自 Noto Sans SC。Dependencies and asset licenses are listed in the [third-party notices](converter/ftx-notices.txt).
- The builder checks the SHA-256 of its CW/SSTV input. Use the previous release’s browser patch and your Japanese 1.40 DAT to obtain that baseline. The previous [version manifest](https://github.com/BI1BIF/IC-705-Firmware/blob/d147a32/docs/converter/latest.json) identifies the patch and the required baseline digest. The builder reads that baseline under `.analysis/j140-sstv-rx4-tx4/705J140-CW-D6-SSTV-RX4-TX4.dat` and the original at `firmware/705J140.dat`.

构建入口为 `python -m tools.build_705_ftx_rx`，输出 `.analysis/j140-ftx-tx2j/bench-rx.dat`。此次重建使用 Arm GNU 14.2.1、Android NDK 27.2.12479018 的 Clang、Node 24.14.0、Pillow 12.1.1、resvg-py 0.5.0、Unicorn 2.1.4 及 pyelftools 0.33。Windows 可用 `IC705_CLANG` 指定 Clang 路径，并设置 `PYTHONUTF8=1`。构建脚本按固定 Git 提交读取第三方源码和图标。
