"""AI 创作（图生视频）：用于素材库里只有图片、没有实拍视频的产品镜头。"""
from __future__ import annotations

from .client import ChanjingClient

CREATION_TYPE_VIDEO = 4
FAILED_PROGRESS = {"Error", "Fail", "Cancelled"}


def build_i2v_payload(model_code: str, prompt: str, ref_img_urls: list[str],
                      aspect_ratio: str = "9:16", clarity: int = 1080, duration: int = 5) -> dict:
    return {
        "creation_type": CREATION_TYPE_VIDEO,
        "model_code": model_code,
        "ref_prompt": prompt,
        "ref_img_url": ref_img_urls,
        "aspect_ratio": aspect_ratio,
        "clarity": clarity,
        "video_duration": duration,
    }


def submit(client: ChanjingClient, payload: dict) -> str:
    data = client.post("/open/v1/ai_creation/task/submit", payload)
    return data if isinstance(data, str) else data["unique_id"]


def _outputs(task: dict) -> list[str]:
    out = task.get("output_url") or []
    return out if isinstance(out, list) else [out]


def wait_task(client: ChanjingClient, unique_id: str, interval: int, timeout: int) -> dict:
    # 文档：任务状态在 progress_desc（Queued/Ready/Generating/Success/Error/Fail/Cancelled），
    # 没有数值 status 字段。成功仍以"有产出地址"为准，失败以 Error/Fail/Cancelled 或 err_msg 判定
    return client.poll(
        fetch=lambda: client.get("/open/v1/ai_creation/task", unique_id=unique_id),
        is_done=lambda t: bool(_outputs(t)),
        is_failed=lambda t: t.get("progress_desc") in FAILED_PROGRESS or bool(t.get("err_msg")),
        interval=interval, timeout=timeout, label=f"ai_creation:{unique_id}")


def first_output(task: dict) -> str:
    return _outputs(task)[0]
