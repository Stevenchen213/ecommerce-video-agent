"""只读引用仓库内蝉镜侧交付物（chanjing 包），不修改对方目录。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class ChanjingBridgeError(RuntimeError):
    pass


def _candidates(explicit: str = "") -> list[Path]:
    here = Path(__file__).resolve()
    # .../周思含_短片编排/app/chanjing_bridge.py → parents[2]=电商视频剪辑AI
    workspace = here.parents[2]
    return [
        Path(explicit) if explicit else Path(),
        Path(os.getenv("CHANJING_ROOT", "")),
        Path(os.getenv("LUYAO_ROOT", "")),
        workspace / "_deps" / "ecommerce-video-agent" / "路遥",
        workspace / "ecommerce-video-agent" / "路遥",
    ]


def resolve_chanjing_root(explicit: str = "") -> Path:
    for cand in _candidates(explicit):
        if not cand or str(cand) in {".", ""}:
            continue
        p = cand.resolve()
        if (p / "chanjing" / "client.py").exists() and (p / "chanjing" / "ai_creation.py").exists():
            return p
    raise ChanjingBridgeError(
        "找不到蝉镜侧代码目录。请在设置里填写 chanjing_root，"
        "或 clone 仓库到 _deps/ecommerce-video-agent/路遥"
    )


def ensure_import_path(root: Path) -> None:
    s = str(root.resolve())
    if s not in sys.path:
        sys.path.insert(0, s)


def load_chanjing_modules(explicit_root: str = ""):
    root = resolve_chanjing_root(explicit_root)
    ensure_import_path(root)
    from chanjing import ai_creation  # type: ignore
    from chanjing.client import ChanjingClient  # type: ignore

    return root, ChanjingClient, ai_creation
