// Usage: node tools/verify_705_e140_converter.cjs <verified DAT directory> [page URL]
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright-core");

async function main() {
  const root = path.resolve(__dirname, "..");
  assert(process.argv[2], "Supply the directory containing both verified DAT files");
  const trial = path.resolve(process.argv[2]);
  const site = path.join(root, "docs");
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    const file = path.resolve(site, "." + (url.pathname === "/" ? "/index.html" : url.pathname));
    if (!file.startsWith(site + path.sep) || !fs.statSync(file, {throwIfNoEntry: false})?.isFile()) {
      res.writeHead(404).end();
      return;
    }
    const types = {".js":"text/javascript", ".css":"text/css", ".html":"text/html; charset=utf-8"};
    res.writeHead(200, {"Content-Type": types[path.extname(file)] || "application/octet-stream"});
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve => server.listen(0,"127.0.0.1",resolve));
  let browser;
  try {
    browser = await chromium.launch({channel:"chrome", headless:true});
    const page = await browser.newPage({acceptDownloads:true});
    const url = process.argv[3] || "http://127.0.0.1:" + server.address().port;
    await page.goto(url);
    const input = page.locator("#source");
    await page.waitForFunction(() => !document.querySelector("#source").disabled);
    const manifest = name => JSON.parse(fs.readFileSync(path.join(site, "converter", name), "utf8"));
    const {history, features} = manifest("release-notes.json");
    const digest = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
    const cardPath = path.join(site, "converter", "digital-voice-sd.zip");
    const digitalCard = fs.existsSync(cardPath) ? fs.readFileSync(cardPath) : null;
    const preview = process.env.IC705_PREVIEW_DIR;
    if (preview) fs.mkdirSync(preview, {recursive: true});
    const demoAssets = {};
    let cardHash;
    assert.equal(await page.locator("#version").innerText(), history[0].version);
    for (const language of ["en", "zh"]) {
      await page.locator("#" + language).click();
      const dates = await page.locator("#history h3 time").evaluateAll(nodes =>
        nodes.map(node => [node.dateTime, node.textContent]));
      assert.deepEqual(dates, history.map(row => [row.date, row.date]));
      const headings = await page.locator("#history h3").allTextContents();
      assert.deepEqual(headings, history.map((row, i) => [row.date, row.version, row.regions.join(" / "),
        ...(i ? [] : [language === "en" ? "Latest" : "最新版"])].join(" · ")));
      assert.deepEqual(await page.locator("#features li").allTextContents(), features[language]);
      assert((await page.locator("#history article").first().innerText()).includes(history[0][language]));
      if (digitalCard) {
        const playName = language === "en" ? "Play preview" : "播放预览";
        assert(await page.getByRole("button", {name: playName}).isVisible());
        const heading = language === "en" ? "Digital voice SD files" : "数字语音 SD 卡文件";
        assert.equal(await page.locator("#digital-card-heading").innerText(), heading);
        assert.equal(await page.locator("#install-title").innerText(),
          language === "en" ? "Install on your IC-705" : "在 IC-705 上安装");
        assert.equal(await page.locator("#install ol > li").count(), 4);
        assert.deepEqual(await page.locator("#install .install-paths code").allTextContents(),
          ["IC-705/705J140.dat", "IC-705/705E140.dat", "IC-705/DMRRX.BIN"]);
        assert((await page.locator("#install").innerText()).includes("MENU → SD CARD → Firmware Update"));
        assert((await page.locator("#install ol > li").last().innerText()).includes("DMR"));
      }
    }
    if (digitalCard) {
      const picker = page.locator("#demo-kind");
      const screen = page.locator("#demo-screen");
      const play = page.getByRole("button", {name: "播放预览"});
      const stop = page.getByRole("button", {name: "停止预览"});
      assert.equal(await picker.inputValue(), "digital");
      for (const [kind, asset] of Object.entries({
        digital: "digital-voice-v160", ftx: "ftx-v160", aprs: "aprs-v160", radio: "radio-v160",
      })) {
        await picker.selectOption(kind);
        const cover = "images/" + asset + "-cover.png";
        const gif = "images/" + asset + ".gif";
        assert.equal(await screen.getAttribute("src"), cover);
        assert(await page.locator("#" + kind + "-steps").isVisible());
        await page.waitForFunction(() => document.querySelector("#demo-screen").complete
          && document.querySelector("#demo-screen").naturalWidth === 480
          && document.querySelector("#demo-screen").naturalHeight === 272);
        if (kind === "digital" && preview) {
          await page.locator(".walkthrough").screenshot({path: path.join(preview, "demo-preview.png")});
        }
        if (kind === "ftx" && preview) {
          await page.locator(".walkthrough").screenshot({path: path.join(preview, "ftx-v2-web-preview.png")});
        }
        await play.press("Enter");
        await stop.waitFor();
        assert.equal(await screen.getAttribute("src"), gif);
        await page.waitForFunction(() => document.querySelector("#demo-screen").complete
          && document.querySelector("#demo-screen").naturalWidth === 480
          && document.querySelector("#demo-screen").naturalHeight === 272);
        demoAssets[kind] = gif;
        await stop.click();
        assert.equal(await screen.getAttribute("src"), cover);
        await play.waitFor();
      }
      await picker.selectOption("digital");
      await page.getByRole("link", {name: "安装说明与 SD 卡文件"}).click();
      assert.equal(new URL(page.url()).hash, "#install");
      await page.getByRole("link", {name: "查看更新日志"}).click();
      assert.equal(new URL(page.url()).hash, "#release-history");
      const [cardDownload] = await Promise.all([
        page.waitForEvent("download"), page.locator("#digital-card").click(),
      ]);
      assert.equal(cardDownload.suggestedFilename(), "digital-voice-sd.zip");
      const downloadedCard = fs.readFileSync(await cardDownload.path());
      assert(downloadedCard.equals(digitalCard));
      cardHash = digest(downloadedCard);

      if (preview) {
        await page.locator("#install").screenshot({path: path.join(preview, "install-preview.png")});
      }
      await page.setViewportSize({width: 360, height: 800});
      for (const language of ["en", "zh"]) {
        await page.locator("#" + language).click();
        assert(await page.evaluate(() => document.documentElement.scrollWidth === window.innerWidth));
        assert(await page.locator("#digital-card").isVisible());
        const playName = language === "en" ? "Play preview" : "播放预览";
        assert(await page.getByRole("button", {name: playName}).isVisible());
      }
      if (preview) {
        await page.locator("#install").screenshot({path: path.join(preview, "install-mobile.png")});
      }
      await page.setViewportSize({width: 1280, height: 720});
    }
    const stock = fs.readFileSync(path.join(root,"firmware","705E140.dat"));
    const damaged = Buffer.from(stock);
    damaged[400] ^= 1;
    const set = (name,buffer) => input.setInputFiles({name,mimeType:"application/octet-stream",buffer});
    async function rejected(name, data) {
      await set(name,data);
      await page.getByRole("status").filter({hasText:"底包不匹配"}).waitFor();
      assert(await page.locator("#build").isDisabled() && await page.locator("#save").isHidden());
    }
    const japanese = fs.readFileSync(path.join(root,"firmware","705J140.dat"));
    const damagedJ = Buffer.from(japanese);
    damagedJ[42] ^= 1;
    await rejected("705J140.dat",damagedJ);
    await set("705E140.dat",japanese);
    const [japanOutput] = await Promise.all([page.waitForEvent("download"),page.locator("#build").click()]);
    assert.equal(japanOutput.suggestedFilename(),"705J140.dat");
    const downloadedJ = fs.readFileSync(await japanOutput.path());
    assert(downloadedJ.equals(fs.readFileSync(path.join(trial,"705J140.dat"))));
    assert.equal(await page.locator("#version").innerText(), `${manifest("latest.json").version} · J140`);
    assert.equal(await page.locator("#output-path").innerText(),"IC-705/705J140.dat");

    await rejected("705E140.dat",damaged);
    await set("renamed.dat",stock);
    const [download] = await Promise.all([page.waitForEvent("download"),page.locator("#build").click()]);
    assert.equal(download.suggestedFilename(),"705E140.dat");
    await page.locator("#en").click();
    assert.equal(await page.locator("#save").getAttribute("download"),"705E140.dat");
    assert.equal(await page.locator("#output-path").innerText(),"IC-705/705E140.dat");
    assert.equal(await page.locator("#version").innerText(), `${manifest("e140.json").version} · E140`);
    await page.locator("#zh").click();

    const downloaded = fs.readFileSync(await download.path());
    assert(downloaded.equals(fs.readFileSync(path.join(trial,"705E140.dat"))));
    await rejected("705E140.dat",damaged);
    assert.equal(await page.locator("#save").getAttribute("href"),null);
    console.log(JSON.stringify({url,version:history[0].version,J140:digest(downloadedJ),E140:digest(downloaded),
      digitalVoiceSd:cardHash,demoAssets}));
  } finally {
    if (browser) await browser.close();
    server.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
