# 日版 1.40：CW 真机地址与内存预算

2026-11-15。**现有 CW 电脑试验版不能原样在原厂内存布局中运行。** 这次从日版原厂 ARM 复位入口运行到页表建成，再启用原厂地址映射。用于 CW 的三个试验地址在电脑平坦映射中可读或可执行；启用原厂映射后，同样的访问全部触发异常。同时，原厂数据读取和原厂代码执行两个对照仍然正常。

[Renesas RZ/A1H 硬件手册，表 5.5](https://www.renesas.com/en/document/mah/rza1h-group-rza1m-group-users-manual-hardware)把片上 RAM 列在 `0x20000000–0x209FFFFF`；实验的 `0x2100xxxx` 窗口不属于这段物理 RAM。日版 J140 复位从 `0x20005060` 起跑，其中调用 `0x20124E90` 产生原厂页表；`TTBR0=0x20000009`，表从 `0x20000000` 起。再运行原厂 `0x20125520` 的启用代码至 `0x20125568`，CPU 已打开 MMU，页表内容未变。试验地址所在 1 MiB 段的首级项为 `0x21000000`，低两位为零。REA 给出的原厂窗口及主程序哈希见下方；访问是否成功由 Cortex-A9 回放实测。

| 当前试验版内存 | 预算 | 原厂地址映射启用后的对照 |
| --- | ---: | --- |
| ARM 指令及只读数据，`0x21008000` | 14,500 字节 | 取指失败，模拟器报告预取异常 |
| 解码、音频和瀑布状态及任务描述符，旧地址 `0x21001000` | 4,096 字节，原厂分配另计 8 字节 | 旧地址不可读；[迁移后的状态已通过冷启动回放和单独读写验证](#原厂分配-cw-会话状态) |
| 波形和瀑布图的 RGB565 暂存，旧地址 `0x2100C000` | 22,080 字节，原厂分配另计 8 字节 | 旧地址不可读；[已验证原厂分配、绘制和归还](#原厂分配波形及瀑布画布)，另测新画布地址首尾均可读写 |
| RTX 任务栈 | 4,096 字节栈，另有 8 字节分配头 | 原厂 RTX 实际分配；[电脑回放最深写入 212 字节、栈首尾按原厂映射可读写](#原厂-rtx-栈分配和实测) |

上述旧试验版合计 **44,772 字节（约 44 KiB）**，未计分配开销；按试验回放的页映射和栈申请是 **48 KiB**。迁移状态和画布后的试验版为 **44,672 字节**，其中 **30,272 字节**是数据和栈，**14,400 字节**是代码和只读数据。完整程序现已在[原厂映射下通过冷启动接收](#原厂地址映射下运行-cw)；由宿主加载，原厂还没有经验证的安装入口。

复现（原厂 DAT 只读，仅在主机生成证据；报告拒绝较旧的日版输入）：

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
py -3.14 -X utf8 -m tools.probe_705_cw_address_map firmware/705J140.dat .analysis/cw-deployment-budget/verify.json
```

结果 `.analysis/cw-deployment-budget/evidence.json`，SHA-256 为 `fd4fdb167b918959ebdb089a1456ce57f950eb24b281170b48f539e67f0bdc4f`，重复生成逐字节一致。REA 文件窗口绑定的主程序 SHA-256 为 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`；页表构造、启用例程的完整证据分别为 `ev_6f35804038ace79373f3185387bd5b292eb43d95a362948931d4bb81acb95131`、`ev_b32bf8c73d887b6679bb3ebcd46004a50d4346a5231e987a1bca168c627778be`。测试只运行原厂启动片段，未把整个无线电系统切到 MMU 模式下完成冷启动，也未接触实机。

## 原厂 RTX 栈分配和实测

原厂线程创建入口 `0x202D48C1` 进入 `0x202D5FE8`，从线程描述符读取 `4096`，再调用原厂分配器 `0x202D4B16`。启动实跑先观察到 `0x202D4E68` 初始化 `0x2049A5C0–0x204B9EB0` 的 129,264 字节栈池（末地址不含），然后从分配器返回值和 CW 线程控制块两处分别取得 `0x2049CD00`，栈上界为 `0x2049DD00`。分配器另计 8 字节管理头；原厂设置初始保存 SP `0x2049DCC0`，在栈底写入哨兵 `0xE25A2EA5`。池大小不是剩余容量，也不作为图形或指令的分配依据。

| 日版 1.40 原厂调度电脑回放 | 模拟 DMA 组数 | 栈最深写入 |
| --- | ---: | ---: |
| 解码计算中两次抢占：发射请求、EXIT 后重新进入；译文按预期恢复 | 27,322 | **212 字节** |
| 41 次屏幕重画中插入音频中断；对照的 41 帧逐张一致、无丢组 | 9,840 | 208 字节（有无插入均相同） |
| WIDE、FIX、AUTO，含邻台与慢漂移，原厂界面照常更新 | 148,960 | 208 字节 |

最深写入发生在原厂保存 CW 线程寄存器时（PC `0x200057A8`，写到 `0x2049DC2C`）；CW 代码本身最深写到 `0x2049DC30`。各组管理头和栈底哨兵均未动；最深的一组仍有 3,880 字节位于哨兵以上且未观测到写入。另用不装观测器的 `--cw` 对照，除新增的栈报告外，其余字段完全一致。这里测的是受测场景对**工作线程栈实际写到的最低位置**，不计保留但未写的空间，也不代表所有中断时序或 UI 线程栈的峰值。

独立的复位回放使用原厂页表项 `0x20485C06`；MMU 开启后，用原厂 ARM 指令读写该栈的首尾字 `0x2049CD00` 和 `0x2049DCFC`，并核对到相同的物理地址。这一步在分配器还未运行的另一个来宾中进行，测完复原测试字；没有在实时调度中覆盖栈内容，也没有把整个 CW 程序迁入原厂映射。原厂 DAT 全程未变。

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-stack-audit/preempt/evidence.json --cw --measure-worker-stack
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-stack-audit/redraw/evidence.json --stress-screen --measure-worker-stack
py -3.14 -X utf8 -m tools.probe_705_rtx_audio firmware/705J140.dat .analysis/cw-stack-audit/adjust/evidence.json --adjust-screen --measure-worker-stack
py -3.14 -X utf8 -m tools.probe_705_cw_address_map firmware/705J140.dat .analysis/cw-stack-audit/address-map-recheck.json --worker-stack-report .analysis/cw-stack-audit/preempt/evidence.json
```

证据 `.analysis/cw-stack-audit/`。报告 SHA-256：`preempt/evidence.json` 为 `bc341d365be3ea2bd0667cbd63e51d7243e2575506bcdc757b8e7a0043a1246f`；`redraw/evidence.json` 为 `51ff8b57388ab858b5cdc8dd72986a5beb9ee8099dff8065408373121d92f599`；`adjust/evidence.json` 为 `617d4f85ffe9937db714c6f0816224838b2a184e63f4ae122b07f1bdd58ab610`；`address-map.json` 为 `fabef25bbe797fa6a0965190188761536e008011dfd7a427a60e6fef8812908e`。REA 将线程创建、栈分配与初始化依次绑定到 J140 的三个原厂窗口：`ev_c0787b2df00fcaf24926db849283a1d89f81fe652864063f6eaf0e524e33cf15`、`ev_2252639914a8a550ffcfa1e6816f129f5bc321f4e469fc31ab3c4b18696d8a83`、`ev_bd3278e11b28978b05f223b84a9631789c24171fabb7ae578738e654aaea1b88`。行为及峰值来自 ARM 回放。

## 原厂分配波形及瀑布画布

原厂通用分配包装 `0x20127A28` 调用 Thumb `0x202D3A18`，将对齐后的 917,496 字节设为池初始长度。空闲链表入口 `0x20381F2C`，堆范围 `0x20750A44–0x20830A3C`（末地址不含）。在原厂冷启动后实际读链表，首次到达可操作 HOME 时剩余 **379,896 字节**，其中最大的一块 **367,888 字节**；这是日版 1.40 在该回放条件下的余量，不是所有模式的余量。原厂两块 LCD 缓冲 `0x208AE000`、`0x208EDC00` 与中间画布 `0x2094EB00` [已确认正在使用](IC705_SD_RESOURCES.md)；实验没有借用这些地址，也未使用 `TextSurface` 的电脑堆模型。

原厂 UI 任务第一次绘制 `CW DECODE` 时请求 **22,080 字节**，分配器返回 `0x207D6D30`，末地址 `0x207DC370`。连同管理开销，活跃时比固定画布对照少 **22,088 字节**。同一块画布供 5 次原厂 RGB565 图形拷贝，每次核对源地址、尺寸及像素散列；收到模拟的 2,827 组 DMA 后，屏上显示 `CQ`。按实体 EXIT 的模拟输入后，原厂 UI 调用 `0x20127A78` 归还画布，原内存区重新进入空闲链表。回到 HOME 时两组空闲清单逐项相同（379,072 字节／98 块），因此分配画布没有留下净占用。两组进入前相同、退出后相同，但任一组自身前后都少 824 字节；保留这项原厂界面活动的共同变化，不假定系统其他分配静止。两组 12 张 LCD 帧和 10 张导出 PNG 完全一致；调度时间戳有少量差别，不算作耗时相同。

这条冷启动回放关闭了硬件地址转换，由软件模型执行图形命令。同一份原厂页表在独立复位试验中实际开启后，使用原厂指令读写 `0x207D6D30`、`0x207DC36C`，确认首尾字映射到相同物理地址；页表项 `0x20785C06`。这两组证据合起来支持分配与地址可达；不能代替原厂映射开启后的连续回放、真实 GPU 缓存一致性或长期实机压力测试。声学输入为模拟；原厂 DAT 不变，无实体写入。

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
$out = '.analysis/cw-stock-canvas-recheck'
foreach ($kind in 'stock','fixed') {
    py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-current-format --startup-home-probe `
        --no-power-on-check --startup-input close-cw --startup-cw-decode --startup-cw-rx-test `
        --startup-cw-canvas-audit $kind firmware/705J140.dat "$out/$kind"
}
py -3.14 -X utf8 -m tools.probe_705_canvas_heap "$out/stock" "$out/fixed" "$out/evidence.json"
py -3.14 -X utf8 -m tools.probe_705_cw_address_map firmware/705J140.dat "$out/address-map.json" --canvas-report "$out/evidence.json"
```

证据 `.analysis/cw-stock-canvas-final/`：[接收画面](../.analysis/cw-stock-canvas-final/stock/boot-cw-decoded.png)；`evidence.json` SHA-256 `2b730cc538952a78c579163698d1ffa17f643b404d9e9558ce6c0b0edb01a20f`；含线程栈与画布的 `address-map.json` SHA-256 `235876abeda85addadb74412958d5acbb28f5614cbee7c1c79d19e5d6afdce9e`（复跑时加上一节的 `--worker-stack-report`）。REA 的初始化、包装、分配、释放窗口分别是 `ev_09adffd441a10be0af2321ecda291e8d89ad8393e44566fe8bfec0fdcdd49d77`、`ev_8e7b4b2e86af9e68696171e4178b5c587491fdba90f0b9aeca14bc98c8ccef74`、`ev_90a8d7087880aae0ac6b41a9c707e3569e91f8e2aab950a5a7b397f944113b1a`、`ev_2b014c83b835f6beedc5b1d3cd6c5a30ca21096e4361ab251db9caccbe8efdbe`。

## 原厂分配 CW 会话状态

进入原厂 HOME 后，在可中断的主任务上调用原厂带锁分配器 `0x20127A28`，申请 **4,096 字节**，返回范围 `0x207D4740–0x207D5740`（末地址不含）。在申请前后读取原厂空闲链表及分配头，核对有效负载、8 字节管理开销、原任务所有者和软件中断状态。测试工具把这个基址写入扩展代码的只读指针槽再设为只读可执行；没有覆盖原厂全局变量、映射旧 `0x21001000` 或执行持久写入。工作线程描述符、主任务音频队列、译文、估速、音频频谱及画布指针共享同一项分配。

与仍用固定状态地址、但同样走原厂画布分配的对照相比，**12 张 LCD 帧、5 次波形/瀑布的像素数据、2,827 组输入音频全部一致**，屏上显示 `CQ` 后用机身 EXIT 回到相同的 HOME。画布照常释放；存活的 CW 线程保留会话块作后续使用，因此退出后仅比对照少 **4,104 字节**（含管理开销），不会把应继续使用的会话和该次画布一并释放。这次只冷启、进入、接收和退出各一次；未据此宣称重复进入和长时间实机运行都已验收。

独立开启原厂 MMU 后，使用原厂指令读写 `0x207D4740` 与 `0x207D573C`，均落到同名物理地址；加上已验栈和画布，这个报告共通过 11 项（含旧地址异常的负对照）。冷启动整链仍未开启原厂地址转换，因为扩展代码的 `0x21008000` 仍取指失败。正常编译的 `--cw` 抢占回归通过；相对旧报告仅有工作线程入口随本次编译移动 8 字节，其余记录一致。固定画布对照报告重复生成逐字节一致。

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
$out = '.analysis/cw-stock-state-recheck'
py -3.14 -X utf8 -m tools.replay_705_font_boot --startup-current-format --startup-home-probe `
    --no-power-on-check --startup-input close-cw --startup-cw-decode --startup-cw-rx-test `
    --startup-cw-canvas-audit stock --startup-cw-stock-state firmware/705J140.dat "$out/cold"
py -3.14 -X utf8 -m tools.probe_705_canvas_heap "$out/cold" .analysis/cw-stock-canvas-final/stock "$out/evidence.json" --state
py -3.14 -X utf8 -m tools.probe_705_cw_address_map firmware/705J140.dat "$out/address-map.json" `
    --state-report "$out/evidence.json" --canvas-report .analysis/cw-stock-canvas-final/evidence.json `
    --worker-stack-report .analysis/cw-stack-audit/preempt/evidence.json
```

证据 `.analysis/cw-stock-state-final/`：`evidence.json` SHA-256 `be40ff5594f69fddb4bb6d8dbf58e58b9868eabafa6b466049272e0e13b0a2c6`；`address-map-v2.json` SHA-256 `bf9e90cc5e65c3dc296ee69051fc5a86d3eac15297d7e01173abc2ab62fba087`。

下一项是查 14,400 字节代码及只读数据的装载路径和执行区归属。原厂 ARM 启动的已验内存初始化表只有三段（复制初始化数据、清零两段 RAM），入口 `0x200052A0`，表 `0x2000530C–0x2000533C`（末地址不含）；目前没有该表为附加代码留位的证据。REA 对应窗口 `ev_1718166abf7c3fa06004baa7dfb6a32971e07066ffbcd6f85ee27a5d1cf5c028`、`ev_e2ca67af042729a1023da7f77bcebbbc6c2aeb9029e0346b4e2fbf6b6ae13b00`。应先验证原厂代码装载边界与 MMU 下的原厂启动对照，再将有明确归属的代码在同一回放验收收音、画屏和退出。[安全安装和原板独立恢复](IC705_CW_RELEASE.md)仍须另行验收。

## 原厂引导装载边界

用日版 1.40 和 1.32 未修改的主程序数据执行共用 ARM 引导例程 `0x200045F4`。引导从所选源头的第二个字读取长度，然后调用 `0x200044DC` 解包。实际输出与独立解包的文件逐字节相同，起点均为 `0x20005000`；在起点前 64 字节和末端至 `0x20380000` 的整段中填入测试值，监视写入，返回时也逐字节核对，两组均未发现改动。

| 日版 | 输出字节 | 输出末端（不含） | 末端至 J140 数据复制目标 |
| --- | ---: | --- | ---: |
| J140 | 3,558,076 | `0x20369ABC` | 91,460 字节 |
| J132 | 3,636,768 | `0x2037CE20` | 12,768 字节 |

J140 后续从 `0x20367B78` 复制 `0x1F44` 字节，源区结束位置恰好等于输出末端；目标为 `0x20380000`。表格的差距只说明本次解包没有写它，不能作为空闲、可执行或可部署空间的证据；1.32 已经用掉其中大部分。REA 核对引导代码窗口与原件哈希 `ev_b1bd139355e0860c9b5c4c345b554b76eff3ec1e84705790169b2f78c8f8b9bd`。从项目根目录运行：

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_boot_selection firmware/705J140.dat firmware/705J132.dat .analysis/cw-stock-mmu/loader-span.json --catalog research/705j-provenance.json
```

## 原厂地址映射开启的冷启动对照

未修改的 J140 从 `0x20005060` 开始，实际建立页表，按原厂指令复制及清零数据。原厂在 `0x20125560` 启用 MMU；记录显示 SCTLR 的 M 位在 `0x20125568` 由 0 变为 1，串口等待和退出菜单后的调度停点仍为 1，TTBR0 始终为 `0x20000009`。五个检查点读取的 16 KiB 首级页表哈希一致。用 Renesas 硬件手册 R01UH0403EJ0700 表 7.2 补上启动访问的中断控制寄存器；对应原厂初始化字节由 REA 核对，证据 `ev_a25fcb51b545f4bc906e92bd60e988b2321b13f3e28007174c48c4340e1a18f4`。

在此回放中，原厂启动到 VFO A／7.030 MHz／CW，收到模拟机身 MENU 后画出原厂 KEYER 菜单，再由 EXIT 返回首页。两组（原厂 MMU、旧平坦映射）的 8 幅 PNG 全部逐字节相同；两组 HOME 在 EXIT 前后也各自相同。原厂操作码为 5、9，无持久写入。试验使用合成外设及软件绘图，未加载 CW 扩展，未与实体电台通信。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
$replay = @('--startup-current-format', '--startup-home-probe', '--no-power-on-check', '--startup-input', 'close-cw')
py -3.14 -X utf8 -m tools.replay_705_font_boot @replay firmware/705J140.dat .analysis/cw-stock-mmu/flat-control
py -3.14 -X utf8 -m tools.replay_705_font_boot @replay --startup-stock-mmu firmware/705J140.dat .analysis/cw-stock-mmu/mmu
```

结果在 `.analysis/cw-stock-mmu/frame-comparison.json`（SHA-256 `4b726da8ba0a444b28644f54f08664d8d2abff8af40083f47fc2b245221c5532`）与 `mmu/startup-current-format.json`。

## 原厂地址映射下运行 CW

同一次 J140 冷启动到 HOME 后，测试工具请原厂带锁分配器预约 **14,464 字节**（含管理头与对齐），调用地址和值与返回的分配头、空闲链表逐项核对。在宿主进程内重新编译本项目的 **14,400 字节** ARM 代码及只读数据，装入其私有范围 `0x207D6D30–0x207DA570`（末地址不含）。原厂节描述符为 `0x20785C06`；没有改页表，也没有使用旧地址 `0x21008000`。原厂分配器及 RTX 返回到原厂主任务暂停处；调用原厂线程创建函数之后，由仿真挂钩导向本项目代码。退出时代码块保持完整，由仍存活的 CW 线程使用；两组 EXIT 后的空闲总量之差正好是 14,464 字节。REA 核对分配器与 RTX 入口窗口 `ev_48ba3125edbb57edeb49d975626f1ba84677420ddfe609ac194bd3f7ceafd5e5`、`ev_821e733aa0422bc3913c58883c924176aebb6d316d42cb2b896ddf3e52b83d47`。

| 冷启动专项 | 原厂 MMU 开启与旧平坦对照 |
| --- | --- |
| 原厂收音任务 | 2,827 组模拟 DMA 逐字节核对，212 个解码块，屏上显示 `CQ`，无丢组 |
| 原厂 UI | 12 个 LCD 帧、10 张 PNG、5 次波形／瀑布像素拷贝与旧对照一致 |
| 机身 EXIT | 回到字节相同的原厂 HOME；22,080 字节画布归还，启动时分配的代码、会话和线程仍保留 |
| 地址转换 | 原厂打开 MMU 后，挂接和退出都为 `SCTLR=0x20c5187d`；首级页表哈希与原厂空载对照一致 |

第一次按代码实际长度分配，造成画布移到与旧回放不同的对齐位置：原厂调用了 5 次图形接口并归还画布，在那里没有观察到同规格的硬件拷贝命令。最终对照将**代码分配总额**取到 64 字节的倍数，保持后续画布与已验证样本相同的对齐类别，5 次拷贝全部匹配。尚未验证各种实际堆布局下的绘图开销、实体缓存一致性或真机的代码装载；不能把一次首页的堆余量当成常数。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
$out = '.analysis/cw-native-map-recheck'
$replay = @('--startup-current-format', '--startup-home-probe', '--no-power-on-check', '--startup-input', 'close-cw', '--startup-cw-decode', '--startup-cw-rx-test', '--startup-cw-canvas-audit', 'stock', '--startup-cw-stock-state')
py -3.14 -X utf8 -m tools.replay_705_font_boot @replay firmware/705J140.dat "$out/flat-control"
py -3.14 -X utf8 -m tools.replay_705_font_boot @replay --startup-stock-mmu firmware/705J140.dat "$out/mmu"
py -3.14 -X utf8 -m tools.probe_705_canvas_heap "$out/mmu" "$out/flat-control" "$out/evidence.json" --mmu
```

[接收画面](../.analysis/cw-native-map-1115/mmu/boot-cw-decoded.png)与报告 `.analysis/cw-native-map-1115/evidence.json`（SHA-256 `422ad7914f950f66d7210eb486297ab4578831ef332b1734006516a03f8f201c`）。程序只存在于测试进程的来宾 RAM，原厂 DAT 哈希没变，没有持久写入。安装是[独立关口](IC705_CW_RELEASE.md)，仍须证明冷启动时不靠宿主也能装载本项目代码，并有同板恢复能力。

## 波形与瀑布不依赖固定画布地址

上面的首次回放只验证了一种画布位置。现在由 CW 画布自己向 705 的原厂分配器多要 24 字节（合计 22,104），给 RGB565 图的最后一行做 32 字节对齐；原厂绘制从最后一行向上读取。绘图用对齐后的指针，EXIT 用原厂分配器返回的原指针归还。测试分四次改变预约块的尾部余量，让后续画布覆盖原厂 8 字节对齐时所有四种地址。每次使用同一份 14,440 字节测试代码、同一原厂页表和音频。

| 测试预约额外字节 | 画布原地址对 32 的余数 | 画布实际补位 |
| ---: | ---: | ---: |
| 0 | 16 | 0 |
| 8 | 24 | 24 |
| 16 | 0 | 16 |
| 24 | 8 | 8 |

四次各由原厂任务收 2,827 组模拟音频，屏幕解出 `CQ`。12 个 LCD 帧、10 个 PNG、5 次波形／瀑布像素拷贝全部与已确认的旧对照一致；退回 HOME 后画布均已归还，无持久写入。对照记录见 `.analysis/cw-canvas-placement-1115/placements.json` 和 `compare-{0,8,16,24}.json`。这是电脑回放，未测真机液晶刷新、图形加速和实际运行耗时。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
$out = '.analysis/cw-canvas-placement-recheck'
$replay = @('--startup-current-format', '--startup-home-probe', '--no-power-on-check', '--startup-input', 'close-cw', '--startup-cw-decode', '--startup-cw-rx-test', '--startup-cw-canvas-audit', 'stock', '--startup-cw-stock-state')
py -3.14 -X utf8 -m tools.replay_705_font_boot @replay firmware/705J140.dat "$out/flat"
foreach ($offset in 0,8,16,24) {
    py -3.14 -X utf8 -m tools.replay_705_font_boot @replay --startup-stock-mmu --startup-cw-heap-offset $offset firmware/705J140.dat "$out/offset-$offset"
    py -3.14 -X utf8 -m tools.probe_705_canvas_heap "$out/offset-$offset" "$out/flat" "$out/compare-$offset.json" --mmu
}
```
