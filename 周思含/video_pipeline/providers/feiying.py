"""飞影数字人 Provider — 真实 API 占位。"""

from __future__ import annotations

from pathlib import Path

from video_pipeline.providers.base import GenerateResult, NotConfiguredProvider, VideoProvider
from video_pipeline.schema import Shot


class FeiyingProvider(NotConfiguredProvider):
    """接入飞影数字人 API 后在此实现 generate()。"""

    def __init__(self, api_base: str = "", api_key: str = ""):
        super().__init__("feiying")
        self.api_base = api_base
        self.api_key = api_key

    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        if not self.api_base or not self.api_key:
            return super().generate(shot, output_path)
        # TODO: 调用飞影数字人 API，下载到 output_path
        raise NotImplementedError("飞影数字人真实 API 尚未实现")
