const state = {
  scriptPath: "",
  script: null,
  batchId: null,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);

function log(el, msg) {
  const ts = new Date().toLocaleTimeString();
  el.textContent = `[${ts}] ${msg}\n` + el.textContent;
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
  if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
  return data;
}

/* tabs */
document.querySelectorAll("#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "library") refreshLibrary();
    if (btn.dataset.tab === "assemble") refreshOutputs();
    if (btn.dataset.tab === "settings") loadSettings();
    if (btn.dataset.tab === "queue" && state.batchId) pollBatch();
  });
});

async function checkHealth() {
  try {
    await api("/health");
    $("health").textContent = "API · ONLINE";
    $("health").style.color = "#0a7a3e";
  } catch {
    $("health").textContent = "API · OFFLINE";
    $("health").style.color = "#b00020";
  }
}

/* script editor */
function shotRow(shot, index) {
  const tr = document.createElement("tr");
  tr.dataset.index = String(index);
  tr.innerHTML = `
    <td>
      <button class="btn tiny" data-up type="button">↑</button>
      <button class="btn tiny" data-down type="button">↓</button>
    </td>
    <td><input data-k="id" value="${esc(shot.id)}" /></td>
    <td><input data-k="role" value="${esc(shot.role)}" /></td>
    <td>
      <select data-k="platform">
        <option value="feiying" ${shot.platform === "feiying" ? "selected" : ""}>feiying</option>
        <option value="chanjing" ${shot.platform === "chanjing" ? "selected" : ""}>chanjing</option>
      </select>
    </td>
    <td><input data-k="duration_sec" type="number" min="0.5" step="0.5" value="${shot.duration_sec}" style="width:70px" /></td>
    <td><input data-k="text" value="${esc(shot.text || "")}" /></td>
    <td><input data-k="person_id" value="${esc(shot.person_id || "")}" /></td>
    <td><input data-k="voice_id" value="${esc(shot.voice_id || "")}" /></td>
    <td><button class="btn tiny" data-del type="button">删</button></td>
  `;
  return tr;
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;");
}

function readEditorShots() {
  const shots = [];
  $("editor-body").querySelectorAll("tr").forEach((tr) => {
    const get = (k) => tr.querySelector(`[data-k="${k}"]`)?.value ?? "";
    shots.push({
      id: get("id").trim(),
      role: get("role").trim() || "shot",
      platform: get("platform"),
      duration_sec: Number(get("duration_sec") || 3),
      text: get("text"),
      person_id: get("person_id") || null,
      voice_id: get("voice_id") || null,
      transition_in: "cut",
      fade_duration_sec: 0.35,
      notes: "",
      extra: {},
    });
  });
  return shots;
}

function currentScriptPayload() {
  return {
    title: $("script-title").value.trim() || "untitled",
    description: $("script-desc").value.trim(),
    brand_name: $("script-brand").value.trim() || null,
    default_transition: "cut",
    shots: readEditorShots(),
  };
}

function renderEditor(detail) {
  state.scriptPath = detail.path;
  state.script = detail;
  $("path-hint").textContent = detail.path || "";
  $("script-title").value = detail.title || "";
  $("script-desc").value = detail.description || "";
  $("script-brand").value = detail.brand_name || "";
  $("editor-body").innerHTML = "";
  (detail.shots || []).forEach((shot, i) => {
    $("editor-body").appendChild(shotRow(shot, i));
  });
  bindEditorButtons();
  $("yaml-preview").textContent = JSON.stringify(currentScriptPayload(), null, 2);
  renderMissing(detail.missing || []);
}

function bindEditorButtons() {
  $("editor-body").querySelectorAll("tr").forEach((tr) => {
    tr.querySelector("[data-del]")?.addEventListener("click", () => {
      tr.remove();
      $("yaml-preview").textContent = JSON.stringify(currentScriptPayload(), null, 2);
    });
    tr.querySelector("[data-up]")?.addEventListener("click", () => {
      const prev = tr.previousElementSibling;
      if (prev) tr.parentNode.insertBefore(tr, prev);
    });
    tr.querySelector("[data-down]")?.addEventListener("click", () => {
      const next = tr.nextElementSibling;
      if (next) tr.parentNode.insertBefore(next, tr);
    });
    tr.querySelectorAll("input,select").forEach((el) => {
      el.addEventListener("input", () => {
        $("yaml-preview").textContent = JSON.stringify(currentScriptPayload(), null, 2);
      });
    });
  });
}

function renderMissing(missing) {
  $("missing-list").innerHTML = "";
  if (!missing.length) {
    $("missing-list").innerHTML = "<li>无缺镜</li>";
    return;
  }
  missing.forEach((m) => {
    const li = document.createElement("li");
    li.innerHTML = `<code>${m.shot_id}</code> · ${m.platform}`;
    $("missing-list").appendChild(li);
  });
}

async function loadScripts() {
  const data = await api("/api/scripts");
  $("script-select").innerHTML = "";
  for (const item of data.scripts || []) {
    const opt = document.createElement("option");
    opt.value = item.path;
    opt.textContent = item.name;
    $("script-select").appendChild(opt);
  }
  if (data.scripts?.length) {
    $("script-select").value = data.scripts[0].path;
    await loadScriptDetail(data.scripts[0].path);
  }
}

async function loadScriptDetail(path) {
  const detail = await api(`/api/script?path=${encodeURIComponent(path)}`);
  renderEditor(detail);
}

$("script-select").addEventListener("change", () => loadScriptDetail($("script-select").value));
$("btn-reload").addEventListener("click", () => state.scriptPath && loadScriptDetail(state.scriptPath));
$("btn-add-shot").addEventListener("click", () => {
  const n = $("editor-body").children.length + 1;
  $("editor-body").appendChild(
    shotRow(
      {
        id: `shot_${n}`,
        role: "product",
        platform: "chanjing",
        duration_sec: 3,
        text: "",
        person_id: "",
        voice_id: "",
      },
      n - 1
    )
  );
  bindEditorButtons();
});

$("btn-save-script").addEventListener("click", async () => {
  try {
    const detail = await api("/api/script/save", {
      method: "POST",
      body: JSON.stringify({ path: state.scriptPath || null, script: currentScriptPayload() }),
    });
    renderEditor(detail);
    log($("assemble-log"), `脚本已保存 → ${detail.path}`);
    await loadScripts();
    $("script-select").value = detail.path;
  } catch (e) {
    alert("保存失败: " + e.message);
  }
});

$("btn-upload-script").addEventListener("click", () => $("script-file").click());
$("script-file").addEventListener("change", async () => {
  const file = $("script-file").files?.[0];
  if (!file) return;
  try {
    const content = await file.text();
    const detail = await api("/api/script/upload", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, content }),
    });
    await loadScripts();
    $("script-select").value = detail.path;
    renderEditor(detail);
    log(
      $("assemble-log"),
      `已上传脚本（${detail.imported_as || "yaml"}）→ ${detail.path}`
    );
    alert(`已上传并载入：${file.name}`);
  } catch (e) {
    alert("上传失败: " + e.message);
  } finally {
    $("script-file").value = "";
  }
});

$("btn-import-luyao").addEventListener("click", () => $("luyao-file").click());
$("luyao-file").addEventListener("change", async () => {
  const file = $("luyao-file").files?.[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const detail = await api("/api/script/import-luyao", {
      method: "POST",
      body: JSON.stringify({ data, filename: file.name.replace(/\.json$/i, "") + ".yaml" }),
    });
    await loadScripts();
    $("script-select").value = detail.path;
    renderEditor(detail);
    alert("已导入并保存为 " + detail.path);
  } catch (e) {
    alert("导入失败: " + e.message);
  } finally {
    $("luyao-file").value = "";
  }
});

$("btn-estimate").addEventListener("click", async () => {
  if (!state.scriptPath) return;
  try {
    const c = await api(`/api/estimate?path=${encodeURIComponent(state.scriptPath)}`);
    $("estimate-box").textContent = `飞影约 ${c.feiying_points_est} 积分（${c.feiying_seconds}s）· 蝉镜 ${c.chanjing_shots} 镜 · mock=${c.use_mock}`;
  } catch (e) {
    $("estimate-box").textContent = e.message;
  }
});

