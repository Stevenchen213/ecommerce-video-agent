"""编排层：分镜脚本 → 三道闸检查 → 产品镜头调蝉镜 → 按数字人音轨切时间轴 → 合成。

分工（2026-10 起）：数字人走飞影，蝉镜只做产品画面。
  avatar  镜头 → 本模块不再调用任何数字人接口。整条 voiceover_full 由飞影侧生成一条
                 数字人视频（声音统一、口型准确），通过 avatar_video 传进来，
                 再按时间轴切出各 avatar 镜头的画面；它的音轨作为整条成片的唯一音轨。
  product 镜头 → 有 clips（实拍素材）：本地 ffmpeg 剪辑，不花蝉豆；
                 只有图片素材：调蝉镜图生视频（chanjing.product.gen_product）。
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from chanjing import product
from . import checks, composer, timeline

log = logging.getLogger("orchestrator")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


@dataclass
class JobConfig:
    script_path: str
    person_id: str                          # 飞影 avatar_id，用于授权校验（authorized_avatars.json）
    voice_id: str = ""                      # 飞影克隆声音 ID，仅写入 plan 供飞影侧使用
    brand: str | None = None
    fills: dict[str, str] = field(default_factory=dict)
    assets_dir: str = "assets"
    asset_library: str | None = None       # 额外素材登记表（图片 URL 等）
    registry: str = "authorized_avatars.json"
    workdir: str = "work"
    output: str = "renders/output.mp4"
    dry_run: bool = False
    avatar_video: str | None = None        # 飞影生成的整条口播数字人视频（必填，dry_run 除外）
    mock_avatar_video: str | None = None   # 旧字段，等同 avatar_video，保留兼容周思含的桥接代码

    @property
    def avatar_source(self) -> str | None:
        return self.avatar_video or self.mock_avatar_video


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
    # 只有图片：优先用已登记的 url，否则用本地文件（gen_product 会自动上传）
    images = [lib[r].get("url") or lib[r]["file"] for r in vis["asset_refs"]]
    if not images:
        raise ValueError(f"镜头{shot['shot_id']} 没有任何产品素材，无法生成")
    prompt = f"{vis['description']}。{vis.get('camera') or ''}。竖屏商品展示，真实质感，不要出现文字"
    return {"mode": "ai_creation", "images": images, "prompt": prompt,
            "target_duration": shot.get("duration_sec"),
            "model_code": settings.i2v_model_code,
            "requested_duration": product.request_duration(shot.get("duration_sec"))}


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

    # 2) 调用计划：数字人部分只写给飞影侧看的请求，本模块不调用
    plan = {"avatar": {"provider": "feiying", "person_id": cfg.person_id, "voice_id": cfg.voice_id,
                       "text": script["voiceover_full"],
                       "shots": [s["shot_id"] for s in shots if s["type"] == "avatar"],
                       "video": cfg.avatar_source},
            "product": product_plans}
    (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if cfg.dry_run:
        return {"ok": True, "stage": "dry_run", "plan": str(work / "plan.json")}
    if not cfg.avatar_source or not Path(cfg.avatar_source).exists():
        return {"ok": False, "stage": "avatar",
                "errors": {"avatar": ["缺少飞影生成的整条口播数字人视频（avatar_video）。"
                                      "请先用 plan.json 里的 avatar.text 在飞影侧生成，再传入路径"]}}
    avatar_video = Path(cfg.avatar_source)

    # 3) 产品镜头并发调蝉镜图生视频
    ai_plans = {sid: p for sid, p in product_plans.items() if p["mode"] == "ai_creation"}
    ai_videos: dict[int, Path] = {}
    if ai_plans:
        client = product.make_client()
        upload_cache: dict[str, str] = {}
        # 先串行上传图片（有缓存，同图只传一次），再并发提交任务
        for p in ai_plans.values():
            p["image_urls"] = product.resolve_image_urls(client, p["images"], upload_cache)

        def run_ai(shot_id: int, p: dict) -> Path:
            info = product.gen_product(p["image_urls"], p["prompt"], work / f"ai_shot_{shot_id}.mp4",
                                       target_duration=p["target_duration"],
                                       model_code=p["model_code"], client=client)
            return Path(info["path"])

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {sid: pool.submit(run_ai, sid, p) for sid, p in ai_plans.items()}
            ai_videos = {sid: f.result() for sid, f in futs.items()}

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
