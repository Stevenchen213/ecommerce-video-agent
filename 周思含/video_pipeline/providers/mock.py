from __future__ import annotations

import subprocess
from pathlib import Path

from video_pipeline.compose.concat import FFMPEG
from video_pipeline.providers.base import GenerateResult, VideoProvider
from video_pipeline.schema import Shot


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            "命令失败: "
            + " ".join(cmd)
            + "\n"
            + (proc.stderr or proc.stdout or "")
        )


class MockColorCardProvider(VideoProvider):
    """用 FFmpeg 生成带文案的纯色卡，模拟平台出片（每镜必用）。"""

    def __init__(
        self,
        name: str,
        color: str,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
    ):
        self.name = name
        self.color = color
        self.width = width
        self.height = height
        self.fps = fps

    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        seg = shot.extra.get("segment_id")
        pos = shot.extra.get("segment_position")
        size = shot.extra.get("segment_size")
        if seg is not None and pos is not None and size is not None:
            label = f"{self.name}|{seg}|{pos + 1}/{size}|{shot.id}"
        else:
            label = f"{self.name}|{shot.id}|{shot.role}"
        # drawtext 对中文依赖字体；用英文标签保证 mock 在无中文字体环境也能跑
        text = label.replace(":", " ").replace("'", "")
        duration = max(0.5, float(shot.duration_sec))
        cmd = [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={self.color}:s={self.width}x{self.height}:d={duration}:r={self.fps}",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=stereo",
            "-vf",
            f"drawtext=text='{text}':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
        _run(cmd)
        return GenerateResult(
            provider=self.name,
            shot_id=shot.id,
            local_path=output_path,
            duration_sec=duration,
            width=self.width,
            height=self.height,
            task_id=f"mock-{self.name}-{shot.id}",
            raw={
                "mock": True,
                "text": shot.text,
                "segment_id": seg,
                "coherent_brief": shot.extra.get("coherent_brief"),
            },
        )


class MockFeiyingProvider(MockColorCardProvider):
    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30):
        super().__init__("feiying", "0x1a3a5c", width, height, fps)


class MockChanjingProvider(MockColorCardProvider):
    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30):
        super().__init__("chanjing", "0x1a5c3a", width, height, fps)
