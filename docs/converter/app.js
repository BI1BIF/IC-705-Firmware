const el = id => document.getElementById(id);
let lang = "zh", release, downloadUrl, state = "", failed = false;
try { if (localStorage.getItem("ic705-language") === "en") lang = "en"; } catch {}
let received = 0, notes;
const releases = [];
const conversionPaused = Boolean(el("conversion-pause"));
const messages = {
  fetching:["正在下载转换补丁","Downloading the patch"],
  network:["补丁下载中断或服务器未响应。请检查网络，再点“转换并下载”重试。","The patch download stalled or failed. Check your connection, then select Build and download to retry."],
  unsupported:["请使用支持本地解压的新版浏览器。","Use a current browser with gzip support."],
  loadError:["无法加载版本信息，请刷新页面。","Could not load the release. Refresh to retry."],
  wrongBase:["底包不匹配。请选择 IC-705 原厂 1.40 的 705J140.dat 或 705E140.dat。","Choose the original IC-705 1.40 file, 705J140.dat or 705E140.dat."],
  badOutput:["补丁或输出校验失败，请刷新重试。","Verification failed. Refresh and retry."],
  checking:["正在校验原厂文件…","Checking the original firmware…"],
  readError:["无法读取文件，请重新选择原厂 DAT。","Could not read the file. Select the original DAT again."],
  building:["正在生成并校验固件…","Building and verifying firmware…"],
  ready:["固件已生成。如果下载未开始，请点下方按钮手动保存。若在微信内仍无法保存，请用系统浏览器打开此页并重新选择原厂 DAT。","Firmware is ready. If the download did not start, use the save button below. If saving fails in an in-app browser, reopen this page in your system browser and select the original DAT again."],
  retry:["转换失败，请检查网络后重试。","Build failed. Check your connection and retry."]
};
const translated = document.querySelectorAll("[data-en]");
for (const node of translated) node.dataset.zh = node.textContent;
function setState(key) {
  state = key;
  el("status").textContent = key ? messages[key][lang === "en" ? 1 : 0] : "";
  if (key === "fetching") el("status").textContent += " · " + (received / 1048576).toFixed(2) + " MiB";
}
function node(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text;
  return item;
}
function filename() {
  el("filename").textContent = el("source").files[0]?.name || (lang === "en" ? "No file selected" : "尚未选择文件");
}
function render() {
  document.documentElement.lang = lang === "en" ? lang : "zh-CN";
  for (const item of translated) item.textContent = item.dataset[lang];
  document.title = document.querySelector("h1").textContent;
  for (const code of ["zh","en"]) el(code).setAttribute("aria-pressed", String(code === lang));
  filename();
  setState(state);
  const sharedVersion = releases.length === 2 && releases[0].version === releases[1].version ? releases[0].version : "";
  const target = release ? release.version + " · " + release.region : sharedVersion;
  el("version").textContent = conversionPaused ? (lang === "en" ? "Conversion paused" : "转换已暂停") : failed ? (lang === "en" ? "Unavailable" : "不可用") :
    target || (lang === "en" ? "Select a file" : "请选择底包");
  const name = release?.filename;
  el("sd-path").hidden = !name;
  if (name) {
    el("save").download = name;
    el("save").textContent = lang === "en" ? "Save " + name + " ↓" : "手动保存 " + name + " ↓";
    el("output-path").textContent = "IC-705/" + name;
  }
  if (!notes) return;
  el("features").replaceChildren(...notes.features[lang].map(line => node("li", line)));
  el("history").replaceChildren(...notes.history.map((row, index) => {
    const entry = document.createElement("article");
    entry.className = "entry";
    const title = node("h3", row.version + " · " + row.regions.join(" / ") + (index ? "" : lang === "en" ? " · Latest" : " · 最新版"));
    if (row.date) {
      const date = node("time", row.date);
      date.dateTime = row.date;
      title.prepend(date, " · ");
    }
    entry.append(title, ...row[lang].split("\n\n").map(paragraph => node("p", paragraph)));
    return entry;
  }));
}
for (const code of ["zh","en"]) el(code).onclick = () => {
  lang = code;
  try { localStorage.setItem("ic705-language", code); } catch {}
  render();
};
render();

