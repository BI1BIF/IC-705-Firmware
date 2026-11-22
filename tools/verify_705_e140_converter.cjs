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
    const digest = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
    console.log(JSON.stringify({url,version:history[0].version,J140:digest(downloadedJ),E140:digest(downloaded)}));
  } finally {
    if (browser) await browser.close();
    server.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
