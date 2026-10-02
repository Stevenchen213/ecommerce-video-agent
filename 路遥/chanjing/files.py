"""素材上传：create_upload_url → PUT 到 sign_url → 轮询 file_detail 直到可用。"""
from __future__ import annotations

import mimetypes
from pathlib import Path

import requests

from .client import ChanjingClient

# service 取值（文档）：ai_creation（AI 创作参考图）、make_video_audio（驱动音频）、
# make_video_background（背景）、customised_person（定制数字人）等
# file_detail.status：0 未同步，1 可用，98 内容安全检测失败，99 已标记删除，100 已清理
FILE_READY = 1
FILE_FAILED = {98, 99, 100}


def upload_file(client: ChanjingClient, path: str | Path, service: str,
                interval: int = 3, timeout: int = 300) -> dict:
    path = Path(path)
    info = client.get("/open/v1/common/create_upload_url", service=service, name=path.name)
    mime = info.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = info.get("headers") or {"Content-Type": mime}   # 接口返回的请求头优先
    with path.open("rb") as f:
        r = requests.put(info["sign_url"], data=f, headers=headers, timeout=300)
    r.raise_for_status()
    file_id = info["file_id"]

    detail = client.poll(
        fetch=lambda: client.get("/open/v1/common/file_detail", id=file_id),
        is_done=lambda d: d.get("status") == FILE_READY,
        is_failed=lambda d: d.get("status") in FILE_FAILED,
        interval=interval, timeout=timeout, label=f"file:{path.name}")
    # file_detail 的地址字段是 file_path（不是 url），可作为 AI 创作的 ref_img_url；
    # 同时补一个 url 别名方便调用方
    return {"file_id": file_id, "url": detail.get("file_path") or info.get("full_path"), **detail}
