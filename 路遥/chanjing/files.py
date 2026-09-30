"""素材上传：create_upload_url → PUT 到 sign_url → 轮询 file_detail 直到可用。"""
from __future__ import annotations

import mimetypes
from pathlib import Path

import requests

from .client import ChanjingClient

# service 取值示例：make_video_audio（驱动音频）、make_video_background（背景）等，以文档为准


def upload_file(client: ChanjingClient, path: str | Path, service: str,
                interval: int = 3, timeout: int = 300) -> dict:
    path = Path(path)
    info = client.get("/open/v1/common/create_upload_url", service=service, name=path.name)
    mime = info.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as f:
        r = requests.put(info["sign_url"], data=f, headers={"Content-Type": mime}, timeout=300)
    r.raise_for_status()
    file_id = info["file_id"]

    detail = client.poll(
        fetch=lambda: client.get("/open/v1/common/file_detail", id=file_id),
        is_done=lambda d: d.get("status") in (1, "success"),   # 成功状态值以文档为准
        is_failed=lambda d: d.get("status") in (-1, 2, "failed"),
        interval=interval, timeout=timeout, label=f"file:{path.name}")
    return {"file_id": file_id, **detail}   # detail 里若有 url，可作为 AI 创作的 ref_img_url
