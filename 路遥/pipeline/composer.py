"""用 ffmpeg 把数字人片段与产品片段按时间轴拼成成片，统一音轨并加 AI 标识。"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("composer")


def _run(cmd: list[str]) -> None:
    log.debug(" ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{p.stderr[-800:]}")


def probe_duration(path: str | Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def _fit(w: int, h: int) -> str:
    """等比缩放并裁满画布，不拉伸。"""
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def _crop_filter(crop: str | None) -> str:
    """脚本里的 crop 是给人看的描述，这里只识别常见关键词；需要精确裁切时在脚本里加 crop_box。"""
    if not crop:
        return ""
    if any(k in crop for k in ("底部", "下方")):
        return "crop=iw:ih*0.45:0:ih*0.55,"
    if any(k in crop for k in ("顶部", "上方")):
        return "crop=iw:ih*0.45:0:0,"
    return ""


def extract_frame(video: str | Path, at: float, out: Path) -> Path:
    _run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(video),
          "-frames:v", "1", str(out)])
    return out


def avatar_segment(avatar_video: Path, start: float, end: float, out: Path,
                   w: int, h: int, fps: int, overlay_img: Path | None = None) -> Path:
    base = f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS,{_fit(w, h)},fps={fps}"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(avatar_video)]
    if overlay_img:   # 数字人镜头侧边浮现产品图
        cmd += ["-loop", "1", "-i", str(overlay_img)]
        fc = (f"{base}[bg];[1:v]scale={w // 3}:-1[ov];"
              f"[bg][ov]overlay=W-w-40:H*0.18:shortest=1[v]")
    else:
        fc = f"{base}[v]"
    _run(cmd + ["-filter_complex", fc, "-map", "[v]", "-an", "-t", str(end - start),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    return out


def product_segment(clips: list[dict], duration: float, out: Path,
                    w: int, h: int, fps: int) -> Path:
    """clips: [{path, start, end, speed, crop}]；拼接后整体变速到目标时长，保证卡住配音。"""
    cmd, parts = ["ffmpeg", "-y", "-v", "error"], []
    raw_len = 0.0
    for i, c in enumerate(clips):
        cmd += ["-i", str(c["path"])]
        speed = c.get("speed") or 1.0
        raw_len += (c["end"] - c["start"]) / speed
        parts.append(f"[{i}:v]trim={c['start']}:{c['end']},setpts=(PTS-STARTPTS)/{speed},"
                     f"{_crop_filter(c.get('crop'))}{_fit(w, h)},fps={fps}[p{i}]")
    factor = duration / raw_len
    fc = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(clips)))
    fc += f"concat=n={len(clips)}:v=1:a=0[cat];[cat]setpts=PTS*{factor:.4f}[v]"
    _run(cmd + ["-filter_complex", fc, "-map", "[v]", "-an", "-t", f"{duration:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    return out


def assemble(segments: list[Path], audio_source: Path, out: Path,
             ai_label: str, font: str, workdir: Path) -> Path:
    lst = workdir / "segments.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segments), encoding="utf-8")
    label = ""
    if ai_label and Path(font).exists():
        label = (f",drawtext=fontfile='{font}':text='{ai_label}':fontsize=34:fontcolor=white@0.85:"
                 f"box=1:boxcolor=black@0.35:boxborderw=10:x=w-tw-30:y=40")
    elif ai_label:
        log.warning("找不到字体 %s，未加 AI 标识，交付前必须补上", font)
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-i", str(audio_source),
          "-filter_complex", f"[0:v]null{label}[v]",
          "-map", "[v]", "-map", "1:a:0", "-shortest",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
          "-movflags", "+faststart", str(out)])
    return out
