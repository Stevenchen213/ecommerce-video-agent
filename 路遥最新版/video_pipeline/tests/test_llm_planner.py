"""豆包规划层测试：不联网，用假的 chat 客户端按顺序返回预设回复。"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_pipeline.compose.concat import FFMPEG, probe
from video_pipeline.config import load_settings
from video_pipeline.planner.compliance import find_banned
from video_pipeline.planner.llm import (
    ProductBrief,
    dump_script_yaml,
    extract_json,
    plan_with_llm,
)
from video_pipeline.providers.doubao import DoubaoProvider
from video_pipeline.schema import Platform, Shot, load_script


def _clip(path: Path, sec: float = 6, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=180x320:d={sec}:r=30", "-c:v", "libx264", str(path)],
                   check=True)
    return path


class FakeChat:
    model = "fake-doubao-seed"

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def complete(self, messages, temperature=None):
        self.calls.append(list(messages))
        r = self.replies.pop(0)
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


def _assets(tmp_path: Path) -> Path:
    assets = tmp_path / "assets"
    _clip(assets / "qlg" / "3.mp4", color="red")
    _clip(assets / "qlg" / "18.mp4", color="blue")
    (assets / "asset_index.json").write_text(json.dumps([
        {"file": "qlg/3.mp4", "tags": ["秋梨糕", "掰开特写"], "start": 1, "end": 4,
         "desc": "手掰开秋梨糕，酥皮掉渣"},
        {"file": "qlg/18.mp4", "tags": ["秋梨糕", "配料表"], "start": 0, "end": 3},
        {"file": "qlg/missing.mp4", "tags": ["秋梨糕", "不存在"]},   # 文件不存在：不应发给模型
    ], ensure_ascii=False), "utf-8")
    return assets


def _brief(**kw) -> ProductBrief:
    base = dict(product_name="秋梨糕", selling_points=["酥到掉渣", "配料干净"],
                target_duration_sec=14, product_images=["qlg/box.jpg"], voiceover="per_shot")
    return ProductBrief(**{**base, **kw})


GOOD = {"title": "秋梨糕", "shots": [
    {"id": "s1_hook", "role": "hook", "platform": "feiying", "text": "你吃过会掉渣的秋梨糕吗", "duration_sec": 3},
    {"id": "s2_break", "role": "selling_point", "platform": "doubao", "text": "一掰全是酥皮", "duration_sec": 3,
     "asset": 0, "proves": "酥到掉渣"},
    {"id": "s3_ingr", "role": "trust", "platform": "doubao", "text": "配料表干干净净", "duration_sec": 3, "asset": 1},
    {"id": "s4_gift", "role": "scene", "platform": "doubao", "text": "送长辈也体面", "duration_sec": 2,
     "asset": None, "seedance_prompt": "礼盒放在木桌上，镜头缓慢推近", "image": "qlg/box.jpg"},
    {"id": "s5_cta", "role": "cta", "platform": "feiying", "text": "喜欢的点下方小黄车", "duration_sec": 3},
]}


def test_extract_json_from_fenced_reply():
    assert extract_json('好的：\n```json\n{"a": [1]}\n```\n希望有帮助') == {"a": [1]}


def test_banned_words():
    assert {"最好", "第一", "全网最"} <= set(find_banned("全网最好吃，第一名"))
    assert find_banned("最近很火") == []


def test_plan_retries_on_validation_errors(tmp_path):
    assets = _assets(tmp_path)
    bad = json.loads(json.dumps(GOOD))
    bad["shots"][1]["asset"] = 7                       # 不存在的素材编号
    bad["shots"][2]["text"] = "全网最好的配料"           # 违禁词
    chat = FakeChat([bad, GOOD, {"ok": True, "issues": []}])

    script, report = plan_with_llm(_brief(), chat, assets_dir=assets, log=lambda *_: None)

    assert report.ok and report.rounds == 2
    assert any("素材编号 7" in x for x in report.issues_by_round[0])
    assert any("违禁词" in x for x in report.issues_by_round[0])
    # 问题被发回给模型重写
    assert "素材编号 7" in chat.calls[1][-1]["content"]
    # 不存在的素材文件不出现在发给模型的清单里
    assert "missing.mp4" not in chat.calls[0][1]["content"]

    by_id = {s.id: s for s in script.shots}
    assert by_id["s2_break"].asset_refs == ["qlg/3.mp4@1-4"]
    assert by_id["s4_gift"].image_ref == "qlg/box.jpg" and by_id["s4_gift"].prompt.startswith("礼盒")
    assert by_id["s1_hook"].platform == Platform.FEIYING
    assert report.library_shots == ["s2_break", "s3_ingr"] and report.seedance_shots == ["s4_gift"]


def test_review_feedback_triggers_rewrite(tmp_path):
    assets = _assets(tmp_path)
    review_bad = {"ok": False, "issues": [{"shot_id": "s3_ingr", "problem": "画面和文案无关", "fix": "换素材"}]}
    chat = FakeChat([GOOD, review_bad, GOOD, {"ok": True}])
    _, report = plan_with_llm(_brief(), chat, assets_dir=assets, log=lambda *_: None)
    assert report.ok and report.rounds == 2
    assert "画面和文案无关" in chat.calls[2][-1]["content"]


def test_structure_rules(tmp_path):
    assets = _assets(tmp_path)
    bad = json.loads(json.dumps(GOOD))
    bad["shots"][2]["asset"] = 0                       # 连续两镜同一素材
    bad["shots"] = bad["shots"][:-1]                   # 结尾不是数字人 CTA
    chat = FakeChat([bad, bad, bad])
    with pytest.raises(Exception):
        plan_with_llm(_brief(), chat, assets_dir=assets, max_rounds=3, log=lambda *_: None)
    assert len(chat.calls) == 3


def test_no_avatar_mode_rejects_feiying(tmp_path):
    assets = _assets(tmp_path)
    chat = FakeChat([GOOD, GOOD])
    with pytest.raises(Exception):
        plan_with_llm(_brief(use_avatar=False), chat, assets_dir=assets, max_rounds=2,
                      review=False, log=lambda *_: None)


def test_yaml_roundtrip_keeps_duration(tmp_path):
    assets = _assets(tmp_path)
    script, report = plan_with_llm(_brief(), FakeChat([GOOD]), assets_dir=assets,
                                   review=False, log=lambda *_: None)
    path = dump_script_yaml(script, tmp_path / "out.yaml", report)
    again = load_script(path)
    assert [s.id for s in again.shots] == [s.id for s in script.shots]
    s4 = next(s for s in again.shots if s.id == "s4_gift")
    assert "duration_sec" in s4.model_fields_set and s4.duration_sec == 2


def test_tag_match_requires_all_tags(tmp_path):
    """修复前：[秋梨糕, 礼盒场景] 只要命中「秋梨糕」就会随便配一条素材，Seedance 永远不触发。"""
    assets = _assets(tmp_path)
    prov = DoubaoProvider(assets)
    miss = Shot(id="x", role="r", platform=Platform.DOUBAO, asset_tags=["秋梨糕", "礼盒场景"])
    hit = Shot(id="y", role="r", platform=Platform.DOUBAO, asset_tags=["秋梨糕", "配料"])
    assert prov._by_tags(miss) is None
    assert prov._by_tags(hit)[0].name == "18.mp4"


def test_duration_sec_used_when_explicit(tmp_path):
    assets = tmp_path / "assets"
    _clip(assets / "a.mp4", sec=6)
    shot = Shot(id="p", role="r", platform=Platform.DOUBAO, asset_refs=["a.mp4"], duration_sec=2.5)
    DoubaoProvider(assets).generate(shot, tmp_path / "o.mp4")
    assert abs(probe(tmp_path / "o.mp4").duration - 2.5) < 0.2


def test_end_to_end_plan_then_assemble(tmp_path):
    """豆包脚本 → 真实素材库裁剪 + mock 数字人 → 拼接成片。"""
    from video_pipeline.pipeline import Pipeline
    from video_pipeline.providers.mock import MockFeiyingProvider

    assets = _assets(tmp_path)
    plan = json.loads(json.dumps(GOOD))
    plan["shots"] = [s for s in plan["shots"] if s["id"] != "s4_gift"]
    plan["shots"][2]["duration_sec"] = 4   # 补足总时长
    script, _ = plan_with_llm(_brief(target_duration_sec=13), FakeChat([plan]), assets_dir=assets,
                              review=False, log=lambda *_: None)

    settings = replace(load_settings(), root=tmp_path, use_mock=False, width=180, height=320,
                       feiying_api_key="", ark_api_key="")
    pipe = Pipeline(settings)
    pipe.feiying = MockFeiyingProvider(180, 320, 30)
    paths = pipe.generate_all(script)
    result = pipe.assemble(script, paths, tmp_path / "output" / "final.mp4")
    assert result.output_path.exists()
    assert 11 < (result.duration_sec or 0) < 16

    # 第二次运行：数字人内容没变，不重复生成
    calls = []
    pipe.feiying.generate = lambda shot, out: calls.append(shot.id)
    pipe.generate_all(script)
    assert calls == []
