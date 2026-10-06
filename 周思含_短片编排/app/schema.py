from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class Platform(str, Enum):
    FEIYING = "feiying"  # 数字人短片
    CHANJING = "chanjing"  # 产品 AI 短片


TransitionType = Literal["cut", "fade"]


class ScriptAsset(BaseModel):
    asset_id: str
    file: str = ""
    url: str | None = None
    description: str = ""


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
    asset_refs: list[str] = Field(default_factory=list, description="产品素材 ID 列表")
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
    assets: list[ScriptAsset] = Field(default_factory=list, description="产品素材库（图/视频）")
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


def save_script(script: Script, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = script.model_dump(mode="json")
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def import_luyao_shots_json(data: dict) -> Script:
    """粗映射蝉镜侧 shots.json → 本系统 Script。"""
    if not isinstance(data, dict):
        raise ValueError("分镜 JSON 必须是 object")
    project = data.get("project") or {}
    shots_in = data.get("shots") or []
    shots: list[Shot] = []
    for s in shots_in:
        sid = s.get("origin_id") or f"shot_{s.get('shot_id')}"
        typ = s.get("type")
        platform = Platform.FEIYING if typ == "avatar" else Platform.CHANJING
        tr = s.get("transition") if s.get("transition") in ("cut", "fade") else "cut"
        vis = s.get("visual") or {}
        refs = list(vis.get("asset_refs") or [])
        shots.append(
            Shot(
                id=str(sid),
                role=str(s.get("purpose") or typ or "shot"),
                platform=platform,
                text=str(s.get("voiceover") or ""),
                duration_sec=float(s.get("duration_sec") or 3),
                notes=str(vis.get("description") or ""),
                transition_in=tr,
                asset_refs=refs,
                extra={
                    "on_screen_text": s.get("on_screen_text"),
                    "visual": vis,
                },
            )
        )
    avatar = data.get("avatar") or {}
    for sh in shots:
        if sh.platform == Platform.FEIYING:
            if not sh.person_id:
                sh.person_id = avatar.get("person_id")
            if not sh.voice_id:
                sh.voice_id = avatar.get("voice_id")
    assets = [
        ScriptAsset(
            asset_id=str(a.get("asset_id")),
            file=str(a.get("file") or ""),
            url=a.get("url"),
            description=str(a.get("description") or ""),
        )
        for a in (data.get("assets") or [])
        if a.get("asset_id")
    ]
    return Script(
        title=str(project.get("product_name") or data.get("title") or "imported"),
        description="从分镜 JSON 导入",
        brand_name=project.get("brand"),
        assets=assets,
        shots=shots,
    )
