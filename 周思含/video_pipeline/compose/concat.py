from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from video_pipeline.schema import Shot, TransitionType


def _ffmpeg_exe() -> str:
    """优先系统 PATH；没有则用 imageio_ffmpeg 自带二进制（免装 ffmpeg）。"""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FFMPEG = _ffmpeg_exe()
FFPROBE = shutil.which("ffprobe")  # imageio_ffmpeg 不带 ffprobe，缺失时 probe 走 ffmpeg -i 解析


def _probe_via_ffmpeg(path: Path) -> MediaInfo:
    """无 ffprobe 时用 ffmpeg -i 的 stderr 解析元数据。"""
    proc = _run([FFMPEG, "-hide_banner", "-i", str(path)])
    info = proc.stderr or ""
    duration = None
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    width = height = None
    fps = None
    has_audio = "Audio:" in info
    vm = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    if vm:
        width, height = int(vm.group(1)), int(vm.group(2))
    fm = re.search(r"([\d.]+) fps", info)
    if fm:
        fps = float(fm.group(1))
    return MediaInfo(path, duration, width, height, has_audio, fps)


@dataclass
class MediaInfo:
    path: Path
    duration: float | None
    width: int | None
    height: int | None
    has_audio: bool
    fps: float | None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path: Path) -> MediaInfo:
    if not FFPROBE:
        return _probe_via_ffmpeg(path)
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {path}\n{proc.stderr}")
    data = json.loads(proc.stdout or "{}")
    duration = None
    if "format" in data and data["format"].get("duration"):
        duration = float(data["format"]["duration"])
    width = height = None
    has_audio = False
    fps = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = stream.get("width")
            height = stream.get("height")
            rate = stream.get("r_frame_rate") or "0/1"
            try:
                num, den = rate.split("/")
                fps = float(num) / float(den) if float(den) else None
            except Exception:
                fps = None
        elif stream.get("codec_type") == "audio":
            has_audio = True
    return MediaInfo(path, duration, width, height, has_audio, fps)


def _normalize_clip(
    src: Path,
    dest: Path,
    width: int,
    height: int,
    fps: int,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"
    )
    if info.has_audio:
        cmd = [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(dest),
        ]
    else:
        cmd = [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(dest),
        ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"normalize 失败: {src}\n{proc.stderr}")
    return dest


def mux_narration(src: Path, narration: Path, dest: Path) -> Path:
    """把旁白音频铺到（无声的）产品镜头上，替换其音轨。旁白比画面长则截断。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG,
        "-y",
        "-i",
        str(src),
        "-i",
        str(narration),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(dest),
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"旁白叠加失败: {src} + {narration}\n{proc.stderr}")
    return dest


@dataclass
class ConcatResult:
    output_path: Path
    duration_sec: float | None
    segment_count: int


def _hard_concat(normalized: list[Path], output_path: Path, work_dir: Path) -> None:
    list_file = work_dir / "concat_list.txt"
    lines = [f"file '{p.resolve().as_posix()}'" for p in normalized]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd_copy = [
        FFMPEG,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(output_path),
    ]
    proc = _run(cmd_copy)
    if proc.returncode != 0:
        cmd_re = [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(output_path),
        ]
        proc2 = _run(cmd_re)
        if proc2.returncode != 0:
            raise RuntimeError(f"concat 失败\n{proc.stderr}\n{proc2.stderr}")


def _fade_concat(
    normalized: list[Path],
    output_path: Path,
    work_dir: Path,
    fade_secs: list[float],
) -> None:
    """相邻镜头用 xfade/acrossfade。fade_secs[i] 表示进入第 i 段的淡化时长（i=0 忽略）。"""
    if len(normalized) == 1:
        output_path.write_bytes(normalized[0].read_bytes())
        return

    current = normalized[0]
    for i in range(1, len(normalized)):
        nxt = normalized[i]
        fade = max(0.05, float(fade_secs[i] if i < len(fade_secs) else 0.4))
        info_a = probe(current)
        info_b = probe(nxt)
        da = info_a.duration or 0
        db = info_b.duration or 0
        # offset 必须落在第一段内
        fade = min(fade, max(0.05, da - 0.05), max(0.05, db - 0.05))
        offset = max(0.0, da - fade)
        out = work_dir / f"xfade_{i:03d}.mp4"
        filt = (
            f"[0:v][1:v]xfade=transition=fade:duration={fade}:offset={offset}[v];"
            f"[0:a][1:a]acrossfade=d={fade}[a]"
        )
        cmd = [
            FFMPEG,
            "-y",
            "-i",
            str(current),
            "-i",
            str(nxt),
            "-filter_complex",
            filt,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(out),
        ]
        proc = _run(cmd)
        if proc.returncode != 0:
            raise RuntimeError(f"xfade 失败 idx={i}\n{proc.stderr}")
        current = out
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(current.read_bytes())


def concat_segments(
    segments: list[Path],
    output_path: Path,
    *,
    work_dir: Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    transitions: list[TransitionType] | None = None,
    fade_durations: list[float] | None = None,
) -> ConcatResult:
    if not segments:
        raise ValueError("没有可拼接的片段")
    for p in segments:
        if not p.exists():
            raise FileNotFoundError(f"缺少必用镜头文件: {p}")

    work_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    for i, src in enumerate(segments):
        dest = work_dir / f"norm_{i:03d}_{src.stem}.mp4"
        _normalize_clip(src, dest, width, height, fps)
        normalized.append(dest)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    transitions = transitions or ["cut"] * len(segments)
    fade_durations = fade_durations or [0.4] * len(segments)
    use_fade = any(t == "fade" for t in transitions[1:])

    if use_fade:
        # 非 fade 的接缝用极短 fade 近似硬切，简化实现
        fades = []
        for i, t in enumerate(transitions):
            if i == 0:
                fades.append(0.0)
            elif t == "fade":
                fades.append(fade_durations[i] if i < len(fade_durations) else 0.4)
            else:
                fades.append(0.05)
        _fade_concat(normalized, output_path, work_dir, fades)
    else:
        _hard_concat(normalized, output_path, work_dir)

    info = probe(output_path)
    return ConcatResult(
        output_path=output_path,
        duration_sec=info.duration,
        segment_count=len(segments),
    )


def transitions_from_shots(
    shots: list[Shot],
    default: TransitionType = "cut",
) -> tuple[list[TransitionType], list[float]]:
    transitions: list[TransitionType] = []
    fades: list[float] = []
    for i, shot in enumerate(shots):
        if i == 0:
            transitions.append("cut")
            fades.append(0.0)
        else:
            t = shot.transition_in or default
            transitions.append(t)
            fades.append(shot.fade_duration_sec)
    return transitions, fades
