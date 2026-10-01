from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from video_pipeline.schema import Script, Shot


@dataclass
class MissingShot:
    shot_id: str
    platform: str
    expected_path: Path


@dataclass
class LibraryCheckResult:
    ok: bool
    present: dict[str, Path]
    missing: list[MissingShot]

    def raise_if_missing(self) -> None:
        if self.ok:
            return
        lines = [
            f"- {m.shot_id} ({m.platform}): 期望 {m.expected_path}" for m in self.missing
        ]
        raise FileNotFoundError(
            "以下必用镜头文件缺失，无法组装：\n" + "\n".join(lines)
        )


def expected_library_path(library_dir: Path, shot: Shot) -> Path:
    return library_dir / shot.platform.value / f"{shot.id}.mp4"


def check_library(script: Script, library_dir: Path) -> LibraryCheckResult:
    present: dict[str, Path] = {}
    missing: list[MissingShot] = []
    for shot in script.shots:
        path = expected_library_path(library_dir, shot)
        if path.exists() and path.stat().st_size > 0:
            present[shot.id] = path
        else:
            missing.append(
                MissingShot(
                    shot_id=shot.id,
                    platform=shot.platform.value,
                    expected_path=path,
                )
            )
    return LibraryCheckResult(ok=not missing, present=present, missing=missing)
