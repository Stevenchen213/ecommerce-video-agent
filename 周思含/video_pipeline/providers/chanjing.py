"""蝉镜 Provider — 优先只读调用路遥模块；无配置时走占位/mock。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from video_pipeline.planner import ProductSegment, enrich_shot_with_segment
from video_pipeline.providers.base import GenerateResult, NotConfiguredProvider
from video_pipeline.schema import Shot


class ChanjingProvider(NotConfiguredProvider):
    """
    主架构蝉镜接口位。
    - 有路遥桥接且配置了 APP_ID/SECRET 时：产品镜走她的计划逻辑（实拍/图生）
    - 否则保持显式 NotConfigured / NotImplemented，便于 mock 联调
    """

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        app_id: str = "",
        secret_key: str = "",
        luyao_root: str = "",
    ):
        super().__init__("chanjing")
        self.api_base = api_base
        self.api_key = api_key
        self.app_id = app_id
        self.secret_key = secret_key
        self.luyao_root = luyao_root

    def _configured(self) -> bool:
        return bool(self.app_id and self.secret_key) or bool(self.api_base and self.api_key)

    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        if not self._configured():
            return super().generate(shot, output_path)
        # 单镜真实生成：后续由路遥产品函数补齐；当前先标明未实现
        raise NotImplementedError(
            "蝉镜单镜真实生成请用模式 A，或待路遥提供 gen_product() 后再接模式 B"
        )

    def generate_segment(
        self,
        segment: ProductSegment,
        path_for_shot: Callable[[Shot], Path],
    ) -> list[GenerateResult]:
        if not self._configured():
            return super().generate_segment(segment, path_for_shot)
        # 同段连贯上下文已注入；真实 API 仍等路遥可 import 的产品函数
        results: list[GenerateResult] = []
        for pos, shot in enumerate(segment.shots):
            enriched = enrich_shot_with_segment(shot, segment, pos)
            out = path_for_shot(shot)
            results.append(self.generate(enriched, out))
        return results