/* generate queue */
$("btn-generate").addEventListener("click", async () => {
  if (!state.scriptPath) return alert("先选脚本");
  // 先保存编辑器内容
  try {
    const saved = await api("/api/script/save", {
      method: "POST",
      body: JSON.stringify({ path: state.scriptPath, script: currentScriptPayload() }),
    });
    state.scriptPath = saved.path;
  } catch (e) {
    return alert("保存脚本失败: " + e.message);
  }
  const platforms = [];
  if ($("gen-feiying").checked) platforms.push("feiying");
  if ($("gen-chanjing").checked) platforms.push("chanjing");
  try {
    const detail = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        script_path: state.scriptPath,
        only_missing: $("only-missing").checked,
        dry_run: $("dry-run").checked,
        platforms,
      }),
    });
    state.batchId = detail.batch.batch_id;
    log($("queue-log"), `batch=${state.batchId} 任务数=${detail.shots.length}`);
    document.querySelector('[data-tab="queue"]').click();
    startPolling();
  } catch (e) {
    log($("queue-log"), "生成失败: " + e.message);
  }
});

function renderQueue(detail) {
  const fill = (idBar, idSum, idList, agg, shots, plat) => {
    $(idBar).style.width = `${Math.round((agg.progress || 0) * 100)}%`;
    $(idSum).textContent = `总${agg.total} · 完成${agg.done} · 失败${agg.failed} · 进行中${agg.running} · ${Math.round(
      (agg.progress || 0) * 100
    )}%`;
    $(idList).innerHTML = "";
    shots
      .filter((s) => s.platform === plat)
      .forEach((s) => {
        const li = document.createElement("li");
        li.textContent = `${s.shot_id} · ${s.status} · ${Math.round((s.progress || 0) * 100)}% ${s.message || ""} ${
          s.error ? "· " + s.error : ""
        }`;
        $(idList).appendChild(li);
      });
  };
  fill("bar-feiying", "sum-feiying", "list-feiying", detail.feiying || {}, detail.shots || [], "feiying");
  fill(
    "bar-chanjing",
    "sum-chanjing",
    "list-chanjing",
    detail.chanjing || {},
    detail.shots || [],
    "chanjing"
  );
}

async function pollBatch() {
  if (!state.batchId) return;
  try {
    const detail = await api(`/api/batches/${state.batchId}`);
    renderQueue(detail);
    const st = detail.batch?.status;
    if (["done", "failed", "partial", "cancelled"].includes(st)) {
      stopPolling();
      log($("queue-log"), `batch 结束 status=${st}`);
      refreshLibrary();
      if (state.scriptPath) loadScriptDetail(state.scriptPath);
    }
  } catch (e) {
    log($("queue-log"), "轮询失败: " + e.message);
  }
}

function startPolling() {
  stopPolling();
  pollBatch();
  state.pollTimer = setInterval(pollBatch, 1200);
}

function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

/* library / assemble */
async function refreshLibrary() {
  const lib = await api("/api/library");
  const fill = (id, items) => {
    $(id).innerHTML = "";
    if (!items.length) {
      $(id).innerHTML = "<li>空</li>";
      return;
    }
    items.forEach((it) => {
      const li = document.createElement("li");
      li.textContent = `${it.shot_id} · ${it.size_mb}MB`;
      $(id).appendChild(li);
    });
  };
  fill("lib-feiying", lib.feiying || []);
  fill("lib-chanjing", lib.chanjing || []);
  if (state.scriptPath) {
    const detail = await api(`/api/script?path=${encodeURIComponent(state.scriptPath)}`);
    renderMissing(detail.missing || []);
  }
}

async function refreshOutputs() {
  const data = await api("/api/outputs");
  $("output-list").innerHTML = "";
  (data.outputs || []).forEach((o) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = o.preview_url;
    a.textContent = `${o.name} (${o.size_mb}MB)`;
    a.addEventListener("click", (e) => {
      e.preventDefault();
      $("output-box").textContent = o.path;
      $("preview").src = o.preview_url + "?t=" + Date.now();
      $("preview").classList.add("show");
    });
    li.appendChild(a);
    $("output-list").appendChild(li);
  });
}

