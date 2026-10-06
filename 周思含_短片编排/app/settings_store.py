from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import PROJECT_ROOT


SETTINGS_PATH = PROJECT_ROOT / "data" / "settings.json"


@dataclass
class AppSettings:
    use_mock: bool = True
    feiying_api_base: str = "https://hfw-api.hifly.cc"
    feiying_api_key: str = ""
    feiying_default_person_id: str = "qbK4XQ1bdH0Of_vcczaSRA"
    feiying_default_voice_id: str = "b0c66f97-4b39-46c3-81ff-33df16d8ac41"
    chanjing_base_url: str = "https://open-api.chanjing.cc"
    chanjing_app_id: str = ""
    chanjing_secret_key: str = ""
    chanjing_root: str = ""  # 蝉镜侧交付目录（只读引用）
    chanjing_assets_dir: str = ""  # 产品素材根目录，默认 <chanjing_root>/assets
    chanjing_i2v_model: str = "tx_kling-v2-1-master"
    chanjing_poll_interval: int = 10
    chanjing_poll_timeout: int = 1800
    estimate_feiying_points_per_sec: float = 9.5
    estimate_chanjing_note: str = "图生视频按蝉豆/次计，实拍 clips 不花钱"

    def public_dict(self) -> dict:
        d = asdict(self)
        if d.get("feiying_api_key"):
            k = d["feiying_api_key"]
            d["feiying_api_key_masked"] = (k[:4] + "****" + k[-4:]) if len(k) > 8 else "****"
        else:
            d["feiying_api_key_masked"] = ""
        if d.get("chanjing_secret_key"):
            k = d["chanjing_secret_key"]
            d["chanjing_secret_key_masked"] = (k[:4] + "****" + k[-4:]) if len(k) > 8 else "****"
        else:
            d["chanjing_secret_key_masked"] = ""
        return d


def load_app_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    base = asdict(AppSettings())
    base.update({k: v for k, v in raw.items() if k in base})
    return AppSettings(**base)


def save_app_settings(data: dict) -> AppSettings:
    cur = asdict(load_app_settings())
    for k, v in data.items():
        if k not in cur:
            continue
        if k in {"feiying_api_key", "chanjing_secret_key"} and v == "" and cur.get(k):
            continue
        cur[k] = v
    settings = AppSettings(**cur)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings
