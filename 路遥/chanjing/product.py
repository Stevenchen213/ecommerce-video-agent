"""产品镜头生成（蝉镜侧对外唯一入口）。

分工约定：数字人走飞影（陈铭嵩 / 周思含侧），蝉镜只负责产品画面。
周思含的 ChanjingProvider 只需要 import 这一个函数：

    from chanjing.product import gen_product
    info = gen_product(["images/box_front.jpg"], "包装盒静置在木桌上，镜头缓慢推近",
                       "library/chanjing/p2.mp4", target_duration=3.2)

产出是一段无声视频（蝉镜视频模型不出声音），口播音轨由拼接层统一铺。
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

import requests

from config import settings
from . import ai_creation
from .client import ChanjingClient
from .files import upload_file

log = logging.getLogger("chanjing.product")

MAX_DURATION = 15
MAX_REF_IMAGES = 7


def make_client() -> ChanjingClient:
    return ChanjingClient(settings.app_id, settings.secret_key, settings.base_url,
                          settings.request_timeout)


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def resolve_image_urls(client: ChanjingClient, images: list[str],
                       cache: dict[str, str] | None = None) -> list[str]:
    """本地图片先上传到蝉镜拿 URL；已经是 URL 的直接用。cache 避免同一张图重复上传。"""
    if not images:
        raise ValueError("至少需要 1 张产品参考图")
    if len(images) > MAX_REF_IMAGES:
        raise ValueError(f"参考图最多 {MAX_REF_IMAGES} 张，当前 {len(images)} 张")
    cache = cache if cache is not None else {}
    urls = []
    for img in images:
        if _is_url(img):
            urls.append(img)
            continue
        key = str(Path(img).resolve())
        if key not in cache:
            if not Path(img).exists():
                raise FileNotFoundError(f"找不到产品图：{img}")
            cache[key] = upload_file(client, img, service="ai_creation")["url"]
            log.info("已上传参考图 %s", Path(img).name)
        urls.append(cache[key])
    return urls


def request_duration(target: float | None) -> int:
    """蝉镜最短 5 秒；目标更短时也生成 5 秒，拼接时再截取。"""
    if not target:
        return ai_creation.MIN_DURATION
    return min(MAX_DURATION, max(ai_creation.MIN_DURATION, math.ceil(target)))


def _download(url: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(out)   # 下载完整后再改名，避免拼接层读到半截文件
    return out


def gen_product(images: list[str], prompt: str, out_path: str | Path, *,
                target_duration: float | None = None, model_code: str | None = None,
                clarity: int | None = None, aspect_ratio: str = "9:16",
                client: ChanjingClient | None = None,
                upload_cache: dict[str, str] | None = None) -> dict:
    """产品图 + 画面描述 → 一段无声产品视频，落到 out_path。

    images: 本地路径或 URL，1-7 张
    prompt: 只写画面和运镜；不要写产品名、价格、促销文字（模型会画成乱码，文字由拼接层叠加）
    target_duration: 这个镜头在成片里要占几秒，用来决定向蝉镜请求的时长
    返回值同时写入 out_path 同名 .json，记录模型、任务 ID、耗时，方便对比和对账。
    """
    out = Path(out_path)
    client = client or make_client()
    model = model_code or settings.i2v_model_code
    t0 = time.time()

    urls = resolve_image_urls(client, images, upload_cache)
    payload = ai_creation.build_i2v_payload(
        model, prompt, urls, aspect_ratio=aspect_ratio,
        clarity=clarity or settings.i2v_clarity, duration=request_duration(target_duration))

    uid = ai_creation.submit(client, payload)
    log.info("图生视频已提交 model=%s unique_id=%s", model, uid)
    task = ai_creation.wait_task(client, uid, settings.poll_interval, settings.poll_timeout)
    source_url = ai_creation.first_output(task)
    _download(source_url, out)

    info = {
        "path": str(out),
        "model_code": model,
        "unique_id": uid,
        "prompt": prompt,
        "ref_img_url": urls,
        "requested_duration": payload["video_duration"],
        "target_duration": target_duration,
        "elapsed_sec": round(time.time() - t0, 1),
        # 蝉镜链接不永久保存；本地文件才是准，这里仅留档
        "source_url": source_url,
    }
    out.with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return info
