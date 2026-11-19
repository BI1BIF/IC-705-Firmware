# 日版 1.40：原厂应用入口核查

2026-11-14。**结论：本轮没有找到可信的日版原厂入口来启动独立 ARM 应用，原生路线暂停。** 这是对已核查入口的结论，并不证明固件任何位置都没有此类入口。按[验收约定](IC705_NATIVE_DECISION.md#下一轮只判断自写程序能否接入)，未制作 `APP OK` 演示或可刷写包，未访问实体电台。

| 检查 | 结果 | 能支持的结论 |
| --- | --- | --- |
| 官方与第三方文档 | [Icom 产品页](https://www.icom.co.jp/lineup/products/IC-705/)及[日版 1.40 公告](https://www.icom.co.jp/support/drivers/8603/)说明 SD 的数据与固件用途，未给应用加载接口；SQ6EMM 的 `icom-custom-firmware` 发布清单仅在其欧版 1.40 第三方条目列出 IC-705 的 `Apps`，日版条目未列。 | 第三方欧版属于线索，不构成原厂或日版接口证据。未使用第三方补丁文件。 |
| 两份原厂镜像 | 日版 `main.bin` SHA-256 `d25971deae61ab0db52ed80338516119367887728da6e67a29d05710aceac4a9`；欧版 SHA-256 `3df33f33de9b2754a86cc61608334e61364e409f5a8ce905f0fac0e42afd3b3c`。两版精确检索均捕获 71 个 `C:\IC-705\…` / `U:\IC-705\…` 路径片段，分别归并为相同的 42 个路径。`IC-705\Apps`、`IC-705/Apps`、`Homebrew`、`APP.BIN`、`dlopen` 和 `dlsym` 在 ASCII、UTF-16LE 中均未命中。 | 结果只覆盖所查字面量；动态拼接、其他编码和未解组件不在范围内。 |
| SD 文件分发表 | 日版 `0x20071C8C`、欧版 `0x20071BF4`。两版均有 63 个表内槽位：同一组 16 个走默认分支，其余 47 个有独立目标。日版静态解码逐项与 Unicorn 实际分支一致；`0x3F` 和 `0xFFFFFFFF` 也都转入 `0x20071F70` 默认分支。 | 命令先进入固件内固定分支；没有看到针对未知命令的动态分发。并未执行或完全分类所有 47 个处理例程。 |
| 原厂阳性对照 | 日版 `0x09` 到 ICF 设置处理，`0x37` 到开机图处理。进一步查到 `0x39` 也调用原厂 BMP 校验和转像素例程。重跑 BMP 对照，标准合成图返回 `0`，错误标记和宽度 479 均返回 `1`，输出 261,120 字节 RGB565。 | 可以区分已证实的原厂数据输入与应用执行入口；没有从文件字节到客体指令的证据。 |

已发现的路径可以作为接收功能和显示测试的参考。原生路线仅在出现日版实际调用一个独立应用的可复核证据，或找到有同等证据的日版接口时重开。完整备份和独立恢复仍是另一个门槛。[接收音频](IC705_RX_AUDIO.md)、[CW 基准](CW_BASELINE.md)和[离线卫星结果](IC705_SATELLITE_PASS.md)可独立使用。

## 2026-11-15：排除 AH-705 天调菜单作为本机应用入口

Icom 的[日版 1.20 发布说明](https://www.icom.co.jp/support/drivers/6128/)确认增加外接 AH-705 支持；Icom 的[规格变更说明，第 4 页](https://www.icomfrance.com/uploads/files/produit/not-IC-705_ENG_Info_V120_0a-en.pdf#page=4)明确区分 IC-705 本机升级与外接 AH-705 升级，后者由开机后的 SD 菜单读 `IC-705/AH-705` 下的 `.dat`。因此这是一条值得单独核对的原厂二进制读取路径。

| 对照 | 核查结果 |
| --- | --- |
| 日版 J140 天调升级（原厂 ARM，隔离回放） | 原始菜单描述项 `0x202E5980` 指向标签和 `0x200FAC04` 回调。用空目录列表，回调返回 `2`，没有提交请求；输入一条仅有文件名的 `PROBE.DAT` 记录，原厂回调返回 `1`，提交 UI `0x48`。原厂 UI 分发提交 SD `0x3B`，原厂 SD 分发进入固定读取器 `0x2006F434`，请求以模式 `0` 打开 `C:\IC-705\AH-705\PROBE.DAT`。在文件打开函数的第一条指令前停止。 |
| 日版 J140 原厂开机图（阳性对照） | 同一 SD 分发器在原厂开机图请求中走 `0x37`，进入独立处理器 `0x20069448`；资源测试的标准图得到 261,120 字节 RGB565，错误标记及宽 479 均被拒。 |

这证明所查 `.DAT` 菜单走固定的天调更新读取器，与官方定义一致；不构成 IC-705 主 CPU 加载独立应用的证据。回放单独调用原厂描述项回调和两个分发入口；没有重新上电，也没有走真实触屏。未放入文件内容、挂载存储或执行写入；没有尝试复刻天调固件或测试其上传。REA 的菜单记录字节窗证据号：`ev_8e0b43dfbfd3260b85f3f34a33c39b2d1edfb260177c7ad0af28f8f6d0c407a9`。记录的镜像哈希与上表相同。

要改变当前判断，仍需针对未修改的日版 1.40 找到由正常 UI 或原厂文档指定的加载接口，满足三项：可获得的合法组件及其明确的格式和适用条件；主 CPU 实际调用组件入口、退出并返回原厂界面的可复核轨迹；相同条件下无组件不启动。电脑回放出现原厂 HOME、能读菜单数据或能打开外接配件更新包，均不满足这些条件。实际刷机还须独立验证日版备份与恢复，见[安全与恢复](SAFETY_AND_RECOVERY.md)。

2026-11-15 再核公开接口：[Icom 日版产品支持](https://www.icom.co.jp/lineup/products/IC-705/)公开的[补足说明书](https://www.icom.co.jp/support/manual/5068/)是 CI-V 命令资料，另列 CS-705 配置程序和原厂固件更新；未找到公开的机内应用 SDK 或日版第三方模块安装说明。外部控制接口不等于机内组件装载接口。[未发送的日文核对单](IC705_REPAIR_INQUIRY.md)现同时询问厂家是否提供授权安装途径和同板恢复；应分别记结论。

## 复现

使用官方日版（原始 DAT SHA-256 `2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45`）及[既有的日欧解包样本](MAIN_CPU_DECODE.md)。以下命令只读固件，输出保留在 Git 忽略的 `.analysis`：

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath .analysis/ic705-emulator/deps).Path
py -3.14 -X utf8 -m tools.probe_705_menu_origin firmware/705J140.dat .analysis/ic705-emulator/j140-native-decision-baseline
arm-none-eabi-objdump -D -b binary -m arm -EL --adjust-vma=0x20005000 --start-address=0x20071c8c --stop-address=0x20071d98 .analysis/main-decode/705J140/main.bin
arm-none-eabi-objdump -D -b binary -m arm -EL --adjust-vma=0x20005000 --start-address=0x20071bf4 --stop-address=0x20071d00 .analysis/main-decode/705E140/main.bin
py -3.14 -X utf8 -c "from pathlib import Path; from tools.probe_705_resource_paths import bitmap, LAYOUTS; print(bitmap(Path('.analysis/main-decode/705J140/main.bin').read_bytes(), LAYOUTS['705J140']))"
py -3.14 -X utf8 -m tools.probe_705_ah705_route .analysis/main-decode/705J140/main.bin
```

分支表的首槽在入口加 `0x10`，每槽 4 字节；比对各槽是否命中各版的默认地址。路径统计用正则 `[CU]:\\IC-705\\[A-Z0-9_.\\-]+`（忽略大小写），字面量分别以 ASCII 和 UTF-16LE 搜索。此次结果目录 `.analysis/ic705-emulator/j140-native-decision-baseline/` 包含：`menu-origin.json`（SHA-256 `b44e72e5fdecb87b5f1decf3762892816b0a6484a893ab41f5bb934a10fe0212`）、`sd-entry-compare.json`（`1ef61415329464ab5af60ee78de5d0df6ac9b999da38230083cc7d44d1ea62b3`）、`stock-bmp-control.json`（`dc0d32894ec8d2b2ac865e87bfbe30249cc8bc27a52377d094cd2de1e2c93796`）。REA 字节范围及证据号见[工具报告](REA_ANALYSIS.md#j140-应用入口核查)。

天调对照输出 `ah705-route.json` 也在该目录，SHA-256 `47f98639320fa9c0964a8155063bcb93273ee4e77dfc7965b2ea26057c0198d4`。已确认旧版 1.32 镜像被哈希门槛拒绝，避免混用地址。
