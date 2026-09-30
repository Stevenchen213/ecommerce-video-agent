"""以整条配音为主线切时间轴。

做法：用完整口播一次性生成数字人视频 → 声音统一、对口型准确；
再按每个镜头口播字数占比，把真实音频时长分配给各镜头。
（若蝉镜返回字幕时间戳，可替换 allocate() 做到逐句精确对齐。）
"""
from __future__ import annotations

import re

_SPOKEN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def spoken_len(text: str) -> int:
    return max(1, len(_SPOKEN.findall(text)))


def allocate(shots: list[dict], total_duration: float) -> list[tuple[float, float]]:
    weights = [spoken_len(s["voiceover"]) for s in shots]
    total_w = sum(weights)
    spans, t = [], 0.0
    for w in weights:
        d = total_duration * w / total_w
        spans.append((round(t, 3), round(t + d, 3)))
        t += d
    spans[-1] = (spans[-1][0], round(total_duration, 3))
    return spans
