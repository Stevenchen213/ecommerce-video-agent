from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class Platform(str, Enum):
    FEIYING = "feiying"  # 陈：数字人短片
    CHANJING = "chanjing"  # 路遥：产品 AI 短片


TransitionType = Literal["cut", "fade"]


class Shot(BaseModel):
    id: str = Field(..., description="镜头 ID = library 内文件名（不含扩展名）")
    role: str = Field(..., description="hook / host / product / cta / ...")
    platform: Platform
    text: str = Field("", description="口播或画面说明（给人看 / 旁白参考）")
    duration_sec: float = Field(3.0, gt=0)
    notes: str = ""
    person_id: str | None = None
    voice_id: str | None = None
    transition_in: TransitionType = "cut"
    fade_duration_sec: float = Field(0.35, gt=0, le=2.0)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def id_safe(cls, v: str) -> str:
        v = v.strip()
        if not v or any(ch in v for ch in r'\/:*?"<>|'):
            raise ValueError(f"非法 shot id: {v!r}")
        return v


class Script(BaseModel):
    title: str = "untitled"
    description: str = ""
    default_transition: TransitionType = "cut"
    brand_name: str | None = None
    shots: list[Shot]

    @field_validator("shots")
    @classmethod
    def unique_ids(cls, shots: list[Shot]) -> list[Shot]:
        if not shots:
            raise ValueError("脚本至少需要 1 个 shot")
        ids = [s.id for s in shots]
        if len(ids) != len(set(ids)):
            raise ValueError("shot.id 必须唯一")
        return shots


def load_script(path: str | Path) -> Script:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("脚本 YAML 根节点必须是 mapping")
    return Script.model_validate(data)
