"""编排层：分镜脚本 → 三道闸检查 → 分流并发提交蝉镜 → 轮询下载 → 按时间轴合成。

分流规则（与分镜 JSON 的 type 字段一一对应）：
  avatar  镜头 → 不单独调用。整条 voiceover_full 只调一次数字人 create_video，
                 得到统一音轨 + 对口型视频，再按时间轴切出各 avatar 镜头的画面。
  product 镜头 → 有 clips（实拍素材）：本地 ffmpeg 剪辑，不花蝉豆；
                 只有图片素材：调用 AI 创作图生视频。
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import requests

from config import settings
from chanjing import ai_creation, avatar
from chanjing.client import ChanjingClient
from . import checks, composer, timeline

log = logging.getLogger("orchestrator")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


@dataclass
class JobConfig:
    script_path: str
    person_id: str
    voice_id: str
    brand: str | None = None
    source: str = "common"                 # common | customised
    figure_type: str | None = None
    fills: dict[str, str] = field(default_factory=dict)
    assets_dir: str = "assets"
    asset_library: str | None = None       # 额外素材登记表（图片 URL 等）
    registry: str = "authorized_avatars.json"
    workdir: str = "work"
    output: str = "renders/output.mp4"
    dry_run: bool = False
    mock_avatar_video: str | None = None   # 本地联调：用现成视频代替数字人接口


# ---------------- 素材库 ----------------
def build_asset_library(script: dict, cfg: JobConfig) -> dict[str, dict]:
    lib: dict[str, dict] = {}
    for a in script.get("assets", []):
        lib[a["asset_id"]] = {**a, "file": str(Path(cfg.assets_dir) / a["file"])}
    if cfg.asset_library:
        for a in json.loads(Path(cfg.asset_library).read_text(encoding="utf-8")):
            lib[a["asset_id"]] = {**lib.get(a["asset_id"], {}), **a}
    for a in lib.values():
        a["kind"] = "video" if Path(a.get("file", "")).suffix.lower() in VIDEO_EXT else "image"
    return lib


# ---------------- 计划 ----------------
def plan_product_shot(shot: dict, lib: dict[str, dict]) -> dict:
    vis = shot["visual"]
    if vis.get("clips"):
        return {"mode": "local_clips", "clips": [
            {**c, "path": lib[c["asset_ref"]]["file"]} for c in vis["clips"]]}
    videos = [r for r in vis["asset_refs"] if lib[r]["kind"] == "video"]
    if videos:
        return {"mode": "local_clips", "clips": [
            {"asset_ref": r, "path": lib[r]["file"], "start": 0,
             "end": lib[r].get("duration_sec") or composer.probe_duration(lib[r]["file"])}
            for r in videos]}
    urls = [lib[r]["url"] for r in vis["asset_refs"] if lib[r].get("url")]
    if not urls:
        raise ValueError(f"镜头{shot['shot_id']} 只有图片素材但没有可访问的 url，无法图生视频")
    prompt = f"{vis['description']}。{vis.get('camera') or ''}。竖屏商品展示，真实质感，不要出现文字"
    return {"mode": "ai_creation", "payload": ai_creation.build_i2v_payload(
        settings.i2v_model_code, prompt, urls, duration=5)}


def overlay_path(shot: dict, lib: dict, workdir: Path) -> Path | None:
    refs = shot["visual"].get("overlay_asset_refs") or []
    if not refs:
        return None
    ref, _, at = refs[0].partition("@")
    asset = lib[ref]
    if asset["kind"] == "image":
        return Path(asset["file"])
    return composer.extract_frame(asset["file"], float(at.rstrip("s") or 0),
                                  workdir / f"overlay_{shot['shot_id']}.png")


# ---------------- 下载 ----------------
def download(url: str, out: Path) -> Path:
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with out.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return out


# ---------------- 主流程 ----------------
def run(cfg: JobConfig) -> dict:
    work = Path(cfg.workdir); work.mkdir(parents=True, exist_ok=True)
    Path(cfg.output).parent.mkdir(parents=True, exist_ok=True)

    script = json.loads(Path(cfg.script_path).read_text(encoding="utf-8"))
    script = checks.fill_placeholders(script, cfg.fills)
    lib = build_asset_library(script, cfg)

    # 1) 三道闸：任何一道不过，都不调用付费接口
    reports = {
        "structure": checks.check_structure(script, set(lib)),
        "compliance": checks.check_compliance(script),
        "authorization": checks.check_avatar_authorization(cfg.person_id, cfg.brand, cfg.registry),
    }
    for name, rep in reports.items():
        for w in rep.warnings:
            log.warning("[%s] %s", name, w)
    errors = {k: v.errors for k, v in reports.items() if v.errors}
    if errors:
        return {"ok": False, "stage": "checks", "errors": errors}

    shots = script["shots"]
    product_plans = {s["shot_id"]: plan_product_shot(s, lib) for s in shots if s["type"] == "product"}

    # 2) 数字人 payload（真实调用前先查形象，拿真实 figure 宽高）
    client = None
    if cfg.dry_run or cfg.mock_avatar_video:
        figure = {"type": cfg.figure_type, "width": settings.width, "height": settings.height}
    else:
        client = ChanjingClient(settings.app_id, settings.secret_key, settings.base_url,
                                settings.request_timeout)
        person = avatar.get_person(client, cfg.person_id, cfg.source)
        figure = avatar.pick_figure(person, cfg.figure_type)
    avatar_payload = avatar.build_tts_payload(cfg.person_id, figure, cfg.voice_id,
                                              script["voiceover_full"], settings.width, settings.height)

    plan = {"avatar": {"payload": avatar_payload,
                       "shots": [s["shot_id"] for s in shots if s["type"] == "avatar"]},
            "product": product_plans}
    (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if cfg.dry_run:
        return {"ok": True, "stage": "dry_run", "plan": str(work / "plan.json")}

    # 3) 并发：数字人任务 + 所有图生视频任务同时跑
    def run_avatar() -> Path:
        if cfg.mock_avatar_video:
            return Path(cfg.mock_avatar_video)
        vid = avatar.create_video(client, avatar_payload)
        log.info("数字人任务已提交 video_id=%s", vid)
        res = avatar.wait_video(client, vid, settings.poll_interval, settings.poll_timeout)
        return download(res["video_url"], work / "avatar_full.mp4")

    def run_ai(shot_id: int, payload: dict) -> Path:
        uid = ai_creation.submit(client, payload)
        log.info("镜头%s 图生视频已提交 unique_id=%s", shot_id, uid)
        task = ai_creation.wait_task(client, uid, settings.poll_interval, settings.poll_timeout)
        return download(ai_creation.first_output(task), work / f"ai_shot_{shot_id}.mp4")

    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_avatar = pool.submit(run_avatar)
        fut_ai = {sid: pool.submit(run_ai, sid, p["payload"])
                  for sid, p in product_plans.items() if p["mode"] == "ai_creation"}
        avatar_video = fut_avatar.result()
        ai_videos = {sid: f.result() for sid, f in fut_ai.items()}

    # 4) 以数字人音轨真实时长切时间轴
    total = composer.probe_duration(avatar_video)
    spans = timeline.allocate(shots, total)

    # 5) 逐镜头出片段，再统一合成
    segments = []
    for shot, (t0, t1) in zip(shots, spans):
        out = work / f"seg_{shot['shot_id']:02d}.mp4"
        if shot["type"] == "avatar":
            composer.avatar_segment(avatar_video, t0, t1, out, settings.width, settings.height,
                                    settings.fps, overlay_path(shot, lib, work))
        else:
            p = product_plans[shot["shot_id"]]
            clips = p["clips"] if p["mode"] == "local_clips" else [
                {"path": ai_videos[shot["shot_id"]], "start": 0,
                 "end": composer.probe_duration(ai_videos[shot["shot_id"]])}]
            composer.product_segment(clips, t1 - t0, out, settings.width, settings.height, settings.fps)
        segments.append(out)

    final = composer.assemble(segments, avatar_video, Path(cfg.output),
                              settings.ai_label_text, settings.ai_label_font, work)
    manifest = {"ok": True, "output": str(final), "duration": composer.probe_duration(final),
                "timeline": [{"shot_id": s["shot_id"], "type": s["type"], "start": a, "end": b}
                             for s, (a, b) in zip(shots, spans)]}
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
