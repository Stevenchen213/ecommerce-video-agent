"""数字人视频合成：查形象 → 组装 payload → create_video → 轮询 /open/v1/video。"""
from __future__ import annotations

from .client import ChanjingClient

STATUS_SUCCESS = 30
STATUS_FAILED = {40, 41, 50, 1101, 999}


def get_person(client: ChanjingClient, person_id: str, source: str) -> dict:
    """查询数字人真实记录。找不到直接报错，不猜默认值。"""
    if source == "common":
        page = 1
        while True:
            data = client.get("/open/v1/list_common_dp", page=page, size=100)
            items = data.get("list", [])
            found = next((p for p in items if p.get("id") == person_id), None)
            total_page = data.get("page_info", {}).get("total_page", page)
            if found or not items or page >= total_page:
                break
            page += 1
    else:
        data = client.post("/open/v1/list_customised_person", {"page": 1, "page_size": 100})
        found = next((p for p in data.get("list", []) if p.get("id") == person_id), None)
    if not found:
        raise ValueError(f"数字人 {person_id} 不存在于 {source} 列表")
    return found


def pick_figure(person: dict, wanted: str | None) -> dict:
    """公共数字人有多个形态(figures)，必须从真实存在的形态里选，禁止默认 whole_body。"""
    figures = person.get("figures") or []
    if not figures:        # 定制数字人通常没有 figures，直接用本身宽高
        return {"type": None, "width": person.get("width"), "height": person.get("height")}
    if wanted:
        fig = next((f for f in figures if f.get("type") == wanted), None)
        if not fig:
            raise ValueError(f"形态 {wanted} 不存在，可用：{[f.get('type') for f in figures]}")
        return fig
    return figures[0]


def build_tts_payload(person_id: str, figure: dict, voice_id: str, text: str,
                      screen_w: int, screen_h: int, show_subtitle: bool = False) -> dict:
    """文本驱动数字人。字段结构以蝉镜 create_video 文档为准，改这里即可。"""
    fw, fh = figure.get("width") or screen_w, figure.get("height") or screen_h
    if fh > fw and screen_w > screen_h:
        raise ValueError("竖版数字人不能放进横屏任务，会变形")
    scale = min(screen_w / fw, screen_h / fh)       # 等比缩放，保持原始比例
    w, h = int(fw * scale), int(fh * scale)
    person = {"id": person_id, "x": (screen_w - w) // 2, "y": screen_h - h,
              "width": w, "height": h}
    if figure.get("type"):
        person["figure_type"] = figure["type"]
    payload = {
        "person": person,
        "audio": {"type": "tts", "tts": {"text": [text], "speed": 1, "audio_man": voice_id},
                  "volume": 100, "language": "cn"},
        "screen_width": screen_w,
        "screen_height": screen_h,
        "bg_color": "#EDEDED",
    }
    if show_subtitle:   # 官方推荐的 1080p 默认值；字幕若在合成阶段统一加，这里保持关闭
        payload["subtitle_config"] = {"x": 31, "y": 1521, "width": 1000, "height": 200,
                                      "font_size": 64, "stroke_width": 7, "asr_type": 0}
    else:
        payload["hide_subtitle"] = True
    return payload


def create_video(client: ChanjingClient, payload: dict) -> str:
    return client.post("/open/v1/create_video", payload)   # data 为 video_id


def wait_video(client: ChanjingClient, video_id: str, interval: int, timeout: int) -> dict:
    return client.poll(
        fetch=lambda: client.get("/open/v1/video", id=video_id),
        is_done=lambda d: d.get("status") == STATUS_SUCCESS and bool(d.get("video_url")),
        is_failed=lambda d: d.get("status") in STATUS_FAILED,
        interval=interval, timeout=timeout, label=f"avatar:{video_id}")
