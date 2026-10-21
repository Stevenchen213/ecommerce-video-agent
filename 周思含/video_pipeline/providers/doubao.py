"""素材库 Provider — 从已拍摄素材库匹配/裁剪产品镜头，零成本复用素材。

陈铭嵩负责的产品镜头部分（替代已废弃的蝉镜）：
  1) 库里已有匹配片段 → 直接用（资产登记/标签表选择）
  2) 库里没有 → 提示兜底走 Seedance/AI 生成（本次不做真调）

镜头写法（YAML）：
  platform: doubao
  asset_refs: [xingan_packshot]        # 资产 ID（优先用 asset_id@start-end 秒裁剪）
  # 或：asset_file: 素材视频/C0255.MP4  # 直接按相对/绝对文件路径
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

from video_pipeline.providers.base import GenerateResult, VideoProvider
from video_pipeline.schema import Shot


class DoubaoProvider(VideoProvider):
    """doubao 平台名义上=产品镜头。本次实现用素材库，后续接 Seedance 图生视频。"""

    name = "doubao"
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

    def __init__(self, assets_dir: Path | str = ""):
        self.assets_dir = Path(assets_dir) if assets_dir else None

    def _resolve(self, shot: Shot) -> Path:
        """从 shot.asset_refs[0] 或 asset_file 定位素材文件（先剥离 @区间 后缀）。"""
        ref = shot.asset_refs[0] if shot.asset_refs else shot.extra.get("asset_file", "")
        ref = ref.split("@", 1)[0]
        p = Path(ref)
        if not p.is_absolute() and self.assets_dir:
            cand = self.assets_dir / p
            if cand.exists():
                p = cand
        if not p.exists():
            raise FileNotFoundError(
                f"shot={shot.id} 素材找不到: {ref}"
                f"（把素材放进 {self.assets_dir or '<绝对路径>'}，或写绝对路径）"
            )
        return p

    def _parse_range(self, shot: Shot) -> tuple[float | None, float | None]:
        """asset_id@start-end → 裁剪区间秒。"""
        if not shot.asset_refs:
            return None, None
        ref = shot.asset_refs[0]
        if "@" not in ref:
            return None, None
        _, rng = ref.split("@", 1)
        if "-" in rng:
            a, b = rng.split("-", 1)
            start = float(a) if a else 0.0
            return (start, float(b)) if b else (start, None)
        return 0.0, float(rng)

    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        src = self._resolve(shot)
        start, end = self._parse_range(shot)

        if start is None and end is None:
            # 全段：ffmpeg 重封装（直拷容器会丢元数据，时长读不出来）
            subprocess.run(
                [self.FFMPEG, "-y", "-v", "error", "-i", str(src),
                 "-c:v", "libx264", "-c:a", "aac", "-crf", "18", str(output_path)],
                capture_output=True, check=True)
            return GenerateResult(provider=self.name, shot_id=shot.id,
                                  local_path=output_path, raw={"source": str(src)})

        cmd = [self.FFMPEG, "-y", "-v", "error", "-ss", str(start), "-i", str(src)]
        if end is not None:
            cmd += ["-t", str(end - start)]
        cmd += ["-c:v", "libx264", "-c:a", "aac", "-crf", "18", str(output_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"素材裁剪失败 shot={shot.id}: {proc.stderr[-500:]}")
        return GenerateResult(provider=self.name, shot_id=shot.id,
                              local_path=output_path,
                              raw={"source": str(src), "range": [start, end]})
