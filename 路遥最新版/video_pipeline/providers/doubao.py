"""产品镜头 Provider：素材库优先，查不到再走 Seedance 图生视频兜底。

查找顺序（命中即停）：
  1) asset_refs 显式指定     asset_refs: [秋梨糕-3.mp4@0-4]      ← 脚本里写死文件名
  2) asset_tags 标签匹配     asset_tags: [秋梨糕, 掰开特写]       ← 查 assets/asset_index.json
  3) AI 生成缓存             assets/ai_generated/<shot>_<hash>.mp4 ← 同 prompt+图 之前生成过
  4) Seedance 现场生成       需要 ARK_API_KEY；生成完存进第 3 层缓存，下次免费

asset_index.json 两种写法都支持：
  简单版（和豆包给的 MATERIAL_INDEX 一样）：
    {"掰开特写": "秋梨糕/8.3-3.mp4", "配料表": "秋梨糕/8.3-18.mp4@1-5"}
  完整版（推荐，可多标签、可带区间、可写画面描述；desc 会发给豆包做选镜）：
    [{"file": "秋梨糕/8.3-3.mp4", "tags": ["秋梨糕", "掰开特写"], "start": 0, "end": 4,
      "desc": "手把秋梨糕从中间掰开，酥皮掉渣，露出梨馅"}]

标签匹配规则：镜头写的每个标签都要命中（允许包含关系，如「掰开」命中「掰开特写」），
否则视为素材库没有 → 走 AI 缓存 / Seedance。只写一个产品名不会再随便配上别的镜头。
文件路径相对 root/assets/。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

from video_pipeline.providers.base import GenerateResult, VideoProvider
from video_pipeline.providers.seedance import SeedanceClient
from video_pipeline.schema import Shot

_SEGMENT_BRIEF_MARK = "\n\n[产品段连贯上下文"


@dataclass
class IndexEntry:
    file: str
    tags: list[str]
    start: float | None = None
    end: float | None = None
    desc: str = ""


def _parse_ref(ref: str) -> tuple[str, float | None, float | None]:
    """'file@start-end' → (file, start, end)；'file@4' → (file, 0, 4)。"""
    if "@" not in ref:
        return ref, None, None
    name, rng = ref.split("@", 1)
    if "-" in rng:
        a, b = rng.split("-", 1)
        return name, float(a) if a else 0.0, float(b) if b else None
    return name, 0.0, float(rng)


def load_asset_index(path: Path) -> list[IndexEntry]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[IndexEntry] = []
    if isinstance(data, dict):
        for tag, ref in data.items():
            f, s, e = _parse_ref(str(ref))
            entries.append(IndexEntry(file=f, tags=[tag], start=s, end=e))
    else:
        for item in data:
            entries.append(IndexEntry(
                file=item["file"], tags=list(item.get("tags", [])),
                start=item.get("start"), end=item.get("end"),
                desc=str(item.get("desc") or item.get("description") or ""),
            ))
    return entries


class DoubaoProvider(VideoProvider):
    name = "doubao"
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

    def __init__(
        self,
        assets_dir: Path | str = "",
        seedance: SeedanceClient | None = None,
        index_file: str = "asset_index.json",
    ):
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self.seedance = seedance
        self.index_path = (self.assets_dir / index_file) if self.assets_dir else None
        self._index: list[IndexEntry] | None = None

    # ---------- 素材查找 ----------

    @property
    def index(self) -> list[IndexEntry]:
        if self._index is None:
            self._index = load_asset_index(self.index_path) if self.index_path else []
        return self._index

    def _abs(self, ref: str) -> Path:
        p = Path(ref)
        if not p.is_absolute() and self.assets_dir:
            p = self.assets_dir / p
        return p

    def _by_refs(self, shot: Shot):
        ref = shot.asset_refs[0] if shot.asset_refs else shot.extra.get("asset_file", "")
        if not ref:
            return None
        f, s, e = _parse_ref(ref)
        p = self._abs(f)
        if not p.exists():
            # 显式写了却找不到：多半是文件名写错，不要悄悄花钱去生成
            raise FileNotFoundError(
                f"shot={shot.id} asset_refs 指定的素材不存在: {p}"
                f"（检查文件名；想让它自动兜底就删掉 asset_refs、改写 asset_tags）"
            )
        return p, s, e, f"asset_refs:{ref}"

    def _by_tags(self, shot: Shot):
        tags = [t.strip() for t in getattr(shot, "asset_tags", []) if t.strip()]
        if not tags or not self.index:
            return None
        best, best_extra = None, None
        for entry in self.index:
            # 每个镜头标签都必须命中；只命中产品名（如「秋梨糕」）不算
            if not all(any(t in et or et in t for et in entry.tags) for t in tags):
                continue
            if not self._abs(entry.file).exists():
                continue
            extra = len(entry.tags) - len(tags)  # 多余标签越少越贴切
            if best is None or extra < best_extra:
                best, best_extra = entry, extra
        if best is None:
            return None
        return self._abs(best.file), best.start, best.end, f"asset_tags:{best.tags}"

    def _ai_cache_path(self, shot: Shot) -> Path | None:
        if not self.assets_dir:
            return None
        key = f"{self._clean_prompt(shot)}|{getattr(shot, 'image_ref', '') or ''}"
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        return self.assets_dir / "ai_generated" / f"{shot.id}_{h}.mp4"

    @staticmethod
    def _clean_prompt(shot: Shot) -> str:
        # planner 会在 prompt 后面拼「产品段连贯上下文」，那是给人/规划看的，不发给 Seedance
        return (shot.prompt or shot.text or "").split(_SEGMENT_BRIEF_MARK, 1)[0].strip()

    @staticmethod
    def _target_sec(shot: Shot) -> float | None:
        # 优先：完整音轨模式按音频段长度写入的 target_duration_sec
        t = shot.extra.get("target_duration_sec")
        if t:
            return float(t)
        # 其次：脚本里显式写了 duration_sec（豆包规划出来的脚本都会写）
        if "duration_sec" in shot.model_fields_set:
            return float(shot.duration_sec)
        return None

    # ---------- 裁剪 ----------

    def _cut(self, src: Path, out: Path, start: float | None, end: float | None) -> None:
        cmd = [self.FFMPEG, "-y", "-v", "error"]
        if start:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(src)]
        if end is not None:
            cmd += ["-t", f"{end - (start or 0):.3f}"]
        # 重编码：直接拷贝容器会丢时长元数据，裁剪点也不准
        cmd += ["-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"素材裁剪失败 {src}: {proc.stderr[-500:]}")

    # ---------- 主入口 ----------

    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target = self._target_sec(shot)

        hit = self._by_refs(shot) or self._by_tags(shot)
        if hit:
            src, start, end, how = hit
            if end is None and target:
                end = (start or 0) + target
            self._cut(src, output_path, start, end)
            print(f"  [素材库] {shot.id} 命中 {how} → {src.name}", flush=True)
            return GenerateResult(provider=self.name, shot_id=shot.id, local_path=output_path,
                                  raw={"source": "library", "file": str(src), "match": how,
                                       "range": [start, end]})

        cache = self._ai_cache_path(shot)
        if cache and cache.exists():
            self._cut(cache, output_path, None, target)
            print(f"  [AI缓存] {shot.id} 复用 {cache.name}（不再计费）", flush=True)
            return GenerateResult(provider=self.name, shot_id=shot.id, local_path=output_path,
                                  raw={"source": "ai_cache", "file": str(cache)})

        if self.seedance is None:
            raise FileNotFoundError(
                f"shot={shot.id} 素材库没有匹配（asset_tags={getattr(shot, 'asset_tags', [])}），"
                f"且未配置 ARK_API_KEY / SEEDANCE_MODEL，无法 AI 兜底"
            )

        image = getattr(shot, "image_ref", None)
        if image and not str(image).startswith(("http://", "https://", "data:")):
            p = self._abs(str(image))
            image = str(p) if p.exists() else image
        print(f"  [素材库] {shot.id} 未命中 → Seedance 生成（{'图生' if image else '文生'}视频）", flush=True)
        dest = cache or output_path.with_name(output_path.stem + "_ai_raw.mp4")
        info = self.seedance.generate(self._clean_prompt(shot), dest, image=image, need_sec=target)
        self._cut(dest, output_path, None, target)
        return GenerateResult(provider=self.name, shot_id=shot.id, local_path=output_path,
                              task_id=info["task_id"],
                              raw={"source": "seedance", "cache": str(dest), **info})
