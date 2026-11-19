# 合成测试数据

单元测试在内存构造 A32 编码、周期性字节、字符串和虚构的四组容器，不依赖任何原厂文件。[arm-smoke.s](arm-smoke.s) 是独立的 GNU ARM 工具链验证样本；只汇编和反汇编，不执行。构建输出放在 `.analysis/`。

Windows 验证示例，在项目根目录执行：

```powershell
$armBin = 'C:/Program Files (x86)/Arm GNU Toolchain arm-none-eabi/14.2 rel1/bin'
$reaNode = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$reaCli = Join-Path $env:USERPROFILE '.codex/tools/rea/node_modules/rea-agents/scripts/rea.mjs'
New-Item -ItemType Directory -Path .analysis -Force | Out-Null
& "$armBin/arm-none-eabi-as.exe" -march=armv7-a -o .analysis/arm-smoke.o samples/arm-smoke.s
& "$armBin/arm-none-eabi-ld.exe" -Ttext=0x8000 -e demo -o .analysis/arm-smoke.elf .analysis/arm-smoke.o
$objdumpBefore = $env:REA_OBJDUMP_COMMAND
try {
    $env:REA_OBJDUMP_COMMAND = "$armBin/arm-none-eabi-objdump.exe"
    & $reaNode $reaCli inspect-with-objdump .analysis/arm-smoke.elf disassemble --format json
} finally {
    $env:REA_OBJDUMP_COMMAND = $objdumpBefore
}
```

应报告 `elf32-littlearm`、`0x8000: mov r0,#7`、`0x8004: bx lr`。

转换同一合成样本为无头二进制可单独验证 REA 的 Windows 准入范围：

```powershell
& "$armBin/arm-none-eabi-objcopy.exe" -O binary .analysis/arm-smoke.elf .analysis/arm-smoke.bin
& $reaNode $reaCli inspect-native-load-image .analysis/arm-smoke.bin --target-format raw-binary --architecture arm --entry-point 0x8000 --provider ghidra --json
```

本机实测返回 `target_format_unsupported`，另有 Ghidra 未安装的独立诊断。原始诊断保存在 `.analysis/rea-raw-arm-smoke.txt`。

[arm-vectors.s](arm-vectors.s) 是 A32 向量探针的阳性对照。沿用上面的 ARM 工具链，将源换成 `samples/arm-vectors.s`，目标改为 `.analysis/arm-vectors.o` 与 `.analysis/arm-vectors.elf`，链接入口改为 `-e vectors`。用 `arm-none-eabi-objcopy -j .text -O binary` 导出裸字节。REA objdump 的预期结果是 `0x8000` 分支到 `0x8024`、`0x8004` 通过 `0x8020` 字面池跳转；`a32_vectors` 在导出的裸样本偏移 0 找到七个槽。只汇编和反汇编，没有执行该样本。

## C 交叉编译对照

沿用上面的 `$armBin`、`$reaNode`、`$reaCli`。每次使用新的输出目录；该样本只做编译和静态检查，不用于任何设备。

```powershell
$out = New-Item -ItemType Directory -Path '.analysis/arm-compile-replay' -ErrorAction Stop
$objdumpBefore = $env:REA_OBJDUMP_COMMAND
try {
    $env:REA_OBJDUMP_COMMAND = "$armBin/arm-none-eabi-objdump.exe"
    foreach ($mode in @('arm', 'thumb')) {
        $elf = Join-Path $out.FullName "$mode.elf"
        & "$armBin/arm-none-eabi-gcc.exe" -mcpu=cortex-a9 "-m$mode" -mfloat-abi=soft -Os -ffreestanding -nostdlib '-Wl,-e,toolchain_smoke' samples/arm-compile.c -o $elf
        if ($LASTEXITCODE -ne 0) { throw "Compiler failed: $mode" }
        & "$armBin/arm-none-eabi-readelf.exe" -h -A $elf
        & $reaNode $reaCli inspect-with-objdump $elf disassemble --format json
        if ($LASTEXITCODE -ne 0) { throw "REA failed: $mode" }
    }
} finally {
    $env:REA_OBJDUMP_COMMAND = $objdumpBefore
}
```

应看到两个小端 ARM ELF32，`toolchain_smoke` 的指令都是左移、加 7、返回。A32 入口为 `0x8000`，Thumb 入口值为 `0x8001`。完整记录见 [REA 报告](../docs/REA_ANALYSIS.md#c-交叉编译对照)。

## CW 离线测试样本

在项目根目录运行以下命令。输出目录必须是新的；WAV 和 manifest 都留在本地。

```powershell
.\.venv\Scripts\python.exe tools/make_cw_fixtures.py .analysis/cw-baseline
```

三个 WAV 均为单声道 8 kHz、16-bit PCM，预期文本是 `CQ TEST 123`。12 WPM / 500 Hz 和 28 WPM / 750 Hz 是干净对照；20 WPM / 600 Hz 的一组混入固定种子的白噪声，标记段的标称信噪比为 6 dB（按完整振幅的正弦 RMS 与噪声标准差计算，不是整段录音的信噪比）。点划及间隔依据 [ITU-R M.1677-1](https://www.itu.int/rec/R-REC-M.1677-1-200910-I/en)。manifest 记录 WPM、音调、帧数和文件哈希。

后续给解码器输入 WAV，记录软件版本、参数及输出；按大写、连续空白折叠为单空格后计算编辑距离除以参考文本字符数，另记 WPM 绝对误差。当前样本只覆盖机器匀速和一档噪声，尚未跑解码器，也不代表真机音频或手键条件。

## 离线卫星轨道

[satellite-pass.json](satellite-pass.json)保存公开历史 TLE、各自的 UTC 窗口和同一个观察点，不含当前卫星频率。来源、复现命令及与参考程序的比较见[过境回放报告](../docs/IC705_SATELLITE_PASS.md)。
