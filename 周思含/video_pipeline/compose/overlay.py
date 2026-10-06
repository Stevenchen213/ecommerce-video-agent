"""overlay_asset_refs：把产品图叠加到数字人镜头画面侧边。

与路遥模式 A 的 composer.avatar_segment 同一几何：产品图缩到画面宽 1/3，
放在右侧（右留 40px、距顶 18% 高）。ref 支持 `asset_id@3s` 语法——
素材是视频时抽该秒帧当叠加图。
"""
from __future__ import annotations

from pathlib import Path

from video_pipeline.compose.concat import FFMPEG, _run
from video_pipeline.schema import ScriptAsset

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


def resolve_overlay_image(
    ref: str,
    assets: dict[str, ScriptAsset],
    assets_dir: Path,
    work_dir: Path,
    tag: str,
) -> Path | None:
    ref_id, _, at = ref.partition("@")
    asset = assets.get(ref_id)
    if not asset or not asset.file:
        return None
    p = Path(asset.file)
    if not p.is_absolute():
        p = assets_dir / p
    if not p.exists():
        return None
    if p.suffix.lower() in VIDEO_EXT:
        t = float(at.rstrip("s")) if at else 0.0
        frame = work_dir / f"overlay_{tag}.png"
        _run([FFMPEG, "-y", "-v", "error", "-ss", str(t), "-i", str(p),
              "-frames:v", "1", str(frame)])
        return frame
    return p


def apply_overlay(src: Path, img: Path, dest: Path, width: int, height: int) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fc = (
        f"[0:v]null[bg];[1:v]scale={width // 3}:-1[ov];"
        f"[bg][ov]overlay=W-w-40:H*0.18:shortest=1[v]"
    )
    cmd = [
        FFMPEG, "-y", "-v", "error",
        "-i", str(src), "-loop", "1", "-i", str(img),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(dest),
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"产品图叠加失败: {src} + {img}\n{proc.stderr}")
    return dest
