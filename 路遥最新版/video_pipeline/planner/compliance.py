"""广告法用语检查（本地规则，不调 API）。

带货口播最常见的违规是极限词和功效承诺。这里只做「明显违规」的硬拦截，
更细的判断交给豆包审核（llm.review_script）。词表可在 brief.banned_words 里追加。
"""

from __future__ import annotations

# 极限词 / 绝对化用语
_ABSOLUTE = [
    "最好", "最佳", "最强", "最优", "最便宜", "最低价", "最高级", "最先进", "最受欢迎",
    "第一", "No.1", "NO.1", "TOP1", "顶级", "极品", "极致", "首选", "唯一", "独家",
    "史上", "全网最", "全球首", "国家级", "世界级", "王牌", "绝对", "100%", "百分百",
    "万能", "永久", "零风险", "无敌",
]
# 食品 / 保健类不能说的功效承诺
_EFFICACY = [
    "治疗", "治愈", "根治", "药效", "疗效", "包治", "抗癌", "防癌", "降血压", "降血糖",
    "无副作用", "减肥", "瘦身", "排毒", "增强免疫力", "延年益寿",
]

DEFAULT_BANNED = tuple(_ABSOLUTE + _EFFICACY)


def find_banned(text: str, extra: list[str] | tuple[str, ...] = ()) -> list[str]:
    """返回文案里命中的违禁词（去重、保持出现顺序）。"""
    hits: list[str] = []
    for word in (*DEFAULT_BANNED, *extra):
        if word and word in text and word not in hits:
            hits.append(word)
    return hits
