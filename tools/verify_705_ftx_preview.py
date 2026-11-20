"""Replay the actual offline panel, file chooser and TX download in Chromium."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import statistics
import wave

from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".analysis/ftx-station"


def verify(chrome):
    evidence = {}
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=chrome, args=["--allow-file-access-from-files"])
        p = browser.new_page(viewport={"width": 900, "height": 700})
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto((OUT / "IC-705-FT8-FT4.html").as_uri())
        p.wait_for_selector(".record", timeout=10000)
        def press(label):
            p.get_by_role("button", name=label, exact=True).click()

        def settings():
            press("TX…")
            press("TX 设置")

        def save_back():
            press("保存")
            press("返回")

        def through_qso(auto):
            press("开始演练")
            history = []
            for _ in range(9):
                if p.evaluate("qso.done"): break
                confirm=p.get_by_role("button", name="确认本条")
                if not auto and confirm.count() and confirm.is_enabled():
                    press("确认本条")
                press("快进一隙")
                msg=p.locator(".qso-info .last").inner_text()
                if not auto and p.evaluate("qso.step===1 && !qso.waiting"):
                    p.locator("#lcd").screenshot(path=OUT/f"{mode}-report.png")
                if msg not in history: history.append(msg)
            assert p.evaluate("qso.done"), history
            press("返回")
            return history

        for mode in ("FT8", "FT4"):
            p.select_option("#layout", "dense")
            p.get_by_role("button", name="PRESET", exact=True).click()
            p.get_by_role("button", name=mode+" · 机内操作").click()
            expected = ["CQ JA1ABC PM95", "CQ VK2ABC QF56", "CQ DL1ABC JO62", "CQ G4ABC IO91",
                        "F4ABC I4ABC RR73", "CQ F4ABC JN18", "CQ VE3ABC FN03", "JA1ABC F4ABC -12",
                        "CQ EA1ABC IN73", "CQ W6ABC CM87", "CQ SP4ABC KO03"]
            assert p.locator(".message").all_text_contents() == expected[:10]
            assert p.locator(".record img").count() == 10
            assert p.locator(".km").nth(4).inner_text() == "—"
            assert len(set(p.locator(".snr").all_text_contents())) >= 4
            calibration=p.evaluate("""() => {
                const pcm=generate('CQ JA1ABC PM95',1000);
                return [-6,-10,-14].map(target=>{
                    let seed=54321;
                    const gain=Math.sqrt(2*2500/6000)*1800*Math.pow(10,target/20)/24000;
                    const noisy=Int16Array.from(pcm,s=>{
                        seed=(Math.imul(seed,1664525)+1013904223)>>>0;
                        return Math.round(s*gain+(seed/4294967296-0.5)*Math.sqrt(12)*1800);
                    });
                    return [target,decode(noisy).find(r=>r.text==='CQ JA1ABC PM95')?.snr];
                });
            }""")
            assert all(db is not None and abs(db-target)<=3 for target,db in calibration), calibration
            rect = p.locator("#work").bounding_box()
            assert (rect["width"], rect["height"]) == (480, 186)
            header = p.locator(".radiohead").bounding_box()
            assert header["y"] + header["height"] == rect["y"]
            records = p.locator(".record")
            keys = p.locator(".keys").bounding_box()
            for i, record in enumerate(records.all()):
                box = record.bounding_box()
                assert box["height"] == 17 and box["y"] == rect["y"] + 16 + i*17
                assert box["x"] + box["width"] <= keys["x"]
                assert record.locator(".message").evaluate("(el) => el.scrollWidth <= el.clientWidth")
            assert box["y"] + box["height"] == rect["y"] + rect["height"]
            records.last.click()
            assert p.locator(".detail b").inner_text() == expected[9]
            p.get_by_role("button",name="返回").click()
            p.mouse.move(0,0)
            p.locator("#lcd").screenshot(path=OUT / f"{mode}-compact.png")
            stock=Image.open(OUT/f"{mode.lower()}-home.png").convert("RGB").crop((0,0,480,86))
            screen=Image.open(BytesIO(p.locator(".radiohead").screenshot())).convert("RGB")
            assert ImageChops.difference(stock,screen).getbbox() is None
            p.get_by_role("button", name="▶").click()
            assert p.locator(".message").all_text_contents() == expected[10:]
            assert p.get_by_role("button", name="▶").is_disabled()
            p.get_by_role("button", name="◀").click()
            press("7 行")
            assert p.locator(".record").count()==7 and p.locator(".record").first.bounding_box()["height"]==24
            press("10 行")
            assert p.locator(".record").count()==10
            p.select_option("#layout", "half")
            assert p.locator(".message").all_text_contents() == expected[:4]
            p.get_by_role("button", name="▶").click()
            assert p.locator(".message").all_text_contents() == expected[4:8]
            p.select_option("#layout", "large")
            settings()
            p.select_option("#position","none")
            save_back()
            assert p.locator(".km").all_text_contents() == ["—"]*7
            press("地图")
            assert "本台位置未知" in p.locator(".mapnotes").inner_text()
            press("返回")
            for valid in (True,False):
                settings()
                p.select_option("#position","gps")
                state={"position_valid":valid,"coordinates":["35300000N","139300000E"]}
                p.locator("#gpsFile").set_input_files(dict(name="gps.json",mimeType="application/json",
                                                          buffer=json.dumps(state).encode()))
                p.wait_for_function("document.querySelector('#gpsFile').value === ''")
                save_back()
                assert (p.locator(".km").first.inner_text()=="45") == valid
            settings()
            press("示例值")
            p.locator("#lcd").screenshot(path=OUT/f"{mode}-identity.png")
            press("时隙 / 应答")
            p.select_option("#sequence","manual")
            p.locator("#lcd").screenshot(path=OUT/f"{mode}-tx-settings.png")
            save_back()
            press("地图")
            assert "听到 10 台" in p.locator(".mapnotes").inner_text()
            assert "已定位 9 台" in p.locator(".mapnotes").inner_text()
            p.locator("#lcd").screenshot(path=OUT/f"{mode}-overview.png")
            press("逐报查看")
            for _ in range(2): press("下一报")
            p.locator("#lcd").screenshot(path=OUT/f"{mode}-map.png")
            assert "DL1ABC" in p.locator(".mapnotes").inner_text()
            for _ in range(2): press("下一报")
            assert "端点位置不全" in p.locator(".mapnotes").inner_text()
            for _ in range(3): press("下一报")
            assert "报文收发方" in p.locator(".mapnotes").inner_text() and "约" in p.locator(".mapnotes").inner_text()
            p.locator("#lcd").screenshot(path=OUT/f"{mode}-directed-map.png")
            press("返回")
            p.locator(".record").first.click()
            press("回复此 CQ")
            p.locator("#lcd").screenshot(path=OUT/f"{mode}-reply.png")
            assert p.evaluate("qso.txParity===1 && !qso.started")
            manual=through_qso(False)
            assert any("R-10" in s for s in manual) and manual[-1].endswith("73")
            settings()
            press("时隙 / 应答")
            p.select_option("#sequence","auto")
            save_back()
            press("TX…")
            press("呼叫 CQ")
            auto=through_qso(True)
            assert any("RR73" in s for s in auto) and auto[-1].endswith("73")
            p.locator(".record").first.click()
            press("回复此 CQ")
            p.locator(".qso-info input").uncheck()
            press("开始演练")
            for _ in range(9):
                if p.evaluate("qso.paused"): break
                press("快进一隙")
            assert p.evaluate("qso.paused && qso.count===Number(station.limit)")
            press("停止")
            p.locator(".record").first.click()
            press("回复此 CQ")
            press("开始演练")
            press("机身 EXIT")
            assert p.evaluate("!qso && clockTimer===null && rows.length===0 && !selected && !rehearsalOffset")
            restored=Image.open(BytesIO(p.locator("#lcd").screenshot())).convert("RGB")
            home=Image.open(OUT/f"{mode.lower()}-home.png").convert("RGB")
            assert ImageChops.difference(home,restored).getbbox() is None
            press("MENU · PRESET")
            press(mode+" · 机内操作")
            press("TX…")
            press("WAV 工具")
            p.fill("#txtext","JA1ABC K1ABC PM95")
            p.fill("#txhz","550")
            message = p.input_value("#txtext")
            assert message == "JA1ABC K1ABC PM95"
            with p.expect_download() as dl:
                p.get_by_role("button",name="导出 TX WAV").click()
            path=OUT / mode / "261119_120000.wav"
            path.parent.mkdir(exist_ok=True)
            dl.value.save_as(path)
            with wave.open(str(path)) as wav:
                assert wav.getframerate() == 12000
                frames=wav.getnframes()
                assert frames == (180000 if mode=="FT8" else 90000)
            p.locator("#file").set_input_files(path)
            p.wait_for_function("document.querySelectorAll('.message').length===1")
            assert p.locator(".message").inner_text() == message
            evidence[mode] = dict(stock_header_pixel_match=True,manual_reply=manual,auto_cq=auto,
                                  snr_reference_and_measured_db=calibration,
                                  exit_restored_full_frame=True, unanswered_limit_stopped=True,
                                  sample_messages=expected, visible_rows=10, row_height_px=17,
                                  old_half_visible_rows=4, reply=message, samples=frames)
        independent = OUT / "FT4/independent/000000_000001.wav"
        if independent.exists():
            p.locator("#file").set_input_files(independent)
            p.wait_for_function("document.querySelector('#notice').textContent.includes('000000_000001.wav')")
            evidence["wsjtx_ft4_input"] = p.evaluate("rows.map(r=>r.text)")
            assert set(evidence["wsjtx_ft4_input"]) == {expected[i] for i in (0,2,4,5)}
        p.get_by_role("button",name="PRESET",exact=True).click()
        p.get_by_role("button",name="FT8 · 机内操作").click()
        p.locator("#file").set_input_files(ROOT / ".analysis/ftx-lib/test/wav/websdr_test1.wav")
        p.wait_for_function("document.querySelector('#notice').textContent.includes('websdr_test1.wav')")
        evidence["websdr_test1"] = p.evaluate("rows.map(r=>r.text)")
        assert "CQ IK4LZH JN54" in evidence["websdr_test1"]
        visible = p.locator(".message").all_text_contents()
        while p.get_by_role("button", name="▶").is_enabled():
            p.get_by_role("button", name="▶").click()
            visible.extend(p.locator(".message").all_text_contents())
        assert visible == evidence["websdr_test1"]
        comparisons = {}
        snr_errors = []
        heard_before = set()
        for n in range(1,5):
            path=ROOT / f".analysis/ftx-lib/test/wav/websdr_test{n}.wav"
            if n!=1:
                p.locator("#file").set_input_files(path)
                p.wait_for_function("name=>document.querySelector('#notice').textContent.includes(name)",arg=path.name)
            got=set(p.evaluate("rows.map(r=>r.text)"))
            calls=set(p.evaluate("Array.from(heard.keys())"))
            assert heard_before <= calls and "VK2ABC" not in calls
            heard_before=calls
            reference={re.split(r"\s{2,}",s.split("~",1)[1].strip())[0]
                       for s in path.with_suffix(".txt").read_text().splitlines() if "~" in s}
            measured=p.evaluate("rows.map(({text,hz,snr})=>({text,hz,snr}))")
            for line in path.with_suffix(".txt").read_text().splitlines():
                if "~" not in line: continue
                meta,body=line.split("~",1)
                msg=re.split(r"\s{2,}",body.strip())[0]
                db,_,hz=meta.split()[1:4]
                matches=[r for r in measured if r["text"]==msg and abs(r["hz"]-int(hz))<=6]
                if len(matches)==1 and matches[0]["snr"] is not None:
                    snr_errors.append(matches[0]["snr"]-int(db))
            comparisons[path.stem]=dict(matched=len(got & reference),reference=len(reference),
                                        missing=sorted(reference-got),extra=sorted(got-reference))
        evidence["ft8_receive_comparison"]=comparisons
        evidence["ft8_reference_snr_db"]=dict(count=len(snr_errors),median_bias=statistics.median(snr_errors),
                                              median_absolute_error=statistics.median(map(abs,snr_errors)),
                                              worst_absolute_error=max(map(abs,snr_errors)))
        assert not errors, errors
        browser.close()
    (OUT / "panel-check.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument("--chrome",required=True)
    verify(parser.parse_args().chrome)
