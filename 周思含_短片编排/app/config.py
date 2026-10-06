from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent


@dataclass(frozen=True)
class Settings:
    root: Path
    width: int
    height: int
    fps: int

    @property
    def library_dir(self) -> Path:
        return self.root / "library"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def tmp_dir(self) -> Path:
        return self.root / "tmp"

    @property
    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    @property
    def examples_dir(self) -> Path:
        return self.root / "examples"

    @property
    def web_dir(self) -> Path:
        return self.root / "web"


def load_settings() -> Settings:
    env = PROJECT_ROOT / ".env"
    if env.exists():
        load_dotenv(env)
    root = Path(os.getenv("CLIP_ASSEMBLER_ROOT") or PROJECT_ROOT).resolve()
    return Settings(
        root=root,
        width=int(os.getenv("CLIP_WIDTH", "1080")),
        height=int(os.getenv("CLIP_HEIGHT", "1920")),
        fps=int(os.getenv("CLIP_FPS", "30")),
    )
