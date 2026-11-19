"""Run the J140 Chinese display catalogue in the original ARM renderer, on a PC only."""

import argparse
from hashlib import sha256
from pathlib import Path

from tools.arm_705_display import SET_CAPTION, THIRD_LABEL, THIRD_TOKEN, base_words, build, word_table
from tools.render_705_display import load
from tools.render_705_stock_row import require
from tools.virtual_705_panel import make_window
from tools.zh_705_row import ZH_LABEL

FONT_SOURCE_SHA = "d68bafcb48a2707749396aa12bbbd833cb70401f3a9a689fd2902c7e0d295964"
DISPLAY = {
    "ディスプレイ設定": "显示设置",
    "受信LED": "接收 LED",
    "メーターピークホールド": "仪表峰值保持",
    "メモリーネーム": "存储名称",
    "グループネームポップアップ": "组名称弹窗",
    "受信コールサイン表示": "接收呼号显示",
    "受信位置インジケーター": "接收位置指示",
    "受信位置表示": "接收位置显示",
    "受信位置表示時間": "接收位置显示时间",
    "ノーマル": "普通",
    "受信ホールド": "接收时保持",
    "ホールド": "保持",
    **{f"{n}秒": f"{n} 秒" for n in (5, 10, 15, 30)},
    "自動応答位置表示": "自动应答位置显示",
    "受信画像インジケーター": "接收图像指示",
    "DV受信バックライト": "DV 接收背光",
    "送信コールサイン表示": "发射呼号显示",
    "相手局": "对方电台",
    "自局": "本机",
    "スクロール速度": "滚动速度",
    "遅い": "慢",
    "速い": "快",
    "オープニングメッセージ": "开机消息",
    "パワーオンチェック": "开机检查",
    "表示単位": "显示单位",
}
UNITS = {
    "表示単位": "显示单位",
    "緯度/経度": "纬度/经度",
    "高度/距離": "高度/距离",
    "速度": "速度",
    "気温": "气温",
    "気圧": "气压",
    "雨量": "雨量",
    "風速": "风速",
    "knots": "节",
    "inch": "英寸",
}
LANGUAGE = {"英語": "英语", "日本語": "日语"}
TIME = {
    "時間設定": "时间设置",
    "日時設定": "日期与时间",
    "UTCオフセット": "UTC 偏移",
    "日付": "日期",
    "時間": "时间",
    "<<ネットワーク時刻補正>>": "<<网络校时>>",
    "NTP機能": "NTP 功能",
    "NTPサーバーアドレス": "NTP 服务器地址",
    "GPS時刻補正": "GPS 校时",
}
SET_NAV = {
    "セット": SET_CAPTION,
    "トーンコントロール/送信帯域幅": "音调控制/发射带宽",
    "機能設定": "功能设置",
    "自局設定": "本机设置",
    "DV設定": "DV 设置",
    "DVレピータモニター設定": "DV 中继监听设置",
    "交信/受信履歴ログ": "通联/接收记录",
    "外部端子": "外部接口",
    "ディスプレイ設定": "显示设置",
}


def catalogue(*, third_language=False):
    # Identical source/target pairs share a single record, while retaining distinct scopes.
    combined = {}
    for flags, source, target in base_words():
        if source in ("OFF", "ON"):
            flags |= 16 | 128
        combined[source, target] = flags
    for scope, words in ((16, DISPLAY), (32, UNITS), (64, LANGUAGE), (128, TIME)):
        for source, target in words.items():
            if source != target:
                combined[source, target] = combined.get((source, target), 0) | scope
    if third_language:
        combined[THIRD_TOKEN, THIRD_LABEL] = 256
        combined["MENU", "菜单"] = 512
        for source, target in SET_NAV.items():
            combined[source, target] = combined.get((source, target), 0) | 1024
    return [(flags, source, target) for (source, target), flags in combined.items()]


def prepare(source, output, *, third_language=False, omit_glyphs="", arm_build=None):
    from tools.probe_zh_cn_page import build_font

    require(sha256(source.read_bytes()).hexdigest() == FONT_SOURCE_SHA,
            "expected the verified NotoSansSC-VF.ttf from the prior display experiment")
    output.mkdir(parents=True, exist_ok=True)
    entries = catalogue(third_language=third_language)
    chars = "".join(sorted(set("".join(target for _, _, target in entries) + "表") - set(omit_glyphs)))
    font_path = output / "IC705LabSC-Regular.ttf"
    build_font(source, font_path, chars)
    font = font_path.read_bytes()
    return dict(zh_font=font, arm_build=arm_build or build(output), arm_table=word_table(entries),
                arm_font_sha=sha256(font).hexdigest(), third_language=third_language)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="original Japanese 705J140.dat")
    parser.add_argument("--font-source", type=Path, default=Path(".analysis/zh-cn-preview/noto/NotoSansSC-VF.ttf"))
    parser.add_argument("--build", type=Path)
    parser.add_argument("--replay", type=Path, metavar="OUTPUT", help="save the matched original and Chinese replays")
    parser.add_argument("--third-language", action="store_true", help="enable a separate Simplified Chinese choice in the PC emulator")
    args = parser.parse_args()
    images = load(args.dat.read_bytes())
    build_dir = args.build or Path(".analysis/ic705-emulator") / (
        "j140-third-build" if args.third_language else "display-catalog-build")
    settings = prepare(args.font_source, build_dir, third_language=args.third_language)
    if args.third_language:
        if args.replay:
            from tools.verify_705_third_language import MISSING_GLYPHS, replay
            fallback = prepare(args.font_source, args.replay / "missing-font", third_language=True,
                               omit_glyphs=MISSING_GLYPHS, arm_build=settings["arm_build"])
            replay(images, settings, args.replay, fallback=fallback)
        else:
            from tools.replay_705_language_storage import LogicalStorage
            storage_path = build_dir / "pc-display-settings.bin"
            root, _ = make_window(images, storage=LogicalStorage.read_file(storage_path), storage_path=storage_path, **settings)
            root.mainloop()
        return
    if args.replay:
        from tools.verify_705_display_catalog import replay
        replay(images, settings, args.replay)
    else:
        root, _ = make_window(images, **settings)
        root.mainloop()


if __name__ == "__main__":
    main()
