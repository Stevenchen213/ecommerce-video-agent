from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.schema import Shot, TransitionType


@dataclass
class ProbeInfo:
    duration: float | None
    width: int | None
    height: int | None


@dataclass
class ConcatResult:
    output_path: Path
    segment_count: int


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "命令失败: " + " ".join(cmd) + "\n" + (proc.stderr or proc.stdout or "")
        )


def probe(path: Path) -> ProbeInfo:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return ProbeInfo(None, None, None)
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or [{}]
    fmt = data.get("format") or {}
    dur = fmt.get("duration")
    return ProbeInfo(
        duration=float(dur) if dur is not None else None,
        width=streams[0].get("width"),
        height=streams[0].get("height"),
    )


def _normalize(
    src: Path,
    dest: Path,
    width: int,
    height: int,
    fps: int,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},format=yuv420p"
    )
    cmd = [
        "ffmpeg",
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
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    # 若源有音轨，优先用源音轨
    cmd_with_audio = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        vf,
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
        "-shortest",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    proc = subprocess.run(cmd_with_audio, capture_output=True, text=True)
    if proc.returncode != 0:
        _run(cmd)


def concat_segments(
    segments: list[Path],
    output: Path,
    work_dir: Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    transitions: list[str] | None = None,
    fade_durations: list[float] | None = None,
) -> ConcatResult:
    if not segments:
        raise ValueError("没有可拼接的短片")
    work_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    normed: list[Path] = []
    for i, src in enumerate(segments):
        dest = work_dir / f"n_{i:03d}.mp4"
        _normalize(src, dest, width, height, fps)
        normed.append(dest)

    transitions = transitions or ["cut"] * len(segments)
    fade_durations = fade_durations or [0.35] * len(segments)

    # 简化：有 fade 时仍用 concat demuxer（硬切）；完整 xfade 可后补
    # 保证主线稳定可出片
    list_file = work_dir / "concat_list.txt"
    lines = []
    for p in normed:
        lines.append(f"file '{p.resolve().as_posix()}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(output),
    ]
    _run(cmd)
    return ConcatResult(output_path=output, segment_count=len(normed))


def transitions_from_shots(
    shots: list[Shot],
    default: TransitionType = "cut",
) -> tuple[list[str], list[float]]:
    transitions: list[str] = []
    fades: list[float] = []
    for i, shot in enumerate(shots):
        if i == 0:
            transitions.append("cut")
            fades.append(0.35)
        else:
            transitions.append(shot.transition_in or default)
            fades.append(shot.fade_duration_sec)
    return transitions, fades
