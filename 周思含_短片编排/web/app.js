const logEl = document.getElementById("log");
const healthEl = document.getElementById("health");
const selectEl = document.getElementById("script-select");
const metaEl = document.getElementById("script-meta");
const planBox = document.getElementById("plan-box");
const shotBody = document.getElementById("shot-body");
const missingList = document.getElementById("missing-list");
const outputBox = document.getElementById("output-box");
const preview = document.getElementById("preview");
const pathHint = document.getElementById("path-hint");

let currentScriptPath = "";
let busy = false;

function log(msg) {
  const ts = new Date().toLocaleTimeString();
  logEl.textContent = `[${ts}] ${msg}\n` + logEl.textContent;
}

function setBusy(v) {
  busy = v;
  ["btn-assemble", "btn-validate", "btn-reload"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = v;
  });
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    throw new Error(data.detail || data.message || res.statusText);
  }
  return data;
}

async function checkHealth() {
  try {
    await api("/health");
    healthEl.textContent = "API · ONLINE";
    healthEl.style.color = "#0a7a3e";
  } catch {
    healthEl.textContent = "API · OFFLINE";
    healthEl.style.color = "#b00020";
  }
}

function sourceLabel(platform) {
  if (platform === "feiying") return "陈·数字人";
  if (platform === "chanjing") return "路遥·产品短片";
  return platform;
}

function renderShots(detail) {
  const missing = new Set((detail.missing || []).map((m) => m.shot_id));
  shotBody.innerHTML = "";
  (detail.shots || []).forEach((shot, i) => {
    const tr = document.createElement("tr");
    const inLib = !missing.has(shot.id);
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td><code>${shot.id}</code></td>
      <td>${shot.role}</td>
      <td><span class="tag ${shot.platform}">${sourceLabel(shot.platform)}</span></td>
      <td>${shot.duration_sec}s</td>
      <td>${shot.text || "—"}</td>
      <td><span class="tag ${inLib ? "ok" : "bad"}">${inLib ? "有" : "缺"}</span></td>
    `;
    shotBody.appendChild(tr);
  });

  missingList.innerHTML = "";
  if (!detail.missing?.length) {
    const li = document.createElement("li");
    li.textContent = "无缺镜，可组装";
    missingList.appendChild(li);
  } else {
    detail.missing.forEach((m) => {
      const li = document.createElement("li");
      li.textContent = `${m.shot_id} ← ${sourceLabel(m.platform)}`;
      missingList.appendChild(li);
    });
  }

  const plan = detail.plan || {};
  const tl = (plan.timeline || [])
    .map((u) => `${u.kind === "feiying" ? "数" : "产"}:${u.shot_id}`)
    .join(" → ");
  planBox.innerHTML = `数字人 ${ (plan.feiying || []).length } 镜 · 产品短片 ${
    (plan.chanjing || []).length
  } 镜<br/>顺序：${tl || "—"}`;
}

async function refreshScript() {
  if (!currentScriptPath) return;
  const detail = await api(`/api/script?path=${encodeURIComponent(currentScriptPath)}`);
  metaEl.innerHTML = `<strong>${detail.title}</strong> · ${detail.shots?.length || 0} 镜 · ${
    detail.description || "无描述"
  }`;
  pathHint.textContent = currentScriptPath;
  renderShots(detail);
}

async function loadScripts() {
  const data = await api("/api/scripts");
  selectEl.innerHTML = "";
  for (const item of data.scripts || []) {
    const opt = document.createElement("option");
    opt.value = item.path;
    opt.textContent = item.name;
    selectEl.appendChild(opt);
  }
  if (data.scripts?.length) {
    currentScriptPath = data.scripts[0].path;
    selectEl.value = currentScriptPath;
    await refreshScript();
  } else {
    metaEl.textContent = "未找到 examples 下的脚本";
  }
}

document.getElementById("btn-assemble").addEventListener("click", async () => {
  if (!currentScriptPath || busy) return;
  setBusy(true);
  try {
    log("assemble 开始…");
    const res = await api("/assemble", {
      method: "POST",
      body: JSON.stringify({ script_path: currentScriptPath, output: "final.mp4" }),
    });
    log(`assemble 完成 · ${res.duration_sec?.toFixed?.(2) ?? res.duration_sec}s\n${res.output}`);
    outputBox.textContent = res.output;
    if (res.preview_url) {
      preview.src = res.preview_url + "?t=" + Date.now();
      preview.classList.add("show");
    }
    await refreshScript();
  } catch (e) {
    log(`assemble 失败: ${e.message}`);
  } finally {
    setBusy(false);
  }
});

document.getElementById("btn-validate").addEventListener("click", async () => {
  if (!currentScriptPath || busy) return;
  setBusy(true);
  try {
    const res = await api("/validate", {
      method: "POST",
      body: JSON.stringify({ script_path: currentScriptPath }),
    });
    log(
      `validate ok library_ok=${res.library_ok} missing=${(res.missing || []).length}`
    );
    await refreshScript();
  } catch (e) {
    log(`validate 失败: ${e.message}`);
  } finally {
    setBusy(false);
  }
});

document.getElementById("btn-reload").addEventListener("click", () => refreshScript());
selectEl.addEventListener("change", async () => {
  currentScriptPath = selectEl.value;
  await refreshScript();
});

(async function init() {
  await checkHealth();
  try {
    await loadScripts();
    log("短片编排工作台已就绪");
  } catch (e) {
    log(`初始化失败: ${e.message}`);
  }
})();
