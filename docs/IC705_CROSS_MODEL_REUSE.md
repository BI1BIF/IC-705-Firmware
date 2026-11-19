# IC-705 日版：跨机型线索与原厂启动对照

2026-11-14。以原厂 705J140 为主。跨机型查找解决的是「哪个已有实现能帮助日版在电脑上继续运行」。

## CW：可以沿用的原厂部件

2026-11-15 对照 [705 CI-V 手册](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf)第 4、26 页和 [7300MK2 CI-V 手册](https://icomuk.co.uk/files/icom/PDF/productAdditionalFile/IC-7300MK2_ENG_CI-V_0.pdf)第 4、24 页（印刷页码）。两台的 CW 音调 `14 09`、电键速度 `14 0C` 的指令和取值相同；`27 00` 射频频谱输出均为 **475 点、幅度 0–160**，USB 都分 11 段。`14 0C` 是电键设置，不能代替实收译码报速；`27 00` 的输出也不能直接当作板内数据输入。

| 借用什么 | 直接结论 |
| --- | --- |
| 705 原厂音频、调谐、按键和显示 | 当前 CW 已接 705 原厂收音任务、旋钮和显示任务；五格底栏取自本机 RTTY 外观。保留已跑通的解码器和原厂入口，不因 MK2 参考重写。RTTY 的五位符号来自 DSP，不能直接当 CW 的 PCM 输入。见[实跑验收](IC705_CW_RELEASE.md#电脑连续操作验收)与[原厂 RTTY 路径](MAIN_CPU_DECODE.md#rtty-从五位符号到正文)。 |
| MK2 的操作和译码核心 | Icom 明确称 IC-7110 沿用 MK2 CW 解码器，同时使用 705 风格界面，说明功能层可以跨机型复用。MK2 把译码放在 DSP；虽与 705 同属 SHARC 系列，现有证据仍不能把 MK2 的 DSP 程序直接装到 705。只在取得解码段并能对齐音频和结果接口时评估替换核心，保留本机其余功能。见[原厂资料及固件比对](IC705_CW_MK2_PICTURE.md)。 |
| 初代 7300 的动态瀑布回放 | [公开 QEMU 工程](https://github.com/jeskko/ic7300-homebrew/blob/84fb65b457f00bddcf5fb3d044e9f29dad3be48b/notes/fpga-link.md#7-the-model-built-2026-09-24-)已有生成连续载波、噪底和控制供帧节奏的方法。可借用这组刺激思路，交由 705 自己的原厂频谱和瀑布处理。初代 7300 的 RSPI2 模型给出字节序列；705 已找到的是 32 位字块接收入口，尚未复现到它的底层板级传输，不能照搬该模型的地址、包头或时序。 |

**日版 1.40 原厂频谱收帧与发布已在电脑局部实跑。** 用 GNU objdump 定位 `0x201203F4` 收块、`0x2012038C → 0x201202D0` 转换、`0x2011FE38` 发布；REA 取样记录 `ev_fcdb2970f52fb129601a69729e8ae2ca7147abe95b19129a5846eb5b34ffc5e4` 绑定同一原厂主程序及接收窗口。使用现有 ARM 模拟器，在未修改的主程序里供应七个模拟块，给每个点可独立计算的幅度；标记相符且数据齐备时，原厂代码转换并发布目标 475 点（0–160、SHA-256 `1b2af1839b6e921dff956247bffe1110a12b07173634b863520e029b18792fb9`）。给满数据但改错标记、或给正确标记但少最后一块，两者均不发布。测试只布置函数入口所需状态和输入；没有直接填发布缓冲、没有绘屏、未模拟扫描硬件或衡量帧速。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_rf_sweep .analysis/main-decode/705J140/main.bin
```

后续已通过[变化射频的同场 A/B](IC705_CW_RELEASE.md#原厂射频频谱和瀑布开关-cw-对照)：同一模拟输入经过 705 的原厂 DMA 和绘图，开关 CW 都显示 48 次频谱变化、12 次瀑布新增行，最长相邻间隔相同。CW 增加总提交次数；实体板的实时耗时仍未测。这次继续复用 705 原厂处理，没有引入初代 7300 的驱动或重做瀑布。

| 公开线索 | 已有证据与可用范围 |
| --- | --- |
| [IC-7300 QEMU 工程](https://github.com/jeskko/ic7300-homebrew/tree/84fb65b457f00bddcf5fb3d044e9f29dad3be48b) | 作者用未修改的 IC-7300 固件跑到可操作原厂首页；其 [QEMU 外设说明](https://github.com/jeskko/ic7300-homebrew/blob/84fb65b457f00bddcf5fb3d044e9f29dad3be48b/qemu-machine/README.md)涵盖 MTU2、VDC5、OpenVG、SDHI 和音频输入。可参考同型号芯片的外设模型；显示、存储、DSP/FPGA 和中断的板级连接仍要用 705 证据核对。作者的 SSTV 示例使用自制加载器，只在仿真中测试，无法证明日版原厂支持应用加载。 |
| [SQ6EMM 的格式研究](https://github.com/sq6emm/ic705-ic9700-ic905-bring-your-own-firmware/blob/6adfab19d58e64f3362d72e8fd7d41dbd47a8eee/IC705_DAT_FORMAT.md) | [本地跨机型比对](CROSS_MODEL_FORMAT.md)见到 IC-705、IC-9700、IC-905 的尾段结构关联，但包头、分段边界或摘要规则不同。可用于互相验证文件结构假设。日版与国际版 Apps 差别见[加载入口记录](IC705_APP_ENTRY.md)。 |
| [独立的 IC-7300 FT8 研究](https://github.com/zarthur/ic-7300_firmware#feasibility-boundary) | 作者的桌面解码测得约 231 KiB 编解码器堆占用，另需栈和上下文。可作为 705 接收端资源评估的参照，但板上余量、音频缓冲和实时表现还需独立验证。 |

## 在日版 1.40 上复现

[Renesas 硬件手册](https://www.renesas.com/en/document/mah/rza1h-group-rza1m-group-users-manual-hardware)给出时钟门控和 MTU2；IC-7300 模拟器的 [MTU2 源码](https://github.com/jeskko/ic7300-homebrew/blob/84fb65b457f00bddcf5fb3d044e9f29dad3be48b/qemu-machine/src/mtu2.c)给出通道 4 的 `TCR_4 = 0xFCFF0000 + 0x201`。使用本地提取的 J140 主程序（SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`），从原厂资源函数入口 `0x2010490C` 开始执行，只增加被观察寄存器的模拟响应。控制组将时钟寄存器初值分别设为 `0x00` 和 `0xFF`：

| 同一原厂代码的三次对照 | 实际结果 |
| --- | --- |
| 原有模型 | 停在 `0x20367B04`：读取 `0xFCFE0420`（STBCR3）。 |
| 加入 STBCR3 | `0x20367B10` 清除 bit 3，写回分别为 `0x00` 和 `0xF7`。两组下一站都是 `0x20005D80` 向 IC-7300 模型中同地址的 `TCR_4` 写零。 |
| 再接受 TCR_4 的初始化写入 | 原厂 ARM 接着在 `0x20005D84` 向 `0xFCFF0203` 写零。探针停止；两个字体指针和长度在两组实验中均未填入。 |

确认的是共享外设寄存器和日版执行顺序。尚未模拟 MTU2 计数或中断，不能从此次写入推断通道职责、时钟频率或任务调度与 7300 相同。也没有运行 IC-7300 的固件、构建其 QEMU，或修改 IC-705 样本。

静态反汇编还给出下一组可核对的参数：J140 在 `0x20005D9C` 拟向同一通道的 `TGRA_4` 写入 `8000`，在 `0x20005DBC` 以编号 `159` 调用候选中断注册函数。后者与 7300 模型中的 `TGI4A` 一致。这两条指令在上述回放中还未执行，不能据此认定处理函数或周期相同。

复用[现有字体回放](IC705_SD_RESOURCES.md#复现)，把结果目录设为 `.analysis/ic705-emulator/j140-cross-model-mtu/replay`。新证据位于 `font-boot.json` 的 `mtu2_controls`，SHA-256 `adbaddd0913992ee59c95d7eba0793f3ab12c2c33b253d1e0a5601dfc11d5f80`。旧停点、字体标签控制、原厂菜单行和替代字库继续作为对照。当前 Windows 已能完成这段验证；若需要周期中断，再在已有 Debian WSL2 环境评估 QEMU。

后续验收已通过：[从同一个原厂入口连续写入字库表，并用表绘出原厂菜单行](IC705_SD_RESOURCES.md#j140从函数入口连续写表并用写出的字库绘制)。观察到原厂使能和 IC-7300 相同的两个中断编号；此段只配置它们，不需要模拟实际触发。
