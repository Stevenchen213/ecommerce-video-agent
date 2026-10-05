from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from video_pipeline.compose.concat import FFMPEG, probe
from video_pipeline.schema import BrandOptions


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("品牌叠加失败:\n" + (proc.stderr or proc.stdout or ""))


@dataclass
class BrandAssets:
    logo: Path | None = None
    bgm: Path | None = None
    endcard: Path | None = None


def discover_brand_assets(brand_dir: Path) -> BrandAssets:
    logo = None
    for name in ("logo.png", "logo.jpg", "logo.webp"):
        p = brand_dir / name
        if p.exists():
            logo = p
            break
    bgm = None
    for name in ("bgm.mp3", "bgm.wav", "bgm.m4a", "bgm.aac"):
        p = brand_dir / name
        if p.exists():
            bgm = p
            break
    endcard = brand_dir / "endcard.mp4"
    return BrandAssets(
        logo=logo,
        bgm=bgm,
        endcard=endcard if endcard.exists() else None,
    )


def apply_brand(
    video_path: Path,
    output_path: Path,
    brand_dir: Path,
    options: BrandOptions,
    *,
    work_dir: Path,
) -> Path:
    """按可用资产叠加 logo / 混音 BGM / 追加片尾。无资产则原样拷贝。"""
    if not options.enable:
        if video_path.resolve() != output_path.resolve():
            output_path.write_bytes(video_path.read_bytes())
        return output_path

    assets = discover_brand_assets(brand_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    current = video_path

    if options.overlay_logo and assets.logo:
        logoed = work_dir / "brand_logo.mp4"
        margin = options.logo_margin
        # 右上角半透明 logo
        filt = (
            f"[1:v]scale=180:-1,format=rgba,colorchannelmixer=aa=0.85[lg];"
            f"[0:v][lg]overlay=W-w-{margin}:{margin}[v]"
        )
        cmd = [
            FFMPEG,
            "-y",
            "-i",
            str(current),
            "-i",
            str(assets.logo),
            "-filter_complex",
            filt,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(logoed),
        ]
        _run(cmd)
        current = logoed

    if options.mix_bgm and assets.bgm:
        mixed = work_dir / "brand_bgm.mp4"
        info = probe(current)
        dur = info.duration or 0
        vol = options.bgm_volume
        # 主音量保留，BGM 降音循环并裁到成片时长
        filt = (
            f"[1:a]volume={vol},aloop=loop=-1:size=2e+09,atrim=0:{dur}[bg];"
            f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        if info.has_audio:
            cmd = [
                FFMPEG,
                "-y",
                "-i",
                str(current),
                "-i",
                str(assets.bgm),
                "-filter_complex",
                filt,
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-t",
                str(dur),
                str(mixed),
            ]
        else:
            cmd = [
                FFMPEG,
                "-y",
                "-i",
                str(current),
                "-i",
                str(assets.bgm),
                "-filter_complex",
                f"[1:a]volume={vol},aloop=loop=-1:size=2e+09,atrim=0:{dur}[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-t",
                str(dur),
                str(mixed),
            ]
        _run(cmd)
        current = mixed

    if options.append_endcard and assets.endcard:
        from video_pipeline.compose.concat import concat_segments

        ended = work_dir / "brand_end.mp4"
        concat_segments(
            [current, assets.endcard],
            ended,
            work_dir=work_dir / "endcard_concat",
        )
        current = ended

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if current.resolve() != output_path.resolve():
        output_path.write_bytes(current.read_bytes())
    return output_path
