"""用 ffmpeg 把数字人片段与产品片段按时间轴拼成成片，统一音轨并加 AI 标识。"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("composer")


# 产品镜头允许的变速范围：超出就会肉眼可见地快进/慢放
SPEED_MIN, SPEED_MAX = 0.8, 1.25


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    log.debug(" ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
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
    """clips: [{path, start, end, speed, crop}]，拼成一段正好 duration 秒的画面。

    时长对齐策略（避免肉眼可见的快进）：
      - 素材比目标长：不变速，直接截取开头 duration 秒（图生视频的开头最接近参考图，最不易变形）
      - 素材略短/略长：在 0.8~1.25 倍范围内微调速度
      - 素材明显偏短：放慢到 0.8 倍后，用最后一帧定格补足
    """
    cmd, parts = ["ffmpeg", "-y", "-v", "error"], []
    raw_len = 0.0
    for i, c in enumerate(clips):
        cmd += ["-i", str(c["path"])]
        speed = c.get("speed") or 1.0
        raw_len += (c["end"] - c["start"]) / speed
        parts.append(f"[{i}:v]trim={c['start']}:{c['end']},setpts=(PTS-STARTPTS)/{speed},"
                     f"{_crop_filter(c.get('crop'))}{_fit(w, h)},fps={fps}[p{i}]")

    stretch = duration / raw_len            # 时间拉伸倍数：>1 放慢，<1 加快
    if stretch < 1.0 / SPEED_MAX:           # 素材明显偏长：不加速，直接截取
        stretch = 1.0
    elif stretch > 1.0 / SPEED_MIN:         # 素材明显偏短：最多放慢到 0.8 倍，其余定格
        stretch = 1.0 / SPEED_MIN
    tail = f",setpts=PTS*{stretch:.4f}" if abs(stretch - 1.0) > 1e-3 else ""
    shortfall = duration - raw_len * stretch
    if shortfall > 0.02:
        tail += f",tpad=stop_mode=clone:stop_duration={shortfall + 0.1:.3f}"
        log.warning("%s 素材不足，最后 %.2fs 用定格补齐", out.name, shortfall)

    fc = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(clips)))
    fc += f"concat=n={len(clips)}:v=1:a=0[cat];[cat]null{tail}[v]"
    _run(cmd + ["-filter_complex", fc, "-map", "[v]", "-an", "-t", f"{duration:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    return out


def assemble(segments: list[Path], audio_source: Path, out: Path,
             ai_label: str, font: str, workdir: Path) -> Path:
    """拼接全部片段 + 铺统一音轨 + 加 AI 显式标识。

    AI 标识是合规要求：设置了标识文字但找不到字体时直接报错，不再静默跳过。
    只有显式把 AI_LABEL_TEXT 设为空（本地调试）才会不加标识。
    字体和文字都复制到工作目录、用相对路径引用，避开 Windows 盘符冒号在 ffmpeg 滤镜里的转义问题。
    """
    workdir = workdir.resolve()
    out = out.resolve()
    lst = workdir / "segments.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segments), encoding="utf-8")

    label = ""
    if ai_label:
        if not Path(font).exists():
            raise RuntimeError(f"找不到 AI 标识字体 {font}。请设置 AI_LABEL_FONT 指向一个中文字体文件；"
                               "成片必须带 AI 生成标识")
        shutil.copyfile(font, workdir / ("label_font" + Path(font).suffix))
        (workdir / "label.txt").write_text(ai_label, encoding="utf-8")
        label = (f",drawtext=fontfile='label_font{Path(font).suffix}':textfile='label.txt':"
                 f"fontsize=34:fontcolor=white@0.85:box=1:boxcolor=black@0.35:boxborderw=10:"
                 f"x=w-tw-30:y=40")
    else:
        log.warning("AI_LABEL_TEXT 为空，本次成片没有 AI 标识，仅限内部调试，不能交付")

    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name,
          "-i", str(Path(audio_source).resolve()),
          "-filter_complex", f"[0:v]null{label}[v]",
          "-map", "[v]", "-map", "1:a:0", "-shortest",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
          "-movflags", "+faststart", str(out)], cwd=workdir)
    return out
