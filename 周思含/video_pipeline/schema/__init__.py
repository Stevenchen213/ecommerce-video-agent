from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class Platform(str, Enum):
    FEIYING = "feiying"  # 飞影数字人
    CHANJING = "chanjing"  # 蝉镜（产品镜头）


TransitionType = Literal["cut", "fade"]


class Shot(BaseModel):
    id: str = Field(..., description="镜头唯一 ID，也是库内文件名")
    role: str = Field(..., description="hook / host / product_closeup / product_break / cta / ...")
    platform: Platform
    text: str = Field("", description="口播文案或画面说明")
    duration_sec: float = Field(3.0, gt=0, description="目标时长秒")
    prompt: str = Field("", description="给生成 API 的提示词（可选）")
    notes: str = Field("", description="备注，给人看")
    person_id: str | None = Field(None, description="数字人 ID（飞影等）")
    voice_id: str | None = Field(None, description="声音 ID")
    aspect: str = Field("9:16", description="期望画幅，如 9:16 / 16:9")
    transition_in: TransitionType = Field("cut", description="进入本镜的转场：cut|fade")
    fade_duration_sec: float = Field(0.4, gt=0, le=2.0, description="fade 转场时长")
    asset_refs: list[str] = Field(default_factory=list, description="产品镜素材 ID（对接路遥）")
    overlay_asset_refs: list[str] = Field(
        default_factory=list, description="数字人画面叠加素材（对接路遥）"
    )
    extra: dict[str, Any] = Field(default_factory=dict, description="平台私有扩展字段")

    @field_validator("id")
    @classmethod
    def id_safe(cls, v: str) -> str:
        v = v.strip()
        if not v or any(ch in v for ch in r'\/:*?"<>|'):
            raise ValueError(f"非法 shot id: {v!r}")
        return v


class BrandOptions(BaseModel):
    enable: bool = True
    overlay_logo: bool = True
    mix_bgm: bool = True
    append_endcard: bool = True
    bgm_volume: float = Field(0.12, ge=0.0, le=1.0)
    logo_margin: int = Field(48, ge=0)


class ScriptAsset(BaseModel):
    asset_id: str
    file: str = ""
    url: str | None = None
    description: str = ""


class Script(BaseModel):
    title: str = "untitled"
    description: str = ""
    default_transition: TransitionType = "cut"
    brand: BrandOptions = Field(default_factory=BrandOptions)
    brand_name: str | None = Field(None, description="品牌名（路遥授权校验用）")
    assets: list[ScriptAsset] = Field(default_factory=list, description="路遥素材库条目")
    compliance: dict[str, Any] | None = Field(
        None, description="合规字段；默认空禁用词 + 要求 AI 标识"
    )
    extra: dict[str, Any] = Field(default_factory=dict)
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
