from __future__ import annotations

import subprocess
import time
from pathlib import Path

import requests

from app.chanjing_product import generate_chanjing_product, plan_product_shot, build_asset_lib
from app.chanjing_bridge import resolve_chanjing_root
from app.config import load_settings
from app.jobs import ShotJob, get_store
from app.library_check import expected_path
from app.schema import Platform, Shot, load_script
from app.settings_store import load_app_settings


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg failed")[:800])


def _mock_clip(shot: Shot, out: Path, color: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    dur = max(0.8, float(shot.duration_sec))
    label = f"{shot.platform.value}|{shot.id}".replace(":", " ")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={settings.width}x{settings.height}:d={dur}:r={settings.fps}",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-vf",
        f"drawtext=text='{label}':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
        "-t",
        str(dur),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    _run(cmd)


def _progress(job: ShotJob, p: float, msg: str) -> None:
    store = get_store()
    job.progress = max(0.0, min(1.0, p))
    job.message = msg
    store.upsert_shot(job)


def generate_shot_job(job: ShotJob) -> None:
    app = load_app_settings()
    settings = load_settings()
    batch = get_store().get_batch(job.batch_id)
    if not batch:
        raise RuntimeError("batch 不存在")
    script = load_script(batch.script_path)
    shot = next((s for s in script.shots if s.id == job.shot_id), None)
    if not shot:
        raise RuntimeError(f"脚本中无镜头 {job.shot_id}")

    out = expected_path(settings.library_dir, shot)
    if job.dry_run:
        _progress(job, 0.5, "dry-run：跳过真实生成")
        time.sleep(0.3)
        job.output_path = str(out)
        job.message = "dry-run 计划完成"
        get_store().upsert_shot(job)
        return

    _progress(job, 0.15, "准备生成")

    if job.platform == "feiying":
        if app.use_mock or not app.feiying_api_key:
            _progress(job, 0.45, "mock 生成数字人短片")
            _mock_clip(shot, out, "0x1a3a5c")
            job.output_path = str(out)
            _progress(job, 0.95, "mock 完成")
            return
        _generate_feiying_real(shot, out, job, app)
        return

    # 蝉镜产品短片：综合对方交付（实拍优先 / 图生）
    if app.use_mock:
        # 若脚本已带可本地裁切的实拍，即使 mock 也走真裁切（不花钱）
        try:
            from pathlib import Path as _P

            assets_dir = _P(app.chanjing_assets_dir) if app.chanjing_assets_dir else None
            if assets_dir is None:
                try:
                    assets_dir = resolve_chanjing_root(app.chanjing_root) / "assets"
                except Exception:
                    assets_dir = settings.root / "assets"
            lib = build_asset_lib(script, assets_dir)
            plan = plan_product_shot(shot, lib, app.chanjing_i2v_model)
            if plan["mode"] == "local_clips":
                generate_chanjing_product(shot, script, out, app, job, _progress)
                return
        except Exception:
            pass
        _progress(job, 0.45, "mock 生成产品短片")
        _mock_clip(shot, out, "0x1a5c3a")
        job.output_path = str(out)
        _progress(job, 0.95, "mock 完成")
        return

    generate_chanjing_product(shot, script, out, app, job, _progress)


def _generate_feiying_real(shot: Shot, out: Path, job: ShotJob, app) -> None:
    _progress(job, 0.25, "提交飞影 create_by_tts")
    person = shot.person_id or app.feiying_default_person_id
    voice = shot.voice_id or app.feiying_default_voice_id
    if not person or not voice or not shot.text.strip():
        raise ValueError("飞影需要 person_id / voice_id / text")
    headers = {"Authorization": f"Bearer {app.feiying_api_key}"}
    base = app.feiying_api_base.rstrip("/")
    resp = requests.post(
        f"{base}/api/v2/hifly/video/create_by_tts",
        headers=headers,
        json={
            "avatar": person,
            "voice": voice,
            "text": shot.text,
            "title": shot.id,
            "st_show": 0,
        },
        timeout=30,
    )
    data = resp.json()
    if resp.status_code == 401 or data.get("code") not in (0, None):
        raise RuntimeError(f"飞影提交失败: {data}")
    task_id = data.get("task_id") or (data.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"飞影无 task_id: {data}")

    _progress(job, 0.4, f"轮询任务 {task_id}")
    deadline = time.time() + 600
    video_url = None
    while time.time() < deadline:
        pr = requests.get(
            f"{base}/api/v2/hifly/video/task",
            headers=headers,
            params={"task_id": task_id},
            timeout=30,
        )
        pdata = pr.json()
        status = pdata.get("status")
        if status == 3:
            video_url = pdata.get("video_Url") or pdata.get("video_url")
            break
        if status == 4:
            raise RuntimeError(f"飞影失败: {pdata}")
        _progress(job, min(0.9, job.progress + 0.05), "飞影生成中…")
        time.sleep(8)
    if not video_url:
        raise TimeoutError("飞影任务超时")
    _progress(job, 0.92, "下载成片")
    out.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(video_url, stream=True, timeout=300) as r:
        r.raise_for_status()
        tmp = out.with_suffix(".part.mp4")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if chunk:
                    f.write(chunk)
        tmp.replace(out)
    job.output_path = str(out)


def probe_connectivity() -> dict:
    app = load_app_settings()
    cj_root = ""
    try:
        cj_root = str(resolve_chanjing_root(app.chanjing_root))
    except Exception as e:
        cj_root = f"未找到（{e}）"

    result = {
        "ffmpeg": False,
        "feiying": {"configured": bool(app.feiying_api_key), "ok": False, "detail": ""},
        "chanjing": {
            "configured": bool(app.chanjing_app_id and app.chanjing_secret_key),
            "ok": False,
            "detail": "",
            "sdk_root": cj_root,
        },
        "use_mock": app.use_mock,
    }
    try:
        proc = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        result["ffmpeg"] = proc.returncode == 0
    except Exception as e:
        result["ffmpeg"] = False
        result["ffmpeg_error"] = str(e)

    if app.feiying_api_key:
        try:
            r = requests.get(
                f"{app.feiying_api_base.rstrip('/')}/api/v2/hifly/video/task",
                headers={"Authorization": f"Bearer {app.feiying_api_key}"},
                params={"task_id": "ping-connectivity"},
                timeout=15,
            )
            # 有响应即网络/鉴权通路大致可用（无效 task 也算通）
            result["feiying"]["ok"] = r.status_code in {200, 400, 404} or r.status_code < 500
            result["feiying"]["detail"] = f"HTTP {r.status_code}"
        except Exception as e:
            result["feiying"]["detail"] = str(e)
    else:
        result["feiying"]["detail"] = "未配置 API Key"

    if app.chanjing_app_id and app.chanjing_secret_key:
        try:
            r = requests.post(
                f"{app.chanjing_base_url.rstrip('/')}/open/v1/access_token",
                json={"app_id": app.chanjing_app_id, "secret_key": app.chanjing_secret_key},
                timeout=20,
            )
            body = r.json()
            ok = body.get("code") == 0 and bool((body.get("data") or {}).get("access_token"))
            result["chanjing"]["ok"] = ok
            result["chanjing"]["detail"] = "token ok" if ok else str(body.get("msg") or body)[:200]
        except Exception as e:
            result["chanjing"]["detail"] = str(e)
    else:
        result["chanjing"]["detail"] = "未配置 APP_ID / SECRET"

    return result


def estimate_cost(script_path: str) -> dict:
    app = load_app_settings()
    script = load_script(script_path)
    feiying_sec = sum(s.duration_sec for s in script.shots if s.platform == Platform.FEIYING)
    chanjing_n = sum(1 for s in script.shots if s.platform == Platform.CHANJING)
    return {
        "feiying_seconds": feiying_sec,
        "feiying_points_est": round(feiying_sec * app.estimate_feiying_points_per_sec, 1),
        "chanjing_shots": chanjing_n,
        "chanjing_note": app.estimate_chanjing_note,
        "use_mock": app.use_mock,
    }
