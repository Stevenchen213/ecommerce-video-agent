from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from video_pipeline.schema import Platform, Script, Shot


@dataclass(frozen=True)
class ProductSegment:
    """第二步：被数字人切开后的连续产品段。"""

    id: str
    index: int
    shots: tuple[Shot, ...]
    script_start: int
    script_end: int  # inclusive

    @property
    def shot_ids(self) -> list[str]:
        return [s.id for s in self.shots]

    @property
    def size(self) -> int:
        return len(self.shots)

    @property
    def coherent_brief(self) -> str:
        """给蝉镜的连贯上下文：同段内镜头按顺序拼成一段说明。"""
        parts: list[str] = []
        n = len(self.shots)
        for i, shot in enumerate(self.shots, 1):
            body = (shot.text or shot.prompt or shot.role or shot.id).strip()
            parts.append(f"[{i}/{n}] {shot.id}: {body}")
        return " → ".join(parts)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "index": self.index,
            "shot_ids": self.shot_ids,
            "size": self.size,
            "script_start": self.script_start,
            "script_end": self.script_end,
            "coherent_brief": self.coherent_brief,
        }


@dataclass(frozen=True)
class TimelineUnit:
    """按脚本顺序的生成单元：数字人单镜，或一段连续产品。"""

    kind: Literal["feiying", "product_segment"]
    shot: Shot | None = None
    segment: ProductSegment | None = None

    def to_dict(self) -> dict:
        if self.kind == "feiying":
            assert self.shot is not None
            return {"kind": "feiying", "shot_id": self.shot.id}
        assert self.segment is not None
        return {
            "kind": "product_segment",
            "segment_id": self.segment.id,
            "shot_ids": self.segment.shot_ids,
        }


@dataclass(frozen=True)
class Plan:
    feiying_shots: list[Shot]
    chanjing_shots: list[Shot]
    product_segments: list[ProductSegment]
    timeline: list[TimelineUnit]

    @property
    def all_shots(self) -> list[Shot]:
        # 仅用于 ID 校验；成片顺序仍看 Script.shots
        return [*self.feiying_shots, *self.chanjing_shots]

    def to_dict(self) -> dict:
        return {
            "feiying": [s.id for s in self.feiying_shots],
            "chanjing": [s.id for s in self.chanjing_shots],
            "product_segments": [seg.to_dict() for seg in self.product_segments],
            "timeline": [u.to_dict() for u in self.timeline],
        }


def enrich_shot_with_segment(shot: Shot, segment: ProductSegment, position: int) -> Shot:
    """把产品段连贯上下文写入 shot.extra / prompt，供 Provider 使用。"""
    extra = {
        **shot.extra,
        "segment_id": segment.id,
        "segment_index": segment.index,
        "segment_size": segment.size,
        "segment_position": position,
        "segment_shot_ids": segment.shot_ids,
        "coherent_brief": segment.coherent_brief,
    }
    prompt = shot.prompt.strip()
    brief = segment.coherent_brief
    if brief and brief not in prompt:
        prompt = f"{prompt}\n\n[产品段连贯上下文 {segment.id}]\n{brief}".strip()
    return shot.model_copy(update={"extra": extra, "prompt": prompt})


def _group_product_segments(script: Script) -> list[ProductSegment]:
    """第二步：按脚本顺序，把相邻 chanjing 镜聚成连续产品段。"""
    segments: list[ProductSegment] = []
    buf: list[tuple[int, Shot]] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        idx = len(segments)
        start_i = buf[0][0]
        end_i = buf[-1][0]
        shots = tuple(s for _, s in buf)
        segments.append(
            ProductSegment(
                id=f"prod_seg_{idx}",
                index=idx,
                shots=shots,
                script_start=start_i,
                script_end=end_i,
            )
        )
        buf = []

    for i, shot in enumerate(script.shots):
        if shot.platform == Platform.CHANJING:
            buf.append((i, shot))
        else:
            flush()
    flush()
    return segments


def plan_script(script: Script) -> Plan:
    """
    两步分类：
    1) 按 platform 分出飞影数字人 / 蝉镜产品
    2) 在产品侧按脚本顺序聚相邻镜为连续段，便于连贯生成
    """
    feiying: list[Shot] = []
    chanjing: list[Shot] = []
    for shot in script.shots:
        if shot.platform == Platform.FEIYING:
            feiying.append(shot)
        elif shot.platform == Platform.CHANJING:
            chanjing.append(shot)
        else:
            raise ValueError(f"未知 platform: {shot.platform}")

    product_segments = _group_product_segments(script)
    seg_by_start = {seg.script_start: seg for seg in product_segments}

    timeline: list[TimelineUnit] = []
    i = 0
    n = len(script.shots)
    while i < n:
        shot = script.shots[i]
        if shot.platform == Platform.FEIYING:
            timeline.append(TimelineUnit(kind="feiying", shot=shot))
            i += 1
            continue
        if shot.platform == Platform.CHANJING:
            seg = seg_by_start.get(i)
            if seg is None:
                raise RuntimeError(f"产品镜 {shot.id} 未落入任何产品段")
            timeline.append(TimelineUnit(kind="product_segment", segment=seg))
            i = seg.script_end + 1
            continue
        raise ValueError(f"未知 platform: {shot.platform}")

    return Plan(
        feiying_shots=feiying,
        chanjing_shots=chanjing,
        product_segments=product_segments,
        timeline=timeline,
    )
