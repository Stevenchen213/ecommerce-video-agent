"""本地只读引用路遥蝉镜编排；不修改她的仓库目录。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_pipeline.adapters.luyao_script import IdMap, write_luyao_script
from video_pipeline.schema import Script


class LuyaoBridgeError(RuntimeError):
    pass


def _default_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    # 脚本驱动双平台视频组装/video_pipeline/adapters → 上溯到 电商视频剪辑AI
    workspace = here.parents[3]
    return [
        Path(os.getenv("LUYAO_ROOT", "")),
        workspace / "_deps" / "ecommerce-video-agent" / "路遥",
        workspace / "ecommerce-video-agent" / "路遥",
        Path.cwd() / "路遥",
    ]


def resolve_luyao_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not root.is_dir():
            raise LuyaoBridgeError(f"LUYAO_ROOT 不是目录: {root}")
        return root
    for cand in _default_candidates():
        if not cand or str(cand) in {".", ""}:
            continue
        p = cand.resolve()
        if (p / "pipeline" / "orchestrator.py").exists():
            return p
    raise LuyaoBridgeError(
        "找不到路遥代码目录。请设置 LUYAO_ROOT，或先 clone 到 "
        "_deps/ecommerce-video-agent/路遥"
    )


def _ensure_import_path(luyao_root: Path) -> None:
    root = str(luyao_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


@dataclass
class ModeAResult:
    ok: bool
    stage: str
    output_path: Path | None
    plan_path: Path | None
    luyao_script_path: Path
    id_map: IdMap
    raw: dict[str, Any]


def run_mode_a(
    script: Script,
    *,
    workdir: str | Path,
    output: str | Path,
    person_id: str,
    voice_id: str,
    brand: str | None = None,
    dry_run: bool = False,
    mock_avatar_video: str | None = None,
    luyao_root: str | Path | None = None,
    assets_dir: str | None = None,
    registry: str | None = None,
    fills: dict[str, str] | None = None,
) -> ModeAResult:
    """
    模式 A：YAML/Script → 路遥 JSON → 她的 orchestrator（整段口播切轨成片）。
    只 import 她的包，不改她的文件。
    """
    root = resolve_luyao_root(luyao_root)
    _ensure_import_path(root)

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    luyao_script_path = workdir / "luyao_script.json"
    id_map = write_luyao_script(script, luyao_script_path)

    from pipeline.orchestrator import JobConfig, run  # type: ignore

    cfg = JobConfig(
        script_path=str(luyao_script_path),
        person_id=person_id,
        voice_id=voice_id,
        brand=brand or script.brand_name,
        fills=fills or {},
        assets_dir=assets_dir or str(workdir / "assets"),
        registry=registry or str(root / "authorized_avatars.json"),
        workdir=str(workdir / "luyao_work"),
        output=str(output),
        dry_run=dry_run,
        mock_avatar_video=mock_avatar_video,
    )
    raw = run(cfg)
    plan_path = Path(cfg.workdir) / "plan.json"
    out = Path(raw["output"]) if raw.get("output") else None
    return ModeAResult(
        ok=bool(raw.get("ok")),
        stage=str(raw.get("stage") or ("done" if raw.get("ok") else "error")),
        output_path=out,
        plan_path=plan_path if plan_path.exists() else None,
        luyao_script_path=luyao_script_path,
        id_map=id_map,
        raw=raw,
    )


def dump_converted_script(script: Script, path: str | Path) -> dict[str, Any]:
    """只做转换，不调用蝉镜（联调用）。"""
    from video_pipeline.adapters.luyao_script import script_to_luyao_dict

    payload, id_map = script_to_luyao_dict(script)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path), "id_map": id_map.to_int, "shots": len(payload["shots"])}
