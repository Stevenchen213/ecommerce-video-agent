"""豆包大模型（doubao-seed 系列）规划层：产品信息 + 素材库 → 带货脚本。

整体分工：豆包负责「剪什么」，代码负责「怎么剪」。
  1) generate：把产品卖点和素材库清单发给豆包，输出结构化分镜 JSON
  2) validate：代码检查（素材编号是否存在、违禁词、结构、AI 镜头数量…）
  3) review  ：再调一次豆包，检查「每句文案和画面是否对得上、逻辑是否顺」
  2/3 有问题就把问题发回给豆包重写，最多 DOUBAO_LLM_MAX_ROUNDS 轮
输出的是普通 Script（和手写 YAML 完全一样），可以先人工看一眼再 run。

素材选择用「编号」而不是文件名，避免模型编造不存在的文件；
素材库里实在没有的画面，模型写 seedance_prompt，后面自动走 Seedance 图生视频。
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import requests
import yaml
from pydantic import BaseModel, Field

from video_pipeline.planner.compliance import find_banned
from video_pipeline.providers.doubao import IndexEntry, load_asset_index
from video_pipeline.schema import Platform, Script, Shot

DEFAULT_ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"
CHARS_PER_SEC = 4.5  # 中文口播语速约 4~5 字/秒


# ---------------------------------------------------------------- 输入：产品简报


class ProductBrief(BaseModel):
    product_name: str
    brand: str = ""
    selling_points: list[str] = Field(..., min_length=1, description="核心卖点，按重要性排序")
    target_audience: str = ""
    price_info: str = Field("", description="价格 / 优惠，如「到手价 29.9 两盒」")
    style: str = "真实口语化，像朋友推荐，不夸张叫卖"
    target_duration_sec: float = Field(30, gt=5, le=180)
    use_avatar: bool = Field(True, description="是否使用数字人口播镜头")
    person_id: str | None = None
    voice_id: str | None = None
    voiceover: Literal["full_track", "per_shot"] = "full_track"
    product_images: list[str] = Field(
        default_factory=list, description="产品图（相对 assets/），Seedance 图生视频用"
    )
    banned_words: list[str] = Field(default_factory=list, description="额外违禁词")
    notes: str = ""


def load_brief(path: str | Path) -> ProductBrief:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ProductBrief.model_validate(data)


# ---------------------------------------------------------------- 方舟 Chat API


class DoubaoLLMError(RuntimeError):
    pass


class DoubaoChat:
    """火山方舟 chat/completions（OpenAI 兼容），requests 直调，与 seedance.py 写法一致。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        *,
        temperature: float = 0.7,
        timeout_sec: float = 180.0,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError("缺少 ARK_API_KEY")
        if not model:
            raise ValueError("缺少 DOUBAO_LLM_MODEL（方舟控制台里 doubao-seed 模型的 ID）")
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or DEFAULT_ARK_BASE).rstrip("/")
        self.temperature = temperature
        self.timeout_sec = timeout_sec
        self._http = session or requests.Session()

    def complete(self, messages: list[dict[str, Any]], temperature: float | None = None) -> str:
        resp = self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature if temperature is None else temperature,
            },
            timeout=self.timeout_sec,
        )
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text[:500]}
        if resp.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            msg = err.get("message") if isinstance(err, dict) else data
            raise DoubaoLLMError(f"豆包 HTTP {resp.status_code}: {msg}")
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise DoubaoLLMError(f"豆包响应格式异常: {str(data)[:300]}") from e


def extract_json(text: str) -> Any:
    """从模型回复里取 JSON：兼容 ```json 代码块、前后多余说明文字。"""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start < 0 or end <= start:
        raise DoubaoLLMError(f"回复里没有 JSON: {text[:200]}")
    return json.loads(text[start : end + 1])


# ---------------------------------------------------------------- 提示词

