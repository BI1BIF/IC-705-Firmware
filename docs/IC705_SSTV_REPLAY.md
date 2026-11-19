# 日版 IC-705：SSTV Robot 36 离线回放

**日版 1.32 和 1.40 的 8 kHz 录音输出都能解出干净的 Robot 36 测试图。** 在同一输入中加入 6.1 kHz 后，原厂录音分支把它折到 1.9 kHz，仍然输出完整尺寸的图，但颜色和亮度受损。下一步应优先核实 IF DSP 交给 SSIF0 的带宽；如果无法保证上游滤波，就在抽样前取音频并做低通，而不是依赖录音链路自行滤波。

## 方法和结果

2026-11-13。从自制的 320×240 RGB 色条直接合成 48 kHz 单声道 16 位音频。上下半幅颜色顺序不同，用于检查行序和色差。参考 [Robot 36 模式规格](https://www.classicsstv.com/downloads/daytonpaper.pdf)与 [QSSTV 模式表](https://github.com/jbdubbs/QSSTV-Experimental/blob/10.1.1/src/sstv/sstvparam.cpp)：VIS 8、每行 150 ms、交替发送两路色差。样本 38.16 秒，包含帧头和前后静音。用 [QSSTV-Experimental 10.1.1](https://github.com/jbdubbs/QSSTV-Experimental/releases/tag/10.1.1)离线自动解码，`--min-complete 100`。用同一解码器比较原始 48 kHz、FFmpeg 低通降至 8 kHz、以及两版[原厂 ARM 录音队列](IC705_RX_AUDIO.md)输出。QSSTV 批处理会把 8 kHz 输入重采样到 48 kHz；这个步骤不会还原已丢失的音频。

| 路径 | 干净图 RGB 平均绝对误差 | 加 6.1 kHz 后 | 两组图像 |
| --- | ---: | ---: | --- |
| 直接读取 48 kHz | 5.654 | 5.654 | 均为 R36，320×240 |
| FFmpeg 低通后降到 8 kHz | 5.655 | 5.655 | 均为 R36，320×240 |
| J132/J140 原厂录音 8 kHz | 5.631 | 26.016 | 均为 R36，320×240 |

平均误差按每个像素的 RGB 三通道计算，量程 0–255。边缘处各路径均有解码过渡带，因此再看色条中心：原厂干净与直接解码分别为 0.806 和 0.809；加入干扰后原厂上升到 23.679，低通对照仍为 0.810。两版的录音 WAV 和解出的图在各自对照中互相一致。另用 [colaclanth/sstv](https://github.com/colaclanth/sstv/tree/3e556eee8ad4c4425799cb652bac26ee58f8e113)在四份干净输入上独立检测到通过奇偶校验的 VIS 8；该解码器图像误差较大，不用于本表的颜色评分。

纯 6.1 kHz 单音对照：原厂输出的主峰在 **1.9 kHz**，首尾各裁 100 ms 后电平约为 −15.26 dBFS，与输入相当；FFmpeg 低通的中段量化为零。单音在 QSSTV 不产生图像。加入测试图时，干扰幅值为图像音频的一半，两版都出现明显斜纹。因而「R36 且收齐 240 行」只能证明解码器报完整，不能代替颜色校验。

每版干净回放送入 1,831,680 点，共 50,886 个 DMA 块，预录队列回卷一次，输出 305,280 点。固件逐样本等于 `input[::6]`。输出 PCM SHA-256 `28ec9c7d1a191270d88e42b8345a8f7fa31dbb23bfa961d6a2b2b88e27444fdd`。A32 反汇编定位 J132 `0x2010C418`、J140 `0x2010FA54`；所测分支直接复制每第六个 16 位值，循环里无滤波。[REA](REA_ANALYSIS.md#日版接收音频复核)复核字节窗口和主程序哈希。未测实机 DSP 的带外抑制；也没有执行机内解码、LCD 逐行绘制或 SD 写入。

## 复现

从项目根目录运行。使用已有 Unicorn 和 FFmpeg；生成目录必须是新的。外部解码器下载、配置和结果均放到 `.analysis/`，没有安装系统包。QSSTV-Experimental 使用发布页的 `QSSTV-Experimental-10.1.1-x86_64.AppImage`，核对发布资产 SHA-256 `8cdb563be11516ba238a0db9b9e5fce8cf83ad66a6a141b4e9c7dd00b8ebbfab`，对应提交 `d3d168ad24661cdc31c97a30ef06802e5f1eea58`。WSL Debian 用 `--appimage-extract` 展开到 `.analysis/sstv-qsstv/runtime/squashfs-root`；缺少的 `libgpg-error0`（1.51-4）通过 `apt-get download` 及 `dpkg-deb -x` 展开到同目录下的 `deps/`。

```powershell
$d = '.analysis/sstv-robot36-repro'
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
python tools/make_sstv_fixtures.py $d
ffmpeg -nostdin -v error -n -i "$d/robot36.wav" -f lavfi `
    -i 'aevalsrc=7000/32768*sin(2*PI*6100*t):s=48000' `
    -filter_complex 'amix=inputs=2:duration=first:normalize=0' -c:a pcm_s16le "$d/robot36-plus6100.wav"
foreach ($stem in 'robot36','robot36-plus6100','alias6100') {
    ffmpeg -nostdin -v error -n -i "$d/$stem.wav" -ar 8000 -c:a pcm_s16le "$d/filtered8k-$stem.wav"
}
python tools/probe_705_rx_audio.py .analysis/main-decode/705J132/main.bin .analysis/main-decode/705J140/main.bin `
    --wav "$d/robot36.wav" --wav "$d/robot36-plus6100.wav" --wav "$d/alias6100.wav" --out-dir "$d/guest"
```

以下在 WSL 的项目根目录执行。干扰混合图是阳性对照，单音单独解码时应无图，并可返回非零状态。

```bash
r="$PWD/.analysis/sstv-qsstv/runtime"
d="$PWD/.analysis/sstv-robot36-repro"
export LD_LIBRARY_PATH="$r/deps/usr/lib/x86_64-linux-gnu" QT_QPA_PLATFORM=offscreen
export QT_PLUGIN_PATH="$r/squashfs-root/usr/plugins"
export XDG_CONFIG_HOME="$d/qsstv-config" XDG_DATA_HOME="$d/qsstv-data" XDG_CACHE_HOME="$d/qsstv-cache"
mkdir -p "$d/qsstv"
"$r/squashfs-root/AppRun" --batch --min-complete 100 --out-dir "$d/qsstv" \
    "$d/"robot36*.wav "$d/"filtered8k-robot36*.wav "$d/guest/"*-robot36*.wav
```

回到 PowerShell 后，用已有 Python 3.12 venv 指向本地的 `Pillow==12.1.1`。实测目录为 `.analysis/sstv-robot36-v1/`，保存 `replay.json`、`mixed-replay.json`、`qsstv*.log`、`image-scores.tsv` 与 `comparison.png`。原始色卡和 WAV 都由脚本生成，无第三方图片。

```powershell
uv pip install --target .analysis/sstv-score-deps 'Pillow==12.1.1'
$env:PYTHONPATH = (Resolve-Path .analysis/sstv-score-deps).Path
.\.venv\Scripts\python.exe tools/score_sstv_replay.py $d
```
