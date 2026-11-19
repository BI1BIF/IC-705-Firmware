# CW 离线解码基准

2026-11-18 最新补充：[默认选音与长静默电脑修复](IC705_CW_RX_REACQUIRE.md)。直接改 AUTO、跟随原厂中心 FIX 两方案均在独立实录失败，已撤回默认变更；当前仍 D5 WIDE，默认音调覆盖未解决。AUTO 长静默开发干扰 15→6 误字，但不是零误报；不能用其改善抵消弱台漏字。新保留集只可靠转写一份 VHF 弱信标，完整输出和失败均保留。新 [黑屏唤醒修复](IC705_CW_BACKLIGHT.md)通过电脑独立验收；该研究阶段没有新 DAT，随后同一 RX3 已静态导出 [D6 唤醒测试包](IC705_CW_RELEASE.md#d6-黑屏唤醒测试版)，没有操作电台。下文为各阶段历史基准，不能累加成当前全功能通过。

2026-11-13。用现成开源解码器验证从 PCM 到文字的独立链路。四个合成样本都发送 `CQ TEST 123`，输入和参考文字均已知。没有连接 IC-705，没有移植算法，也没有测量机内性能。

| 合成输入 | 解码器配置 | 文本结果（去行尾空格） | 字符错误数 / 9 | 末次点长折算 WPM |
| --- | --- | --- | ---: | ---: |
| 12 WPM，500 Hz，干净 | 自动 | `NETE TTA T E ST 123` | 7 / 9 | 14.81（偏差 2.81） |
| 12 WPM，500 Hz，干净 | 固定点长及间隔 100 ms | `CQ TEST 123` | 0 / 9 | 12.00（预设） |
| 20 WPM，600 Hz，干净对照 | 自动 | `CQ TEST 123` | 0 / 9 | 31.58（偏差 11.58） |
| 20 WPM，600 Hz，标记段标称 6 dB 白噪声 | 自动 | `<_._._>Q TEST 123` | 1 / 9 | 23.08（偏差 3.08） |
| 28 WPM，750 Hz，干净 | 自动 | `CQ TEST 123` | 0 / 9 | 22.22（偏差 5.78） |

字符错误数是去除所有空白后的 Levenshtein 距离，解码器的尖括号未知标记按一个字符计。末次速度按解码器退出时的整数毫秒 `TIMING_DIT` 用 `1200 / 点长毫秒` 换算，只反映最后的内部估计，不能代替全程速度跟踪。固定 12 WPM 那行是对照，不算自动估速通过。

直接用 [原始三个样本](../samples/README.md#cw-离线测试样本)时都漏最后的 `3`。只追加 1.5 秒数字静音重跑，三个样本的 `3` 都恢复，说明这个漏字与文件末尾的输出时机有关。20 WPM 同音调的干净对照能解对全文，6 dB 样本仍错首字母；12 WPM 手动指定点长后通过。现有候选能从 PCM 解出文字，但还不能用它证明可靠的自动测速或抗干扰能力。

## 复现

- [Debian trixie multimon-ng](https://packages.debian.org/trixie/multimon-ng) amd64 `1.3.1+dfsg-1`，SHA-256 `0669b127ec23d483adb273e4808f37bd88361bc8afe531c3492c9cd512cc2242`。以已有 WSL 的 APT 索引核对后，用 `dpkg-deb -x` 解包到 `.analysis/cw-baseline/debian/root/`，未安装系统包。程序 [MORSE_CW 源码](https://sources.debian.org/src/multimon-ng/1.3.1%2Bdfsg-1/demod_morse.c/)定义输入为 22,050 Hz，`-v 1` 输出点长统计。
- 使用 Windows 已有 FFmpeg 8.1，解码器只读单声道 16-bit PCM 文件。原始三个样本哈希见生成的 `manifest.json`。20 WPM 干净对照使用同一 `render(TEXT, 20, 600, None)` 生成并保存为相同 WAV 格式，SHA-256 `6b36c233a8644b7817798f919adfbcb4a652be2e32c789e8eca6257bacb9b563`。各次标准输出、重采样文件和包清单留在 `.analysis/cw-baseline/`。

下面以 12 WPM 为例，从项目根目录用已有 WSL 解包路径运行；另外三个样本复用同样参数，固定点长对照仅额外加入 `-d 100 -g 100 -y`。示例输出只写入本地分析目录。

```powershell
$p = '.analysis/cw-baseline/slow-clean'
ffmpeg -nostdin -v error -y -i "$p.wav" -af 'apad=pad_dur=1.5' -ar 22050 -ac 1 -c:a pcm_s16le -f s16le "$p.padded.raw"
$root = '.analysis/cw-baseline/debian/root'
$ld = "LD_LIBRARY_PATH=$root/usr/lib/x86_64-linux-gnu`:$root/usr/lib/x86_64-linux-gnu/pulseaudio"
wsl.exe -d Debian --exec env $ld "$root/usr/bin/multimon-ng" -q -v 1 -c -a MORSE_CW -t raw "$p.padded.raw"
```

## ARRL 练习录音续测

使用 [ARRL W1AW 20 WPM 档案](https://www.arrl.org/20-wpm-code-archive) **2026 年 1 月 6 日**同日配对的 MP3 和参考文本。正文在开头的来源报文与结束报文之间，评分去除空白、保留标点，不把首尾报文和程序符号计入。音频为 8,000 Hz 单声道，469.316 秒；音调在录音前 80 秒的一个高能量窗测得约 750 Hz。

| 检验 | 结果 |
| --- | --- |
| multimon-ng，自动 | 正文 **0 / 670 字符错误**；末次 `TIMING_DIT = 40 ms`，折算 **30 WPM**（对 20 WPM 偏高 10）。 |
| PCM 时序独立测量 | 5 ms 窗、RMS 门限 4,000 与 8,000 均得到 1,118 个短音和 852 个长音；中位数分别 65/185 ms。以两者差值 120 ms 对应两个点长，估计 **20 WPM**。 |
| [OpenTone](https://github.com/TigreGotico/OpenTone)，固定 750 Hz / 20 WPM | 对 600 Hz / 20 WPM 合成阳性对照（显式指定 600 Hz）能完整解出；对 ARRL 只输出 90 个非空白字符，未保留可对齐的首尾标记，不计算正文错误率。 |

这证明 multimon-ng 可以在这段 ARRL 练习音频上把正文解对，仍不能用它的末次点长当作可靠速度。独立测量使用已知速度附近的时长窗口，只用来核对这一录音。下一轮用**已有实收录音**做噪声、衰落和手键对照，再评估连续测速；练习音频不是经过本项目电台实收的样本。

MP3 SHA-256 `4b02f78eb2d5a7357f9d933c10ee2c15a8adf86945314ad997f388f2b9487eef`；参考文本 SHA-256 `93f77eea0c8af975f11db058e6438fd008119306418b2a96c005d320deb19fe5`。音频与文本来自同一档案页的 `260106_20WPM.mp3`、`260106_20.txt`，原文、音频和输出只保存在 `.analysis/cw-baseline/arrl-20260106/`。

```powershell
$d = '.analysis/cw-baseline/arrl-20260106'
$base = 'https://www.arrl.org/files/file/Morse/Archive/20%20WPM/'
New-Item -ItemType Directory -Force -Path $d | Out-Null
curl.exe -fsSL --output "$d/260106_20WPM.mp3" ($base + '260106_20WPM.mp3')
curl.exe -fsSL --output "$d/260106_20.txt" ($base + '260106_20.txt')
$mp3 = "$d/260106_20WPM.mp3"
ffmpeg -nostdin -v error -y -i $mp3 -af 'apad=pad_dur=1.5' -ar 22050 -ac 1 -c:a pcm_s16le -f s16le "$d/20.22050.raw"
ffmpeg -nostdin -v error -y -i $mp3 -af 'apad=pad_dur=1.5' -ar 8000 -ac 1 -c:a pcm_s16le "$d/20.8000.wav"
$root = '.analysis/cw-baseline/debian/root'
$ld = 'LD_LIBRARY_PATH={0}/usr/lib/x86_64-linux-gnu:{0}/usr/lib/x86_64-linux-gnu/pulseaudio' -f $root
wsl.exe -d Debian --exec env $ld "$root/usr/bin/multimon-ng" -q -v 1 -c -a MORSE_CW -t raw "$d/20.22050.raw" |
    Set-Content -Encoding UTF8 "$d/multimon-auto.txt"
.\.venv\Scripts\python.exe tools/score_arrl_cw.py "$d/260106_20.txt" "$d/multimon-auto.txt" "$d/20.8000.wav"
```

OpenTone 为 MIT 许可，使用提交 `cf3118282fadc9763b60fd08eb144b12dc72b437` 的 `opentone/_audio.py` 和 `opentone/morse/__init__.py`，临时作为无第三方依赖的 Python 命名空间包导入。未安装系统包，未修改上游代码；调用 `opentone.morse.decode(path, freq=750, wpm=20)`，阳性对照用 `freq=600`。

## 经日版原厂录音路径复测

2026-11-13。对每个输入分别解码原始 WAV、日版 1.32 和 1.40 的[原厂录音队列回放输出](IC705_RX_AUDIO.md#cw-长录音与延迟读取对照)。三份 PCM 转到 22,050 Hz 后的 SHA-256 一致，解码器三份日志的 SHA-256 也一致。四段合成音频单独补 1.5 秒静音；ARRL 的 8 kHz 输入已包含静音，不重复添加。

| 输入 | 直接解码／J132／J140 字符错误 | 三者末次点长折算 WPM |
| --- | ---: | ---: |
| 12 WPM 干净 | 7 / 9 | 14.81 |
| 20 WPM 干净 | 0 / 9 | 31.58 |
| 20 WPM、标记段标称 6 dB 白噪声 | 1 / 9 | 23.08 |
| 28 WPM 干净 | 0 / 9 | 22.22 |
| ARRL 20 WPM | 0 / 670 | 30.00 |

ARRL 两个 RMS 门限测出的长短音中位数在三份 WAV 上同为 65/185 ms，对应 20 WPM。录音链没有引入新的错字或速度偏差；20 WPM 干净录音里的偏差在直读原文件时已存在。下一轮要用带已知时间标记的变速、衰落和实收手键素材核对分段速度，不能以末次点长决定是否通过。

## ARM 解码器：中途变速、首字和人工直键

2026-11-14。先用原来的 Cortex-A9 ARM 解码器建立对照，同一实例连续接收 10 ms 音频块，记录出字时刻和每次速度变化。音频直接送给 `cw_feed`；未经过原厂 DMA、RTX 或真机收音。计时以该样本的首个标记为零；仅计回放输入时钟，不是电脑耗时。合成条件为 600 Hz、无噪声，分段只留前一速度的标准词间空白。

| 样本 | 含空格错字数 | 分段末估速 |
| --- | ---: | --- |
| 12、20、28 WPM 各自匀速 | 各 0/34 | 分别 12、20、30 WPM |
| 12 → 28 → 12 WPM | 13/34 | 12 → 12 → 12 WPM |
| 28 → 12 → 28 WPM | 11/34 | 30 → 30 → 30 WPM |
| 20 → 24 → 16 WPM | 0/34 | 20 → 20 → 20 WPM |
| 冷启后只发 `E`、`T`、`5`、`0`、`CQ`（均 20 WPM） | `E`、`5`、`CQ` 正确；`T` 被认成 `E`，`0` 被认成 `5` | 单独的划长被当成点长，报为约 6.67 WPM。`T`、`0` 首次错字分别在首个音开始约 580、1,540 ms 后显示。 |

因此，能读对匀速和原 ARRL 样本，还不能证明能跟上速度变化。首字只有划时，如果没有既有速度或其它时序证据，点和划存在歧义；下一轮应比较保留上次可信速度、手动锁速与延迟提交待确认的首字符，并以同一诊断量化影响。目标用例：匀速和变速均无错字，速度在每段结束前进入标称 ±3 WPM；首字符要区分“仍未确认”和“已误译”。

另用 [NW6V 自述的人工直键录音和参考说明](https://groups.google.com/g/radio-officers/c/ccZ8aXi4sfI/m/olJ8QNxtDwAJ)作实录对照。[原始音频](https://archive.org/download/sending_morse_code_sound_recordings/nw6v_handkey_Vail_3June1844.mp3)长 166.644 秒，测得主音约 710 Hz。录的是操作者发送，来源没有将它标为无线电实收。固定出字窗口 `15,000–151,300 ms` 比对发送者说明中的正文，排除引导呼号和尾部署名，只比较 A–Z、0–9 和解码器未知字符：**50/282 字符编辑错误（17.7%）**，文字粘连不计入。正文首字 `E` 可读；同一段起音约在 `15,120 ms`，完整播放时约 160 ms 后输出，去掉引导从 `14,500 ms` 起播约 1,320 ms 后输出，正文误码相同。原始 MP3 SHA-256 `3af73b8efc948beb621011f0c7004bb8cb7277ee83fc17c700cfd50b3f3165a5`。所用样本和参考文本只留本地，未提交。

不用外部样本即可复现合成诊断：

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_cw_quality .analysis/cw-quality-repro
```

输出的 `quality_passed` 及每例 `passed` 记录通过或失败；加 `--check` 会在任一质量条件不满足时返回 1。手键测试可加 `--manual-wav`（8 kHz、16 位、单声道）、`--manual-reference`（UTF-8，窗口内已人工核对的正文）、`--manual-window-ms 15000 151300`、`--manual-first-mark-ms 15120`。用 `--manual-replay-start-ms 14500` 对比没有引导音的冷启；这不会改变评分窗口。该诊断不写入设备，也不生成可刷写文件。

### 增加词边界速度重估后的结果

原来的整数估速会将小幅变化舍去；遇到大幅变速，按旧速度丢弃或误判点划后也无法追回。新版在识别到词间停顿后用原有缓冲暂存最多八个音与间隔，以点划和短间隔的组合重估；有足够差异才采用新速度，随后用新速度补译这几个符号。缓冲与原厂实验的调用接口不变。稳态也会承担重估成本：例如 20 WPM 匀速中间段首次显示从 780 ms 增至约 850 ms。

| 同一输入 | 改前 → 改后错字数 | 改后分段估速 |
| --- | ---: | --- |
| 12 → 28 → 12 WPM | 13 → 0 / 34 | 12 → 30 → 12 WPM |
| 28 → 12 → 28 WPM | 11 → 0 / 34 | 30 → 12 → 30 WPM |
| 20 → 24 → 16 WPM | 0 → 0 / 34 | 20 → 24 → 15 WPM |
| 18 → 30 → 15 WPM，另一组呼号和句子 | 改后 0 / 36 | 17.14 → 30 → 15 WPM |
| 20 WPM ARRL 练习录音 | 0 → 0 / 670 | 末次由 17.14 改为 20 WPM |
| NW6V 直键，去引导冷启 | 50 → 50 / 282 | 正文首字仍正确，约 1,320 ms 后输出 |

原有匀速、6 dB 合成噪声、静音、纯噪声及 J140 录音链全部通过；J140 ARM 会话、三档 Break-in × CW/CW‑R，以及原厂 RTX 菜单、波形、收发与 EXIT 回放也通过。证据见 `.analysis/cw-adaptive-20261114/` 下的 `quality-final`、`baseline-q1`、`session`、`break` 和 `rtx`。新测试代码为 1,660 字节，ARM 状态仍为 88 字节；ARRL 对照最高 8,900 条仿真指令／10 ms 输入块，不能换算为真机耗时。

这个改法只在原本的词间停顿处另行估速，暂未保证词内突变，也不能从只有同一种长度的声音判定它是点或划。冷启单独 `T` 或 `0` 仍错，直键评分也未通过。建议下一步单独验证从不规则手键音及空白识别点划，有误译要能区分低置信或等待，不继续扩大自动改速范围来掩盖这项失败。

### 缩短直键字母分隔门槛

2026-11-15。以原 ARM 音调检测公式逐 10 ms 检查 NW6V 录音。第 24,070、62,030、138,070 ms 开始的字母间隔均为 90 ms，附近同一字内部的间隔多为 50–70 ms。自动估速在这三处保持 24 WPM（点长约 50 ms）。原先至少等两个点长（100 ms）才分字，会把 `AS` 连成未知符号，也会把 `TH` 连成 `6`。现改为至少达到 1.8 个点长，保留原有点划门槛、词间分隔及估速规则。

| 同一输入 | 原门槛 | 1.8 点长 | 1.6 点长反例 |
| --- | ---: | ---: | ---: |
| NW6V 直键冷启正文，字符编辑错误 | 50 / 282 | **20 / 282** | 59 / 282 |
| NW6V 按独立时间窗复核（112 / 90 / 80 字，同一发报员） | 20 / 8 / 22 | 6 / 2 / 12 | 27 / 16 / 16 |
| ARRL 20 WPM 练习正文 | 0 / 670 | 0 / 670 | 0 / 670 |
| 合成音：四对字母各只隔 90 ms，每字内部保持 50 ms | 8 / 22 | **0 / 22** | — |
| 合成音：12、20、28 WPM 六组短字距加时序扰动，累计错误 | 48 | 26 | 4 |
| 合成音：12、20、28 WPM 的加宽字内间隔，累计错误 | 0 | 0 | 32 |

1.6 点长虽然更常拆开紧挨的两个字，却会拆开原本正确的字内长间隔；因此采用 1.8。三档 6 dB 噪声、纯噪声、静音和两组词间突变没有回归。短字距对照已加入 `python -m tools.probe_705_cw_quality` 的默认合成用例 `tight-letter-gaps-24wpm`。代码改动后的原厂 J140 录音和显示回放、AUTO/LOCK 同录音回放以及 27,409 次原厂 DMA 音频分组检查均通过。实验脚本、候选对照和正式验证报告在 `.analysis/cw-handkey-1115/`；公开直键录音来源见上文。仍有 20 个字符错误，没有据此宣布手键质量验收通过，也没有验证真实射频或真机开销。

执行[录音回放命令](IC705_RX_AUDIO.md#复现)后，从根目录比较 ARRL 的三个输入。四个合成样本将输入名替换为对应 WAV，并在 FFmpeg 增加 `-af 'apad=pad_dur=1.5'`；合成样本直接比对日志和 `CQ TEST 123`。

```powershell
$src = '.analysis/cw-baseline'
$out = '.analysis/cw-recorder-repro'
$root = "$src/debian/root"
$ld = 'LD_LIBRARY_PATH={0}/usr/lib/x86_64-linux-gnu:{0}/usr/lib/x86_64-linux-gnu/pulseaudio' -f $root
$inputs = @{ direct = "$src/arrl-20260106/20.8000.wav"
    '705J132' = "$out/705J132-20.8000.wav"; '705J140' = "$out/705J140-20.8000.wav" }
foreach ($key in 'direct', '705J132', '705J140') {
    $wav = $inputs[$key]
    $stem = "$out/$key-20.8000"
    ffmpeg -nostdin -v error -n -i $wav -ar 22050 -ac 1 -c:a pcm_s16le -f s16le "$stem.raw"
    if ($LASTEXITCODE) { throw "FFmpeg: $stem" }
    wsl.exe -d Debian --exec env $ld "$root/usr/bin/multimon-ng" -q -v 1 -c -a MORSE_CW -t raw "$stem.raw" |
        Set-Content -Encoding UTF8 "$stem.txt"
    if ($LASTEXITCODE) { throw "multimon-ng: $stem" }
    python tools/score_arrl_cw.py "$src/arrl-20260106/260106_20.txt" "$stem.txt" $wav
    if ($LASTEXITCODE) { throw "ARRL score: $stem" }
}
Get-FileHash "$out/*-20.8000.raw", "$out/*-20.8000.txt"
```

实测文件在 `.analysis/cw-recorder-replay/`，`*-score.json` 为各自评分。结果限于给定样本和 PC 解码器；尚未测量原厂 CPU 上的解码开销、真实射频条件或向 RTTY 界面交付文本。

### 定频滤波、门限与强邻台

2026-11-15。对同一组 8 kHz PCM，在仿真 Cortex-A9 上逐块比较旧宽带检测和新定频检测，二者共用同一套点划计时和译码逻辑。新检测每 10 毫秒用最近 30 毫秒音频测量指定音调。自适应门限取“固定最低门限”和“近期峰值的四分之一振幅”中的较大值。这里的“自适应”只指检测门限；不跟踪最强音调，也不改变接收机频率、CW 音调设定或原厂 DSP。MK2 [原厂说明第 2-14 页](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300MK2_ENG_Advanced_0.pdf)也把 `FILTER` 和 `THRESH` 分为两项：`FIX` 用固定目标频率，`AUTO` 跟随最强信号；门限另选自动或手动。

| 同一输入 | 旧宽带检测 | 定频＋自适应门限 |
| --- | ---: | ---: |
| 600 Hz 目标，邻台强 4.9 dB，间隔 200 Hz | 16 / 16 字符编辑错误 | 0 / 16 |
| 同样强度，间隔 100 Hz | 16 / 16 | 0 / 16 |
| 只有 800 Hz 邻台，滤波器仍对准 600 Hz | 18 个多余字符 | 无输出 |
| 目标峰值约 745，叠加标准差 220 的白噪声 | 16 / 16 | 0 / 16 |
| 同频双台 | 16 / 16 | 15 / 16，未通过 |
| ARRL 2026-01-06 W1AW 20 WPM 练习录音，750 Hz | 0 / 670 | 0 / 670 |
| NW6V 直键录音，710 Hz | 20 / 282 | 最低门限 350：178 / 282；改为 1100：20 / 282 |

350 和 1100 是相对于测试音频的峰值采样单位，不能直接当作原厂界面的百分比。同一弱目标用 1100 固定门限完全漏收；同一手键用 350 固定门限也有 123 个错误。ARRL 只用 350 固定门限时仍有译文，但未正确识别评分起点，不能得出正文误码。手键目前只是达到原成绩，未达到零错字。纯白噪声无输出；干净 600 Hz/20 WPM 和 750 Hz/28 WPM 样本均零错字。双台样本为电脑混音；ARRL 是官方练习录音，NW6V 是发报者直键录音，均未作为 705 从天线实收的证明。这些结果支持手动定频及独立门限的设计，不支持把定频方案直接换成默认解码器。

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_cw_filter .analysis/cw-filter-repro `
  --arrl-wav .analysis/cw-baseline/arrl-20260106/20.8000.wav `
  --arrl-reference .analysis/cw-baseline/arrl-20260106/260106_20.txt `
  --handkey-wav .analysis/cw-quality-audit-20261114/nw6v-handkey.wav `
  --handkey-reference .analysis/cw-quality-audit-20261114/nw6v-reference-local.txt --check
```

两对外部录音参数均可分别省略。报告 `.analysis/cw-filter-final-1115/evidence.json`（SHA-256 `267840cbebfe7171493a36c2991d7e1549ee2bbb2030580ab5d35b4050c32602`）记录输入哈希、各模式首字时间、输出和评分；`--check` 确认邻台、弱信号、干净和白噪声等专项通过，提供直键录音时核对门限调高后的非回归。这个报告来自独立 ARM 实验；随后相同的定频检测进入 [J140 的 ADJ 专项](IC705_CW_DISPLAY.md#adj频率和门限)，同一 100 Hz 混音已走通原厂 DMA、收音线程、菜单和 LCD。[自动跟音的对照](IC705_CW_DISPLAY.md#auto-跟音与-fix-对照)复用了这组样本。

### 40 米通联实收验收

2026-11-15。新增两段与前述 NW6V、ARRL 不同的无线电实收录音。英国 Verulam Amateur Radio Club 的[原始音频与通联转写](https://www.verulam-arc.org.uk/cw-class/)明确记录第 3 课（2025-05-13）和第 7 课（2025-06-10）的 40 米通联，两名操作员为 G0OIK 和 G4IYT。未独立确认他们各用哪种电键、接收机型号或录音路径；不能据此认定第二份直键样本，也没有测出接收机的实际信噪比。MP3 原样保留在忽略目录，转成 8 kHz 单声道 PCM，未降噪或归一化，两段定频用频谱实测的约 580 Hz。原始 MP3 和参考全文不提交。

| 解码模式 | 第 3 课：四个片段 | 第 7 课：五个片段 | 第 7 课前后两个无目标音窗口里的额外字符 |
| --- | ---: | ---: | ---: |
| WIDE | 37 / 61 | 120 / 120 | 40 |
| FIX，自适应最低门限 350 | 36 / 61 | 64 / 120 | 67 |
| FIX，自适应最低门限 2200 | **27 / 61** | 35 / 120 | 24 |
| FIX，自适应最低门限 3400 | 47 / 61 | **1 / 120** | 10 |

错字用字符编辑距离衡量，忽略空格及已知的标点；未知字符 `~` 计入。先按俱乐部转写选定可读片段，避免更正、含糊和连发送的操作符；分窗按解码器实际输出时间计分。背景误字单独计数。只对所列片段评分，不把 1 / 120 当作整次通联成绩；第 7 课 WIDE 在评分窗全漏，第 3 课的同一门限仍漏了许多字。2200、3400 为试验采样单位，用来对比，不适合作为统一默认值。

同一份第 7 课录音另取相对 WAV 的 `49.800–66.300 s`，在 705 电脑面板上通过触摸进入 CW、设 `FIX 580 Hz`、自适应最低门限 3350（界面以 250 为步长）。22,000 组音频走过 J140 原厂收音任务和 ARM 解码，最终原厂字形显示 `G 0 OIK DE G 4 I Y T`；字母、数字顺序正确，但呼号内有额外空格。无排队残留或丢组，机身 EXIT 路径通过。见[屏幕实跑](../.analysis/cw-offair-varc/panel-excerpt-verified/frame-66300.png)、同目录 `evidence.json` 及上一级 `panel-clip.py`。这是一段实收音频在电脑里的回放，机器本身没有接收该录音，也没有写入设备。

测试过“目标音在总声量中必须占较高比例”，可让第 7 课两个控制窗不再出字，但同一实现让干净合成样本出现 9 个错误，并让原厂界面回放的 `FIX` 不再能从强邻台中抄到指定弱台；NW6V 优选门限也回退到 154 / 282。因此已撤回算法改动。下一步应比较目标音附近的局部噪声与持续性，分别验收弱台、双台和背景声；保留这两段和 NW6V 作为回归，另用未参与调参的样本验收。撤回后原 CW 滤波回归（含 ARRL 0/670 与 NW6V 20/282）和评分单测通过。

可复现评分（原始音频分别来自 [第 3 课](https://archive.org/download/morse-class-3/Morse%20Class%203.mp3) 和 [第 7 课](https://archive.org/download/morse-class-7/Morse%20Class%207.mp3)）：

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
$d = '.analysis/cw-offair-varc'
ffmpeg -nostdin -v error -n -ss 00:45:05 -i "$d/class3.mp3" -t 530 -ac 1 -ar 8000 -c:a pcm_s16le "$d/class3-qso.wav"
ffmpeg -nostdin -v error -n -ss 65 -i "$d/class3-qso.wav" -t 173 -ac 1 -ar 8000 -c:a pcm_s16le "$d/class3-score.wav"
ffmpeg -nostdin -v error -n -ss 00:18:30 -i "$d/class7.mp3" -t 770 -ac 1 -ar 8000 -c:a pcm_s16le "$d/class7-qso.wav"
py -3.14 -X utf8 -m tools.probe_705_cw_offair "$d/class3-score.wav" "$d/class3-windows.json" "$d/repro-class3" --pitch 580 --threshold 350 --threshold 2200 --threshold 3400
py -3.14 -X utf8 -m tools.probe_705_cw_offair "$d/class7-qso.wav" "$d/class7-windows.json" "$d/repro-class7" --pitch 580 --threshold 350 --threshold 2200 --threshold 3400
```

`class3-windows.json`、`class7-windows.json` 在同目录，逐行记录 `[开始毫秒, 结束毫秒, 原文]`，原文为空即背景对照。第 3 课评分窗为 `13000–23500`、`86000–95100`、`95100–133400`、`148000–165900`；第 7 课的正文窗为 `51000–98000`、`210000–249000`、`380000–412000`、`414000–448250`、`696000–709000`，背景窗为 `0–30000` 和 `744000–758000`，均相对生成的 WAV。原始 MP3 SHA-256：第 3 课 `f72f451d478acb9d7017561076f083ebea77400496f097950f5680de7d933eea`；第 7 课 `2bcd15505c23b3bc95d471b5c71bd83ab5a45b25b5fa751e12b2fda3f5ab07b3`。正式报告 `final-class3/evidence.json`、`final-class7/evidence.json` 同时记录原始输出、ARM 程序及评分文件哈希；`filter-final/evidence.json` 保留已撤回方案的反例，`filter-original-check/evidence.json` 为撤回后的复验。

### 局部噪声门限与空格评分

2026-11-15。定频或自动选频启用 `THRESH AUTO` 时，同一 30 ms 音频窗测目标音和两侧频带；用较安静一侧估计附近噪声，避免强邻台单独抬高门限。频带边缘改用同侧两个频点。原来设定的最低值和近期峰值仍参与门限；`THRESH MANUAL`、`WIDE` 和分词规则未变。算法进入共用 ARM 解码器。试验版 `FILTER AUTO` 切换电台时清掉旧台峰值和噪声估计。

| 固定 580 Hz、自适应门限 | 第 3 课字符编辑错误 | 第 7 课字符编辑错误 | 第 7 课背景误字 |
| --- | ---: | ---: | ---: |
| 最低值 350，旧 → 新 | 36 → 19 / 61 | 64 → 34 / 120 | 67 → 35 |
| 最低值 3400，旧 → 新 | 47 → 10 / 61 | 1 → 1 / 120 | 10 → 10 |

低门限仍不能作为弱信号实收通过的证明。合成干净音、相隔 100/200 Hz 的强邻台和低音量背景噪声对照继续通过；ARRL 0/670，NW6V 直键在最低值 1100 时仍为 20/282。对照另取 [第 4 课](https://www.verulam-arc.org.uk/cw-class/) `37:30` 起的录音，按俱乐部 `37:36` 的段落索引和 [CWops 教材](https://cwops.org/wp-content/uploads/2025/04/Fundamental-Curriculum-v1.13.htm)的练习句确认正文；固定评估剪出后 `35–146 s`，约 590 Hz，评估段新旧均为 0/49 字符错误、39 个多余空格。这是同一社团的无线电课堂练习段，不能视为独立短波通联或另一位直键发报者。原 MP3 SHA-256 `81ddfedd61e338858ff435d7b0bab1e7ec380e0c0fca3e8d5589e97e0d228e57`，FFmpeg 剪 230 秒转 8 kHz 单声道 16 位 PCM 后 SHA-256 `ef2b02c286864324a6ab4b9aab3c0145eb7d1cc254b0a18595430dd0f5ff1c73`。参考窗口文件为本地 `class4-windows.json`。

评分增加多余与缺失空格。只比较参考和译文中两边都匹配、且都紧邻的字符；字符错误跨过的空格不计。第 7 课 `3400` 的“1 个字符错误”同时有 113 处可比间隔、61 个多余空格，新旧相同。两组呼号的短截取为 12 个正确字母数字、6 个多余空格。把显示分词与自动估速拆开，再把显示阈值改到 7 倍点长，短截取的多余空格由 6 变 1，整段由 61 变 37，但新增 4 个漏分词；第 4 课的长间隔练习仍有 39 个多余空格。因此还没有替换分词逻辑。简单要求音调持续更久亦未采用：较激进的方案把背景误字由 10 降至 2，同时第 7 课正文由 1 错增到 24 错。

复现仍用上一节的 `tools.probe_705_cw_offair`，换新输出目录即可；其中第 4 课额外用 `--pitch 590 --threshold 350`。最终实测在 `.analysis/cw-local-noise-1115/{real3-specialized,real7-specialized,holdout-specialized,guards-specialized}/evidence.json`。以同一含噪输入的 160 个 10 ms 块抽样，独立 ARM 检测函数的平均仿真指令数，自动门限从 5,036 到 10,697，手动门限从 5,015 到 4,777；报告 `instructions-final.json`。该统计省略了收音、界面任务和实际硬件计时。原版本和各试验版本的脚本及原始输出在 `.analysis/cw-offair-spacing-1115/`（`spacing-sweep.py`、`split-spacing.py`、`floor-sweep.py`、`pulse-sweep.py`）。录音和完整来源参考文本仅在本地忽略目录。

### 按发报节奏分词

分词与重新估速分开：估速沿用原停顿标记，分词记录真正结束的字间停顿，使用近期停顿的滚动水平；若一个被丢弃的短声打断静音，保留最长的那段。长暂停清除历史，观察到明显换速时保留本次词间空格并重新学习。只影响空格，不用呼号表，不更改滤波、点划判定或 88 字节状态大小。原厂 TX/RX 切回后仍使用原来的清空机制；新规则在还没有足够历史时保留原来的短报文分词。

对第 7 课短截取，在 580 Hz 上用独立 30 ms 窗测到：`0` 后约 460 ms，`4` 后约 470 ms，`Y` 后约 600 ms，`K` 到 `DE` 首划约 1,030 ms。`DE` 到下一呼号中有一段约 620 ms、后接约 10 ms 的额外音和约 180 ms 的静音；不能把短额外音当成新字符。意大利通联的标注窗则有约 230–290 ms 的呼号间短暂停顿。原始量测与 ARM 输出旁路记录见 `.analysis/cw-gap-training-1115/{varc-gaps-3350,clip-max-traced,italian-max-traced}.json`。

| 固定接收设置，原算法 → 新算法 | 字符错数 | 多余空格 | 漏掉的空格 |
| --- | ---: | ---: | ---: |
| Verulam 第 3 课，`FIX 580`／350 | 19 → 19／61 | 29 → 24 | 0 → 0 |
| Verulam 第 7 课，`FIX 580`／350 | 34 → 34／120 | 46 → 14 | 0 → 1 |
| Verulam 第 7 课，`FIX 580`／3400 | 1 → 1／120 | 61 → 11 | 0 → 3 |
| Verulam 第 7 课，两组呼号的 J140 实收录音回放 | 0 → 0／12 | 6 → 2 | 0 → 0 |
| Verulam 第 4 课，拉长停顿的练习段 | 0 → 0／49 | 39 → 39 | 0 → 0 |
| IZ4KBW 提供的意大利 7.036 MHz 桨键通联，`FIX 530`／350，两段 | 0 → 0／27 | 0 → 0 | 0 → 0 |

第 7 课背景误字不变（最低值 350 时 35，3400 时 10）。[J140 画面](../.analysis/cw-gap-training-1115/panel-v6/frame-66300.png)现为 `G 0OIK DE G4IY T`，连续输入 22,000 组无丢失。ARRL 0/670、NW6V 20/282、两组 12/28 WPM 切换、24 WPM 短字间距、100/200 Hz 强邻台和低音量对照均保持成绩。冷启孤立 `T` 和 `0` 的自动估速错误仍存在；第 4 课练习也未改善，不能说已解决所有分词。

意大利样本来自 [IZ4KBW 的实收音频原始发布](https://swling.com/blog/2021/11/large-archive-of-cw-off-air-recordings-from-italy/)，2021-11-21，注明桨键和参与呼号。公开出处列参与者，无完整转写；仅取两次可明确对齐的呼号交换来评分，不把 27 字结果当作 15 分钟音频全段成绩。`56.000–63.000 s` 为 `I8QFK DE IZ8VKW`，`199.100–206.200 s` 为同句加 `K`；原 MP3 SHA-256 `a717e752cb5cdbeb2465ad497d2132c41e88618d9b0dbaa38ae2dc6dfa745f2d`，8 kHz 单声道 WAV SHA-256 `405116041220fe89e50e8aa7cbbc634fa85c28826dacb2c99d5f4c723aa1ce52`。使用 `tools.probe_705_cw_offair`，本地评分文件 `iz4kbw-windows.json`；对照报告位于 `.analysis/cw-gap-training-1115/` 的 `*-v6` 子目录。

## 冷启识别 0 与侧摆键实收

冷启时，`0` 的五条长音之间有四段短静音；慢速 `5` 的间隔与点音接近。ARM 解码器在首个待判定字确有五个长度相近的音、且四个间隔都足够短时，用音长的三分之一估点长。原始 20 WPM 样本把 `0` 抄成 `5`；新版在 15、20、25 WPM 全部正确，`5` 对照仍正确，包括点音和 20 WPM 的 `0` 一样长的约 6.67 WPM 样本。`CQ` 及跨 12／28 WPM 变速复验通过。单个 20 WPM 的 `T` 与约 6.67 WPM 的 `E` 可得到字节完全相同的 PCM（报告中有 SHA-256）；AUTO 仍将这对波形解释为 `E`，已知速度可用 `MANUAL` 或先估速再 `LOCK`。保留该项为未通过。报告：`.analysis/cw-initial-1115/{baseline,after-final,filter,rtx,cold-start}/`，其中 ARRL 0/670、NW6V 手键 20/282，弱台和分开的近邻台保持通过；日版原厂显示任务 21,464 组、冷启动收音 `CQ` 2,827 组均通过。

独立样本分别保留两种证据，不把电键已确认和短波实收混为一谈：

| 材料 | 可核对范围 | 固定音调，门限自适应 | 宽带 |
| --- | --- | --- | --- |
| [AA7FV／WA4FAT 的 40 米 SSN 实收](https://www.sideswipernet.org/qni/us40m_2020.php)，2020-12-24 当地、12-25 UTC，7044 kHz；该场日志确认 AA7FV 为主控，独立 20 ms 音频窗逐段确认 `CQ CQ CQ SIDESWIPER NET SSN DE AA7FV AA7FV` | 21.800–48.450 s；同一操作员另在 2020-10-15 和 [2021-01-24](https://www.sideswipernet.org/qni/inter_2021.php) 自述使用侧摆键，无法确认 12 月 24 日的确切键型。2021-01-24 同场实收链接返回 404。 | 640 Hz，最低门限 350、1100 均 0/34，空格全对 | 34/34，评分窗未出字 |
| [N1EA 发布的侧摆手键演示](https://www.sideswipernet.org/resources.php) | 独立量测 `VVV` 与 `DEMONSTRATION OF` 两窗；是明确键型的演示，不算短波实收。 | 710 Hz，350、1100 均 4/18 | 4/18 |

前后两版对这两组评分相同。SSN 的 FIX 640／350 也通过 705 的电脑面板：从菜单进入，64,600 组原厂音频任务处理后，[LCD](../.analysis/cw-sideswiper-1115/panel-opening/frame-48450.png)出现整段评分文字，退出回原画面，原 DAT 未变。换成自动选音（`FILTER AUTO`、门限仍为 350），三个检查点都选 650 Hz，第二个 `AA7FV` 成为 `AA7FU`（1/34），与独立的固定 650 Hz 错误相同；这是之后细化自动音调定位的回归用例。截图中开场评分窗之前仍可见误字。不将评分推广到整场约 40 分钟的录音、其他电键或真机。

可复现输入：SSN `ssn_122420.mp3` 由 [通联档案的录音链接](https://drive.google.com/file/d/1IULJ2tqtqM7Ocl56Ofld4m2AjJWB4lqZ/view)发布，MP3 SHA-256 `62afece4852cc0cf6e26495aaae677fcb9aee7a769176174b270f9591d9b4800`；N1EA `n1ea_cootie_sending_demo.mp3` SHA-256 `812ff41debda93dd0a352d06a566508d9d3e22b44d67a3663eb9c7e140845892`。用 FFmpeg 转 8 kHz 单声道有符号 16 位 PCM，然后分别截取前 58 秒和 13 秒作为输入。截取 WAV 哈希依次是 `0cc2f1143908ecac45f3862a19c3a7f99d3847634e91b415fb6e68609205f405`、`30c01603942095c184a9867982afb0ca01c9c57e9b34faa7456de8a7aa20a5f7`。音频仅存 Git 忽略的 `.analysis/cw-sideswiper-1115/`；时窗标注在 `samples/cw-{ssn40,n1ea}-opening-windows.json`，按现有 `tools.probe_705_cw_offair` 用上述两个音调、`--threshold 350 --threshold 1100` 评分。完整对照和面板复现脚本在同一证据目录。

## 自动选音细化

在 J140 电脑试验版中，使用[峰顶三点插值](https://www.dsprelated.com/freebooks/SASP/Quadratic_Interpolation_Spectral_Peaks.html)从现有 50 Hz 频谱细化到 10 Hz 档位；瀑布分辨率和每 40 ms 刷新保持原样。判定换台仍用原来的粗频段，避免相邻频段的小步跟踪重置译码。相同的 SSN 音频和门限，`AUTO` 的三个检查点由 650 Hz 变成 640 Hz，`AA7FU` 恢复为 `AA7FV`，34 字及空格全对；`FIX 640` 仍全对。每档 64,600 组原厂模拟输入无丢失。开场评分窗之外还存在错字。

两个独立实收短截取未退步：VARC 两个呼号字母数字 0/12，仍有两处多余空格；意大利截取两版均抄出 `I8QFK` 与 `IZ8VKW`，窗口前段译出 `ELORA`，将整个截取与目标短句比较仍有 5 个多余字符。原厂调度的合成对照覆盖噪声、两台相隔 100 Hz 时自动取强台和手动取弱台、600→900 Hz 换台以及 600→800 Hz 缓慢漂移，共 148,960 组；漂移时译文全对，最后检查点估到 790 Hz。标准显示 21,464 组及冷启动 `CQ`、`EXIT` 复跑通过。结果和截图在 `.analysis/cw-refine-1115/{auto,fix,independent,adjust-final,screen,cold-final}/`。

## 连续接收验收

2026-11-15。从进入 CW DECODE 开始连续送原录音，不在各片段间重置，原厂接收任务供给日版 1.40 电脑面板。毫秒标注覆盖整段：正文按原发布转写（VARC）或独立测音并核对词句（SSN 和 N1EA）；明确没有目标来报的窗口单记误字，练习段、过门等不确定内容记为未标注。明文末尾和紧接的空白留出译码延时，在报告中保留全部字及时间。正文错数忽略空格和标点，另外按已对应的相邻字统计空格。首字延时从相应来报的第一声到首个可计分字符入缓冲，只在字符正确且未提前出现时给值。不测物理屏幕刷新时间。

| 连续输入 | 模式／门限 | 正文错误／字符 | 多／少空格 | 无目标来报时的误字 | 首字示例 |
| --- | --- | ---: | ---: | --- | --- |
| SSN 40 米，58 秒 | AUTO 选到 640 Hz／350 | 1/63 | 0/0 | 未标注独立背景 | 第一段 668 ms；第二段首字前多了一个 `E` |
| 同上 | FIX 640 Hz／350 | 1/63 | 0/0 | 未标注独立背景 | 第一段 620 ms |
| 同上 | WIDE | 63/63 | — | 未标注独立背景 | 无译文 |
| VARC 第 7 课，101 秒 | AUTO／350 → 3350 | 18/49 → 2/49 | 12/0 → 12/1 | 30 秒内 28 → 9 | 3350 时两段均未正确起首 |
| 同上 | FIX 580 Hz／350 → 3350 | 18/49 → 0/49 | 7/0 → 6/1 | 30 秒内 20 → 5 | 两段 944、1089 ms |
| N1EA 侧摆键演示，77.531 秒 | AUTO／350，FIX 710 Hz／350，WIDE | 67/81、67/81、66/81 | — | 0.825 秒内无误字 | FIX 在简介 935 ms；快报未正确起首 |

SSN 正文四段的已知呼号仍正确。VARC 固定音调在这段提高门限后，正文的字母数字全对，但背景 30 秒还有 5 个 `E`，空格也仍有错；不可从这段录音决定全局默认门限。N1EA 的后半段短间隔明显，三种模式均大范围漏字；部分音之间的间隔短于现有定频检测的 30 ms 采样窗。宽带也失败，因此不能把问题单归于选音或采样窗。接下来应在同一片段对比从零开始估速、沿用前段估速和已知速度，再用可控短间隔样本分辨音检测和点划计时的问题。

各轮清空音频队列后确认无丢组、机身 EXIT 回到原首页、原 DAT 哈希不变。VARC 低门限的 AUTO 和 FIX 分别记录了 148、136 个字符事件（含空格/标点），与界面最后 128 个字符核对一致。报告在 `.analysis/cw-continuous-1115/{ssn40,varc350,varc3350,n1ea}/evidence.json`。原始 WAV 仅本机保存，见[上述录音来源](#冷启识别-0-与侧摆键实收)和[第 7 课输入](#40-米通联实收验收)。SSN 和 VARC 在复核音频包络后用保留的事件重算了段尾边界；不改译码或播入数据。以下命令可从头复现 SSN：

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat .analysis/cw-sideswiper-1115/ssn40.wav samples/cw-ssn40-continuous.json .analysis/cw-continuous-repro --pitch 640 --modes AUTO FIX WIDE
```

## 快手键：区分速度估错与短停顿合并

同一份 N1EA 录音、同一定频 710 Hz 和门限 350，每次从页面进入开始送相同的 103,375 组模拟原厂音频。旧 AUTO 在 11.22 秒处把点长从 70 ms 一次改成 140 ms，并逐步偏到更慢；对应第一个音连续判为 480 ms，超出旧速度能接受的 350 ms。修正为：已有速度、已采足重估样本时，不把这个过长的第一个音用于拟合，仍按原规则处理待译码的整段。该时刻新版只调整到 80 ms。三轮的 EXIT 均恢复首页，原 DAT 哈希相同。

| 同一录音，日版 1.40 电脑面板 | 全部标注的 81 字 | 末段快报的 41 字 |
| --- | ---: | ---: |
| 修正前，SPEED AUTO | 67 错 | 41 错 |
| 修正后，SPEED AUTO | 46 错 | 41 错 |
| SPEED MANUAL，模拟原厂 KEY SPEED 为 24 WPM | 14 错 | 5 错 |

独立 ARM 回放从 59.5 秒重新开始，避开前段发报，快报 AUTO 仍有 39/41，锁定 24 WPM 后为 4/41。这把「从前段带来的估速误差」与「进入快报后仍然估不准」分开。另给检测器四个已知的 50 ms 音，分别以不同间隔、不同起始时刻送入。已知速度下，5 ms 的间隔在宽带和定频都被合并；10 ms 随起始时刻而变；两组起始时刻的 15 ms 及以上均报出四个点、正确译为 `H`。实验中提高相对振幅门限能拆开其中一组 10 ms 停顿，但未解决末段自动估速，未并入电脑版本。

全部逐字时间线、自动点长和短停顿实验在 `.analysis/cw-fast-key-1115/`。`panel-auto`、`panel-auto-candidate`、`panel-manual` 各有报告及最后一帧。模拟面板重跑手动档：

```powershell
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat .analysis/cw-sideswiper-1115/n1ea.wav samples/cw-n1ea-continuous.json .analysis/cw-n1ea-manual-repro --pitch 710 --modes FIX --key-speed-raw 110
```

回归：ARRL 0/670，NW6V 20/282，SSN 0/34，VARC 原定频条件 34/120、1/120 及背景计数不变；弱台和相隔 100/200 Hz 的强邻台合成样本通过。20/24 WPM 锁速、12/28 WPM 双向变速与单字 `0/5` 保持；冷启孤立的 `T/E` 仍歧义。电脑面板按键、双窗、收发和退出再次通过 19,661 组模拟音频（`panel-layout-candidate/panel-evidence.json`）。此次改进针对因过长首音触发的错误重估，仍不能宣称快手键 AUTO 已经可用。

## 错把多字连成一字后的自动恢复

2026-11-15。快报起首前的停顿在该轮回放只有约 350 ms，旧估速偏慢，把许多正常字间停顿继续当成字内停顿。一些输出一直累积到内部字形表容量之外。新版只在已有较慢估速、已累积至少七个点划、又遇到足够停顿时，记一个 `~` 并重估下一组点划。只改速度 AUTO 的恢复；不把无把握的坏字猜成某个字，也不影响 LOCK 或 MANUAL。

先实跑了「普遍缩短重估停顿、延长观察窗口」的较激进方案：两种滤波模式的日版面板都把 N1EA 末段降到 5/41，但常规 12→28→12 WPM 样本由 0 错变成 1 错，VARC 高门限由 1/120 变为 5/120，该方案已撤回，报告 `.analysis/cw-speed-restart-1115/{j140-fixed,quality,varc}/evidence.json`。保留的较窄方案在独立 ARM 回放的 N1EA 末段 41→21 错；从 59.5 秒重新进样 39→20 错。未解决快报全部字符，也没有改变对 5–10 ms 短停顿的音频检测。

新合成对照：12 WPM 转 24 WPM，中间只停 310 ms，两种检测均由 15 降至 7 错（24 字），后半的 `BROWN FOX` 恢复；同一来报停 520 ms 原本就全对。16→24 WPM、停 310 ms，定频 16→5 错，宽带 16→8。相同速度的对照没有新增错字。可用 `py -3.14 -X utf8 -m tools.probe_705_cw_quality .analysis/cw-restart-repro` 复验 310 ms 专项；报告中孤立 `T/E` 的已知失败依然单列。

较窄方案的回归：ARRL 0/670，NW6V 定频门限 1100 为 20/282，SSN 0/34、意大利样本 0/27，VARC 两个门限的正文错误、空格计数和背景误字保持原值；弱台、强邻台和普通变速通过。100 Hz 邻台使用低的固定门限时仍未通过；定频自适应门限模式保持零错。证据在 `.analysis/cw-speed-restart-1115/`，原 DAT 不变。

正式日版电脑面板复跑：定频 710 Hz 和自动选音，在速度 AUTO 下都为 26/81，末段 21/41。对照前版同条件定频 46/81、末段 41/41。每轮 103,375 组模拟音频无丢失、机身 EXIT 返回原画面。报告 `j140-overflow/evidence.json`（SHA-256 `12f2927affc915a561e6f0517282375b75713d99548ceb29f0b5b6868ac7d3c7`），有逐字输出时间、速度和截图；`j140-panel-overflow`、`j140-speed-overflow` 记录原厂风格底栏、双窗、收发切换及三档速度回归。
### 极短停顿与两份手键对照录音

在相同 24 WPM 合成样本中插入 5 或 7 ms 停顿，按 0–9 ms 的十种起始时刻播放四个点。原程序在两档停顿下都没有一组能保留四个点；定频试验版限制在左右有较强同频信号、短窗内有明显低谷时才拆开，两档均通过 10/10。但它没有改善下表三份有人手发报的音频。放宽条件后，N1EA 反从 26 增至 34 个错字。两种试验均未合入。

| 音频与固定音调 | 自动估速错误 | 预先指定速度的错误 |
| --- | ---: | ---: |
| N1EA，710 Hz | 26／81 | 14／81（24 WPM） |
| 公开快手键档案的评分片段，460 Hz | 12／30 | 8／30（24 WPM） |
| F6UIG 自制侧摆键，700 Hz | 8／68 | 0／68（17 WPM） |

这里只计字母与数字；F6UIG 两档还各有 5 个多余空格。两档 F6UIG 在 J140 原厂收音路径中各通过 120,686 组模拟 DMA，均能 EXIT 返回首页；它是演示录音，没有当作电台实收。快手键档案由 [N1EA 页面](https://www.qsl.net/n1ea/sideswiper.html)提供，说明录音还含键盘重发；这里只按[已转写片段](../samples/cw-archive-handkey-continuous.json)评分，未确认历史发报的具体起止。F6UIG 的[作者说明](https://sideswipernet.org/keys/f6uig-keys.php)与[评分窗](../samples/cw-f6uig-continuous.json)可公开核对。快手键档案和 N1EA 的本表数字来自直接 ARM 回放，F6UIG 也有原厂面板证据。选择下一步时优先对照同段 `AUTO`／`MANUAL` 的点长估计；不能用短停顿合成题代替实录验收。

复现实验保存在 `.analysis/cw-gap-resolution-1115/`（`gaps-current.json`、`gaps-context32lo.json`、`recordings-*.json`、`f6uig-{auto,manual}/evidence.json`）。可从[快手键 MP3](https://www.sideswipernet.org/audio/fast_hand_key.mp3)及 [F6UIG MP3](https://www.sideswipernet.org/audio/f6uig_hacksaw_blade_demo.mp3)以 `ffmpeg -i 输入.mp3 -ac 1 -ar 8000 -c:a pcm_s16le 输出.wav` 生成测试音频。两份 WAV 的 SHA-256 依次为 `aaa3211bce303836ed2f21cbf129a3f9acd39e4f5b085f51f6f67f381e4f65b8`、`0d2ecb3a0cd595496fd1a1289f58c94a05ac5fa7d9f7c492fa71253f0ad4140e`；仓库可保留评分窗，音频及试验二进制放本地忽略目录。

```powershell
$env:PYTHONPATH = (Resolve-Path '.analysis/ic705-emulator/deps').Path
$wav = '.analysis/cw-gap-resolution-1115/f6uig_hacksaw_blade_demo.wav'
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat $wav samples/cw-f6uig-continuous.json .analysis/f6uig-auto-replay --modes FIX --pitch 700
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat $wav samples/cw-f6uig-continuous.json .analysis/f6uig-manual-replay --modes FIX --pitch 700 --key-speed-raw 67
```

### 自动估速：防止长点拖慢和短点翻倍

固定音调和门限，先记录旧版每 10 ms 观察到的载音，再以完全相同的点划输入对照估速，最后用 J140 原厂录音任务从头播放 WAV。F6UIG 约 23.6 s 的四个点为 100／60／90／60 ms，中间是 10／20／20 ms 停顿。旧程序把短点同时计作快速档的点和划，24.39 s 将点长从 60 改为 30 ms，并输出 `C`。新版只把接近候选速度的短、长音计作证据，输出 `H`、点长为 70 ms。N1EA 的长点原来会在每个字内推慢估速；现在已开始一个字时，暧昧长点仍按当前速度识别，但不会单独推慢下一次分字。干净的真正变速仍由停顿后的观察处理。没有改音调检测、滤波、门限或手动锁速。

| 录音及评分范围 | 字符错误：旧 → 新 | 空格 |
| --- | ---: | --- |
| N1EA 全部四窗，日版原厂收音回放 | 26 → 18／81 | 少 2 个不变 |
| N1EA 最后快报，同一次回放 | 21 → 15／41 | 包含在上行 |
| F6UIG 全部三窗，日版原厂收音回放 | 8 → 2／68 | 多 5 → 多 8 |
| F6UIG 约 23.5–38.15 s，包含 `HERE MY KEY IS SIDESWIPER` | 6 → 0／21 | 词内仍有两个多余空格 |
| 第 7 课较弱实收，独立 ARM，低门限 | 34 → 18／120 | 多 14 → 多 11，少 1 不变 |
| 同一实收的高门限、SSN、意大利侧键 | 1／120、0／34、0／27 保持 | 按既有评分窗核对 |

前两份手键演示实际分别经过 103,375 和 120,686 组 J140 模拟 DMA，均退出回到原厂首页。更激进的版本虽然能让 N1EA 降至 7 错，却使 24→12 WPM 三组停顿的首词更差，因此未采用。当前版本保住标准快慢切换、弱信号、100/200 Hz 强邻台、静音和噪声、ARRL 0/670 和 NW6V 20/282。新增 `similar-dots-after-pause` 直接送 8 kHz PCM：旧版 `CQ C`／40 WPM，新版 `CQ H`／17.14 WPM。总评分依然保留未通过项：冷启单音 `T` 和 NW6V 20 个错字；不能据此宣布自动档已完全可靠。

证据：`.analysis/cw-auto-estimator/{n1ea-panel,f6uig-panel,quality-with-regression,filter}/evidence.json`；前两份 SHA-256 分别为 `7eaf11ab1fd35e76955e5b02d92790f6d01b93e69291a45f14f1a3a368f7a324`、`f030c019d8b7cb7d95a928a6e37c2446de983707a664e4665724b8f446b93dff`。`cmth4eight.json` 保存独立输入序列的逐窗评分。用上一节 F6UIG 自动档命令可复跑；N1EA 改用 `n1ea.wav`、`samples/cw-n1ea-continuous.json`、`--pitch 710`。`python -m tools.probe_705_cw_quality 新目录` 可直接跑合成对照。下一次如果改善译文空格，必须同时守住已有正确的呼号、词间停顿和短间隔变速，不能只凭手键样本改全局门槛。

### 速度重估和长字间隔的分词

逐个回放 F6UIG 多出的 8 个空格，确认 3 处来自大幅重估速度时直接保留空格；其他位置是普通分词门槛偏低。新版在重估前用原发报节奏判断停顿；正常速度变化保留词间空格，但不拿这次停顿当作新速度下的超长字母间距。快点划配长停顿时，只有学到足够长的字母间距，才放宽分词门槛。只调分词，音频门限、点划识别和估速判断未改。

| 对照（等号两边用同一音频和参数） | 多余空格 | 漏掉的空格 | 字符错误（不计空格） |
| --- | ---: | ---: | ---: |
| F6UIG，日版原厂收音回放，700 Hz | 8 → 1 | 0 → 0 | 2／68 不变 |
| N1EA，日版原厂收音回放，710 Hz | 0 → 0 | 2 → 2 | 18／81 不变 |
| VARC 第 4 课长停顿练习，590 Hz | 39 → 10 | 0 → 0 | 0／49 不变 |
| VARC 第 7 课实收，580 Hz，门限 3400 | 11 → 8 | 3 → 3 | 1／120 不变 |
| 同一实收，门限 350 | 11 → 11 | 1 → 1 | 18／120 不变 |

F6UIG 的整行 `HERE MY KEY IS SIDESWIPER` 现在逐字且空格正确；同段回放仍有一个 `FRI END`。日版 1.40 分别处理两份手键录音 120,686 和 103,375 组模拟 DMA，均无丢组，机身 EXIT 恢复首页。第 7 课的 22,000 组面板片段仍显示 `G 0OIK DE G4IY T`，不能算呼号空格已全部解决。练习录音和第 7 课的正文计数来自直接 ARM PCM 回放，各评分窗只统计能对齐的相邻字符；没有被正确译出的字符不能反推空格是否对。

`wide-letter-gaps-20wpm` 增加独立的 1.4 秒字间、2.6 秒词间合成对照。统计最后两词：旧版多 8 个空格，新版正确得到 ` RADIO MORSE`；初期仍需学习，整个序列的字母顺序正确。两组 12／28 WPM 突变、其他速度对照、弱台和 100／200 Hz 邻台、ARRL 0／670、NW6V 20／282 均保留原成绩。日版原厂任务重跑 23,148 组和 26 张画面；冷启动仍在屏幕译出 `CQ`（2,827 组）并退出。冷启孤立 `T` 的已知失败仍在，未操作实体电台。

证据和复跑输出在 `.analysis/cw-spacing-v2/`：`f6uig-final`、`n1ea-final`、`class4-pcm-before`、`class4-final`、`class7-final`、`lesson7-panel`、`quality-final`、`filter-final`、`native-final`、`cold-final`。正式录音的复现命令沿用前节，合成题用 `py -3.14 -X utf8 -m tools.probe_705_cw_quality 新目录`。

### 自动选音：没有来报时别出字

2026-11-15。对象是日版 1.40 的电脑版 `FILTER AUTO` + 自动速度 + 自动音量门限。旧版有时把短暂的窄带噪声当成点划，拟合出很短的点长，再一次性把积攒的 `E`、`I`、`T` 等显示出来。新版在第一次估速前要求至少三个已结束的点划，保留前面的点划等待后续信号，连续 1.2 秒未跟上才丢掉未确认的短序列。第一次识别时更快跟随升高的底噪，也用当前音调旁边的噪声校验信号；一旦学到速度，就放宽即时检查以保留较弱的点划。不提高全局音量门限。`WIDE`、`FIX`、`LOCK`、`MANUAL` 和手动音量门限不启用这套新规则。

| 同一输入改前 → 改后 | 没有来报时乱出的字符 | 正文错误／对照字数（忽略空格、标点） |
| --- | ---: | ---: |
| VARC 第 7 课，用于调参的实收 | **28 → 0**／明确无目标来报的 30 秒 | **9 → 0／49**；两段首字 `G` 分别在来报后 0.98、1.125 秒入文字缓冲 |
| AE5X 实收 WB0JNR 的 100 mW 通联，留出的原录音，两段 | 无单独标注的空白，不计算 | **6 → 6／15**；两段评分窗的输出前后一模一样，`100` 仍未正确抄到 |
| 同一 100 mW 实收片段减小信号再加噪，留出的压力对照 | **0 → 0**／开头 12 秒；结尾 0.33 秒也是 0 → 0 | **13 → 13／7**；两版都抄不出 `100MW HW?`，逐字输出不同 |
| 已有 40 米 SSN 实收回归，AUTO | 没有标注独立空白，不计算 | **1 → 1／63**；`AA7FV` 保持正确；`FIX 640` 对照 **0 → 0／63** |

VARC 计分标准同[连续实收验收](#40-米通联实收验收)；新版正文仍有多余空格、未评分窗口仍有符号，不能称整段录音零误报。曾试过译码过程中仍保持首次的较严门限：VARC 通过，但 40 米回归把一个 `AA7FV` 错抄为 `AA7FU`；最终放宽后恢复。用 20 WPM 合成信号单独发一个 `E`，旧版显示 `E`，新版等待后保持空白；在这个 `E` 结束后隔约 810 ms 再发 `CQ`，新旧均显示 `E CQ`。因此极短、孤立的真码可能被过滤。

两版压力测试的编辑数相同不等于漏字位置相同，也不等于弱台验收通过。加噪样本在译出第一个字符时仍将点长误估成 20 ms；同一音频临时改为 `FIX 530 Hz`、速度仍自动，已有 **5／7** 错，虽然好于 `AUTO` 的 13／7，仍抄不完整。下一项先把自动选音漂移和点划被切断分开排查；保持本次等待无来报和已有呼号的电脑回归，不从留出的录音反调门限。

[Colorado QRP Club 的原始录音和通联记录](https://www.coloradoqrpclub.org/audio/index.htm)称，2018-02-23，14.060 MHz，AE5X 在休斯敦接收 WB0JNR 降到 100 mW 的通联，报告 559。发射功率并非接收信噪比；未把原录音的全部内容标为低信噪比。按独立的约 530–540 Hz 音频包络点划标注 `100MW HW?` 和 `55N 55N BK`，只评分两窗；加噪对照对第一窗作了 1/3 振幅衰减，并加固定种子的均匀噪声。按 15 个按键期间的短时频谱点估算，信号相对 2.5 kHz 带宽的注入噪声为约 −5.1 dB（中位数，未计原录音自带噪声）。原录音和加噪对照在看输出前确定，不参与挑候选参数。输入 SHA-256：原 MP3 `4a1fb008a997148cb05fd12288d6f8be7fa32ae15dd1bef4aa4a2f0eb8114ec3`；8 kHz 单声道 WAV `99647c9ad15a952154766cdebc645156c624a9a715776afe4b9b71d2e3beb69c`；加噪 WAV `0f9727b172cb4763226fc10614c88afda730e26cc0d91803dd4f940057c744fd`。录音仅存本地忽略目录。

下面可复现留出录音；原 DAT 以只读方式供电脑面板加载。逐字证据在 `.analysis/cw-auto-quiet-1115/` 的 `cqc-before`、`final-cqc`、`weak-before`、`final-weak`、`final-varc`、`final-ssn`，以及 `weak-fixed-control`、`final-checks`。各录音电脑面板回放无丢组，实体 EXIT 对应的仿真输入恢复原画面。`final-stock` 的原厂任务专项另跑 148,960 组模拟音频，空噪声不出字、600→900 Hz 换台、自动跟音漂移以及固定选音均通过；8 项 CW 单元测试通过。修改前的 VARC、SSN 对照使用 `.analysis/cw-mk2-filter-reference-1115/{varc,ssn}/evidence.json`；已核对与本轮改前的 ARM 构建摘要相同（`ab3033ea…`）。最终 ARM 构建摘要 `b668cef7…`，原 `705J140.dat` SHA-256 `2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45` 始终不变。没有打包、升级或操作电台。

```powershell
$d = '.analysis/cw-auto-quiet-1115'
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
ffmpeg -v error -n -i "$d/input/cqc100.mp3" -ac 1 -ar 8000 -c:a pcm_s16le "$d/input/cqc100.wav"
py -3.14 -X utf8 samples/make-cw-cqc-weak.py "$d/input/cqc100.wav" "$d/input/cqc100-weak.wav"
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat "$d/input/cqc100.wav" samples/cw-cqc100-holdout.json "$d/repro-cqc" --modes AUTO --pitch 530
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat "$d/input/cqc100-weak.wav" samples/cw-cqc100-weak-holdout.json "$d/repro-weak" --modes AUTO --pitch 530
```

### 弱台诊断：正确选音后，长划仍被切断

2026-11-15。给电脑版连续录音回放增加 `--trace-demod`。报告的 `demod_changes_ms_hz_mark` 每行依次记录已处理的音频毫秒数、选中的频率和点划开关状态。每个点划判定对应 10 ms 音频；AUTO 为配合频谱选音另有 40 ms 缓冲。屏幕译文和速度仍另行记录。

在原来 100 mW 录音的衰减加噪窗内，AUTO 从首划附近即选中 540 Hz，正文只在 540–550 Hz 之间浮动。AUTO 仍曾将一条划判成 70 ms 和 60 ms 两段，中间断 10 ms，同一划在 FIX 530 Hz 对照里是连续约 140 ms。隔离 ARM 选音后再做一次对照：强制 530 Hz，但保留 AUTO 的即时门限和首次确认，仍错 **10／7**；普通 FIX 则是 **5／7**（AUTO **13／7**）。AUTO 第一次估的点长为 **20 ms**，FIX 为 **50 ms**。这表明仅改选音无法解决这段弱台，点划判定是主要的后续研究对象；两档测试只用录音，并未调整真实射频。

将较严的起音判定保留，只给已连续成立 30 ms 的点划一些维持余量。隔离 ARM 上，VARC 无来报 30 秒还是 **0** 个误字，正文 **0／49**，SSN 仍 **1／63** 且保住呼号；带此候选的 705 电脑面板在原加噪段也从 **13→6／7**。随后用从未通过 705 解码器调参的 WB0JNR 通联另一段验收：原始录音及同一段的降低音量加噪副本分别评分。原录音是同一通联的 400 mW 片段；不是另一电台或外场环境，发射功率也不能代替接收信噪比。

| 新验收样本 | 现用版 | 候选 |
| --- | --- | --- |
| 400 mW 原录音，期望 `CHECKED I JUST CHECKED` | **0／19**，显示 `CHECKED IJUST CHECKED` | **0／19**，同样少一个空格 |
| 同段减到 1/3 振幅再加噪；前置 12 秒噪声两版均不出字 | **17／19**，有多余字符，末尾仍读出 `UST CHECKED` | **13／19**，却只剩 `HECKED`，至少漏掉 13 个字 |

总编辑数下降不能抵消漏字，**不采用候选，保留现用解码器**。放宽全段门限或对判定做统一平滑的方案也未采用：部分配置重新出现背景误字或破坏已有正文。下一项先各取至少一段新的自然弱台和有窄带干扰但无有效来报的录音，冻结分段及独立转写。在同一音频逐条对照真实长短音，分别验收漏报、误报和字符完整度，再决定是否采用新的噪声估计；不继续用上一段合成加噪音频单独调门限。

证据在 `.analysis/cw-weak-track-1115/`：`panel-final-weak`（现用 AUTO／FIX）、`direct/base-weak-530-1`（定频但保留 AUTO 的判定门槛）、`panel-final-field`、`panel-final-new-weak`、`panel-candidate-weak`、`panel-candidate-new-weak`；候选原录音的逐字记录在 `direct/hold-3-5-6-0-new-field-0-0`。现用版本的 705 面板依次处理 26,574、16,800、33,867 组模拟 DMA，各无丢组且 EXIT 恢复首页。原烧录格式及固件未变；没有打包、升级或操作电台。

原始 [Colorado QRP Club 录音](https://www.coloradoqrpclub.org/audio/index.htm) 的 400 mW MP3 SHA-256 为 `d9c51abb1f040d4a119bef688dd17d3b23c14a0dc634b2db45c3ad2d3f12dc77`。用 FFmpeg 转成 8 kHz 单声道有符号 16 位 PCM，WAV SHA-256 为 `a8f4eb4b2d0dd94308ddf08296e35f73b1ecd82719407f583c7f7b3d6bf0b4a4`。用 Python `wave` 从第 142000 帧保存 100800 帧，即 17.750–30.350 秒；切片 `new-field.wav` SHA-256 为 `9904c8dfe02ee6294a058aa9e121596da74910aaca3f5ce36101bf0367c0ba91`。加噪副本 `new-weak.wav` SHA-256 为 `82723f7a9957d0a437b7a2f868319a035de78d05e434c83631d9475d0c39e7c8`。

```powershell
$d = '.analysis/cw-weak-track-1115'
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
py -3.14 -X utf8 samples/make-cw-cqc-weak.py "$d/new-field.wav" "$d/new-weak.wav" --start-ms 0 --end-ms 12600
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat "$d/new-field.wav" samples/cw-cqc400-holdout.json "$d/repro-field" --modes AUTO --pitch 530 --trace-demod
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat "$d/new-weak.wav" samples/cw-cqc400-weak-holdout.json "$d/repro-new-weak" --modes AUTO --pitch 530 --trace-demod
```

### 自然弱台留出验收：压低一项误报，未修好断划

2026-11-15。新增样本是不同接收机录下的短波实收音频，没有人为降低信号或叠加噪声。20 米弱台和 7.335 MHz 干扰用于开发；候选源码、逐块追踪脚本和标注在打开留出成绩前固定，摘要保存在 `.analysis/cw-natural-weak-1115/freeze-before-holdout.txt`。40 米弱台的开头未能独立标注，不计入成绩；只验收 Radio B 里两份同步录音都能核对的 `CQ CQ`。干扰段只给第 0–30 秒贴「无可辨 CW 来报」标签，不代表整份文件的内容或证明干扰类型。

| 录音及评分窗口 | 改前 | 已保留的频带边缘检查 | 加上补断划的候选 |
| --- | --- | --- | --- |
| 7.335 MHz 干扰，开发，30 秒误字 | 67 | **0** | 0 |
| 7.405 MHz 干扰，留出，30 秒误字 | 43 | **3**（`I IE`） | 13 |
| 2023 年未知干扰，独立来源留出，30 秒误字 | 0 | **0** | 0 |
| 40 米实收弱台，留出，`CQ CQ` | `BB E ~`，4／4 处错误 | `BB E ~`，4／4 处错误 | `DG~`，4／4 处错误 |
| 旧 400 mW 原录音，期望 `CHECKED I JUST CHECKED` | 0／19 | 0／19 | 0／19 |
| 旧 400 mW 加噪副本 | 17／19 | 17／19 | 5／19，仍漏抄正文 |
| 旧 100 mW 加噪副本 | 13／7 | 13／7 | 6／7 |

表中的软判定候选在隔离 ARM 回放中测量；边缘检查另用实际 705 面板程序确认了 7.335 MHz、7.405 MHz、独立干扰和 40 米来报的结果。清晰的 300 Hz 和 1250 Hz 两个端点测试均完整抄出 `CQ TEST 123`，也没有丢组，按 EXIT 正常回首页。字符错误是替换、增字、漏字的总数，不计空格；误字数是标注为空窗时显示出的非空格字符数。

保留的改动是 `samples/cw-arm.c`：例如 AUTO 锁到 300 Hz 时，旧版本的两个噪声探针都落在音调上方，观察不到下方的干扰。两端改为同时取音调上下 80 Hz，采用较强一侧估噪；中间频段及手动选音保留原判定。补断划候选只给已连续两组、随后掉落一组 10 ms 的标记一点余量；它虽改善旧加噪副本，却未恢复这段自然弱台，还令留出干扰多出 10 个误字，所以没有并入。

Radio A 与 B 分别用 675 Hz 和 753 Hz 做 35 ms Hann 窗的独立包络测量，相关峰显示 A 比 B 晚约 690 ms。以 B 的时间计，首个 `Q` 的第二划在两个接收机中都是连续约 **17.020–17.230 秒**。705 选中的音调一直在 740 Hz，却把对应的判定输出成 **120、30、30 ms** 三段，中间是两个 10 ms 断点；输出的时间戳比原始音频晚约 60 ms。同一来报中也有划只剩几个孤立脉冲。下一项以这些真实点划和真实空隙作为开发对照，先比较时窗及噪声跟踪对断划的影响，再取另一台独立实收录音冻结为新的留出；不把这个已经看过的 `CQ CQ` 再算作未参与调参。交付条件是新留出里弱台漏字改善、对照干扰不反弹，再用同一份日版 DAT 做电脑版验收。本轮未生成 DAT、未操作电台。

| 用途 | 公开录音原文件 | 8 kHz PCM 的 SHA-256 |
| --- | --- | --- |
| 开发，20 米 | [Radio A](https://archive.org/download/RadioBSSBCY0Pileup/RadioA-Very-Weak-CW-20MB.mp3)／[Radio B](https://archive.org/download/RadioBSSBCY0Pileup/RadioB-Very-Weak-CW-20MB.mp3) | A `cc508c6a1d7585d70f2daad26e0dd9417ccc23cba1708439fb6c26af750f6634`；B `c5d441cb2f1fda60ffca2d6e65237c9091544099934573f83fa561a93292f75a` |
| 留出，40 米 | [Radio A](https://archive.org/download/SSBRadioA40MB/CW-Weak-RadioA-40MB.mp3)／[Radio B](https://archive.org/download/SSBRadioA40MB/CW-Weak-RadioB-40MB.mp3) | A `df4895d7cd5a07dd1e816533f028d5a95e72b47710f223d18ec0f204507f361d`；B `e69831a525eb85b7f9a064efa0f14b2885ec56896eaa3e03168693335c79687b` |
| 开发干扰 | [7.335 MHz](https://archive.org/download/strange-noise-7335-khz-0500-ut-13-sep-20/strange%20noise%2C%207335KHZ0500%20UT13Sep20.MP3) | `4f9b662fc0ea5a76c3a4f0c8075f62b6e3400de68399c233bbea582b85b4e1e4` |
| 留出干扰，同次记录不同频率 | [7.405 MHz](https://archive.org/download/strange-noise-7335-khz-0500-ut-13-sep-20/strange%20noise%2C%207405KHZ0500UT13Sep20.MP3) | `a861d73b77ae2cecb532b656e79ff9468bb581effedfc74edca91a1677756631` |
| 留出干扰，独立来源 | [2023 年未知信号](https://swling.com/blog/wp-content/uploads/2023/12/UNKNOW-SIGNAL-2.mp3) | `df34b9019bc59ff886b1be2a0c389e665300148d9efe2260e2ea7e3b21f4fc7b` |

原始录音存本机研究目录，不入库。40 米留出和空窗标注分别见 `samples/cw-swling-40m-qsb-holdout.json` 和 `samples/cw-swling-no-cw-30s.json`。回放用 705 日版 1.40 的原始 DAT；其 SHA-256 仍为 `2522f62211ad5fdb313e793f94bb0574a22327660bdbde47ba9124f424114e45`。

```powershell
$d = '.analysis/cw-natural-weak-1115'
$env:PYTHONPATH = '.analysis/ic705-emulator/deps'
ffmpeg -v error -n -i "$d/weak40b.mp3" -ac 1 -ar 8000 -c:a pcm_s16le "$d/weak40b.wav"
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat "$d/weak40b.wav" samples/cw-swling-40m-qsb-holdout.json "$d/repro-weak40b" --modes AUTO --pitch 750 --trace-demod
py -3.14 -X utf8 -m tools.probe_705_cw_continuous firmware/705J140.dat "$d/noise7335.wav" samples/cw-swling-no-cw-30s.json "$d/repro-7335" --modes AUTO --pitch 300 --trace-demod
```

本机证据目录 `.analysis/cw-natural-weak-1115/`。其中 `panel-before-7335`、`panel-final-7335`、`panel-before-7405`、`panel-final-7405`、`panel-final-2023`、`panel-final-weak40b`、`panel-tone-300`、`panel-tone-1250` 是 705 面板重放；`direct/` 的 `base-*`、`edge-base-*`、`edge-drop-2-1-2-*` 是隔离 ARM 对照；`align-cq.py` 是两份录音核对用的小脚本。原厂调度专项（`final-stock.json`）处理 148,960 组模拟 DMA，自动选强台、换台、随频漂跟踪及固定选音通过；8 项 CW 单元测试通过。

### 短衰落修复和独立录音验收

2026-11-15。对上一轮的 40 米短衰落实录逐个音频块读取 ARM 的载音功率、判定门槛、平均噪声项与旧峰值项。首个 `Q` 的第二划在 17.210 和 17.250 秒（面板判定时钟）的两次中断，信号功率分别为总门槛的 77% 和 70%；这两次都由缓降的平均噪声项主导，不是载音完全消失。连续清点同一划前后的真空隙和点仍然必要，不能简单把门槛一直放低。

采用的修复只作用于启用了自动门限与自动速度的 AUTO 中段。一个窗可以标为「强信号」「有可疑的弱音」「无信号」；向后看两个 10 ms 窗，只有强音夹住的一个或两个弱窗可以接回，不凭空补音。弱窗仍须超过绝对门槛、旧峰值的下限、当前旁带功率的四倍和平均旁带功率的三倍。接发报状态和换台使历史失效；频带两端继续使用上一轮的双侧干扰检查。此前单独放宽续音、并允许频率不断小幅移动的候选虽把旧弱台抄成 `CQKQ`，却使 VARC 正文错 5 字，并把 `AA7FV` 抄成了 `AA7FU`，没有采用。

下一张表的 `CQ CQ` 是开发样本；其余三组实录未参与挑选候选。先用独立窄带包络解析标出可清楚确认的来报，未知内容不计分。候选和参考文件哈希在运行前写入 `freeze-before-holdout.txt`、`freeze-additional-holdout.txt`，补充录音也没有再改候选。所有首次成绩和每字记录保存在 `.analysis/cw-fade-1115/`，数值表示字符替换、漏字和多字的合计，不计空格。

| 实录及计分内容 | 原解码器 | 短衰落修复 |
| --- | --- | --- |
| 旧弱台 `CQ CQ`，开发 | `BB E ~`，4／4 | `DGIQ`，3／4；所查的一划不再断开 |
| SWLing 2020 双接收机对照，`CQ`／`K0PC`／`WB3DOM` | 两版都只完整抄出 `WB3DOM` | 同左，另少一个多余字符 |
| Dr vulpes 的两次 `CQ` | 2／4，只抄到第二次 | 2／4，只抄到第二次 |
| Colorado QRP Club 80 米弱应答，`CO` 和 `BK` | 8 处错误；`CO` 空白，`BK` 窗显示 `MTTI HEK` | 4 处错误；两窗分别显示 `CDT`、`WB 6`，抄到 `C` 和 `B`，但未抄对完整应答 |
| 7.405 MHz 无来报，30 秒 | 3 个误字 | 2 个误字 |

三组留出前后均由 705 电脑面板回放：20 个已标注的字符合计 **17→12** 处错误，三个录音各自均未增加。弱应答整词准确率仍低，且候选在 `BK` 窗不再显示原先最后那个 `K`；不能按总数声称每个字都改善。7.335 MHz 与 2023 年独立无来报对照仍为 0。旧录音的隔离 ARM 对照中，100 mW 和 400 mW 加噪副本分别从 **13→9／7** 与 **17→4／19**；400 mW 原录音仍 **0／19**。VARC 正文维持 **0／49**，SSN 维持 **1／63** 且两次 `AA7FV` 正确。原厂音频调度与频谱对照通过，电脑未观察到开关 CW 时原厂频谱及瀑布节拍变化。尚未测量实体机性能。

录音：SWLing 的 [IC-705 与 KX3 对照](https://swling.com/blog/2020/10/icom-ic-705-blind-audio-tests-lets-take-a-look-at-your-choices/)两份 PCM 分别是 `64f7cdc3aa5431911795bfc7a9630daf505098ee6e07372cf7b8ba128dad5c0d` 和 `3e4d16ae61d3c5293a51e6472d139dac506ee0809dff869db4f20553aaf81a59`。以 410／405 Hz 窄带包络核实三个窗的同样点划，B 比 A 晚约 195 ms；A 用于评分。Dr vulpes [2022-11-06 的 40 米接收](https://commons.wikimedia.org/wiki/File:2022-11-06_0204_40_Meter_CW.ogg)的 8 kHz 单声道 PCM 为 `2ac348f9f5c3b9721d4d706c42ad77a7c0e6ea0c1d757913fd544f21e834895a`。[Colorado QRP Club 80 米实收](https://www.coloradoqrpclub.org/audio/k0frp_ki0ii_wa8bxn_fox_010908_utc.mp3)的 PCM 为 `5dc4c70ee4ba8724ccfd995c9d79395ef813257adbdfd8bb08b5d5b5ca378eb`；该录音较强台约 752 Hz，50–57 秒受评分的应答约 845 Hz。录音在忽略目录，只有分段参考进项目。
