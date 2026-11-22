# IC‑705 机内 APRS 功能范围与可行性

## APRS 简明使用说明

适用 **v1.4.0** 及之后支持 APRS 的 **J140（日版）／E140（欧／美版）** 整合固件。APRS 使用普通 FM、1200 波特。

### 1. 开启并设置

1. 切到普通 FM，调到要用的 APRS 频点。进入 **MENU → GPS → GPS TX Mode → APRS**，选 **RX Only**（仅收）或 **RX & TX**（收发）。启用时绑定当前频点。换绑定频点时，先关闭 APRS，再调频并重新开启。
2. 在 **SET → My Station → My Call Sign** 设本机呼号。在 **MENU → GPS → APRS** 设置 **Beacon SSID**（呼号后缀）、**Beacon Symbol**（图标）、**Beacon Comment**（备注）、**TX Path**（转发路径）和 **RX Alert**（分类弹窗和提示音）。默认信标备注为 `ICOM IC-705 APRS TEST`。
3. 在 **GPS → GPS Set → GPS Select** 选 **ON** 使用内置 GPS，或选 **Manual** 并在同级 **Manual Position** 填固定台址。选 **OFF** 仍可收包。位置发射需要实时定位或有效的手动台址。

### 2. 收包和查看台站

在绑定频点的 FM 待机界面，按 **QUICK → APRS RX List** 查看最近 64 条记录，最新在前。每行显示图标、呼号、日期和时间，有本机位置时也可显示收包当时的距离。点一条看详情，按 **EXIT** 回列表，再按一次回待机。**QUICK → APRS Stations** 按呼号和 SSID 汇总台站，可排序和筛选。

### 3. 发送位置 Beacon

- **手动发一次**　选 **RX & TX**，在绑定频点按 **QUICK → Send APRS Beacon**。
- **固定时间发**　进 **GPS → APRS** 打开 **Auto Beacon**，在 **Beacon Interval** 选 1、3、5、10 或 30 分钟。
- **移动时智能发**　在 **Beacon Interval** 选 **SmartBeaconing** 并打开 **Auto Beacon**。速度越高发得越频繁，显著转弯可提前发报。静止或使用手动台址时，每 30 分钟发一次。

**FUNCTION 第 2 页**可快速切换 APRS 模式和 **AUTO BCN**。顶栏 **BCN** 表示自动信标开启，闪烁表示已到期、正在等待发射。普通单工 FM VFO 空闲时，自动信标可暂回绑定频点发射，发完回原频率。

### 4. 收发短消息

按 **QUICK → APRS Messages**。用 **New Message** 输入对方呼号及 SSID、填写正文并点 **Send**。在 **Inbox** 读来信，可在给本台的消息详情点 **Reply**。**Outbox** 可查看回执和送达状态。**Message Tools** 可设置常用短语和自动回复。发送和回复需选 **RX & TX**。

**保存与互斥。** 插入可写 SD 卡可保存配置和常用短语。接收历史和发件记录随关机清空。进入 FT8／FT4 时 APRS 暂停，回到普通 FM 后恢复并重新计时。

---

## 开发背景

首版建议做成一套可独立使用的 **1200 bit/s FM APRS 电台功能**。用本机 VHF/UHF 射频、GPS、屏幕和软调制解调器完成收报、看台站、发位置、定时信标和双向短消息。手机、电脑和互联网均为可选。机内 APRS 的可行性有原厂接口和外部软件的依据，J140／E140 的机内 AFSK 收发仍待验证。

