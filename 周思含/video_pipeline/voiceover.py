"""完整音轨：整条脚本一次 TTS → 按句切开 → 每镜头一段音频。

陈铭嵩负责的「同一个李亚鹏声音贯穿全视频」：
- 数字人镜头：用各自音频段走 create_by_audio 音频驱动（口型准、语气连贯）
- 产品镜头：直接铺对应音频段（无需再调 TTS）
- 输出 timeline.json 给拼接/剪辑侧：每个镜头的精确起止时间
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from video_pipeline.compose.concat import FFMPEG, probe
from video_pipeline.schema import Script


@dataclass
class VoiceoverSegment:
    shot_id: str
    start: float
    end: float
    file: Path


@dataclass
class VoiceoverTrack:
    full_audio: Path
    duration: float
    segments: list[VoiceoverSegment] = field(default_factory=list)

    def to_json(self, path: Path) -> None:
        payload = {
            "full_audio": str(self.full_audio),
            "duration": self.duration,
            "segments": [
                {"shot_id": s.shot_id, "start": round(s.start, 3),
                 "end": round(s.end, 3), "file": str(s.file)}
                for s in self.segments
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _detect_pauses(audio: Path, noise_db: int = -35, min_gap: float = 0.2) -> list[float]:
    """silencedetect 找句间停顿的中点。"""
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(audio),
         "-af", f"silencedetect=n={noise_db}dB:d={min_gap}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end: ([\d.]+)", proc.stderr)]
    return [(s + e) / 2 for s, e in zip(starts, ends)]


def _split_points(pauses: list[float], weights: list[int], total: float) -> list[float]:
    """按文案长度比例定位理想切点，吸附到最近的停顿上。"""
    ideal, acc = [], 0
    for w in weights[:-1]:
        acc += w
        ideal.append(total * acc / sum(weights))
    points = []
    used = set()
    for t in ideal:
        best, best_d = None, total
        for p in pauses:
            if p in used:
                continue
            if abs(p - t) < best_d:
                best, best_d = p, abs(p - t)
        if best is not None and best_d < 1.5:
            points.append(best)
            used.add(best)
        else:
            points.append(t)  # 附近没停顿就按比例硬切
    return points


def build_voiceover(
    script: Script,
    provider,
    work_dir: Path,
    voice_id: str = "",
) -> VoiceoverTrack:
    """整脚本一次 TTS + 切分。provider 需有 generate_audio（飞影真实 API）。"""
    shots = [s for s in script.shots if s.text.strip()]
    if not shots:
        raise ValueError("脚本里没有带文案的镜头")
    work_dir.mkdir(parents=True, exist_ok=True)

    full_text = "。".join(s.text.strip().rstrip("。!！?？") for s in shots) + "。"
    full_audio = work_dir / "voiceover_full.wav"
    provider.generate_audio(full_text, full_audio, voice_id=voice_id, title=script.title)

    info = probe(full_audio)
    total = info.duration or 0
    if total <= 0:
        raise RuntimeError(f"无法读取音轨时长: {full_audio}")

    pauses = _detect_pauses(full_audio)
    weights = [max(1, len(s.text)) for s in shots]
    points = _split_points(pauses, weights, total)

    bounds = [0.0] + points + [total]
    track = VoiceoverTrack(full_audio=full_audio, duration=total)
    for i, shot in enumerate(shots):
        start, end = bounds[i], bounds[i + 1]
        seg_file = work_dir / f"{shot.id}_vo.wav"
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
             "-i", str(full_audio), "-c:a", "pcm_s16le", str(seg_file)],
            capture_output=True, check=True)
        track.segments.append(VoiceoverSegment(shot.id, start, end, seg_file))
    track.to_json(work_dir / "timeline.json")
    return track
