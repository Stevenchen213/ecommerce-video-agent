"""全局配置：全部从环境变量读取，密钥不写进代码。"""
import os
from dataclasses import dataclass

# AI 标识字体：Windows 默认微软雅黑，Linux/Mac 默认 Noto CJK；可用 AI_LABEL_FONT 覆盖
_DEFAULT_FONT = ("C:/Windows/Fonts/msyh.ttc" if os.name == "nt"
                 else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


@dataclass(frozen=True)
class Settings:
    app_id: str = os.getenv("CHANJING_APP_ID", "")
    secret_key: str = os.getenv("CHANJING_SECRET_KEY", "")
    # 官方 skill 使用 open-api.chanjing.cc；部分文档示例为 https://www.chanjing.cc/api，以你们合作方给的地址为准
    base_url: str = os.getenv("CHANJING_BASE_URL", "https://open-api.chanjing.cc")
    request_timeout: int = int(os.getenv("CHANJING_TIMEOUT", "30"))
    poll_interval: int = int(os.getenv("CHANJING_POLL_INTERVAL", "10"))
    poll_timeout: int = int(os.getenv("CHANJING_POLL_TIMEOUT", "1800"))

    # 成片参数
    width: int = 1080
    height: int = 1920
    fps: int = 30
    # AI 生成标识（《人工智能生成合成内容标识办法》显式标识）
    ai_label_text: str = os.getenv("AI_LABEL_TEXT", "本视频由AI生成")
    ai_label_font: str = os.getenv("AI_LABEL_FONT", _DEFAULT_FONT)

    # 图生视频默认模型。tx_kling-v3-0-image2video 已按文档「Kling3.0（图生视频）」页核对
    # （支持 1-7 张参考图、5-15 秒）。三模型对比测试出结果后，用 CHANJING_I2V_MODEL 改默认值，
    # 并通知周思含同步工作台 settings_store.py 里的 chanjing_i2v_model（目前写的是 tx_kling-v2-1-master）
    i2v_model_code: str = os.getenv("CHANJING_I2V_MODEL", "tx_kling-v3-0-image2video")
    i2v_clarity: int = int(os.getenv("CHANJING_I2V_CLARITY", "1080"))


settings = Settings()