_SYSTEM = """你是抖音 / 小红书带货短视频编导，负责把产品信息写成「数字人口播 + 产品画面」交替的分镜脚本。

【成片结构（按顺序）】
1. hook：前 3 秒抓注意力（痛点提问 / 反常识 / 强视觉产品画面）
2. scene：痛点或使用场景，让观众代入
3. product_intro：产品出场，说清楚是什么
4. selling_point ×2~4：每个卖点「先说 → 紧跟一个能证明它的产品画面」。
   说「酥到掉渣」就必须接掰开特写，说「配料干净」就接配料表。画面必须能证明这句话。
5. trust：信任背书（配料、产地、销量、价格优惠）
6. cta：引导下单，由数字人说

【镜头类型 platform】
- feiying：数字人口播，适合 hook / scene / 讲解 / cta。文案就是数字人说的话。
- doubao：产品画面，文案是配在画面上的旁白（同一个声音）。
- 不要连续 3 个以上数字人镜头；产品画面占一半左右。

【产品画面选素材（最重要）】
- 优先从「素材库」里选，填素材编号 asset（整数）。只能用清单里存在的编号。
- 尽量不要重复使用同一条素材，绝不能连续两个镜头用同一条。
- 素材库里确实没有能证明这句话的画面时，asset 填 null，并写 seedance_prompt：
  一句话描述画面主体、动作、镜头运动、光线，不要出现文字/字幕/人脸特写，
  image 从「产品图」里选一张（没有就 null）。AI 生成镜头要花钱，尽量少用。

【文案】
- 口语化、短句，每个镜头 1 句话；时长 duration_sec ≈ 字数 / 4.5，取 2~8 秒。
- 严禁广告法极限词和功效承诺：最好、第一、顶级、绝对、100%、治疗、减肥 等。
- 总时长贴近目标时长。

只输出 JSON，不要任何解释，格式：
{"title": "视频标题",
 "shots": [
   {"id": "s1_hook", "role": "hook", "platform": "feiying",
    "text": "口播或旁白文案", "duration_sec": 3,
    "asset": null, "seedance_prompt": "", "image": null,
    "proves": "这个镜头支撑哪个卖点（没有就空）"}
 ]}"""

_REVIEW_SYSTEM = """你是带货短视频审核。逐镜检查下面的分镜脚本，只关注会让成片「逻辑不清」或违规的问题：
1. 产品画面（doubao）的素材描述 / 生成提示词，是否真的能证明这句旁白？
2. 结构是否完整：开头 3 秒有钩子、卖点有画面证明、结尾有下单引导
3. 前后句是否衔接自然，有没有跳跃、重复、自相矛盾
4. 有没有广告法违禁词或夸大功效
小问题（措辞风格）不要提。只输出 JSON：
{"ok": true/false, "issues": [{"shot_id": "s3_xxx", "problem": "问题", "fix": "建议怎么改"}]}"""


def _fmt_range(e: IndexEntry) -> str:
    if e.start is None and e.end is None:
        return "整段"
    return f"{e.start or 0:g}-{e.end:g}s" if e.end is not None else f"{e.start:g}s 起"


def _asset_table(entries: list[IndexEntry]) -> str:
    if not entries:
        return "（素材库为空，所有产品画面都需要 seedance_prompt）"
    lines = []
    for i, e in enumerate(entries):
        name = Path(e.file).name
        desc = f" | 画面: {e.desc}" if e.desc else ""
        lines.append(f"[{i}] {name} | 标签: {'、'.join(e.tags)} | 可用区间: {_fmt_range(e)}{desc}")
    return "\n".join(lines)


def _brief_text(brief: ProductBrief) -> str:
    sp = "\n".join(f"  {i}. {p}" for i, p in enumerate(brief.selling_points, 1))
    parts = [
        f"产品：{brief.product_name}" + (f"（品牌：{brief.brand}）" if brief.brand else ""),
        f"核心卖点（按重要性）：\n{sp}",
        f"目标人群：{brief.target_audience}" if brief.target_audience else "",
        f"价格 / 优惠：{brief.price_info}" if brief.price_info else "",
        f"风格：{brief.style}",
        f"目标总时长：约 {brief.target_duration_sec:g} 秒",
        "数字人：可用" if brief.use_avatar else "数字人：不使用，全部用产品画面（platform 只能是 doubao）",
        f"补充说明：{brief.notes}" if brief.notes else "",
    ]
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------- 结果与校验


