const el = id => document.getElementById(id);
const source = el("source"), build = el("build"), save = el("save"), status = el("status");
const unsupported = "请使用支持本地解压的新版浏览器。 · Please use a current browser with gzip support.";
const loadError = "无法加载版本信息，请刷新页面。 · Could not load release information. Refresh to retry.";
const wrongBase = "底包不匹配，请选择未经修改的日版 1.40 DAT。 · Select the unmodified Japanese 1.40 DAT.";
const badOutput = "补丁或输出校验失败。请刷新重试。 · Verification failed. Refresh and try again.";
let release, downloadUrl;

async function get(path) {
  const response = await fetch(path, {cache: "no-store", credentials: "omit"});
  if (!response.ok) throw new Error(loadError);
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
  status.textContent = "";
  build.disabled = !source.files.length;
};

build.onclick = async () => {
  const file = source.files[0];
  if (!file) return;
  clearDownload();
  source.disabled = build.disabled = true;
  try {
    status.textContent = "正在校验原厂文件… · Checking original firmware…";
    if (file.size !== release.size) throw new Error(wrongBase);
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (await sha256(bytes) !== release.stock) throw new Error(wrongBase);
    status.textContent = "正在生成并校验固件… · Building and verifying firmware…";
    const packed = await (await get("converter/" + release.patch)).arrayBuffer();
    if (await sha256(packed) !== release.patchHash) throw new Error(badOutput);
    const stream = new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip"));
    const delta = new Uint8Array(await new Response(stream).arrayBuffer());
    if (delta.length !== bytes.length) throw new Error(badOutput);
    for (let i = 0; i < bytes.length; i++) bytes[i] ^= delta[i];
    if (await sha256(bytes) !== release.target) throw new Error(badOutput);
    downloadUrl = URL.createObjectURL(new Blob([bytes], {type: "application/octet-stream"}));
    save.href = downloadUrl;
    save.hidden = false;
    save.click();
    status.textContent = "校验通过，文件已可下载。 · Firmware verified and ready to download.";
  } catch (error) {
    status.textContent = [wrongBase, badOutput, loadError].includes(error.message) ? error.message :
      "转换失败，请检查网络后重试。 · Could not complete the build. Check your connection and retry.";
  } finally {
    source.disabled = build.disabled = false;
  }
};

try {
  if (!globalThis.DecompressionStream || !globalThis.crypto?.subtle) throw new Error(unsupported);
  release = await (await get("converter/latest.json")).json();
  if (![release.stock, release.target, release.patchHash].every(s => /^[0-9a-f]{64}$/.test(s)) ||
      release.patch !== release.patchHash + ".xor.gz" || !Number.isSafeInteger(release.size) ||
      release.size <= 0 || !release.version) throw new Error(loadError);
  el("version").textContent = release.version;
  source.disabled = false;
} catch (error) {
  el("version").textContent = "不可用 · Unavailable";
  status.textContent = error.message === unsupported ? unsupported : loadError;
}
