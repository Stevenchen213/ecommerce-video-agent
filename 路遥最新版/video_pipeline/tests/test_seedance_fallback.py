"""产品镜头路由测试：素材库命中 / 标签匹配 / AI 缓存 / Seedance 兜底 / 预算上限。
不联网：Seedance 用假的 HTTP session。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_pipeline.compose.concat import FFMPEG, probe
from video_pipeline.providers.doubao import DoubaoProvider
from video_pipeline.providers.seedance import SeedanceBudgetExceeded, SeedanceClient
from video_pipeline.schema import Platform, Shot


def _clip(path: Path, sec: float = 6) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c=red:s=180x320:d={sec}:r=30", "-c:v", "libx264", str(path)],
                   check=True)
    return path


class _Resp:
    def __init__(self, data=None, status=200, body=b""):
        self._data, self.status_code, self._body = data, status, body
    def json(self): return self._data
    def raise_for_status(self): pass
    def iter_content(self, chunk_size): yield self._body
    def __enter__(self): return self
    def __exit__(self, *a): pass


class FakeArk:
    """模拟方舟：创建 → 一次 running → succeeded → 下载返回一个真 mp4。"""
    def __init__(self, mp4: Path):
        self.mp4 = mp4.read_bytes()
        self.created: list[dict] = []
        self.polls = 0
    def post(self, url, headers, json, timeout):
        self.created.append(json)
        return _Resp({"id": f"cgt-{len(self.created)}"})
    def get(self, url, headers=None, timeout=None, stream=False, params=None):
        if stream:
            return _Resp(body=self.mp4)
        self.polls += 1
        if self.polls % 2:
            return _Resp({"status": "running"})
        return _Resp({"status": "succeeded", "content": {"video_url": "https://x/v.mp4"}})


def _seedance(fake, **kw):
    return SeedanceClient("k", "m", session=fake, poll_interval_sec=0, **kw)


def _shot(**kw):
    return Shot(id=kw.pop("id", "p1"), role="product_closeup", platform=Platform.DOUBAO, **kw)


def test_explicit_ref_hit(tmp_path):
    assets = tmp_path / "assets"
    _clip(assets / "a.mp4")
    out = tmp_path / "lib" / "p1.mp4"
    r = DoubaoProvider(assets).generate(_shot(asset_refs=["a.mp4@1-3"]), out)
    assert r.raw["source"] == "library"
    assert abs(probe(out).duration - 2) < 0.2


def test_explicit_ref_missing_does_not_spend(tmp_path):
    fake = FakeArk(_clip(tmp_path / "ai.mp4"))
    with pytest.raises(FileNotFoundError):
        DoubaoProvider(tmp_path / "assets", seedance=_seedance(fake)).generate(
            _shot(asset_refs=["typo.mp4"]), tmp_path / "o.mp4")
    assert fake.created == []


def test_tag_match_and_target_duration(tmp_path):
    assets = tmp_path / "assets"
    _clip(assets / "qlg" / "3.mp4")
    (assets / "asset_index.json").write_text(json.dumps(
        [{"file": "qlg/3.mp4", "tags": ["秋梨糕", "掰开特写"]}], ensure_ascii=False), "utf-8")
    shot = _shot(asset_tags=["秋梨糕", "掰开特写"], extra={"target_duration_sec": 2.5})
    out = tmp_path / "o.mp4"
    r = DoubaoProvider(assets).generate(shot, out)
    assert r.raw["source"] == "library"
    assert abs(probe(out).duration - 2.5) < 0.2


def test_simple_dict_index(tmp_path):
    assets = tmp_path / "assets"
    _clip(assets / "18.mp4")
    (assets / "asset_index.json").write_text(json.dumps({"配料表": "18.mp4@0-2"}, ensure_ascii=False), "utf-8")
    r = DoubaoProvider(assets).generate(_shot(asset_tags=["配料表"]), tmp_path / "o.mp4")
    assert r.raw["source"] == "library"


def test_seedance_fallback_then_cache(tmp_path):
    assets = tmp_path / "assets"
    (assets / "img").mkdir(parents=True)
    (assets / "img" / "box.png").write_bytes(b"\x89PNG fake")
    fake = FakeArk(_clip(tmp_path / "ai.mp4", sec=5))
    prov = DoubaoProvider(assets, seedance=_seedance(fake))
    shot = _shot(asset_tags=["新角度"], prompt="手掰开秋梨糕\n\n[产品段连贯上下文 seg0]\nxxx",
                 image_ref="img/box.png", extra={"target_duration_sec": 3.2})

    r1 = prov.generate(shot, tmp_path / "o1.mp4")
    assert r1.raw["source"] == "seedance"
    body = fake.created[0]
    assert body["duration"] == 5 and body["ratio"] == "9:16"
    assert body["content"][0]["text"] == "手掰开秋梨糕"          # 段上下文不发给 Seedance
    assert body["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert abs(probe(tmp_path / "o1.mp4").duration - 3.2) < 0.2

    r2 = prov.generate(shot, tmp_path / "o2.mp4")                # 第二次：走缓存，不再计费
    assert r2.raw["source"] == "ai_cache" and len(fake.created) == 1


def test_params_in_text_and_budget(tmp_path):
    fake = FakeArk(_clip(tmp_path / "ai.mp4"))
    c = _seedance(fake, params_in_text=True, max_calls=1)
    c.generate("p", tmp_path / "a.mp4", need_sec=7)
    assert "--duration 10" in fake.created[0]["content"][0]["text"]
    assert "duration" not in fake.created[0]
    with pytest.raises(SeedanceBudgetExceeded):
        c.generate("p", tmp_path / "b.mp4")


def test_no_seedance_configured_gives_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="ARK_API_KEY"):
        DoubaoProvider(tmp_path).generate(_shot(asset_tags=["x"]), tmp_path / "o.mp4")