@dataclass
class PlanReport:
    rounds: int = 0
    issues_by_round: list[list[str]] = field(default_factory=list)
    final_issues: list[str] = field(default_factory=list)
    seedance_shots: list[str] = field(default_factory=list)
    library_shots: list[str] = field(default_factory=list)
    est_duration_sec: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.final_issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "rounds": self.rounds,
            "final_issues": self.final_issues,
            "issues_by_round": self.issues_by_round,
            "library_shots": self.library_shots,
            "seedance_shots": self.seedance_shots,
            "est_duration_sec": round(self.est_duration_sec, 1),
        }


_ID_SAFE = re.compile(r"[^0-9A-Za-z_\-一-鿿]")


def validate_plan(
    data: Any,
    brief: ProductBrief,
    entries: list[IndexEntry],
    *,
    max_seedance: int,
) -> list[str]:
    """代码层硬校验。返回问题列表（空 = 通过），问题会原样发回给豆包修改。"""
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
        return ["输出必须是 {\"title\":..., \"shots\": [...]} 结构"]
    shots = data["shots"]
    issues: list[str] = []
    if len(shots) < 3:
        issues.append("镜头太少，至少 3 个")
    total = 0.0
    seedance = 0
    prev_asset = None
    for i, s in enumerate(shots):
        tag = f"第{i + 1}镜({s.get('id', '?')})"
        plat = s.get("platform")
        text = str(s.get("text") or "").strip()
        if plat not in ("feiying", "doubao"):
            issues.append(f"{tag} platform 只能是 feiying 或 doubao")
            continue
        if plat == "feiying" and not brief.use_avatar:
            issues.append(f"{tag} 本次不使用数字人，请改成 doubao 产品画面")
        if plat == "feiying" and not text:
            issues.append(f"{tag} 数字人镜头必须有口播文案")
        try:
            total += float(s.get("duration_sec") or 0)
        except (TypeError, ValueError):
            issues.append(f"{tag} duration_sec 必须是数字")
        if hits := find_banned(text, brief.banned_words):
            issues.append(f"{tag} 文案含违禁词 {hits}，请换说法")
        if plat == "doubao":
            asset = s.get("asset")
            if asset is not None:
                if not isinstance(asset, int) or not 0 <= asset < len(entries):
                    issues.append(f"{tag} 素材编号 {asset!r} 不存在（可用 0~{len(entries) - 1}）")
                elif asset == prev_asset:
                    issues.append(f"{tag} 和上一镜用了同一条素材 [{asset}]，请换一条")
                prev_asset = asset
            else:
                prev_asset = None
                seedance += 1
                if not str(s.get("seedance_prompt") or "").strip():
                    issues.append(f"{tag} 没选素材也没写 seedance_prompt")
        else:
            prev_asset = None
    if shots and shots[-1].get("platform") == "doubao" and brief.use_avatar:
        issues.append("结尾应由数字人说下单引导（cta）")
    if seedance > max_seedance:
        issues.append(
            f"AI 生成镜头 {seedance} 个，超过上限 {max_seedance}；请优先用素材库，或合并镜头"
        )
    lo, hi = brief.target_duration_sec * 0.7, brief.target_duration_sec * 1.3
    if total and not lo <= total <= hi:
        issues.append(f"总时长 {total:.0f}s，目标约 {brief.target_duration_sec:g}s，请调整镜头数量或文案长度")
    return issues


