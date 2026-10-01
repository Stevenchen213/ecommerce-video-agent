from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PACKAGE_ROOT.parent


@dataclass(frozen=True)
class Settings:
    root: Path
    use_mock: bool
    width: int
    height: int
    fps: int
    feiying_api_base: str
    feiying_api_key: str
    chanjing_api_base: str
    chanjing_api_key: str
    chanjing_app_id: str
    chanjing_secret_key: str
    luyao_root: str
    default_person_id: str
    default_voice_id: str

    @property
    def library_dir(self) -> Path:
        return self.root / "library"

    @property
    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def brand_dir(self) -> Path:
        return self.root / "assets" / "brand"

    @property
    def tmp_dir(self) -> Path:
        return self.root / "tmp"


def load_settings() -> Settings:
    env_path = PACKAGE_ROOT / ".env"
    example = PACKAGE_ROOT / "config.example.env"
    if env_path.exists():
        load_dotenv(env_path)
    elif example.exists():
        load_dotenv(example)

    root = Path(os.getenv("VIDEO_PIPELINE_ROOT") or PACKAGE_ROOT).resolve()
    return Settings(
        root=root,
        use_mock=os.getenv("VIDEO_PIPELINE_USE_MOCK", "1") not in {"0", "false", "False"},
        width=int(os.getenv("VIDEO_PIPELINE_WIDTH", "1080")),
        height=int(os.getenv("VIDEO_PIPELINE_HEIGHT", "1920")),
        fps=int(os.getenv("VIDEO_PIPELINE_FPS", "30")),
        feiying_api_base=os.getenv("FEIYING_API_BASE", ""),
        feiying_api_key=os.getenv("FEIYING_API_KEY", ""),
        chanjing_api_base=os.getenv("CHANJING_API_BASE", "")
        or os.getenv("CHANJING_BASE_URL", ""),
        chanjing_api_key=os.getenv("CHANJING_API_KEY", ""),
        chanjing_app_id=os.getenv("CHANJING_APP_ID", ""),
        chanjing_secret_key=os.getenv("CHANJING_SECRET_KEY", ""),
        luyao_root=os.getenv("LUYAO_ROOT", ""),
        default_person_id=os.getenv("DEFAULT_PERSON_ID", "C-PLATFORM-DEMO-001"),
        default_voice_id=os.getenv("DEFAULT_VOICE_ID", ""),
    )
