from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_pipeline.planner import ProductSegment, enrich_shot_with_segment
from video_pipeline.schema import Shot


@dataclass
class GenerateResult:
    provider: str
    shot_id: str
    local_path: Path
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    task_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class VideoProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        """根据镜头生成视频并写到 output_path（必用素材）。"""

    def generate_segment(
        self,
        segment: ProductSegment,
        path_for_shot: Callable[[Shot], Path],
    ) -> list[GenerateResult]:
        """
        按产品连续段生成。默认逐镜 generate，但注入段内连贯上下文。
        蝉镜真实 API 可覆盖：同段一次规划再拆成多文件。
        """
        results: list[GenerateResult] = []
        for pos, shot in enumerate(segment.shots):
            enriched = enrich_shot_with_segment(shot, segment, pos)
            out = path_for_shot(shot)
            result = self.generate(enriched, out)
            result.raw = {
                **result.raw,
                "segment_id": segment.id,
                "segment_position": pos,
                "segment_size": segment.size,
            }
            results.append(result)
        return results


class NotConfiguredProvider(VideoProvider):
    """真实 API 未配置时的显式失败占位。"""

    def __init__(self, name: str):
        self.name = name

    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        raise RuntimeError(
            f"Provider {self.name!r} 尚未配置真实 API。"
            f"请设置 USE_MOCK=1 或填写对应 API Key。"
            f" shot={shot.id}"
        )
