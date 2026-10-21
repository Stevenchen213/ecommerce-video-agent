from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_pipeline.library_check import check_library
from video_pipeline.planner import plan_script
from video_pipeline.schema import Platform, Script, Shot, load_script


def test_load_and_plan(tmp_path: Path):
    script_path = tmp_path / "s.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "title": "t",
                "shots": [
                    {
                        "id": "a",
                        "role": "hook",
                        "platform": "doubao",
                        "duration_sec": 1,
                    },
                    {
                        "id": "b",
                        "role": "host",
                        "platform": "feiying",
                        "duration_sec": 1,
                    },
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    script = load_script(script_path)
    plan = plan_script(script)
    assert [s.id for s in plan.doubao_shots] == ["a"]
    assert [s.id for s in plan.feiying_shots] == ["b"]
    assert [seg.shot_ids for seg in plan.product_segments] == [["a"]]
    assert [u.to_dict() for u in plan.timeline] == [
        {"kind": "product_segment", "segment_id": "prod_seg_0", "shot_ids": ["a"]},
        {"kind": "feiying", "shot_id": "b"},
    ]


def test_two_step_product_segments():
    """产品1→数字人→产品2→3→4→数字人2→产品5→6"""
    script = Script(
        title="seg",
        shots=[
            Shot(id="p1", role="product", platform=Platform.DOUBAO),
            Shot(id="h1", role="host", platform=Platform.FEIYING),
            Shot(id="p2", role="product", platform=Platform.DOUBAO),
            Shot(id="p3", role="product", platform=Platform.DOUBAO),
            Shot(id="p4", role="product", platform=Platform.DOUBAO),
            Shot(id="h2", role="host", platform=Platform.FEIYING),
            Shot(id="p5", role="product", platform=Platform.DOUBAO),
            Shot(id="p6", role="product", platform=Platform.DOUBAO),
        ],
    )
    plan = plan_script(script)
    assert [s.id for s in plan.feiying_shots] == ["h1", "h2"]
    assert [s.id for s in plan.doubao_shots] == ["p1", "p2", "p3", "p4", "p5", "p6"]
    assert [seg.shot_ids for seg in plan.product_segments] == [
        ["p1"],
        ["p2", "p3", "p4"],
        ["p5", "p6"],
    ]
    assert [u.to_dict() for u in plan.timeline] == [
        {"kind": "product_segment", "segment_id": "prod_seg_0", "shot_ids": ["p1"]},
        {"kind": "feiying", "shot_id": "h1"},
        {
            "kind": "product_segment",
            "segment_id": "prod_seg_1",
            "shot_ids": ["p2", "p3", "p4"],
        },
        {"kind": "feiying", "shot_id": "h2"},
        {
            "kind": "product_segment",
            "segment_id": "prod_seg_2",
            "shot_ids": ["p5", "p6"],
        },
    ]
    assert "p2" in plan.product_segments[1].coherent_brief
    assert "p4" in plan.product_segments[1].coherent_brief


def test_script_to_luyao_adapter():
    from video_pipeline.adapters.luyao_script import script_to_luyao_dict

    script = Script(
        title="demo",
        brand_name="onlytree",
        assets=[{"asset_id": "box", "file": "assets/box.jpg", "url": "https://x/box.jpg"}],
        shots=[
            Shot(
                id="s1_hook",
                role="hook",
                platform=Platform.DOUBAO,
                text="钩子文案",
                asset_refs=["box"],
                duration_sec=3,
            ),
            Shot(
                id="s2_host",
                role="host",
                platform=Platform.FEIYING,
                text="主播口播",
                person_id="C-PLATFORM-DEMO-001",
                voice_id="V1",
                duration_sec=4,
            ),
            Shot(
                id="s3_prod",
                role="product",
                platform=Platform.DOUBAO,
                text="产品展示",
                asset_refs=["box"],
                duration_sec=5,
            ),
        ],
    )
    payload, id_map = script_to_luyao_dict(script)
    assert id_map.to_int == {"s1_hook": 1, "s2_host": 2, "s3_prod": 3}
    assert [s["type"] for s in payload["shots"]] == ["product", "avatar", "product"]
    assert payload["voiceover_full"] == "钩子文案主播口播产品展示"
    assert payload["avatar"]["person_id"] == "C-PLATFORM-DEMO-001"
    assert payload["assets"][0]["asset_id"] == "box"


def test_resolve_luyao_root():
    from video_pipeline.adapters.luyao_bridge import resolve_luyao_root

    root = resolve_luyao_root()
    assert (root / "pipeline" / "orchestrator.py").exists()


def test_duplicate_shot_id_rejected():
    with pytest.raises(Exception):
        Script(
            title="x",
            shots=[
                Shot(id="a", role="hook", platform=Platform.DOUBAO),
                Shot(id="a", role="host", platform=Platform.FEIYING),
            ],
        )


def test_library_missing(tmp_path: Path):
    script = Script(
        title="x",
        shots=[
            Shot(id="s1", role="hook", platform=Platform.DOUBAO),
            Shot(id="s2", role="host", platform=Platform.FEIYING),
        ],
    )
    lib = tmp_path / "library"
    (lib / "doubao").mkdir(parents=True)
    # only create s1
    (lib / "doubao" / "s1.mp4").write_bytes(b"not-real")
    check = check_library(script, lib)
    assert check.ok is False
    assert check.missing[0].shot_id == "s2"
    with pytest.raises(FileNotFoundError):
        check.raise_if_missing()


def test_assemble_order_paths(tmp_path: Path):
    script = Script(
        title="x",
        shots=[
            Shot(id="s1", role="hook", platform=Platform.DOUBAO),
            Shot(id="s2", role="host", platform=Platform.FEIYING),
            Shot(id="s3", role="product_closeup", platform=Platform.DOUBAO),
        ],
    )
    lib = tmp_path / "library"
    for shot in script.shots:
        p = lib / shot.platform.value
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{shot.id}.mp4").write_bytes(b"x")
    check = check_library(script, lib)
    assert check.ok
    ordered = [check.present[s.id] for s in script.shots]
    assert [p.stem for p in ordered] == ["s1", "s2", "s3"]