def to_script(
    data: dict[str, Any], brief: ProductBrief, entries: list[IndexEntry]
) -> tuple[Script, PlanReport]:
    """模型 JSON → Script。素材编号换成 asset_refs（file@start-end）。"""
    report = PlanReport(raw=data)
    shots: list[Shot] = []
    used_ids: set[str] = set()
    for i, s in enumerate(data["shots"], 1):
        role = str(s.get("role") or "shot")
        sid = _ID_SAFE.sub("_", str(s.get("id") or f"s{i}_{role}"))[:40] or f"s{i}"
        if sid in used_ids:
            sid = f"{sid}_{i}"
        used_ids.add(sid)
        text = str(s.get("text") or "").strip()
        dur = float(s.get("duration_sec") or max(2.0, len(text) / CHARS_PER_SEC))
        dur = min(max(dur, 1.5), 12.0)
        report.est_duration_sec += dur
        extra: dict[str, Any] = {}
        if s.get("proves"):
            extra["proves"] = str(s["proves"])
        kw: dict[str, Any] = dict(id=sid, role=role, text=text, duration_sec=dur, extra=extra)

        if s.get("platform") == "feiying":
            shots.append(Shot(platform=Platform.FEIYING, person_id=brief.person_id,
                              voice_id=brief.voice_id, **kw))
            continue

        asset = s.get("asset")
        if isinstance(asset, int) and 0 <= asset < len(entries):
            e = entries[asset]
            ref = e.file
            if e.start is not None or e.end is not None:
                ref += f"@{e.start or 0:g}-" + (f"{e.end:g}" if e.end is not None else "")
            extra["asset_desc"] = e.desc or "、".join(e.tags)
            shots.append(Shot(platform=Platform.DOUBAO, asset_refs=[ref], **kw))
            report.library_shots.append(sid)
        else:
            image = s.get("image")
            if image not in brief.product_images:
                image = brief.product_images[0] if brief.product_images else None
            shots.append(Shot(platform=Platform.DOUBAO, prompt=str(s.get("seedance_prompt") or text),
                              image_ref=image, **kw))
            report.seedance_shots.append(sid)

    script = Script(
        title=str(data.get("title") or brief.product_name),
        description=f"豆包自动规划：{brief.product_name}",
        brand_name=brief.brand or None,
        compliance={"banned_words": brief.banned_words} if brief.banned_words else None,
        extra={"voiceover": brief.voiceover} if brief.voiceover == "full_track" else {},
        shots=shots,
    )
    return script, report


def _review_text(script: Script) -> str:
    lines = []
    for s in script.shots:
        if s.platform == Platform.FEIYING:
            visual = "数字人口播"
        elif s.asset_refs:
            visual = f"素材：{s.extra.get('asset_desc', s.asset_refs[0])}"
        else:
            visual = f"AI 生成：{s.prompt}"
        lines.append(f"{s.id} [{s.role}] {s.duration_sec:g}s | 画面：{visual} | 文案：{s.text}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程


def plan_with_llm(
    brief: ProductBrief,
    chat: DoubaoChat,
    *,
    assets_dir: Path,
    index_file: str = "asset_index.json",
    max_rounds: int = 3,
    max_seedance: int = 3,
    review: bool = True,
    log=print,
) -> tuple[Script, PlanReport]:
    entries = [e for e in load_asset_index(assets_dir / index_file)
               if (Path(e.file) if Path(e.file).is_absolute() else assets_dir / e.file).exists()]
    log(f"[规划] 素材库可用 {len(entries)} 条，模型 {chat.model}")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"{_brief_text(brief)}\n\n【素材库】\n{_asset_table(entries)}\n\n"
            f"【产品图】{', '.join(brief.product_images) or '无'}\n\n请输出分镜 JSON。"
        )},
    ]
    issues_by_round: list[list[str]] = []
    script: Script | None = None
    report = PlanReport()
    issues: list[str] = []
    script_issues: list[str] = []  # 当前采用的那版脚本对应的问题

    for rnd in range(1, max_rounds + 1):
        reply = chat.complete(messages)
        messages.append({"role": "assistant", "content": reply})
        try:
            data = extract_json(reply)
            issues = validate_plan(data, brief, entries, max_seedance=max_seedance)
        except (DoubaoLLMError, ValueError) as e:
            data, issues = None, [f"JSON 解析失败：{e}"]

        if not issues and data is not None:
            script, report = to_script(data, brief, entries)
            if review:
                rv = extract_json(chat.complete([
                    {"role": "system", "content": _REVIEW_SYSTEM},
                    {"role": "user", "content": f"{_brief_text(brief)}\n\n【分镜】\n{_review_text(script)}"},
                ], temperature=0.2))
                if isinstance(rv, dict) and not rv.get("ok", True):
                    issues = [f"{it.get('shot_id', '')}: {it.get('problem', '')} → {it.get('fix', '')}"
                              for it in rv.get("issues", []) if isinstance(it, dict)]
            script_issues = issues

        issues_by_round.append(issues)
        log(f"[规划] 第 {rnd} 轮：" + ("通过" if not issues else f"{len(issues)} 个问题"))
        for it in issues:
            log(f"    - {it}")
        if not issues:
            break
        messages.append({"role": "user", "content": (
            "请按以下问题修改，输出修改后的完整 JSON（格式不变）：\n" + "\n".join(f"- {x}" for x in issues)
        )})

    if script is None:
        raise DoubaoLLMError(f"{max_rounds} 轮后仍未得到合格脚本：{issues}")
    report.rounds = len(issues_by_round)
    report.issues_by_round = issues_by_round
    report.final_issues = script_issues
    return script, report


