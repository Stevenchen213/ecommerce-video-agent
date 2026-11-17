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
    default_person_id: str
    default_voice_id: str
    ark_api_key: str = ""
    ark_base_url: str = ""
    seedance_model: str = ""
    seedance_ratio: str = "9:16"
    seedance_resolution: str = ""
    seedance_durations: tuple[int, ...] = (5, 10)
    seedance_params_in_text: bool = False
    seedance_max_calls: int = 3
    jianying_draft_dir: str = ""
    doubao_llm_model: str = ""
    doubao_llm_max_rounds: int = 3

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
        default_person_id=os.getenv("DEFAULT_PERSON_ID", ""),
        default_voice_id=os.getenv("DEFAULT_VOICE_ID", ""),
        ark_api_key=os.getenv("ARK_API_KEY", ""),
        ark_base_url=os.getenv("ARK_BASE_URL", ""),
        seedance_model=os.getenv("SEEDANCE_MODEL", ""),
        seedance_ratio=os.getenv("SEEDANCE_RATIO", "9:16"),
        seedance_resolution=os.getenv("SEEDANCE_RESOLUTION", ""),
        seedance_durations=tuple(
            int(x) for x in os.getenv("SEEDANCE_DURATIONS", "5,10").split(",") if x.strip()
        ),
        seedance_params_in_text=os.getenv("SEEDANCE_PARAMS_IN_TEXT", "0") in {"1", "true", "True"},
        seedance_max_calls=int(os.getenv("SEEDANCE_MAX_CALLS_PER_RUN", "3")),
        jianying_draft_dir=os.getenv("JIANYING_DRAFT_DIR", ""),
        doubao_llm_model=os.getenv("DOUBAO_LLM_MODEL", ""),
        doubao_llm_max_rounds=int(os.getenv("DOUBAO_LLM_MAX_ROUNDS", "3")),
    )