$("btn-lib-refresh").addEventListener("click", refreshLibrary);

$("btn-validate").addEventListener("click", async () => {
  if (!state.scriptPath) return;
  try {
    await api("/api/script/save", {
      method: "POST",
      body: JSON.stringify({ path: state.scriptPath, script: currentScriptPayload() }),
    });
    const res = await api("/validate", {
      method: "POST",
      body: JSON.stringify({ script_path: state.scriptPath }),
    });
    log(
      $("assemble-log"),
      `validate library_ok=${res.library_ok} missing=${res.missing.length} cost≈${res.cost?.feiying_points_est}`
    );
    renderMissing(res.missing || []);
  } catch (e) {
    log($("assemble-log"), "validate 失败: " + e.message);
  }
});

$("btn-assemble").addEventListener("click", async () => {
  if (!state.scriptPath) return;
  try {
    await api("/api/script/save", {
      method: "POST",
      body: JSON.stringify({ path: state.scriptPath, script: currentScriptPayload() }),
    });
    log($("assemble-log"), "assemble 开始…");
    const res = await api("/assemble", {
      method: "POST",
      body: JSON.stringify({ script_path: state.scriptPath, output: `final_${Date.now()}.mp4` }),
    });
    log($("assemble-log"), `完成 ${res.duration_sec?.toFixed?.(2) ?? res.duration_sec}s\n${res.output}`);
    $("output-box").textContent = res.output;
    if (res.preview_url) {
      $("preview").src = res.preview_url + "?t=" + Date.now();
      $("preview").classList.add("show");
    }
    refreshOutputs();
  } catch (e) {
    log($("assemble-log"), "assemble 失败: " + e.message);
  }
});

/* settings */
async function loadSettings() {
  const s = await api("/api/settings");
  $("use-mock").checked = !!s.use_mock;
  $("fy-base").value = s.feiying_api_base || "";
  $("fy-key").value = "";
  $("fy-key").placeholder = s.feiying_api_key_masked || "未配置";
  $("fy-person").value = s.feiying_default_person_id || "";
  $("fy-voice").value = s.feiying_default_voice_id || "";
  $("cj-base").value = s.chanjing_base_url || "";
  $("cj-app").value = s.chanjing_app_id || "";
  $("cj-secret").value = "";
  $("cj-secret").placeholder = s.chanjing_secret_key_masked || "未配置";
  $("cj-root").value = s.chanjing_root || "";
  $("cj-assets").value = s.chanjing_assets_dir || "";
  $("cj-model").value = s.chanjing_i2v_model || "";
}

$("btn-save-settings").addEventListener("click", async () => {
  const payload = {
    use_mock: $("use-mock").checked,
    feiying_api_base: $("fy-base").value.trim(),
    feiying_default_person_id: $("fy-person").value.trim(),
    feiying_default_voice_id: $("fy-voice").value.trim(),
    chanjing_base_url: $("cj-base").value.trim(),
    chanjing_app_id: $("cj-app").value.trim(),
    chanjing_root: $("cj-root").value.trim(),
    chanjing_assets_dir: $("cj-assets").value.trim(),
    chanjing_i2v_model: $("cj-model").value.trim(),
  };
  if ($("fy-key").value.trim()) payload.feiying_api_key = $("fy-key").value.trim();
  if ($("cj-secret").value.trim()) payload.chanjing_secret_key = $("cj-secret").value.trim();
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
    $("settings-hint").textContent = "已保存到本机 data/settings.json";
    loadSettings();
  } catch (e) {
    alert(e.message);
  }
});

$("btn-probe").addEventListener("click", async () => {
  try {
    const s = await api("/api/system");
    $("probe-log").textContent = JSON.stringify(s, null, 2);
  } catch (e) {
    $("probe-log").textContent = e.message;
  }
});

(async function init() {
  await checkHealth();
  try {
    await loadScripts();
    await loadSettings();
    log($("assemble-log"), "工作台 v0.2 就绪：脚本 / 双队列 / 素材库 / 组装 / 设置");
  } catch (e) {
    log($("assemble-log"), "初始化失败: " + e.message);
  }
})();