原厂 `MENU → GPS → GPS TX Mode → D-PRS` 使用 D‑STAR DV 的低速数据通道，可随话音传位置，另有 `GPS Auto TX`。FM APRS 使用音频 AFSK 承载 AX.25 UI 帧，接收端在校验 FCS 后解释 APRS 内容。D‑PRS 网关也可能把位置送进 APRS 网络，因此网页上出现轨迹不足以证明两台机器能在 FM APRS 信道直接互收。两项功能可以共用本机 GPS 来源，各自保存发射设置。[Icom 活用手册，第 2、12 章](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_4.pdf) · [Icom D‑PRS 指南](https://www.icomjapan.com/support/manual/4734/) · [TAPR AX.25 v2.2](https://files.tapr.org/tech_docs/AX25/AX25.2.2.pdf)

## 与建伍 TH-D75 的 APRS 功能对照

**SmartBeaconing 移动信标。** 在普通 FM 的绑定频点选择 GPS → GPS TX Mode → APRS → RX & TX，再进 GPS → APRS → Beacon Interval 选择 SmartBeaconing，并打开 Auto Beacon。FUNCTION 第 2 页 AUTO BCN 在启用时显示 ON SMART。原来的五档固定间隔及 SD 配置仍可用。

日欧四功能候选包采用公制预设。每 10 秒从两次实时定位估算地速、航向，两次取样间隔超过 20 秒会重新建立轨迹。低于 5 km/h 或使用手动台址时每 30 分钟一次；5 至 70 km/h 之间的间隔为 8400 除以速度（秒），达到 70 km/h 后每 120 秒一次。距上次发报满 60 秒且相对上次发报航向的最短角度差达到 28° 加 260 除以速度时，可提前发一次。GPS 关闭、位置过期时等待有效位置。门限使用固件预设。转弯和定时共用同一个发射请求、忙信道等待、FT 互斥与普通 FM VFO 返回流程。[建伍手册 14-17～18](https://kasc.kenwood.com/files/prod/3692/5/THD75E_User_manuals_English.pdf#page=78) · [日版轨迹回放](../.analysis/aprs-hop/smart-final/J/default-comment.json) · [欧／美版轨迹回放](../.analysis/aprs-hop/smart-final/E/default-comment.json)

**2026-11-22 · 自动信标与待机操作。** `aprs-beacon-wait` 日欧整合测试包延续启用后等满一个周期的行为。周期到期但信道忙、PTT 有效、位置不可用或菜单尚未关闭时，在绑定普通 FM 频点每秒复查，恢复后只发一包，再从实际启动发射时计下一个周期。退出 FT8/FT4 回到绑定信道仍重新计时。建伍 TH-D75 的 Auto 开启时先发一次、屏上指示闪动，信道忙时等空闲。[建伍手册 14-13](https://manual.kenwood.com/en_contents/attachDownload/109792/)

机主在同一空闲频点观察到 BCN 持续闪烁，此时 QUICK 手发仍能发出。新版四功能测试包让定时信标和 QUICK 共用原厂已确认的 PTT 请求判断。原始手咪采样置位、发射请求为零时，定时器可以申请发送。原厂已经接受手咪发射请求或信道忙时，定时器保留一个待发信标，条件恢复后每秒复查一次。[定时发送与手动发送](../samples/aprs-j140-beacon.c) · [日版回放](../.analysis/aprs-timer-ptt/final/J/messages.json) · [欧／美版回放](../.analysis/aprs-timer-ptt/final/E/messages.json)

**FUNCTION 与顶栏，日欧四功能测试包。** 普通 FM 按 FUNCTION 选第 2 页，MAX TX PWR 右边的 APRS 打开 OFF、RX Only、RX & TX 选择框。选中后回到 FUNCTION，与 GPS TX Mode 共用绑定频点及收发权限。AUTO BCN 直接切换 GPS → APRS 的 Auto Beacon，启用时显示已设周期。仅收时按钮变灰，离开绑定频点时 APRS 键显示 Paused，表示当前位置的 APRS 接收暂停；AUTO BCN 显示定时信标开关及周期。单次发送仍在 QUICK。[FUNCTION 第 2 页](../.analysis/aprs-header/final/J/screens/05-function-armed.png) · [原厂 FM 第 2 页](../.analysis/aprs-beacon-wait/J/function/page2.png)

普通 FM 待机时，电池图标右侧的白色 APRS 表示接收生效，旁边的蓝色 BCN 表示自动信标开启。到期等待时仅 BCN 每 500 毫秒亮灭一次。两枚标志与 TX 上下居中，USB COM 等原厂图标占位时一起右移。右侧三处均被占用时，两枚标志以小字一起放到电池左侧。左侧也被占用时，顶栏优先显示原厂图标，仍可在 FUNCTION 第 2 页查看设置。[顶栏回放对照](../.analysis/aprs-header/final/top-bar-comparison.png) · [等待动图](../.analysis/aprs-header/final/J/screens/beacon-wait.gif)

在绑定的 FM 频点按实体 M.SCOPE 打开迷你频谱时，候选包也在该画面的原厂顶栏显示相同的 APRS 和 BCN 状态。[迷你频谱待机](../.analysis/aprs-scope-rc/candidate/J/screens/scope-armed.png) · [等待闪烁时 BCN 熄灭的半秒](../.analysis/aprs-scope-rc/candidate/J/screens/scope-wait-dark.png)

**2026-11-22 · 台站列表与报文接收更新。** 日欧四功能 `aprs-stations` 测试包在普通 FM 的 QUICK 增加 APRS Stations。Last Heard、Callsign、Distance 分别按最近听到、呼号和收包时的距离排序。Filter 可选全部、有距离、气象、对象／物件。视图从最近 64 个有效包生成，同呼号及 SSID 只列最新记录；收包时无可用距离的台站在距离排序中排在末尾。原有 APRS RX List 仍按包倒序保存，同一台的多次到达和撤销帧都可回看。

Object／Item 接受普通或压缩位置，在详情显示名称、符号、位置和发布台。收到撤销时，活动列表按发布台、名称和类别移除对应条目。第三方报文支持一层 TNC-2 或 AEA 头，详情保留外层网关、识别内层发台，Mic-E 使用内层目的地址。发给本台的带号短消息沿用原有收发权限及发射仲裁，ACK 发给内层原发送台。原始 NMEA、对象主动发布与导入 GPS 位置记忆另列后续。[协议第 11、17 章](https://www.aprs.org/doc/APRS101.PDF) · [接续记录](PROJECT_HANDOFF.md#接续记录)

**2026-11-22 四功能整合测试包更新。** 下表保留首次对照时的基线。本轮信标设置和双向消息进入日、欧两区的 `aprs-two` 整合包。原厂 GPS → GPS TX Mode → APRS 选择绑定普通 FM 频点的收发权限。GPS → APRS 可设置 SSID、图标、备注、三种路径、自动信标和 1／3／5／10／30 分钟间隔。启用自动信标后等待完整周期。装有可写 SD 卡时保存配置，包括绑定频率和收发模式。原厂 D-PRS／NMEA 模式优先于卡内绑定记录。

普通 FM → QUICK → APRS Messages 可看收件箱、标记未读、回复或新建短消息。发件箱保留最近四条，区分等待 ACK、已送达、对方拒绝、超时及取消。正常待机未获回执时每 30 秒用原编号重发，含首次最多发五次。Message Tools 提供 20 条 SD 常用短语及默认关闭的自动答词，可限定呼号、设置延时。设置和短语使用独立的两份校验记录；收发历史和在途消息保留在本次开机的内存中。群组与公告分类、可编辑任意路径及轮换状态文字仍待开发。移动信标见本节开头的 SmartBeaconing 候选包。[两区实测进度](PROJECT_HANDOFF.md#接续记录)

2026-11-22。705 的基线采用 J140／E140 四功能整合测试包 `four-mode-messages/release`。下表中的“独立版”指基于原厂 1.40 单独制作、验证的 APRS 包。D75 的页码为手册页脚编号。[建伍 TH-D75A/E 用户手册，第 14–15 章](https://kasc.kenwood.com/files/prod/3692/5/THD75E_User_manuals_English.pdf#page=62) · [705 整合菜单](../samples/aprs-slot-ui.c) · [两区测试断点](PROJECT_HANDOFF.md#接续记录)

| 使用场景 | D75 的操作和能力 | 705 整合包现状与差距 |
|---|---|---|
| 新建短消息、确认送达（14-9～10） | 指定收件人新建、回复、编辑、手动重发、标记未读。列表区分收发，未获确认最多发送五次。 | 收到发给本台的来信后可用原厂键盘回复，确认发送并识别匹配的 ACK／REJ。缺主动新建、带号来信自动回 ACK、超时重试、取消重试及独立收发件列表。 |
| 消息工具（14-9～10、14-19～20、14-24） | 常用短语、按呼号及延时自动回复正文、群组和公告分组。 | 当前走手工输入。还缺短语、自动答词、群组与公告分类。自动答词与协议级 ACK 应分别控制。 |
| 本台信标（14-1～3、14-11～15） | 呼号、图标、位置状态、可轮换的状态文字、多种发射路径；可选择携带移动速度与高度。 | 本台原厂呼号加 SSID、GPS 或手动台址、位置和备注已能用于手发。整合版设置首页只有 RX Alert、Beacon SSID。独立版的备注编辑、符号选择和三种路径预设须接回；可编辑路径、状态文本轮换、速度和高度开关仍缺。 |
| 定时与移动信标（14-13～14、14-17～18） | 支持手发、松开 PTT、固定周期、按速度和转向发报；另有静止时延长周期和按比例调整路径。 | 独立版有 1、3、5、10、30 分钟五档。整合包已有定时逻辑和 FT 忙时的抑制回放，缺面板开关与间隔。独立版启用后先等一整个周期，D75 自动模式启用即首发。松 PTT、SmartBeaconing、静止退避与比例路径仍待开发。 |
| 查找附近台站（14-5～8、14-19） | 最多 100 个台站；同台新包更新。可按呼号、时间、距离排序，按类别筛选、删除或复制到位置记忆。接收端另有距离和包型过滤。 | 当前 64 条逐包历史可回看同台不同时间、距离。可另建按呼号及 SSID 归并的台站视图，补排序、过滤及台址存储，保留现有历史。 |
| 报文与位置互通（14-4～6、14-15） | 列出 NMEA、遥测、气象等报文，支持 Object／Item 的发布与撤销。 | 已有普通、压缩、Mic-E 位置及带位置天气解析。Object／Item、原始 NMEA 和第三方封装目前留作原文，待结构化；还缺对象发布／撤销、遥测展示、雨量及独立海拔字段。 |
| 语音联络与接收提示（14-16～17、14-20～21、14-24） | QSY 可传递语音频率、亚音等并从台站记录转频；有 CTCSS Voice Alert、指定呼号特响、发射提示、语音播报、弹窗面积与时长选择。 | 已有七类独立提示方式和本台信标被转发的识别。缺 QSY 一键转频、CTCSS 近台语音提醒、指定呼号提示、APRS 语音播报等面板选项。 |
| 无线调制解调器与锁定（14-12～13） | 支持 1200／9600 bps，可选数据频段、忙信道检测方式、发射前置延时与 APRS 锁。 | 已实现普通 FM 下 1200 bps，绑定频点，离频暂停，发射与其他功能仲裁。缺 9600 bps 链路及相应设置。D75 的数据频段操作移到 705 前须验证硬件和音频路径。 |
| 独立中继与外设（14-18、14-21～24、第 15 章） | 本机可作为数字中继，支持按呼号和别名转发、去重、UIflood／UItrace。可输出原始包或航点，USB／蓝牙支持 KISS；另有 Altnet 选择。 | 705 能辨认自己的信标被其他台转发。还缺替其他台转发、独立 KISS 接口、航点／原始包输出和 Altnet。Wi-Fi KISS 或联网 iGate 可作为 705 的独立扩展；D75 手册给出的 iGate 用例有电脑参与。 |

整合优先顺序建议先接回独立版信标菜单并保存参数，再完成主动发信、ACK 和重试，随后做台站列表、Object／Item 与第三方封装。任何新增的自动发射（包括 ACK）应复用四功能发射仲裁。建议用两台电台分别验收正常回执、丢首个回执后重试且对端只显示一次、只收模式不发 ACK，以及 FT 工作期间不键控。当前 APRS 设置的跨模式保留已有回放，断电恢复仍待实现。 [消息回放](../tools/replay_705_aprs_reply.py) · [独立版定时信标](../.analysis/aprs-auto-beacon/verified/J140/verification.json) · [接收兼容样本](../.analysis/aprs-next-research/coverage.json)

## 首版可独立完成的操作

| 功能 | 在 IC‑705 上的建议行为 |
| --- | --- |
| 射频接收 | 在用户选定的 FM APRS 单工信道连续监听。解调 1200 bit/s Bell 202 AFSK（1200／2200 Hz），校验 AX.25 帧。台站列表按呼号及 SSID 归并，保留最近收报、时间、来源、符号和最后位置。详情显示坐标、距离／方位、速度／航向、备注、途经中继及原始内容。支持按类型筛选，并标记位置的年龄。 |
| 位置互通 | 接收普通和带时间戳的位置、压缩位置及 Mic‑E，兼容常见对台。首版广播采用标准非压缩位置，可附图标、备注和有效的速度／航向；高度有有效值时才附加。可收带位置的天气、对象和物件，至少展示其类别和可用字段。 |
| 本台资料及信道 | 呼号和 SSID 分开编辑并显示合成预览。AX.25 呼号字段最多六个字母或数字，RF SSID 为 0–15，0 显示为无后缀。可存 APRS 频率、图标、备注和转发路径；建议初始为 `Direct`，按使用地选择区域频点和路径。源呼号、消息收件人、AX.25 目的地址和中继路径各有职责。D‑STAR `MY` 和 D‑PRS 资料各自保存。 |
| 手动发送与定时 Beacon | 在收发已启用时提供「立即发位置」。自动 Beacon 单独默认关闭，可设周期，显示下次时间及等待原因。关闭自动 Beacon 后仍可手发。固定台可明确选用手动坐标，移动台可选本机 GPS。信道忙、正在通话、遥控占用、频率／模式不符或没有有效位置时，暂停对应发射。周期长短用机内单调计时；一轮过期后不积压多个信标。 |
| 双向短消息 | 支持输入对方完整呼号及 SSID、从台站详情发信、回复、常用短语、收件箱、未读和发件记录。经典互通格式正文至多 67 个允许的 ASCII 字符，界面可中文化，发送时显示字符计数。带编号的消息按 `ack`／`rej`、有限重试、取消、超时处理。状态区分「排队」「已发、等确认」「对台确认」「超时／拒绝」。重复包只显示一次，收发开启时可对重发的已收消息再次回送 ACK。公告按广播显示。 |
| 一般报文与记录 | 接收状态、公告、组消息、对象／物件、天气、遥测、查询／应答和能力报文。首版完整操作位置、短消息与台站记录，支持发送简短状态；其他已知报文显示可识别字段，未知合法帧保留原文。近期记录存在有限队列，后续可导出原始包、位置及消息到 microSD。 |

短消息确认属于 APRS 应用层。AX.25 UI 帧自身无链路确认，看到本机 TX 或收到本包的中继副本只说明发送或转发发生过。GPS 缺定位时仍可发短消息，位置发射继续等待。协议字段、字符范围和各类型定义见 [APRS 1.0.1，第 4、5、8–16 章](https://www.aprs.org/doc/APRS101.PDF) · [APRS 1.1 修订](https://www.aprs.org/aprs11.html) · [APRS 1.2 提案汇总](https://www.aprs.org/aprs12.html)。

## 入口、待机和通知

| 入口 | 职责 |
| --- | --- |
| 实体 `MENU → 第 2 页 → GPS → GPS TX Mode` | 在原厂 `OFF / D-PRS / NMEA` 后选择 `APRS`，再选 `RX Only` 或 `RX & TX`。 |
| 实体 `MENU → 第 2 页 → GPS → APRS` | 在 `GPS TX Mode` 下方管理 `FM Channel`、`Beacon SSID`、`Beacon Comment`、`TX Path`、`Beacon Symbol`、`Auto Beacon` 和 `Beacon Interval`。 |
| FM 待机 `QUICK → APRS RX List` | RX Only 和 RX & TX 可查看本次开机最近收到的 64 条有效报文。最新报文在顶端，每行显示图标、发信呼号及 SSID、接收时间和日期。有距离的记录在呼号下方显示收包时的距离。点行打开详情，实体 `EXIT` 先回列表原页，再回待机。 |
| FM 待机 `QUICK → Send APRS Beacon` | RX & TX 时出现。点第二行手动发一条直接位置包。 |
| `GPS → GPS Set → GPS Select` | APRS 共用原厂本机位置来源。可选 `ON`、`OFF` 或 `Manual`。固定台址在同级 `Manual Position` 设置。 |
| `MODE` 候选快捷项 | APRS 运行在 FM／FM‑D 的音频通道。若需要，可在相关模式提供快捷入口，正式设置仍从 APRS 进入。 |

**同频待机。** 留在预设信道与匹配模式时，回到正常频率／频谱画面，后台解码继续运行。来包短提示参考原厂 DV 的 `RX:`／`MSG:` 显示行。发给本台的新短消息默认弹窗，显示呼号、正文摘录及「详情／返回」。位置包更新历史，可以从小图标打开详情，关注台的位置可另设自动弹窗。发射、调谐、系统确认框或录入期间先记未读，空闲时提示。返回或到时收起窗口后，消息仍可从未读图标或接收历史打开。同一消息重发时沿用原记录。

**普通 FM 异频自动信标。** 开启 RX & TX 和 Auto Beacon 后，离开绑定频点时顶栏显示灰色 APRS 和蓝色 BCN。到期后在单工 FM 的空闲 VFO 短暂切回绑定频点，等待 400 ms 让静噪稳定。信道允许且位置有效时发一个位置包，发射结束并释放 PTT 后恢复原频率和原 VFO。收听会短暂中断。原频点正在收信或有发射请求时继续等待。位置不可用时留在原频点等待。已经切到目标信道后遇忙或定位失效，会返回原频点，下个周期再试。用户在临时切频期间另选 VFO、转动到第三个频率或改模式时，以用户选择为准。关闭自动信标或设置仅收时不进行这种切换，QUICK 手发仍在绑定频点操作。[信标调度](../samples/aprs-j140-beacon.c) · [原厂 VFO 记录和读回](IC705_VFO_SPLIT.md)

**FT8/FT4 工作期间暂停全部 APRS 业务。** FT 独占接收和发射，APRS 暂停解码、入库、提示、消息和信标。FT 工作时到期的信标跳过。退出 FT 并回到可用的普通 FM 后，以保存的设置重新计满一个周期。

### 原厂 DV 弹窗对照

| 原厂画面 | APRS 采用的行为 |
| --- | --- |
| 普通 DV 来呼时，S 表上方出现 `RX:` 呼号行，可滚动来呼留言。原厂显示选项包括关闭、正常、接收期间保留和持续保留。 | 在相应显示区域提供来包呼号或留言的短提示。需保留频率、S 表和正常调谐操作。 |
| 收到 D‑PRS 位置时，会出现黑底、细灰边的位置窗。窗内显示方位、坐标、距离、呼号和留言，右下是返回键。位置窗超时后，点接收位置图标可以重开。原厂定时选项为 5／10／15／30 秒或保持，默认 10 秒。 | APRS 位置详情沿用「窗口 → 返回或超时 → 图标重开」的操作。指定给本台的短消息用同类窗口，补一枚「详情」键进入消息记录。APRS 的弹窗策略与 DV 各自保存。 |
| DV 接收历史用窄标题条、黑底正文、右侧翻页键及下方详情／返回，设定页使用滚动表列。 | APRS 接收历史与设置优先核对这些原厂控件和实际调用。菜单格位、弹窗触摸区、实体 `EXIT` 和状态恢复由面板回放验收。 |

[Icom 活用手册位置窗，12‑3](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_5.pdf#page=97) · [Icom 活用手册 DV 来呼与历史，13‑8](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_5.pdf#page=149) · [Icom 基本手册，8‑17 至 8‑18](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)

[早期六态效果图](images/aprs-icom-concept.png)保留了短消息窗和接收历史的设计草案。当前入口、列表和详情以两版原厂 ARM 回放截图为准。

### FM 待机的接收列表

日版 J140 和欧版 E140 均在 APRS Mode 为 RX Only 或 RX & TX 时，从普通 FM 待机按实体 `QUICK`，点首行 `APRS RX List`。列表沿用原厂选择窗，一页四条，最多 16 页。保留本次开机最近 64 条有效帧，满后覆盖最早一条。位置报文按收包时的本机 GPS 或手动台址计算距离，保存在对应记录里。再次查看时沿用此数值。沿用上次定位或对方坐标精度受限时，距离前显示 `~`。收包时无法计算距离的行只显示呼号。每条在接收时保存本机 RTC 日期和时间，右列上方为 `HH:MM:SS`，下方为 `YYYY-MM-DD`。日期字段无效时显示横线。跨零点或调时后仍按收包先后排序。调离 APRS 频点后可在 FM 模式查看已收记录。空列表显示 `No APRS packets`。[QUICK 入口](../.analysis/aprs-history-date/check/J140/01-quick.png) · [接收列表](../.analysis/aprs-touch-distance/final/E140/history/04-newest-first.png)

点一行打开该帧的 APRS 内容。位置类沿用已有的罗盘、GPS 状态和多行备注，标准短消息显示发信呼号、收件人、正文及报文编号，状态或其他有效帧可查正文。详情时按实体 `EXIT` 或点屏幕返回，回到列表原页，再返回 FM 待机。两版模拟从 48 kHz 音频接收后核对顺序、时间、坏 FCS、异频查看、翻页及两级返回。另用解码输出回放环形记录覆盖，验证第 16 页及最早剩余已收帧。DV 接收记录独立，原厂 DV 的 QUICK 中没有 APRS 入口。[短消息详情](../.analysis/aprs-history/panel/E140/05-message-detail.png) · [位置详情](../.analysis/aprs-history/panel/E140/08-position-detail.png) · [日版回放](../.analysis/aprs-history/panel/J140/history.json) · [欧版回放](../.analysis/aprs-history/panel/E140/history.json)

### 日版和欧版的 GPS/APRS 接收入口

按实体 MENU，翻第 2 页，进入 `GPS → GPS TX Mode`。在原厂 `OFF / D-PRS / NMEA` 之后点 `APRS`。点选 `RX Only` 或 `RX & TX` 即应用并返回 `GPS TX Mode`，第四行 `APRS` 高亮。再次点进第四行可查看当前选项。按 EXIT 回 GPS，当前值为 `APRS`，调离绑定频点或切出普通 FM 时显示 `APRS (Paused)`。在面板上改选 `OFF / D-PRS / NMEA` 即退出 APRS。选择 APRS 时，原厂 DV 位置发射模式按 `OFF` 应用，D‑PRS 和 NMEA 原有设置页继续可用。[原厂 GPS TX Mode](../.analysis/aprs-gps-entry/E140-v2/03b-gps-tx-mode.png) · [Icom 高级手册，第 12 章](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_1a.pdf)

`GPS → APRS` 管理参数。`FM Channel` 绑定当前普通 FM 频率，APRS 关闭时也可先配置频点。首次直接启用会使用当前普通 FM。点选 `Beacon SSID` 或 `TX Path` 后保存并回到 APRS 设置，显示新值。`Beacon Comment` 用原厂键盘提交，`Beacon Symbol` 选定符号后回到 APRS 设置。实体 EXIT 或屏幕返回可取消本级编辑。APRS 模式、频点和 Beacon SSID 保存在本次开机的 RAM，开机默认关闭。

普通 D‑PRS 位置自动窗在原厂 J140 和 E140 回放中均未请求提示音。原厂 GPS Alarm 可对进入指定范围的台站发声。APRS 在有效位置类来报实际自动弹窗时请求一次原厂短音，跟随 `SET → Function → Beep (Confirmation)` 和 `Beep Level`。手动点图标重看沿用普通按键反馈。两版回放确认打开提示音时可立即按实体 EXIT，关闭提示音时同一类来包仍正常开窗。[原厂 D‑PRS 声音对照](../.analysis/aprs-ux/stock/dprs-beep.json) · [Icom GPS 操作手册](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_4.pdf) · [Icom 提示音设置](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)

两版用 144.390 MHz 作为回放测试频点。原厂 VFO 从 144.390000 调到 144.390200 MHz 再调回。异频和 OFF/ON 均隔离已排队的 6 块，调回后下一包自动开窗。设置期间来包照常入库，回待机后可点原位置图标重开。DV 和 USB 下仍可查看 APRS 设置，绑定操作只接纳普通 FM。[日版菜单及调谐报告](../.analysis/aprs-gps-entry/J140/menu.json) · [欧版菜单及调谐报告](../.analysis/aprs-gps-entry/E140-v2/menu.json) · [欧版四种接收窗](../.analysis/aprs-gps-entry/E140-popups/aprs-popup-baseline.png)

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3 -X utf8 -m tools.replay_705_aprs_menu firmware/705J140.dat .analysis/aprs-gps-entry/repro-J140
py -3 -X utf8 -m tools.replay_705_aprs_menu firmware/705E140.dat .analysis/aprs-gps-entry/repro-E140
```

### APRS 本机位置来源

本机位置遵循原厂 `MENU → GPS → GPS Set → GPS Select`。选 `ON` 时取内置 GPS，按定位年龄显示 `GPS`、`LAST FIX` 或 `NO FIX`。选 `Manual` 时读取原厂 `Manual Position` 保存的坐标，无论实时 GPS 是否有有效缓存，距离和方位均以手动台址计算并标 `MANUAL`。选 `OFF` 时接收和对端坐标仍可用，本机相对距离、箭头与方位留空。切换由机主在原厂菜单操作，失锁时不自动切换来源。

两区从测试 DAT 解出的程序分别走原厂菜单选择 Manual、OFF 和 ON，以台架加载的原厂手动台址核对几何结果；另在模拟缓存有实时定位时，从接收历史重开，仍显示相同的手动距离和方位。[原厂手动台址页](../.analysis/aprs-manual/release/J140/position-source/11-original-manual-position.png) · [欧版历史详情](../.analysis/aprs-manual/release/E140/position-source/12b-manual-from-history.png)

### 原厂符号和罗盘实绘

APRS 弹窗与接收列表读取原厂 D‑PRS 使用的主、副符号图库，按来报的符号表和符号码取图。原厂 55×55 素材在 24×24 图标区做像素平均缩放，小车、中继天线、步行台等保留原厂形状。短消息和状态用平滑边缘的信封及文档图标。图标与呼号保持行内对齐。

罗盘直接绘制原厂的分段表圈、四个方位字样和两色针形。APRS 表盘保持北向上，红针为原厂针形的 75%。新版先对原厂透明度蒙版按覆盖面积计算目标像素，再按 LCD 像素一比一绘制，让斜边平滑过渡。定位失效时只画表圈和方位。回放分别核对 D‑PRS 取原厂素材、APRS 取预滤波蒙版，以及无定位时只绘制表圈。[红针放大对照](../.analysis/aprs-needle/compare.png) · [原厂与 APRS 整窗对照](../.analysis/aprs-visual/compare.png) · [接收列表](../.analysis/aprs-needle/release/E140/history/04-newest-first.png)

### 手动发送 Beacon 测试包

普通 FM 待机的 QUICK 随 APRS Mode 改变。OFF 隐藏两项，RX Only 只显示 `APRS RX List`，RX & TX 在列表下面加 `Send APRS Beacon`。调离设定频点后仍可查看历史，选择发射时提示回到 APRS FM 频点。[QUICK 实绘](../.analysis/aprs-beacon/release/E140/beacon/03-quick-rx-tx.png) · [异频提示](../.analysis/aprs-beacon/release/E140/beacon/10-off-channel.png)

本次使用原厂 `SET → My Station → My Call Sign` 已选的本台呼号，`GPS → APRS → Beacon SSID` 选择 0–15。设为 RX & TX 后，点 QUICK 的发射项发一条非压缩位置包，图标为房屋。位置由原厂 GPS Select 决定。Manual 读取手动台址，ON 需要当前有效定位，OFF 与过期定位均不申请发射。频点不符、Split、信道忙、原厂已有发射请求或发射禁止时，本次操作退出并显示对应原因。[APRS 报文规范](https://web.tapr.org/software_library/aprs/aprsspec/spec/aprs101/APRS101.pdf) · [欧版 SSID 设置](../.analysis/aprs-beacon/release/E140/beacon/04-ssid.png)

`GPS → APRS → Beacon Comment` 使用原厂 D‑PRS 的文字键盘。四功能候选包默认预填 `ICOM IC-705 APRS TEST`，最多 43 个可打印 ASCII 字符。手动和定时位置包共用这段备注。按 `ENT` 保存后返回 APRS，实体 EXIT 或屏幕返回可取消。四功能整合包从 SD 配置恢复用户已保存的备注，保留原大小写。D‑PRS 的四组备注单独存放。

### 发射设置提案

在 `GPS → GPS TX Mode → APRS` 选择启用方式，在 `GPS → APRS` 设置参数。呼号和位置来源沿用 `My Call Sign` 和 `GPS Select`。APRS 第二页的 `Auto Beacon` 默认关闭，`Beacon Interval` 预选 10 分钟，提供 1、3、5、10、30 分钟。选定项目后回到 APRS 第二页并显示新值。`QUICK → Send APRS Beacon` 可手动发射。开关和间隔在本次开机有效。[Icom CI‑V 参考](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf) · [APRS 协议规范](https://www.aprs.org/doc/APRS101.PDF)

`GPS → APRS` 第一页的 `TX Path` 提供 `Direct`、`WIDE2-1`、`WIDE1-1,WIDE2-1`，分别请求零、最多一、最多两次射频转发，初始值为 `Direct`。点选路径后回到 APRS 第一页并显示新路径。第二页的 `Beacon Symbol` 进入原厂四行选择窗，可浏览主表、副表和叠加图标，默认房屋。选定符号后回到 APRS 第二页，重新打开定位到所选类别和图标。每次 EXIT 退回一级，浏览后退出保留原值。两项设置有效至关机。[APRS New‑N 路径约定](https://www.aprs.org/fix14439.html)

APRS 图标页每行显示图标与英文名称。主表 86 项、副表 77 项，副表已定义的底图可叠加数字 0–9 或字母 A–Z。叠加字符画进图标，列表与详情共用同一个绘制函数。房屋、小车等沿用原厂图案，缺少的底图由 APRS 图库补齐。发射仍使用标准非压缩位置格式，完整写入所选符号的两个字符。[APRS 主副表和叠加规则](https://www.aprs.org/symbols.html) · [APRS 符号扩充表](https://www.aprs.org/symbols/symbols-new.txt)

补充图案主要使用 Heikki Hannikainen（OH7LZB）的 aprs.fi 24 像素符号，另绘有电力和 GPS 导航副表底图。生成表做 RGB565 调色和游程编码。原图及逐符号署名见 [aprs.fi 图库](https://github.com/hessu/aprs-symbols/tree/f2286a9cd43eb6ba4501250b4c39fff111e3796c) 和 [COPYRIGHT](https://github.com/hessu/aprs-symbols/blob/f2286a9cd43eb6ba4501250b4c39fff111e3796c/COPYRIGHT.md)。英文名称来自 [aprs.fi 符号索引，CC BY-SA 4.0](https://github.com/hessu/aprs-symbol-index/tree/68a273408fa12ea01a9fc50b8bc3e32c31f0f508) 和 Dire Wolf 1.8.1 所附的 APRS 扩充表。固件构建直接读取生成表。需要更新图源时运行 [生成脚本](../tools/make_705_aprs_symbols.py)。

接收位置支持带或不带时间戳的 Base91 压缩位置，以及新旧 Mic‑E 标记。已解码的位置、单位、符号和备注进入现有 APRS 弹窗及接收历史。Mic‑E 或普通位置带精度模糊时，距离和坐标用 `~` 标明采用区域中心。压缩报文中的高度与无线电覆盖半径仍只随原始记录保留。[APRS 位置格式第 7、9、10 章](https://www.aprs.org/doc/APRS101.PDF)

早期独立版的行为如下。启用 `Auto Beacon`、修改间隔、改绑频点或重新选 `RX & TX` 后，从一个完整间隔开始。手动 Beacon 提交给原厂发射路径时也重新计时。定时器使用原厂毫秒计时并调用同一个 APRS Beacon 发射入口，在普通单工 FM 待机、当前频率等于绑定频率、信道空闲且位置有效时才尝试发射。离频、忙信道、定位失效、原厂菜单、弹窗或 PTT 占用时跳过本轮，下一次尝试仍需等一个间隔。原厂 `GPS Auto TX` 属于 DV 的 GPS 数据发射。[Icom 高级手册，第 12 章](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_1a.pdf)

两版台架用原厂请求、过滤、音源和 SSI0 DMA 路径，分别从内置 GPS 和手动位置发送。Dire Wolf 关掉纠错后各解出完整呼号、SSID、坐标、图标和备注。回放提供模拟 DSP 反馈与 DMA 完成。2026-11-21 机主另确认真机手发后另一设备成功解码；地区、调制频偏和前导余量未测记。[日版报告](../.analysis/aprs-beacon/release/J140/beacon/beacon.json) · [欧版报告](../.analysis/aprs-beacon/release/E140/beacon/beacon.json)

现场报告 `Radio TX busy`。两区旧 DAT 的原厂 PTT 采样置位、发射请求和原厂过滤结果均为零时，点 QUICK 可复现此弹窗。修正版以原厂过滤结果判断手咪发射请求，并为发射禁止、遥控 PTT、正在发射和其他发射请求提供独立提示。原厂禁止条件和信道忙判断继续生效。[日版旧 DAT 复现](../.analysis/aprs-tx-busy/old-dat/J140/old-radio-tx-busy.json) · [欧版旧 DAT 复现](../.analysis/aprs-tx-busy/old-dat/E140/old-radio-tx-busy.json) · [日版最终报告](../.analysis/aprs-tx-busy/verified/J140/verification.json) · [欧版最终报告](../.analysis/aprs-tx-busy/verified/E140/verification.json)

### 双向短消息、断电保存和位置兼容的接入验证

2026-11-21 从最新 J140 和 E140 的 DAT 解包，核对应用与包的 SHA-256。两版以 20 组同样的 AX.25 报文字段进入实际 ARM 正文解析器，与 Dire Wolf 的文本解码对照。这个探针从校验后的报文入口开始，音频和实体机互通另验。[两版结果](../.analysis/aprs-next-research/coverage.json) · [Dire Wolf 对照](../.analysis/aprs-next-research/dire-wolf.txt) · [复现脚本](../.analysis/aprs-next-research/probe.py)

- **双向短消息。** 当前能在接收记录中显示正文、收件人和经典 `{ID`。`ack`、`rej` 和 `{MM}AA` 仍作为正文，尚无匹配应答、重试、去重或发信状态。建议由 FM 的 `QUICK → APRS Messages` 进入收件、发件和新建，详情可直接回复。两版探针已用原厂 Beacon Comment 键盘定位并修改第 67 个字符，`ENT` 把 67 字节交给回调。正文按协议限制为可打印 ASCII，收件字段为 9 字节并包含 SSID。匹配确认要核对对台、本台和消息编号。无编号消息及公告不回 ACK。重复的编号消息保留一条，`RX & TX` 可按限速补回 ACK，`RX Only` 只收。发信和 ACK 复用现有 FM 调制、PTT 仲裁、FCS 与位填充，并独立检查本机身份和发射条件。台架验收覆盖 GPS 无定位、错误 SSID、ACK 丢失后重试、REJ、过期和两跳满长消息。当前 Beacon 的帧缓冲上限为 95 字节，两跳短消息的上限为 116 字节，含 FCS、未位填充。延迟取得 DSP 发射许可的满长帧也要测完尾标志。[键盘结果](../.analysis/aprs-next-research/keyboard.json) · [APRS 消息规范第 14 章](https://www.aprs.org/doc/APRS101.PDF) · [Reply‑ACK 规则](https://www.aprs.org/aprs11/replyacks.txt)
- **断电保存。** 最新 APRS 的模式、绑定频点、SSID、路径、图标和备注在 RAM。FT8／FT4 已用原厂 SD 文件接口实现双记录轮换，并验证日欧两版卡状态 3、4 能重读，短读保留上一次有效记录。APRS 可复用该机制，使用独立文件，保存上述参数以及待加的 Auto Beacon 和间隔。提交参数时写入另一份记录，检测完整写入及关闭结果，读取时验版本、序号和校验。无卡或写入失败保留本次开机生效状态。如开机读取到原厂 GPS TX Mode 为 D‑PRS 或 NMEA，保留该原厂模式。上电恢复参数时，短消息未完成的发射和重试队列保持空。整机断电、拔卡、写到一半、两份损坏和更换卡分别验收。[日版 SD 先例](../.analysis/e140-log-retry/callsign-J-after.json) · [欧版 SD 先例](../.analysis/e140-log-retry/callsign-E-after.json) · [FT 短读回退测试](../tools/verify_705_ftx_tx.py#L627)
- **位置接收兼容。** 普通位置、Base91 压缩位置、Mic‑E 和带位置天气在现有两版均得到结构化结果。对象 `;`、物件 `)`、iGate 第三方封装 `}` 及原始 NMEA 目前保留原文。样本中的 `/A=` 与 `!DAO!` 也留在备注。优先补 Object 和 Item 的名字、坐标、符号及撤销标志，再让第三方报文同时保留外层网关和内层原发送台。封装里的短消息回信匹配内层呼号，封装的 Mic‑E 需要使用内层目的地址解经纬度。撤销对象只处理同一发布台及名称的对象，历史仍可查看。后续再验 NMEA 校验、空定位、海拔和精度扩展。在接收记录与罗盘画面逐包比对，普通位置继续用原有弹窗。[报文样本](../.analysis/aprs-next-research/fixtures.tnc2) · [APRS 第 8–12、17 章](https://www.aprs.org/doc/APRS101.PDF)

现版留给应用镜像的余量为 J140 1,360 字节、E140 560 字节。原厂选择器每条历史项使用 72 字节描述符。若沿用图标目录已验证的共用行描述符做法，理论可回收 4,536 字节并保留 64 条接收记录。下一构建应先用两版翻页、选择、回原页、环形覆盖及原厂菜单回归核对这一调整，再测最终装载余量。

### 两版独立接收测试包

本轮在 J140 和 E140 的各自原厂 1.40 底包上构建测试 DAT。APRS 代码、接收状态及菜单表装入应用镜像末尾，结束地址为 `0x2037D8B8`，距首个原厂 RAM 初始化目标 `0x20380000` 还有 10,056 字节。25,312 字节接收状态随应用一起解压到零，原厂初始化完成后仍为零，默认 `OFF`。

原厂更新任务从两个原厂起始槽分别写入另一槽。四次写入的完整虚拟 NOR 与预期逐字节相同，随后由原厂引导加载对应槽，应用 SHA-256 与 DAT 解包结果相同。用同一 DAT 解出的程序回放 GPS/APRS 菜单、调离与调回、四种接收窗、SSI0 和 RTX 任务。两版各通过八组 48 kHz 音频回归。实体机的静噪首包、射频弱信号和实时余量仍待测。

两份 DAT 是独立 APRS RX 验证包，底包采用原厂 1.40。和已发布的 FT8、CW、SSTV 增强合包是后续独立工作。[日版报告](../.analysis/aprs-rx-dat/verified/J140/verification.json) · [欧版报告](../.analysis/aprs-rx-dat/verified/E140/verification.json)

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3 -X utf8 -m tools.build_705_aprs_rx_dat firmware/705J140.dat .analysis/aprs-rx-dat/repro-J140 .analysis/aprs-fm-pcm/final .analysis/aprs-rx-probe/final
py -3 -X utf8 -m tools.build_705_aprs_rx_dat firmware/705E140.dat .analysis/aprs-rx-dat/repro-E140 .analysis/aprs-fm-pcm/final .analysis/aprs-rx-probe/final
```

### J140 原厂 DV 和 FM 面板回放

同一份日版 1.40 原厂主程序输出 12 张 480×272 画面。台架送入合成的已解码 DV 呼号、留言和位置记录。本机位置经原厂 NMEA 输入发布，距离由原厂 GPS 任务计算。原厂代码处理窗口打开、超时、坐标命中、关窗及画面更新。台架提供 LCD、按键输入和 GPS 任务唤醒。验证范围从接收记录开始，DV 慢数据解码、FM AFSK 和真机仍待各自验收。

| 路径 | 回放观察 | APRS 接入依据 |
| --- | --- | --- |
| 呼号及留言短行 | 原厂 `0x2004B7F4 → 0x20162F50` 分别画出 `RX: JA1ABC` 和 `MSG: STOCK PANEL REPLAY`，短行位于频率与 S 表之间。 | 复用短行绘制和更新区域。原厂准备函数取 DV 记录，APRS 接入时提供自己的呼号、留言和可见状态。 |
| D‑PRS 位置窗 | 原厂收到位置有效事件后，`0x20048778 → 0x20048510(3) → 0x200F2030(13)` 请求开窗，`0x2004944C → 0x2018842C` 准备及绘制内容。图中含台站呼号、坐标、留言和原厂算出的 `1852m`。 | APRS 沿用原厂窗框、返回和窗口生命周期。APRS 位置在窗内使用自己的报文头、坐标、符号和备注。短消息窗的正文与详情动作另行验收。 |
| 超时和点图标重开 | 10 秒设置的原厂比较在计数 2500 保持、2501 关闭。点图标 `(401, 101)` 命中 `0x15`，经 `0x200801C0 → 0x20048510(2)` 重开，同一坐标、呼号、留言和距离再次显示。 | 复用同一屏幕区域和原厂触摸、返回流程。由 APRS 的位置或未读状态决定图标是否显示，点按应取对应的 APRS 记录。固定计数对照不测实机时基。 |
| 实体 EXIT 和屏幕返回 | 实体 EXIT 的键样本走原厂扫描和分发。屏幕返回 `(375, 244)` 命中 `0x21A`。两者都进入 `0x200EFE64(1)`，回待机，接收位置图标仍可再开窗。 | 优先接入原厂弹窗关闭和重绘流程。用实时窗口状态判断是否应由 EXIT 关窗，并回归原厂菜单和其他弹窗。 |

把同一份台架记录留在 RAM，只切到 FM，原厂照样绘制短行和位置图标，触摸能重开窗，实体 EXIT 回 FM。清掉 DV 短行启用位和位置标志后，短行消失，点同一坐标不会重开。由此确认布局、命中和关闭路径可在 FM 使用，后续 APRS 要以独立来报状态接入，避免改写 D‑STAR 最近台站和位置记录。

[原厂呼号](../.analysis/aprs-dv-panel/final/02-dv-caller.png) · [原厂位置窗](../.analysis/aprs-dv-panel/final/04-dprs-auto-open.png) · [超时后图标](../.analysis/aprs-dv-panel/final/05-dprs-timeout.png) · [FM 重开位置窗](../.analysis/aprs-dv-panel/final/10-fm-native-position.png) · [调用、触摸与散列](../.analysis/aprs-dv-panel/final/replay.json)

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3 -X utf8 -m tools.replay_705_dv_panel firmware/705J140.dat .analysis/aprs-dv-panel/final
```

[复现工具](../tools/replay_705_dv_panel.py)核对原厂 DAT 和字库并沿用面板台架。台架新增本例指南针位图的 270° 旋转及纯色绘制模拟。REA 核对位置窗原厂代码窗口，证据 `ev_90f7ac860d748b9551a87eab974b990be9300214af60b1c4f8c6657aac9f4150`。调用及屏幕行为以回放为准。

## J140 普通 FM 待机取样与静噪首包

日版 1.40 原厂主程序处于 `FM FIL1` 待机，录音和 `AUDIO SCOPE` 均关闭。台架把 WAV 注入 SSIF0 的 DMA 双缓冲，以每次 1–7 个块的节奏运行原厂音频任务 `0x20110384`。`0x2010FE34` 取第一槽刚读出的 36 个 48 kHz 样本，`0x2010FEAC` 取原厂每六个保留一个后的 6 个 8 kHz 样本。17.64 秒干净音频经过 23,521 块、2,940 次环绕，两处读数分别与输入和 6:1 抽取逐样本一致。信号只送第二槽时，两处均读到静音。[原厂 FM 画面](../.analysis/aprs-fm-pcm/final/stock-fm-standby.png) · [报告与各路采样散列](../.analysis/aprs-fm-pcm/final/replay.json)

用 Dire Wolf 1.8.1 的 `gen_packets` 产生 1200 bit/s Bell 202 测试流，以 `atest -B 1200 -F 0` 校验每帧的完整 TNC2 内容和顺序。`-F 0` 关闭坏帧纠错。独立生成的好 FCS 对照通过，坏 FCS 对照被拒收。[Dire Wolf 1.8.1](https://github.com/wb2osz/direwolf/releases/tag/1.8.1) · [干净音频日志](../.analysis/aprs-fm-pcm/final/continuous-stock48.wav.atest.txt) · [FCS 对照](../.analysis/aprs-fm-pcm/final/fcs-stock48.wav.atest.txt)

| 音频条件 | 输入 48 kHz | 原厂早期 48 kHz | 原厂 8 kHz |
| --- | ---: | ---: | ---: |
| 干净，位置、短消息和状态交错 | 30/30 | 30/30 | 30/30 |
| 同批包，幅度降至 1/16，叠加固定随机种子的宽带白噪声 | 20/30 | 20/30 | 0/30 |

同份早期 PCM 经 FFmpeg 低通重采样至 8 kHz 后解出 13/30。这个合成加噪用例支持将早期 48 kHz 作为机内 APRS 接收候选，原厂简单抽取的 8 kHz 仅作为对照。真机 FM 音频的噪声、通带、去加重和 CPU 余量仍待测。[加噪 48 kHz](../.analysis/aprs-fm-pcm/final/weak-noisy-stock48.wav.atest.txt) · [原厂 8 kHz](../.analysis/aprs-fm-pcm/final/weak-noisy-stock8.wav.atest.txt) · [滤波 8 kHz](../.analysis/aprs-fm-pcm/final/weak-noisy-filtered8.txt)

**原厂录音许可和 SSIF0 输入截音分开测。** 在同一 FM 待机回放中保持 SQL 档值 `100`，切换台架提供的 DSP 噪声读数。原厂静噪例程 `0x200B47D0` 计算状态，经 `0x200623F0` 在 `0x200622D8` 发布录音许可。每次在首包音调开始 120 ms 后打开许可，首包前导为 106.7 ms。三次开静噪时，两处早期取样都解出首包 3/3、后包 3/3。若台架按录音许可屏蔽同一份 8 kHz PCM，首包为 0/3，后包仍为 3/3。接收支路应连续取早期 PCM，录音许可用于这个对照中的后级门控。台架为原厂代码提供接收状态位和噪声读数，未模拟 DSP 自身如何产生或静音音频。[三次原厂许可变化](../.analysis/aprs-fm-pcm/final/replay.json) · [模拟后级门控日志](../.analysis/aprs-fm-pcm/final/stock-squelch-with-post-tap-gate8.wav.atest.txt)

**在 SSIF0 之前模拟截掉头部时，三路首包结果一致。** 26 个用例均有独立 ID 和一帧完整后包，后包 26/26。下表列出此次采样点中的成功与失败边界，具体阈值随发送方前导、噪声和解调器变化。

| 测试前导 | 已测最长可解截断 | 已测最短丢首包截断 |
| --- | ---: | ---: |
| 8 个 HDLC 标志，53.3 ms | 50 ms | 70 ms |
| 16 个标志，106.7 ms | 90 ms | 110 ms |
| 32 个标志，213.3 ms | 210 ms | 220 ms |

下一项真机验收用同一射频测试源，比较 SQL 常开与固定静噪档，重复独立上载波，逐包记录 48 kHz 取样首次见到 AFSK 的时间及首包 FCS 结果。分别测常规 FM 和窄带 FM。

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
$dw = (Get-ChildItem .analysis/aprs-fm-pcm/direwolf -Recurse -Filter atest.exe).Directory.FullName
py -3 -X utf8 -m tools.replay_705_aprs_fm firmware/705J140.dat $dw .analysis/aprs-fm-pcm/repro
```

复现前将官方 Dire Wolf 1.8.1 Windows x64 ZIP 解压到 `.analysis/aprs-fm-pcm/direwolf`。ZIP SHA-256 为 `5389257646882f8c86cf598c1d403fd3400fa915ca70b1843cd61cc43656a1fa`。滤波对照使用 `ffmpeg -i weak-noisy-stock48.wav -ar 8000 -c:a pcm_s16le -fflags +bitexact -flags:a +bitexact weak-noisy-filtered8.wav`，随后用相同 `atest` 参数读出。回放文件只在电脑运行。[复现脚本](../tools/replay_705_aprs_fm.py)

### J140 ARM 只收解码回放

ARM 接收桥在原厂 `0x2010FE34` 取得栈上 36 个 48 kHz 样本，运行解码后执行原指令并回原厂任务。桥检查 FM 接收模式和 DSP 发射状态，静噪许可不参与取样。解码器使用 1200／2200 Hz 定点正交相关、时钟恢复、NRZI 及 HDLC 去填充，只有 FCS 正确的 AX.25 UI `PID F0` 帧进入输出队列。程序与常数共 2,152 字节，可写状态与四帧队列共 2,644 字节。桥只装入虚拟 ARM 内存。[ARM 解码器](../samples/aprs-rx-arm.c) · [J140 接收桥](../samples/aprs-j140-rx.s) · [AX.25 v2.2](https://files.tapr.org/tech_docs/AX25/AX25.2.2.pdf)

复用上一轮 WAV，按散列校验输入和 Dire Wolf 可执行文件。Dire Wolf `atest -B 1200 -F 0 -h` 导出原始帧数据，对照机内导出的地址、控制字段、PID 和正文。报告保留每个匹配及独有帧，ARM 输出另保留收到的两字节 FCS 和帧尾采样位置。[逐包报告](../.analysis/aprs-rx-probe/final/replay.json) · [弱信号对照日志](../.analysis/aprs-rx-probe/final/weak-noisy-stock48.wav.direwolf.txt)

| 用例 | ARM | Dire Wolf 1.8.1 | 逐包核对 |
| --- | ---: | ---: | --- |
| 30 个干净包 | 30 | 30 | 30 帧逐字节一致，顺序相同 |
| 同一批降幅并加白噪声 | 25 | 20 | 17 帧相同，ARM 独有 8 帧，Dire Wolf 独有 3 帧，均属原始 30 帧 |
| 三次延后开静噪 | 6 | 6 | 三个首包和三个后包完全一致，许可为 0 时连续吃入 38,880 个样本 |
| 单独坏 FCS | 0 | 0 | ARM 各判决支路到达 FCS 检查，队列没有出包 |
| 26 组截断扫测 | 首包 20，后包 26 | 首包 22，后包 26 | ARM 少收 `FIRST-08-050` 和 `FIRST-32-210`，两者的后包均完整 |
| 坏 FCS 或截断后紧跟有效包 | 2 | 2 | 两个有效后包逐字节一致，整个 ARM 回放期间许可保持 0 |

调参时对三个独立白噪声样本比较了相关窗口，选择 52 样本窗口和每 4 点更新，以保持三路判决和有限的音频任务开销。表中仍只报告原来的同一批音频。所有用例的输出队列零溢出。独立守卫试验在 CW 与模拟 TX 时均无取样，回 FM 接收后同一帧成功。短前导极限、整机任务实时余量及射频输入质量需要扩展验证。[模式与 TX 守卫](../.analysis/aprs-rx-probe/mode-guards.txt) · [紧邻后包音频](../.analysis/aprs-rx-probe/final/adjacent-recovery.wav)

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
$atest = (Get-ChildItem .analysis/aprs-fm-pcm/direwolf -Recurse -Filter atest.exe).FullName
py -3 -X utf8 -m tools.replay_705_aprs_rx firmware/705J140.dat .analysis/aprs-fm-pcm/final $atest .analysis/aprs-rx-probe/repro
```

这条队列也是下述 FM 面板回放的有效帧来源。实机仍需对照常开与固定静噪的射频首包。[解码复现工具](../tools/replay_705_aprs_rx.py)

### J140 从 APRS 音频到原厂 FM 待机提示

J140 原厂音频任务读取 SSIF0 第一槽的 48 kHz PCM，在任务内将 FCS 有效的 AX.25 帧写入独立的 64 条 APRS 接收记录。记录保留地址、路径、正文、FCS 和帧尾采样位置。原厂界面负责窗口、触摸、返回和实体键，ARM 代码选择 APRS 记录并绘制正文。短消息与状态保留原帧，位置图标取最新的有效位置。[APRS 1.0.1](https://www.aprs.org/doc/APRS101.PDF) · [ARM 位置正文](../samples/aprs-j140-panel.c)

#### 接收弹窗视觉基线

以机主提供的四态参考图为基线。顶部显示报文类型和本机 GPS 状态，左栏显示本机到该台的距离、真北方位和红色指针，右栏用彩色图标和大呼号识别台站。底部留 TNC2 报文头，长路径在小屏上省略，接收记录仍保留整帧。原厂窗框和右下返回键沿用实际可触区域。打开或重开时读取有效的本机 GPS，过期时显示 `NO FIX`、`-- km` 和空表盘。[四态原厂 ARM 实绘](../.analysis/aprs-comment-wrap/release/E140/popups/aprs-popup-baseline.png) · [GPS 过期实绘](../.analysis/aprs-comment-wrap/release/E140/popups/05-position-without-fix.png)

`COMMENT` 按实际字宽折行，续行用满右栏。普通位置与个人台最多四行，移动位置和 iGate 位置最多三行。移动位置带备注时将速度和航向放在一行。末行放不下才显示省略号，收到的完整备注和原始图标代码留在数据中。[中继台长备注](../.analysis/aprs-comment-wrap/release/E140/popups/08-position-symbol-r.png) · [移动车台长备注](../.analysis/aprs-comment-wrap/release/E140/popups/09-mobile-comment.png)

| 接收内容 | 右栏字段 |
| --- | --- |
| `POSITION BEACON` | 经纬度。带有效 `ccc/sss` 扩展时显示航向和速度，速度从节换算为 km/h。 |
| `WEATHER STATION` | 有坐标的气象包显示温度、湿度、风向风速和气压。按 APRS 原始单位换算，缺项显示 `--`。 |
| `APRS IGATE` | 当前位置与网关符号指示的类型。`R&` 显示 `RX ONLY`，含义来自符号定义。 |
| `PERSONAL STATION` | `/[` 个人台样式显示经纬度和报文备注。 |

首次弹窗回放使用了有、无时间戳的非压缩位置，含有效 `!`、`=` 和 `@` 示例。用实际编码的 AX.25 来包选择四种布局，用独立球面参考验证本机到对端的距离和方位。现版也解码压缩位置和 Mic‑E。无位置气象包和短消息双向会话仍在功能清单中。[APRS 报文规范](https://www.aprs.org/doc/APRS101.PDF) · [APRS 网关符号定义](https://www.aprs.org/symbols/symbols-new.txt) · [Dire Wolf TNC2 路径格式](https://github.com/wb2osz/direwolf/blob/master/src/ax25_pad.c#L119)

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3 -X utf8 -m tools.replay_705_aprs_popup firmware/705J140.dat .analysis/aprs-popup-baseline/repro
```

下表保留此前同一原厂窗口路径的验收记录和当时的文本布局截图。

| 待机动作 | 原厂路径与回放结果 |
| --- | --- |
| 呼号短行 | `0x2004B7F4 → 0x20162F50` 从 APRS 专用视图读到 `RX: N0CALL-7`，显示在 144.390 MHz 的频率和 S 表之间。[呼号短行](../.analysis/aprs-native-task/panel-final-v2/02-fm-aprs-callsign.png) |
| 位置自动提示 | 原厂 `0x20048510(3) → 0x200F2030(13)` 开窗。第一包显示 `N0CALL-7>APDW16,WIDE1-1`、`3531.00N  13930.00E`、`SYMBOL  />` 和 `J140-000`。后来收到的位置独立更新，已打开的内容保持第一包。[位置窗](../.analysis/aprs-native-task/panel-final-v2/03-fm-aprs-position.png) |
| 超时与重开 | 原厂计数 `2500` 保持、`2501` 关闭。点 `(401,101)` 命中 `0x15`，原厂 `0x200801C0 → 0x20048510(2)` 从专用记录重开 `J140-027`。此时最后收到的是状态包 `J140 FM 029`，位置窗仍用最新位置记录。[图标重开](../.analysis/aprs-native-task/panel-final-v2/05-fm-aprs-icon-reopen.png) |
| 实体 EXIT 与屏幕返回 | 模拟实体按键走原厂键扫描和事件分发，`0x200EFE64(1)` 关窗回 FM。图标可再打开，屏幕返回 `(375,244)` 命中 `0x21A` 也走原厂关窗。[实体 EXIT 后](../.analysis/aprs-native-task/panel-final-v2/06-fm-aprs-physical-exit.png) · [屏幕返回后](../.analysis/aprs-native-task/panel-final-v2/07-fm-aprs-screen-return.png) |

两版面板回放八个音频用例各写入 110 条 APRS 记录，原始帧、FCS、结束采样和顺序逐条与既有 Dire Wolf 对照相同。干净组 30 条、弱信号组 25 条、静噪组 6 条、FCS 混合组 1 条、截断组 46 条、紧邻恢复组 2 条。单独坏 FCS 和仅第二槽有音频各 0 条。APRS 操作期间监控的 DV 地址零写入，且无原厂 EEPROM 写入口调用。切回 DV 并重开 `JA1ABC` 的原厂位置窗，前后画面逐像素相同。另用原厂 `Duplicate Call Sign.` 告警对照，来包入库，告警维持原优先级，按 EXIT 后可从原图标查看收到的位置。[日版面板报告](../.analysis/aprs-gps-entry/J140-corpus/replay.json) · [欧版面板报告](../.analysis/aprs-gps-entry/E140-corpus/replay.json) · [欧版切回 DV](../.analysis/aprs-gps-entry/E140-corpus/08-dv-after.png)

两版均用原厂 RTX 调度测试同批音频的前三包、关闭接收、异频和调回、单独坏 FCS、原厂八格采样缓冲整圈覆盖。调回时拒收已经排队的异频样本。覆盖发生在包内时，原厂任务识别丢失的八块并重置解码，后两包恢复。RTX 试验验证接收分发和一次原厂界面调用点，面板回放以独立的虚拟时钟和输入驱动相同 ARM 代码。RTX 用例直接设定频率，实操作见 MENU 和转轮回放。虚拟内存中的 ARM 代码与数据尚需规划进入可刷固件的空间，真机静噪与实时余量仍待测。[日版 RTX](../.analysis/aprs-gps-entry/J140-rtx/task.json) · [欧版 RTX](../.analysis/aprs-gps-entry/E140-rtx/task.json) · [任务与采样代码](../samples/aprs-j140-task.c)

```powershell
$env:PYTHONPATH = (Resolve-Path .analysis/ic705-emulator/deps).Path
py -3 -X utf8 -m tools.replay_705_aprs_panel firmware/705J140.dat .analysis/aprs-fm-pcm/final .analysis/aprs-rx-probe/final .analysis/aprs-native-task/repro-panel
py -3 -X utf8 -m tools.replay_705_aprs_task firmware/705J140.dat .analysis/aprs-fm-pcm/final .analysis/aprs-rx-probe/final .analysis/aprs-native-task/repro-rtx
py -3 -X utf8 -m tools.replay_705_aprs_panel firmware/705E140.dat .analysis/aprs-fm-pcm/final .analysis/aprs-rx-probe/final .analysis/aprs-gps-entry/repro-E140-corpus
py -3 -X utf8 -m tools.replay_705_aprs_task firmware/705E140.dat .analysis/aprs-fm-pcm/final .analysis/aprs-rx-probe/final .analysis/aprs-gps-entry/repro-E140-rtx
```

## 接入本机 GPS

- **接收弹窗的定位状态。** 旧版的 `GPS` 跟随原厂有效标志，短暂收不到新定位时仍可能用本机上次的坐标算距离。两版原厂回放确认一次有效定位把倒计时重装为 120，后续无定位的 NMEA 既不刷新倒计时，也不立即清除有效标志。每减少一格与原厂 10 秒弹窗计时的 250 格对应，推算最长约两分钟。新版前约 5 秒显示 `GPS`，再显示 `LAST FIX` 和上次定位算出的距离。倒计时归零或原厂判无效后显示 `NO FIX`，距离和方位留空。本机重新定位后，已打开的窗口也会刷新。右栏仍是来报台站的坐标。[原厂计时回放](../.analysis/aprs-fix-age/stock-timing.json) · [Icom 弹窗计时说明](https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf)
- **画面微调。** 呼号左侧的 APRS 符号下移 8 像素，罗盘红色箭头线性尺寸缩小约 20%。两版按实际 `/r` 来报和四种常用弹窗回放，图标和呼号视觉中心相差至多 2 像素。标题右侧三种定位状态共用 68×20 像素圆角框，标题栏上下各留 3 像素，文字居中。[照片同类符号回放](../.analysis/aprs-rounded-badge/final/E140/popups/08-position-symbol-r.png) · [上次定位](../.analysis/aprs-rounded-badge/final/E140/popups/06-fix-last.png) · [过期](../.analysis/aprs-rounded-badge/final/E140/popups/05-position-without-fix.png)
- 直接读原厂定位服务。J140 已用合成 NMEA 回放验证经纬度、UTC 及各自的有效标志。定位过期后，旧经纬度和旧 3D 状态仍可读到。发位置时使用同一次有效定位快照，独立核对更新时间和来源。失锁时停止发移动位置，恢复后再按信标策略继续。固定台址作为显式选项，可在室内无实时定位时使用。[J140 GPS 回放与复现](IC705_GPS_INPUTS.md)
- 台站距离和相对方位用本机当前位置及最近有效的对端位置计算。收信时间、对端位置的报文时间与本机 GPS UTC 分别保存。UTC 无效时可发送无时间戳的标准位置。速度、航向和高度进入报文前，还需核对 J140／E140 的字段来源、单位和有效条件。[APRS 位置格式](https://www.aprs.org/doc/APRS101.PDF) · [原厂 GPS 字段回放](IC705_GPS_INPUTS.md)

## Wi‑Fi 的三条路径

| 路径 | 能力和前提 |
| --- | --- |
| 外部音频与 PTT | 通过原厂 WLAN 音频、调谐和 PTT，把 IC‑705 接给手机／电脑的软 TNC。SDR‑Control Mobile 的开发者手册已记录其 IC‑705 Wi‑Fi 连接及 APRS 收发功能，可作对照端。原厂也提供 USB 音频，可用电脑上的 Dire Wolf 建立有线参照。 |
| 局域网伴侣 | 后续让本机 APRS 向手机或 ESP32 提供解好的台站、消息与状态。手机较适合地图、轨迹和键盘输入。IC‑705 作为 AP 时可本地直连；原厂说明手机或电脑无法通过电台这个 AP 上互联网。现有遥控音频／CI‑V 已有公开实现，机内结构化 APRS 数据接口需要另行验证。 |
| APRS‑IS | 优先由有外网的手机／电脑桥接，提供地图、网络报文和网络短消息。机内直连另验 WLAN 是否提供可用的出站 TCP、DNS、认证与掉线恢复。直连客户端和 RF↔IS 网关分开启用，界面标明 `RF`／`IS` 来源。IS 消息能否到达只听 RF 的对台取决于覆盖范围内的双向 iGate 及其转发条件。后续先考虑受控 RF→IS，再评估有限的 IS→RF 消息转发和去重规则。 |

[Icom 活用手册，第 11 章](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-705_ENG_Advanced_4.pdf) · [SDR‑Control Mobile APRS 手册](https://documents.roskosch.de/sdr-control-mobile/index.html#aprs) · [Dire Wolf](https://github.com/wb2osz/direwolf) · [APRS‑IS 协议](https://www.aprs-is.net/Specification.aspx) · [iGate 设计与转发约束](https://www.aprs-is.net/IGating.aspx)

## 可以扩展的功能

- **移动与显示。** SmartBeaconing 根据速度和转向调节发送频率，可再支持静止延长间隔、位置模糊度、台站轨迹、附近台站与对象。后续可显示或发送 QSY 语音联络信息，调频由操作者确认。可由手机地图或 SD 轨迹承载更完整的图形显示。[Kenwood TH‑D75 功能说明](https://www.kenwood.com/usa/com/amateur/th-d75a/) · [APRS 1.1](https://www.aprs.org/aprs11.html)
- **其他报文。** 发送公告与对象、发布接入的气象传感器数据和遥测、解析测向及第三方封装、选择性查询和应答。短信／邮件依赖外部服务，支持范围和可用性需单独核验。[APRS 1.0.1](https://www.aprs.org/doc/APRS101.PDF)
- **联网与转发。** 可研究把本机做成 USB／局域网 KISS TNC、专用同频 digipeater、只收或双向 iGate。单位时间发多少、允许何种路径、重复包如何过滤，以及网络侧断连会如何影响待机，均需专项验收。[Dire Wolf 功能与参考实现](https://github.com/wb2osz/direwolf) · [APRS‑IS iGate 细则](https://www.aprs-is.net/IGateDetails.aspx)
- **其他调制与场景。** 可为合适的卫星／ISS 信道配置单独预设，沿用 1200 AFSK 时先核对卫星实际工作参数。HF 300 AFSK 需另测 SSB 音频，9600 G3RUH 需验证基带、滤波与调制能力。现有 1200 AFSK 音频链与软件先例只支持将这两者列为研究项。[SDR‑Control Mobile 手册](https://documents.roskosch.de/sdr-control-mobile/index.html#aprs) · [Dire Wolf 调制选项](https://github.com/wb2osz/direwolf)

## 技术与设计验收点

1. **按原厂界面验收。** J140、E140 的同包 ARM 回放已验证 GPS/APRS 入口、原厂 GPS 选项、接收开关、频点调离与回切、四种位置窗和实体 EXIT。两版原厂写入及双槽冷启动已在虚拟 NOR 通过，下一项是实体机回放。短消息编辑和确认、Beacon 周期与 GPS 失锁各态随对应模块验收。[来报到原厂提示回放](#j140-从-aprs-音频到原厂-fm-待机提示) · [两版独立接收测试包](#两版独立接收测试包)
2. **普通 FM 待机取样与 ARM 只收解码回放已通过。** 原厂 RTX 已验证固定测试信道、异频缓冲拒收和漏块后的重新同步。真机验收仍需用可配对的射频测试信号测静噪首包、常规及窄带 FM 的通带、弱信号和语音干扰，以及音频任务实时余量。[ARM 解码回放](#j140-arm-只收解码回放) · [机内 PCM 证据](IC705_RX_AUDIO.md) · [现有 FT 原厂收发和调度](IC705_FT8_FT4.md)
3. **发射在对端解得出时验收。** 复用项目已回放的原厂音源、发射请求与仲裁思路，验证 FM 单工实际 PTT 前导、调制频偏、首尾完整、忙信道退避、手咪与遥控竞争。先独立软 TNC 读回完整波形，再用实体机做双向 RF。验证 Beacon 关闭／手动／定时、GPS 失锁恢复、重启及异频暂停，最后以两端短消息、ACK 丢失重试和重复包测试闭环。J140、E140 按各自原厂音频、GPS、菜单和资源表核对。[两版台架证据](PROJECT_HANDOFF.md)

机内 APRS 的真机解码和射频互收仍待验收。
