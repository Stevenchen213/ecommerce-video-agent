"""周思含 Script/YAML ↔ 路遥分镜 JSON 字段对照。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import json

from video_pipeline.schema import Platform, Script, Shot


@dataclass
class IdMap:
    """她侧 shot_id 为 int；我们侧为字符串 id。"""

    to_int: dict[str, int] = field(default_factory=dict)
    to_str: dict[int, str] = field(default_factory=dict)

    def add(self, our_id: str, their_id: int) -> None:
        self.to_int[our_id] = their_id
        self.to_str[their_id] = our_id


def _shot_type(shot: Shot) -> str:
    if shot.platform == Platform.FEIYING:
        return "avatar"
    if shot.platform == Platform.CHANJING:
        return "product"
    raise ValueError(f"未知 platform: {shot.platform}")


def _transition(shot: Shot) -> str:
    # 她侧枚举更宽；未知时退回 cut
    t = shot.transition_in or "cut"
    return t if t in {"cut", "fade", "zoom"} else "cut"


def _visual(shot: Shot) -> dict[str, Any]:
    refs = list(shot.asset_refs)
    overlays = list(shot.overlay_asset_refs)
    clips = list(shot.extra.get("clips") or [])
    return {
        "description": (shot.prompt or shot.text or shot.role or "").strip(),
        "camera": str(shot.extra.get("camera") or ""),
        "asset_refs": refs,
        "overlay_asset_refs": overlays,
        **({"clips": clips} if clips else {}),
    }


def script_to_luyao_dict(script: Script) -> tuple[dict[str, Any], IdMap]:
    """
    把主架构 Script 转成路遥 orchestrator 可消费的分镜 dict。
    返回 (luyao_script, id_map)。
    """
    id_map = IdMap()
    shots_out: list[dict[str, Any]] = []
    voice_parts: list[str] = []

    person_id = None
    voice_id = None
    figure_type = None
    for shot in script.shots:
        if shot.platform == Platform.FEIYING:
            person_id = person_id or shot.person_id
            voice_id = voice_id or shot.voice_id
            figure_type = figure_type or shot.extra.get("figure_type")

    for i, shot in enumerate(script.shots, start=1):
        id_map.add(shot.id, i)
        vo = (shot.text or "").strip()
        voice_parts.append(vo)
        shots_out.append(
            {
                "shot_id": i,
                "origin_id": shot.id,
                "type": _shot_type(shot),
                "purpose": shot.role,
                "duration_sec": float(shot.duration_sec),
                "voiceover": vo,
                "on_screen_text": str(shot.extra.get("on_screen_text") or ""),
                "visual": _visual(shot),
                "transition": _transition(shot),
            }
        )

    voiceover_full = "".join(voice_parts)
    assets = [
        {
            "asset_id": a.asset_id,
            "file": a.file,
            **({"url": a.url} if a.url else {}),
            **({"description": a.description} if a.description else {}),
        }
        for a in script.assets
    ]

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "ready",
        "project": {
            "product_name": script.title,
            "brand": script.brand_name or "",
            "category": script.extra.get("category", ""),
            "target_duration_sec": round(sum(s.duration_sec for s in script.shots), 3),
            "aspect_ratio": script.shots[0].aspect if script.shots else "9:16",
            "language": "zh-CN",
        },
        "global_style": script.extra.get("global_style") or {},
        "avatar": {
            "person_id": person_id,
            "voice_id": voice_id,
            "figure_type": figure_type,
            "authorization_required": True,
            "authorization_ref": None,
        },
        "compliance": script.compliance
        or {
            "banned_terms": [],
            "checked": True,
            "ai_label": True,
        },
        "placeholders": [],
        "assets": assets,
        "shots": shots_out,
        "voiceover_full": voiceover_full,
        "origin": {
            "framework": "zhou_sihan_video_pipeline",
            "title": script.title,
            "description": script.description,
        },
    }
    return payload, id_map


def write_luyao_script(script: Script, path: str | Path) -> IdMap:
    payload, id_map = script_to_luyao_dict(script)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return id_map
