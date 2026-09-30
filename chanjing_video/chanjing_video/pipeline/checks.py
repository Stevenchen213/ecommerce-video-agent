"""调用任何付费接口之前的三道闸：脚本结构 / 广告合规 / 数字人授权。"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
# 单字极限词的正常用法，避免"最近""最后"被误杀
BANNED_EXCEPTIONS = {"最": ["最近", "最后", "最初", "最终"]}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------- 占位符 ----------
def fill_placeholders(script: dict, fills: dict[str, str]) -> dict:
    """用企业补填的信息替换 {{key}}，并回写 placeholders[].value。"""
    def sub(text):
        return PLACEHOLDER.sub(lambda m: fills.get(m.group(1), m.group(0)), text) if text else text

    for p in script.get("placeholders", []):
        if p["key"] in fills:
            p["value"] = fills[p["key"]]
    for s in script["shots"]:
        s["voiceover"] = sub(s["voiceover"])
        s["on_screen_text"] = sub(s.get("on_screen_text"))
    script["voiceover_full"] = sub(script["voiceover_full"])
    if not any(PLACEHOLDER.search(s["voiceover"]) for s in script["shots"]):
        script["status"] = "ready"
    return script


# ---------- 结构 ----------
def check_structure(script: dict, asset_ids: set[str]) -> Report:
    r = Report()
    shots = script.get("shots", [])
    if not shots:
        r.errors.append("没有镜头")
    for s in shots:
        sid = s.get("shot_id")
        if s.get("type") not in ("avatar", "product"):
            r.errors.append(f"镜头{sid}: type 必须是 avatar 或 product")
        if PLACEHOLDER.search(s.get("voiceover", "")):
            r.errors.append(f"镜头{sid}: 口播仍有未填占位符 {PLACEHOLDER.findall(s['voiceover'])}")
        vis = s.get("visual", {})
        refs = list(vis.get("asset_refs", [])) + [c["asset_ref"] for c in vis.get("clips", [])]
        refs += [o.split("@")[0] for o in vis.get("overlay_asset_refs", [])]
        for ref in refs:
            if ref not in asset_ids:
                r.errors.append(f"镜头{sid}: 素材 {ref} 不在素材库中")
        if s.get("type") == "product" and not refs:
            r.errors.append(f"镜头{sid}: 产品镜头没有任何素材")
    joined = "".join(s.get("voiceover", "") for s in shots)
    if joined != script.get("voiceover_full"):
        r.errors.append("voiceover_full 与各镜头口播拼接结果不一致")
    total = sum(s.get("duration_sec", 0) for s in shots)
    target = script.get("project", {}).get("target_duration_sec", total)
    if abs(total - target) > 1:
        r.warnings.append(f"镜头总时长 {total}s 与目标 {target}s 不符")
    if script.get("status") != "ready":
        r.errors.append("脚本状态不是 ready")
    return r


# ---------- 合规 ----------
def check_compliance(script: dict) -> Report:
    r = Report()
    terms = script.get("compliance", {}).get("banned_terms", [])
    for s in script["shots"]:
        for label, text in (("口播", s.get("voiceover")), ("字幕", s.get("on_screen_text"))):
            if not text:
                continue
            for t in terms:
                cleaned = text
                for ok in BANNED_EXCEPTIONS.get(t, []):
                    cleaned = cleaned.replace(ok, "")
                if t in cleaned:
                    r.errors.append(f"镜头{s['shot_id']} {label}含禁用词「{t}」：{text}")
    if not script.get("compliance", {}).get("ai_label", True):
        r.errors.append("成片必须加 AI 生成标识")
    return r


# ---------- 授权 ----------
def check_avatar_authorization(person_id: str, brand: str | None, registry_path: str | Path,
                               today: dt.date | None = None) -> Report:
    """只允许使用授权形象库里的数字人；真人/明星形象必须有授权编号、品牌范围和有效期。"""
    r = Report()
    today = today or dt.date.today()
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    rec = next((a for a in registry if a["person_id"] == person_id), None)
    if not rec:
        r.errors.append(f"数字人 {person_id} 不在授权形象库中，禁止使用")
        return r
    if rec.get("is_real_person"):
        if not rec.get("authorization_ref"):
            r.errors.append(f"真人形象 {rec.get('name')} 缺少授权文件编号")
        if rec.get("valid_until") and dt.date.fromisoformat(rec["valid_until"]) < today:
            r.errors.append(f"真人形象 {rec.get('name')} 授权已于 {rec['valid_until']} 过期")
        allowed = rec.get("brands") or []
        if allowed and brand not in allowed:
            r.errors.append(f"真人形象 {rec.get('name')} 未授权用于品牌「{brand}」")
    return r
