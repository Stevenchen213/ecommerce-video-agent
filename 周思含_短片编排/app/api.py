"""短片编排成片台 · 后端 API。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.generators import estimate_cost, generate_shot_job, probe_connectivity
from app.jobs import (
    BatchJob,
    ShotJob,
    enqueue_shot,
    get_store,
    new_ids,
    register_handler,
)
from app.pipeline import Pipeline
from app.schema import Script, import_luyao_shots_json, load_script, save_script
from app.settings_store import load_app_settings, save_app_settings

WEB_DIR = load_settings().web_dir
EXAMPLES = load_settings().examples_dir

app = FastAPI(title="短片编排成片台", version="0.2.0")

register_handler("feiying", generate_shot_job)
register_handler("chanjing", generate_shot_job)


class AssembleRequest(BaseModel):
    script_path: str
    output: str = "final.mp4"


class ValidateRequest(BaseModel):
    script_path: str


class SaveScriptRequest(BaseModel):
    path: str | None = None
    filename: str | None = None
    script: dict[str, Any]


class GenerateBatchRequest(BaseModel):
    script_path: str
    only_missing: bool = True
    dry_run: bool = False
    platforms: list[str] = Field(default_factory=lambda: ["feiying", "chanjing"])


class SettingsUpdate(BaseModel):
    use_mock: bool | None = None
    feiying_api_base: str | None = None
    feiying_api_key: str | None = None
    feiying_default_person_id: str | None = None
    feiying_default_voice_id: str | None = None
    chanjing_base_url: str | None = None
    chanjing_app_id: str | None = None
    chanjing_secret_key: str | None = None
    chanjing_root: str | None = None
    chanjing_assets_dir: str | None = None
    chanjing_i2v_model: str | None = None


class ImportLuyaoRequest(BaseModel):
    data: dict[str, Any]
    filename: str = "imported_from_luyao.yaml"


class UploadScriptRequest(BaseModel):
    """上传 YAML 文本或已解析的 JSON 对象。"""
    filename: str
    content: str | None = None
    data: dict[str, Any] | None = None


@app.get("/health")
def health():
    return {"ok": True, "service": "zhou_sihan_clip_assembler", "version": "0.2.0"}


@app.get("/api/system")
def system_status():
    return probe_connectivity()


@app.get("/api/settings")
def get_settings():
    return load_app_settings().public_dict()


@app.post("/api/settings")
def post_settings(req: SettingsUpdate):
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    saved = save_app_settings(payload)
    return saved.public_dict()


@app.get("/api/scripts")
def list_scripts():
    return {"scripts": Pipeline().list_scripts()}


@app.get("/api/script")
def get_script(path: str = Query(...)):
    try:
        return Pipeline().inspect(path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/script/save")
def api_save_script(req: SaveScriptRequest):
    try:
        script = Script.model_validate(req.script)
        if req.path:
            path = Path(req.path)
        else:
            name = req.filename or "edited_script.yaml"
            if not name.endswith((".yaml", ".yml")):
                name += ".yaml"
            path = EXAMPLES / name
        save_script(script, path)
        return Pipeline().inspect(path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/script/import-luyao")
def api_import_luyao(req: ImportLuyaoRequest):
    try:
        script = import_luyao_shots_json(req.data)
        path = EXAMPLES / req.filename
        save_script(script, path)
        return Pipeline().inspect(path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/script/upload")
def api_upload_script(req: UploadScriptRequest):
    """上传本系统 YAML，或蝉镜侧分镜 JSON（自动识别）。"""
    import json

    import yaml

    name = Path(req.filename).name
    try:
        if req.data is not None:
            data = req.data
        elif req.content is not None:
            text = req.content.strip()
            if not text:
                raise ValueError("文件内容为空")
            if name.lower().endswith(".json") or text.startswith("{"):
                data = json.loads(text)
            else:
                data = yaml.safe_load(text)
        else:
            raise ValueError("需要 content 或 data")

        if not isinstance(data, dict):
            raise ValueError("脚本根节点必须是对象")

        # 蝉镜侧分镜 JSON：有 shots[].type / voiceover_full
        is_luyao = "voiceover_full" in data or (
            isinstance(data.get("shots"), list)
            and data["shots"]
            and isinstance(data["shots"][0], dict)
            and "type" in data["shots"][0]
            and "platform" not in data["shots"][0]
        )
        if is_luyao:
            script = import_luyao_shots_json(data)
            out_name = name.rsplit(".", 1)[0] + ".yaml"
        else:
            script = Script.model_validate(data)
            out_name = name if name.endswith((".yaml", ".yml")) else name + ".yaml"

        path = EXAMPLES / out_name
        save_script(script, path)
        detail = Pipeline().inspect(path)
        detail["imported_as"] = "luyao_json" if is_luyao else "yaml"
        return detail
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/validate")
def validate(req: ValidateRequest):
    try:
        script = load_script(req.script_path)
        detail = Pipeline().inspect(req.script_path)
        cost = estimate_cost(req.script_path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {
        "title": script.title,
        "shots": len(script.shots),
        "plan": detail["plan"],
        "library_ok": detail["library_ok"],
        "missing": detail["missing"],
        "cost": cost,
    }


@app.get("/api/estimate")
def api_estimate(path: str = Query(...)):
    try:
        return estimate_cost(path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/assemble")
def assemble(req: AssembleRequest):
    try:
        result = Pipeline().assemble(req.script_path, output_name=req.output)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e

    settings = load_settings()
    preview = None
    try:
        rel = result.output_path.resolve().relative_to(settings.output_dir.resolve())
        preview = f"/media/output/{rel.as_posix()}"
    except Exception:
        preview = f"/media/output/{result.output_path.name}"

    return {
        "title": result.title,
        "output": str(result.output_path),
        "duration_sec": result.duration_sec,
        "library": result.library,
        "plan": result.plan,
        "preview_url": preview,
    }


@app.get("/api/library")
def api_library():
    return Pipeline().list_library()


@app.get("/api/outputs")
def api_outputs():
    return {"outputs": Pipeline().list_outputs()}


@app.post("/api/generate")
def api_generate(req: GenerateBatchRequest):
    try:
        detail = Pipeline().inspect(req.script_path)
        script = load_script(req.script_path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e

    missing_ids = {m["shot_id"] for m in detail["missing"]}
    batch_id, _ = new_ids()
    batch = BatchJob(
        batch_id=batch_id,
        script_path=str(Path(req.script_path).resolve()),
        title=script.title,
        dry_run=req.dry_run,
        only_missing=req.only_missing,
        status="queued",
    )
    store = get_store()
    shot_job_ids: list[str] = []

    for shot in script.shots:
        if shot.platform.value not in req.platforms:
            continue
        if req.only_missing and shot.id not in missing_ids:
            continue
        _, jid = new_ids()
        job = ShotJob(
            job_id=jid,
            batch_id=batch_id,
            shot_id=shot.id,
            platform=shot.platform.value,
            dry_run=req.dry_run,
            status="queued",
            message="排队中",
        )
        shot_job_ids.append(jid)
        enqueue_shot(job)

    batch.shot_jobs = shot_job_ids
    if not shot_job_ids:
        batch.status = "done"
        batch.updated_at = batch.created_at
    store.upsert_batch(batch)
    return store.batch_detail(batch_id)


@app.get("/api/batches")
def api_batches():
    return {"batches": get_store().list_batches()}


@app.get("/api/batches/{batch_id}")
def api_batch(batch_id: str):
    detail = get_store().batch_detail(batch_id)
    if not detail:
        raise HTTPException(404, "batch 不存在")
    # 分平台汇总进度
    feiying = [s for s in detail["shots"] if s["platform"] == "feiying"]
    chanjing = [s for s in detail["shots"] if s["platform"] == "chanjing"]

    def agg(items: list[dict]) -> dict:
        if not items:
            return {"total": 0, "done": 0, "failed": 0, "running": 0, "progress": 0}
        done = sum(1 for s in items if s["status"] == "done")
        failed = sum(1 for s in items if s["status"] == "failed")
        running = sum(1 for s in items if s["status"] in {"running", "queued"})
        prog = sum(float(s.get("progress") or 0) for s in items) / len(items)
        return {
            "total": len(items),
            "done": done,
            "failed": failed,
            "running": running,
            "progress": round(prog, 3),
        }

    detail["feiying"] = agg(feiying)
    detail["chanjing"] = agg(chanjing)
    return detail


@app.get("/media/output/{file_name:path}")
def media_output(file_name: str):
    settings = load_settings()
    target = (settings.output_dir / file_name).resolve()
    if not str(target).startswith(str(settings.output_dir.resolve())):
        raise HTTPException(400, "非法路径")
    if not target.exists():
        raise HTTPException(404, f"文件不存在: {target}")
    return FileResponse(target, media_type="video/mp4")


@app.get("/")
def index():
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(404, "前端未找到")
    return FileResponse(index_file)


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
