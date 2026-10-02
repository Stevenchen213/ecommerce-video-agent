"""全局配置：全部从环境变量读取，密钥不写进代码。"""
import os
from dataclasses import dataclass


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
    ai_label_font: str = os.getenv(
        "AI_LABEL_FONT", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")

    # 图生视频默认模型。文档中 Kling2.1 Master 的编码是 kling-v2-1-master（无 tx_ 前缀；
    # 只有 Kling3.0 系列才带 tx_ 前缀）。其它模型编码见文档「视频模型使用说明」
    i2v_model_code: str = os.getenv("CHANJING_I2V_MODEL", "kling-v2-1-master")


settings = Settings()