const demos = {digital: "digital-voice-v160", ftx: "ftx-v160", aprs: "aprs-v160", radio: "radio-v160"};
const demoToggle = el("demo-toggle");
function showDemo(play) {
  const kind = el("demo-kind").value;
  demoToggle.dataset.playing = String(play);
  demoToggle.setAttribute("aria-describedby", kind + "-steps");
  el("demo-play").hidden = play;
  el("demo-stop").hidden = !play;
  for (const demo of Object.keys(demos)) el(demo + "-steps").hidden = demo !== kind;
  el("demo-screen").src = "images/" + demos[kind] + (play ? ".gif" : "-cover.png");
}
demoToggle.onclick = () => showDemo(demoToggle.dataset.playing !== "true");
el("demo-kind").onchange = () => showDemo(false);
showDemo(false);

const source = el("source"), build = el("build"), save = el("save");

async function get(path) {
  const response = await fetch(path, {cache: "no-store", credentials: "omit"});
  if (!response.ok) throw new Error("loadError");
  return response;
}

async function downloadPatch(path) {
  const controller = new AbortController();
  let timer;
  function watch() {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(), 45000);
  }
  received = 0;
  setState("fetching");
  watch();
  try {
    // The patch filename is its content hash, so a cached copy is reusable.
    const response = await fetch(path, {signal: controller.signal, credentials: "omit"});
    if (!response.ok) throw new Error("network");
    const reader = response.body.getReader();
    const chunks = [];
    let lastUpdate = 0;
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.byteLength;
      watch();
      if (performance.now() - lastUpdate >= 150) {
        setState("fetching");
        lastUpdate = performance.now();
      }
    }
    return await new Blob(chunks).arrayBuffer();
  } catch {
    throw new Error("network");
  } finally {
    clearTimeout(timer);
  }
}

async function sha256(bytes) {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
}

function clearDownload() {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = null;
  save.hidden = true;
  save.removeAttribute("href");
}

source.onchange = async () => {
  if (conversionPaused) return;
  clearDownload();
  release = null;
  build.disabled = true;
  setState("");
  render();
  const file = source.files[0];
  if (!file) return;
  if (!releases.some(r => r.size === file.size)) return setState("wrongBase");
  setState("checking");
  try {
    const hash = await sha256(await file.arrayBuffer());
    if (file !== source.files[0]) return;
    release = releases.find(r => r.stock === hash && r.size === file.size);
    build.disabled = !release;
    setState(release ? "" : "wrongBase");
    render();
  } catch {
    if (file === source.files[0]) setState("readError");
  }
};

build.onclick = async () => {
  const file = source.files[0];
  if (conversionPaused || !file || !release) return;
  clearDownload();
  source.disabled = build.disabled = true;
  try {
    setState("checking");
    if (file.size !== release.size) throw new Error("wrongBase");
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (await sha256(bytes) !== release.stock) throw new Error("wrongBase");
    const packed = await downloadPatch("converter/" + release.patch);
    setState("building");
    if (await sha256(packed) !== release.patchHash) throw new Error("badOutput");
    const stream = new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));
    const delta = new Uint8Array(await new Response(stream).arrayBuffer());
    if (delta.length !== bytes.length) throw new Error("badOutput");
    for (let i = 0; i < bytes.length; i++) bytes[i] ^= delta[i];
    if (await sha256(bytes) !== release.target) throw new Error("badOutput");
    downloadUrl = URL.createObjectURL(new Blob([bytes], {type: "application/octet-stream"}));
    save.href = downloadUrl;
    save.hidden = false;
    setState("ready");
    save.click();
  } catch (error) {
    setState(["wrongBase","badOutput","loadError","network"].includes(error.message) ? error.message : "retry");
  } finally {
    source.disabled = build.disabled = false;
  }
};

async function loadReleases() {
  if (!globalThis.DecompressionStream || !globalThis.crypto?.subtle) throw new Error("unsupported");
  for (const [manifest, region] of [["latest.json", "J140"], ["e140.json", "E140"]]) {
    const item = await (await get("converter/" + manifest)).json();
    if (![item.stock, item.target, item.patchHash].every(s => /^[0-9a-f]{64}$/.test(s)) ||
        item.patch !== item.patchHash + ".xor.gz" || !Number.isSafeInteger(item.size) ||
        item.size <= 0 || !item.version) throw new Error("loadError");
    releases.push({...item, region, filename: "705" + region + ".dat"});
  }
  source.disabled = false;
}

try {
  notes = await (await get("converter/release-notes.json")).json();
  if (!conversionPaused) await loadReleases();
  render();
} catch (error) {
  release = null;
  failed = true;
  setState(error.message === "unsupported" ? "unsupported" : "loadError");
  render();
}
