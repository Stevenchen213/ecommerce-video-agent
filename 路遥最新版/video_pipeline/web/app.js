const logEl = document.getElementById("log");
const healthEl = document.getElementById("health");
const selectEl = document.getElementById("script-select");
const metaEl = document.getElementById("script-meta");
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
  ["btn-run", "btn-assemble", "btn-status", "btn-reload"].forEach((id) => {
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
    pathHint.textContent = currentScriptPath;
    await refreshScript();
  } else {
    metaEl.textContent = "未找到 examples 下的脚本";
  }
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
      <td><span class="tag ${shot.platform}">${shot.platform}</span></td>
      <td>${shot.duration_sec}s</td>
      <td>${shot.text || "—"}</td>
      <td><span class="tag ${inLib ? "ok" : "bad"}">${inLib ? "有" : "缺"}</span></td>
      <td><button class="btn tiny" data-retry="${shot.id}">重跑</button></td>
    `;
    shotBody.appendChild(tr);
  });

  shotBody.querySelectorAll("[data-retry]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (busy) return;
      const shotId = btn.getAttribute("data-retry");
      setBusy(true);
      try {
        log(`retry ${shotId} …`);
        const res = await api("/retry", {
          method: "POST",
          body: JSON.stringify({ script_path: currentScriptPath, shot_id: shotId }),
        });
        log(`retry ok → ${res.path}`);
        await refreshScript();
      } catch (e) {
        log(`retry 失败: ${e.message}`);
      } finally {
        setBusy(false);
      }
    });
  });

  missingList.innerHTML = "";
  if (!detail.missing?.length) {
    const li = document.createElement("li");
    li.textContent = "无缺镜";
    missingList.appendChild(li);
  } else {
    detail.missing.forEach((m) => {
      const li = document.createElement("li");
      li.textContent = `${m.shot_id} (${m.platform})`;
      missingList.appendChild(li);
    });
  }
}

async function refreshScript() {
  if (!currentScriptPath) return;
  const detail = await api(`/api/script?path=${encodeURIComponent(currentScriptPath)}`);
  metaEl.innerHTML = `<strong>${detail.title}</strong> · ${detail.shots?.length || 0} 镜 · ${
    detail.description || "无描述"
  }<br/><span class="hint">产品段：${
    (detail.product_segments || [])
      .map((s) => `${s.id}[${(s.shot_ids || []).join("→")}]`)
      .join(" · ") || "无"
  }</span>`;
  pathHint.textContent = currentScriptPath;
  renderShots(detail);
}

async function runPipeline(mode) {
  if (!currentScriptPath || busy) return;
  setBusy(true);
  try {
    log(`${mode} 开始…`);
    const endpoint = mode === "run" ? "/run" : "/assemble";
    const res = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ script_path: currentScriptPath, output: "final.mp4" }),
    });
    log(`${mode} 完成 · ${res.duration_sec?.toFixed?.(2) ?? res.duration_sec}s\n${res.output}`);
    outputBox.textContent = res.output;
    if (res.preview_url) {
      preview.src = res.preview_url + "?t=" + Date.now();
      preview.classList.add("show");
    }
    await refreshScript();
  } catch (e) {
    log(`${mode} 失败: ${e.message}`);
  } finally {
    setBusy(false);
  }
}

document.getElementById("btn-run").addEventListener("click", () => runPipeline("run"));
document.getElementById("btn-assemble").addEventListener("click", () => runPipeline("assemble"));
document.getElementById("btn-status").addEventListener("click", async () => {
  try {
    const st = await api("/status", {
      method: "POST",
      body: JSON.stringify({ script_path: currentScriptPath }),
    });
    log(`status library_ok=${st.library_ok} missing=${(st.missing || []).length}`);
    await refreshScript();
  } catch (e) {
    log(`status 失败: ${e.message}`);
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
    log("控制台已就绪");
  } catch (e) {
    log(`初始化失败: ${e.message}`);
  }
})();
