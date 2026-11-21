// Run against the dual-region converter using the project's Playwright installation.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright-core");

async function main() {
  const root = path.resolve(__dirname, "..");
  const trial = path.join(root, ".analysis", "sstv-refresh-tx2j1");
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
    const url = process.argv[2] || "http://127.0.0.1:" + server.address().port;
    await page.goto(url);
    const input = page.locator("#source");
    await page.waitForFunction(() => !document.querySelector("#source").disabled);
    const history = JSON.parse(fs.readFileSync(path.join(site, "converter", "release-notes.json"), "utf8")).history;
    assert.equal(await page.locator("#version").innerText(), "v1.3.2");
    for (const language of ["en", "zh"]) {
      await page.locator("#" + language).click();
      const dates = await page.locator("#history h3 time").evaluateAll(nodes =>
        nodes.map(node => [node.dateTime, node.textContent]));
      assert.deepEqual(dates, history.map(row => [row.date, row.date]));
      const headings = await page.locator("#history h3").allTextContents();
      assert.deepEqual(headings, history.map((row, i) => [row.date, row.version, row.regions.join(" / "),
        ...(i ? [] : [language === "en" ? "Latest" : "最新版"])].join(" · ")));
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
    assert(fs.readFileSync(await japanOutput.path()).equals(fs.readFileSync(path.join(trial,"705J140.dat"))));
    assert.equal(await page.locator("#version").innerText(), "v1.3.2 · J140");
    assert.equal(await page.locator("#output-path").innerText(),"IC-705/705J140.dat");

    await rejected("705E140.dat",damaged);
    await set("renamed.dat",stock);
    const [download] = await Promise.all([page.waitForEvent("download"),page.locator("#build").click()]);
    assert.equal(download.suggestedFilename(),"705E140.dat");
    await page.locator("#en").click();
    assert.equal(await page.locator("#save").getAttribute("download"),"705E140.dat");
    assert.equal(await page.locator("#output-path").innerText(),"IC-705/705E140.dat");
    assert.equal(await page.locator("#version").innerText(), "v1.3.2 · E140");
    assert.match(await page.locator("#history article").first().innerText(),/hidden audio peak meter/);
    await page.locator("#zh").click();

    const dir = path.join(trial,"browser");
    fs.mkdirSync(dir,{recursive:true});
    const file = path.join(dir,download.suggestedFilename());
    await download.saveAs(file);
    const downloaded = fs.readFileSync(file);
    assert(downloaded.equals(fs.readFileSync(path.join(trial,"705E140.dat"))));
    await rejected("705E140.dat",damaged);
    assert.equal(await page.locator("#save").getAttribute("href"),null);
    console.log("J140 and E140 browser downloads verified",url,crypto.createHash("sha256").update(downloaded).digest("hex"));
  } finally {
    if (browser) await browser.close();
    server.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
