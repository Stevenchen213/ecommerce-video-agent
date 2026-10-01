from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from video_pipeline.config import PACKAGE_ROOT, load_settings
from video_pipeline.library_check import check_library
from video_pipeline.pipeline import Pipeline
from video_pipeline.planner import plan_script
from video_pipeline.schema import load_script

WEB_DIR = PACKAGE_ROOT / "web"
EXAMPLES_DIR = PACKAGE_ROOT / "examples"

app = FastAPI(title="脚本驱动双平台视频组装 API", version="0.3.0")


class RunRequest(BaseModel):
    script_path: str = Field(..., description="脚本 YAML 路径")
    output: str = "final.mp4"


class AssembleRequest(BaseModel):
    script_path: str
    output: str = "final.mp4"


class RetryRequest(BaseModel):
    script_path: str
    shot_id: str


class StatusRequest(BaseModel):
    script_path: str | None = None


def _result_payload(result) -> dict:
    out = Path(result.output_path)
    preview = None
    settings = load_settings()
    try:
        rel = out.resolve().relative_to(settings.output_dir.resolve())
        preview = f"/media/output/{rel.as_posix()}"
    except Exception:
        if out.name:
            preview = f"/media/output/{out.name}"
    return {
        "title": result.script_title,
        "output": str(result.output_path),
        "duration_sec": result.duration_sec,
        "library": {k: str(v) for k, v in result.library_paths.items()},
        "preview_url": preview,
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/scripts")
def list_scripts():
    scripts = []
    if EXAMPLES_DIR.exists():
        for p in sorted(EXAMPLES_DIR.glob("*.yaml")):
            scripts.append({"name": p.name, "path": str(p.resolve())})
        for p in sorted(EXAMPLES_DIR.glob("*.yml")):
            scripts.append({"name": p.name, "path": str(p.resolve())})
    return {"scripts": scripts}


@app.get("/api/script")
def get_script(path: str = Query(..., description="脚本绝对或相对路径")):
    try:
        script = load_script(path)
        plan = plan_script(script)
        check = check_library(script, load_settings().library_dir)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {
        "title": script.title,
        "description": script.description,
        "default_transition": script.default_transition,
        "brand": script.brand.model_dump(),
        "path": str(Path(path).resolve()),
        "shots": [s.model_dump() for s in script.shots],
        "feiying": [s.id for s in plan.feiying_shots],
        "chanjing": [s.id for s in plan.chanjing_shots],
        "product_segments": [seg.to_dict() for seg in plan.product_segments],
        "timeline": [u.to_dict() for u in plan.timeline],
        "library_ok": check.ok,
        "missing": [
            {
                "shot_id": m.shot_id,
                "platform": m.platform,
                "expected_path": str(m.expected_path),
            }
            for m in check.missing
        ],
        "present": {k: str(v) for k, v in check.present.items()},
    }


@app.post("/validate")
def validate(req: RunRequest):
    try:
        script = load_script(req.script_path)
        plan = plan_script(script)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {
        "title": script.title,
        "shots": len(script.shots),
        "feiying": [s.id for s in plan.feiying_shots],
        "chanjing": [s.id for s in plan.chanjing_shots],
        "product_segments": [seg.to_dict() for seg in plan.product_segments],
        "timeline": [u.to_dict() for u in plan.timeline],
    }


@app.post("/run")
def run(req: RunRequest):
    try:
        result = Pipeline().run(req.script_path, output_name=req.output)
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return _result_payload(result)


@app.post("/assemble")
def assemble(req: AssembleRequest):
    try:
        result = Pipeline().assemble_only(req.script_path, output_name=req.output)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return _result_payload(result)


@app.post("/retry")
def retry(req: RetryRequest):
    try:
        path = Pipeline().retry_shot(req.script_path, req.shot_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    return {"shot_id": req.shot_id, "path": str(path)}


@app.post("/status")
def status(req: StatusRequest):
    return Pipeline().status(req.script_path)


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