def dump_script_yaml(script: Script, path: Path, report: PlanReport | None = None) -> Path:
    """写成可人工修改的 YAML（和手写脚本同格式）。"""
    data = script.model_dump(mode="json", exclude_defaults=True)
    for shot, src in zip(data["shots"], script.shots, strict=True):
        shot["duration_sec"] = src.duration_sec  # 必须保留：产品镜按它裁剪 / 选 Seedance 时长
    header = "# 由豆包自动规划生成，可直接修改后再 run\n"
    if report and report.final_issues:
        header += "# ⚠ 审核未完全通过，请人工检查：\n" + "".join(f"#   - {x}\n" for x in report.final_issues)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 素材自动打标签（视觉理解）

_DESCRIBE_PROMPT = """这是一段带货素材视频里截出的几帧（按时间顺序）。产品：{product}。
请输出 JSON：{{"desc": "一句话描述画面内容和动作（30 字内）", "tags": ["2~4 个短标签，第一个是产品名"]}}
标签描述画面类型，例如：掰开特写、馅料特写、独立包装、配料表、产品陈列、使用场景、礼盒。只输出 JSON。"""


def _frames_b64(ffmpeg: str, video: Path, times: list[float]) -> list[str]:
    urls = []
    for t in times:
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=512:-2", "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout:
            urls.append("data:image/jpeg;base64," + base64.b64encode(proc.stdout).decode("ascii"))
    return urls


def describe_assets(
    chat: DoubaoChat,
    assets_dir: Path,
    product: str,
    *,
    index_file: str = "asset_index.json",
    overwrite: bool = False,
    log=print,
) -> int:
    """给素材库每条素材截 3 帧，让豆包（需支持图片理解的 doubao-seed 模型）补 desc / tags。

    原文件先备份为 asset_index.json.bak。返回更新条数。
    """
    from video_pipeline.compose.concat import FFMPEG, probe

    path = assets_dir / index_file
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):  # 简单版 → 完整版
        raw = [{"file": e.file, "tags": e.tags, "start": e.start, "end": e.end}
               for e in load_asset_index(path)]
    path.with_suffix(path.suffix + ".bak").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8")

    updated = 0
    for item in raw:
        if item.get("desc") and not overwrite:
            continue
        f = Path(item["file"])
        f = f if f.is_absolute() else assets_dir / f
        if not f.exists():
            log(f"  [跳过] 文件不存在 {f}")
            continue
        start = float(item.get("start") or 0)
        end = item.get("end")
        end = float(end) if end is not None else (probe(f).duration or start + 3)
        span = max(end - start, 0.3)
        frames = _frames_b64(FFMPEG, f, [start + span * k for k in (0.15, 0.5, 0.85)])
        if not frames:
            log(f"  [跳过] 截帧失败 {f.name}")
            continue
        content: list[dict[str, Any]] = [{"type": "text", "text": _DESCRIBE_PROMPT.format(product=product)}]
        content += [{"type": "image_url", "image_url": {"url": u}} for u in frames]
        try:
            out = extract_json(chat.complete([{"role": "user", "content": content}], temperature=0.2))
        except DoubaoLLMError as e:
            log(f"  [失败] {f.name}: {e}")
            continue
        if isinstance(out, dict) and out.get("desc"):
            item["desc"] = str(out["desc"])
            new_tags = [str(t) for t in out.get("tags", []) if str(t).strip()]
            item["tags"] = list(dict.fromkeys([*item.get("tags", []), *new_tags]))
            updated += 1
            log(f"  [打标签] {f.name}: {item['desc']} {item['tags']}")
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated
