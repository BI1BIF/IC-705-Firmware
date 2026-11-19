const el = id => document.getElementById(id);
let lang = "zh", release, downloadUrl, state = "", failed = false;
try { if (localStorage.getItem("ic705-language") === "en") lang = "en"; } catch {}
const messages = {
  unsupported:["请使用支持本地解压的新版浏览器。","Use a current browser with gzip support."],
  loadError:["无法加载版本信息，请刷新页面。","Could not load the release. Refresh to retry."],
  wrongBase:["底包不匹配，请选择未修改的日版 1.40 DAT。","Select the unmodified Japanese 1.40 DAT."],
  badOutput:["补丁或输出校验失败，请刷新重试。","Verification failed. Refresh and retry."],
  checking:["正在校验原厂文件…","Checking the original firmware…"],
  building:["正在生成并校验固件…","Building and verifying firmware…"],
  ready:["校验通过，文件已可下载。","Firmware verified and ready to download."],
  retry:["转换失败，请检查网络后重试。","Build failed. Check your connection and retry."]
};
const translated = document.querySelectorAll("[data-en]");
for (const node of translated) node.dataset.zh = node.textContent;
function setState(key) {
  state = key;
  el("status").textContent = key ? messages[key][lang === "en" ? 1 : 0] : "";
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
  el("version").textContent = release?.version || (failed ? (lang === "en" ? "Unavailable" : "不可用") : "…");
  if (!release?.notes) return;
  el("features").replaceChildren(...release.notes.features[lang].map(line => node("li", line)));
  el("history").replaceChildren(...release.notes.history.map((row, index) => {
    const entry = document.createElement("article");
    entry.className = "entry";
    entry.append(node("h3", row.version + (index ? "" : lang === "en" ? " · Latest" : " · 最新版")), node("p", row[lang]));
    return entry;
  }));
}
for (const code of ["zh","en"]) el(code).onclick = () => {
  lang = code;
  try { localStorage.setItem("ic705-language", code); } catch {}
  render();
};
render();

const source = el("source"), build = el("build"), save = el("save");

async function get(path) {
  const response = await fetch(path, {cache: "no-store", credentials: "omit"});
  if (!response.ok) throw new Error("loadError");
  return response;
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

source.onchange = () => {
  clearDownload();
  filename();
  setState("");
  build.disabled = !source.files.length;
};

build.onclick = async () => {
  const file = source.files[0];
  if (!file) return;
  clearDownload();
  source.disabled = build.disabled = true;
  try {
    setState("checking");
    if (file.size !== release.size) throw new Error("wrongBase");
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (await sha256(bytes) !== release.stock) throw new Error("wrongBase");
    setState("building");
    const packed = await (await get("converter/" + release.patch)).arrayBuffer();
    if (await sha256(packed) !== release.patchHash) throw new Error("badOutput");
    const stream = new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));
    const delta = new Uint8Array(await new Response(stream).arrayBuffer());
    if (delta.length !== bytes.length) throw new Error("badOutput");
    for (let i = 0; i < bytes.length; i++) bytes[i] ^= delta[i];
    if (await sha256(bytes) !== release.target) throw new Error("badOutput");
    downloadUrl = URL.createObjectURL(new Blob([bytes], {type: "application/octet-stream"}));
    save.href = downloadUrl;
    save.hidden = false;
    save.click();
    setState("ready");
  } catch (error) {
    setState(["wrongBase","badOutput","loadError"].includes(error.message) ? error.message : "retry");
  } finally {
    source.disabled = build.disabled = false;
  }
};

try {
  if (!globalThis.DecompressionStream || !globalThis.crypto?.subtle) throw new Error("unsupported");
  release = await (await get("converter/latest.json")).json();
  if (![release.stock, release.target, release.patchHash].every(s => /^[0-9a-f]{64}$/.test(s)) ||
      release.patch !== release.patchHash + ".xor.gz" || !Number.isSafeInteger(release.size) ||
      release.size <= 0 || !release.version) throw new Error("loadError");
  render();
  source.disabled = false;
} catch (error) {
  release = null;
  failed = true;
  setState(error.message === "unsupported" ? "unsupported" : "loadError");
  render();
}
