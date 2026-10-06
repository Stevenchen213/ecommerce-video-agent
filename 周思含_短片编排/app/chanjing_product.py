"""蝉镜产品短片生成：复用对方 chanjing 包（实拍优先 / 图生视频）。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import requests

from app.chanjing_bridge import ChanjingBridgeError, load_chanjing_modules, resolve_chanjing_root
from app.config import load_settings
from app.jobs import ShotJob
from app.schema import Script, Shot
from app.settings_store import AppSettings

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg failed")[:800])


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float((proc.stdout or "0").strip() or 0)
    except ValueError:
        return 0.0


def build_asset_lib(script: Script, assets_dir: Path) -> dict[str, dict]:
    lib: dict[str, dict] = {}
    for a in script.assets:
        file_path = Path(a.file) if a.file else Path()
        if a.file and not file_path.is_absolute():
            file_path = assets_dir / a.file
        entry = {
            "asset_id": a.asset_id,
            "file": str(file_path) if a.file else "",
            "url": a.url,
            "description": a.description,
        }
        suffix = file_path.suffix.lower() if a.file else ""
        if suffix in VIDEO_EXT:
            entry["kind"] = "video"
        elif a.url and any(a.url.lower().endswith(ext) for ext in VIDEO_EXT):
            entry["kind"] = "video"
        else:
            entry["kind"] = "image"
        lib[a.asset_id] = entry
    return lib


def plan_product_shot(shot: Shot, lib: dict[str, dict], i2v_model: str) -> dict:
    vis = shot.extra.get("visual") or {}
    refs = list(shot.asset_refs or vis.get("asset_refs") or [])
    clips = list(vis.get("clips") or shot.extra.get("clips") or [])
    desc = str(vis.get("description") or shot.notes or shot.text or shot.role or "")
    camera = str(vis.get("camera") or "")

    if clips:
        resolved = []
        for c in clips:
            ref = c.get("asset_ref")
            if ref not in lib:
                raise ValueError(f"镜头 {shot.id} clip 素材不存在: {ref}")
            resolved.append({**c, "path": lib[ref]["file"]})
        return {"mode": "local_clips", "clips": resolved}

    if refs:
        videos = [r for r in refs if r in lib and lib[r]["kind"] == "video"]
        if videos:
            clips_out = []
            for r in videos:
                p = Path(lib[r]["file"])
                end = lib[r].get("duration_sec") or (_probe_duration(p) if p.exists() else 3)
                clips_out.append({"asset_ref": r, "path": str(p), "start": 0, "end": end})
            return {"mode": "local_clips", "clips": clips_out}
        urls = [lib[r]["url"] for r in refs if r in lib and lib[r].get("url")]
        if urls:
            prompt = f"{desc}。{camera}。竖屏商品展示，真实质感，不要出现文字".strip("。")
            dur = max(3, min(8, int(round(shot.duration_sec))))
            return {
                "mode": "ai_creation",
                "prompt": prompt,
                "urls": urls,
                "duration": dur,
                "model": i2v_model,
            }

    # 无素材时：用文案/备注做文生视频式 prompt，但仍走图生接口需要图——明确报错
    raise ValueError(
        f"镜头 {shot.id} 缺少产品素材：请在脚本 assets + asset_refs 提供图片 URL（图生）"
        "或本地视频 clips（实拍优先）"
    )


def _cut_local_clips(clips: list[dict], out: Path, target_dur: float, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    pieces: list[Path] = []
    for i, c in enumerate(clips):
        src = Path(c["path"])
        if not src.exists():
            raise FileNotFoundError(f"实拍素材不存在: {src}")
        start = float(c.get("start") or 0)
        end = float(c.get("end") or 0)
        if end <= start:
            end = start + max(0.5, target_dur)
        piece = work / f"clip_{i:02d}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                str(src),
                "-vf",
                "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                str(piece),
            ]
        )
        pieces.append(piece)

    if len(pieces) == 1:
        # 截到目标时长
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(pieces[0]),
                "-t",
                str(max(0.5, target_dur)),
                "-c",
                "copy",
                str(out),
            ]
        )
        if not out.exists():
            shutil.copyfile(pieces[0], out)
        return

    lst = work / "list.txt"
    lst.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in pieces) + "\n",
        encoding="utf-8",
    )
    merged = work / "merged.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            str(merged),
        ]
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(merged),
            "-t",
            str(max(0.5, target_dur)),
            "-c",
            "copy",
            str(out),
        ]
    )


def generate_chanjing_product(
    shot: Shot,
    script: Script,
    out: Path,
    app: AppSettings,
    job: ShotJob,
    progress,
) -> None:
    """
    综合蝉镜侧交付：
    - 有实拍 clips / 本地视频 → 本地裁切（不花蝉豆）
    - 仅有图片 URL → 调对方 ai_creation 图生视频
    """
    try:
        root = resolve_chanjing_root(app.chanjing_root)
    except ChanjingBridgeError:
        root = None

    assets_dir = Path(app.chanjing_assets_dir) if app.chanjing_assets_dir else None
    if assets_dir is None and root is not None:
        assets_dir = root / "assets"
    if assets_dir is None:
        assets_dir = load_settings().root / "assets"

    lib = build_asset_lib(script, assets_dir)
    plan = plan_product_shot(shot, lib, app.chanjing_i2v_model)

    if plan["mode"] == "local_clips":
        progress(job, 0.35, "蝉镜侧：本地实拍裁切（不花蝉豆）")
        work = load_settings().tmp_dir / "chanjing_local" / shot.id
        _cut_local_clips(plan["clips"], out, float(shot.duration_sec), work)
        job.output_path = str(out)
        progress(job, 0.95, "实拍短片已写入 library")
        return

    # ai_creation
    if not (app.chanjing_app_id and app.chanjing_secret_key):
        raise RuntimeError("图生视频需要配置蝉镜 APP_ID / SECRET（设置页）")

    progress(job, 0.25, "加载蝉镜侧 SDK")
    _root, ChanjingClient, ai_creation = load_chanjing_modules(app.chanjing_root)
    client = ChanjingClient(
        app.chanjing_app_id,
        app.chanjing_secret_key,
        app.chanjing_base_url,
    )
    payload = ai_creation.build_i2v_payload(
        plan["model"],
        plan["prompt"],
        plan["urls"],
        aspect_ratio="9:16",
        clarity=1080,
        duration=int(plan["duration"]),
    )
    progress(job, 0.4, "提交图生视频任务")
    uid = ai_creation.submit(client, payload)
    progress(job, 0.5, f"轮询任务 {uid}")
    task = ai_creation.wait_task(
        client,
        uid,
        app.chanjing_poll_interval,
        app.chanjing_poll_timeout,
    )
    url = ai_creation.first_output(task)
    progress(job, 0.9, "下载产品短片")
    out.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        tmp = out.with_suffix(".part.mp4")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if chunk:
                    f.write(chunk)
        tmp.replace(out)
    job.output_path = str(out)
    progress(job, 0.97, "产品短片已写入 library")
