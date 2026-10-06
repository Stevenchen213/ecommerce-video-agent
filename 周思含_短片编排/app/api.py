"""周思含_短片编排 · 后端 API。"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.pipeline import Pipeline
from app.schema import load_script

WEB_DIR = load_settings().web_dir

app = FastAPI(title="周思含_短片编排", version="0.1.0")


class AssembleRequest(BaseModel):
    script_path: str
    output: str = "final.mp4"


class ValidateRequest(BaseModel):
    script_path: str


@app.get("/health")
def health():
    return {"ok": True, "service": "zhou_sihan_clip_assembler"}


@app.get("/api/scripts")
def list_scripts():
    return {"scripts": Pipeline().list_scripts()}


@app.get("/api/script")
def get_script(path: str = Query(...)):
    try:
        return Pipeline().inspect(path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/validate")
def validate(req: ValidateRequest):
    try:
        script = load_script(req.script_path)
        detail = Pipeline().inspect(req.script_path)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return {
        "title": script.title,
        "shots": len(script.shots),
        "plan": detail["plan"],
        "library_ok": detail["library_ok"],
        "missing": detail["missing"],
    }


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
