from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.compose import concat_segments, probe, transitions_from_shots
from app.config import Settings, load_settings
from app.library_check import check_library, expected_path
from app.schema import Platform, Script, load_script


@dataclass
class Plan:
    feiying: list[str]
    chanjing: list[str]
    timeline: list[dict]

    def to_dict(self) -> dict:
        return {
            "feiying": self.feiying,
            "chanjing": self.chanjing,
            "timeline": self.timeline,
        }


def plan_script(script: Script) -> Plan:
    feiying: list[str] = []
    chanjing: list[str] = []
    timeline: list[dict] = []
    for shot in script.shots:
        if shot.platform == Platform.FEIYING:
            feiying.append(shot.id)
            timeline.append({"kind": "feiying", "shot_id": shot.id, "role": shot.role})
        elif shot.platform == Platform.CHANJING:
            chanjing.append(shot.id)
            timeline.append({"kind": "chanjing", "shot_id": shot.id, "role": shot.role})
        else:
            raise ValueError(f"未知 platform: {shot.platform}")
    return Plan(feiying=feiying, chanjing=chanjing, timeline=timeline)


@dataclass
class AssembleResult:
    title: str
    output_path: Path
    duration_sec: float | None
    library: dict[str, str]
    plan: dict


class Pipeline:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()

    def _ensure_dirs(self) -> None:
        for p in (
            self.settings.library_dir / "feiying",
            self.settings.library_dir / "chanjing",
            self.settings.output_dir,
            self.settings.tmp_dir,
            self.settings.jobs_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def inspect(self, script_path: str | Path) -> dict:
        script = load_script(script_path)
        plan = plan_script(script)
        check = check_library(script, self.settings.library_dir)
        return {
            "title": script.title,
            "description": script.description,
            "brand_name": script.brand_name,
            "path": str(Path(script_path).resolve()),
            "shots": [s.model_dump() for s in script.shots],
            "plan": plan.to_dict(),
            "library_ok": check.ok,
            "missing": [
                {
                    "shot_id": m.shot_id,
                    "platform": m.platform,
                    "expected_path": str(m.expected_path),
                }
                for m in check.missing
            ],
            "present": {k: str(v) for k, v in check.present.items()},
        }

    def assemble(
        self,
        script_path: str | Path,
        output_name: str = "final.mp4",
    ) -> AssembleResult:
        self._ensure_dirs()
        script = load_script(script_path)
        plan = plan_script(script)
        check = check_library(script, self.settings.library_dir)
        check.raise_if_missing()

        ordered: list[Path] = []
        for shot in script.shots:
            ordered.append(check.present[shot.id])

        out = self.settings.output_dir / output_name
        work = self.settings.tmp_dir / "assemble"
        transitions, fades = transitions_from_shots(
            script.shots, default=script.default_transition
        )
        result = concat_segments(
            ordered,
            out,
            work_dir=work,
            width=self.settings.width,
            height=self.settings.height,
            fps=self.settings.fps,
            transitions=transitions,
            fade_durations=fades,
        )
        info = probe(result.output_path)
        return AssembleResult(
            title=script.title,
            output_path=result.output_path,
            duration_sec=info.duration,
            library={k: str(v) for k, v in check.present.items()},
            plan=plan.to_dict(),
        )

    def list_scripts(self) -> list[dict]:
        examples = self.settings.examples_dir
        items: list[dict] = []
        if not examples.exists():
            return items
        for p in sorted(list(examples.glob("*.yaml")) + list(examples.glob("*.yml"))):
            items.append({"name": p.name, "path": str(p.resolve())})
        return items

    def list_library(self) -> dict:
        self._ensure_dirs()
        result = {"feiying": [], "chanjing": []}
        for plat in ("feiying", "chanjing"):
            folder = self.settings.library_dir / plat
            for p in sorted(folder.glob("*.mp4")):
                result[plat].append(
                    {
                        "shot_id": p.stem,
                        "path": str(p.resolve()),
                        "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                    }
                )
        return result

    def list_outputs(self) -> list[dict]:
        self._ensure_dirs()
        items = []
        for p in sorted(
            self.settings.output_dir.glob("*.mp4"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            items.append(
                {
                    "name": p.name,
                    "path": str(p.resolve()),
                    "preview_url": f"/media/output/{p.name}",
                    "mtime": p.stat().st_mtime,
                    "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                }
            )
        return items
