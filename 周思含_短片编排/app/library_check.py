from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.schema import Script, Shot


@dataclass
class MissingShot:
    shot_id: str
    platform: str
    expected_path: Path


@dataclass
class LibraryCheck:
    present: dict[str, Path]
    missing: list[MissingShot]

    @property
    def ok(self) -> bool:
        return not self.missing

    def raise_if_missing(self) -> None:
        if self.missing:
            lines = [
                f"- {m.shot_id} ({m.platform}): {m.expected_path}" for m in self.missing
            ]
            raise FileNotFoundError("缺少短片：\n" + "\n".join(lines))


def expected_path(library_dir: Path, shot: Shot) -> Path:
    return library_dir / shot.platform.value / f"{shot.id}.mp4"


def check_library(script: Script, library_dir: Path) -> LibraryCheck:
    present: dict[str, Path] = {}
    missing: list[MissingShot] = []
    for shot in script.shots:
        path = expected_path(library_dir, shot)
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
    return LibraryCheck(present=present, missing=missing)
