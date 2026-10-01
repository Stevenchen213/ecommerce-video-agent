from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Status = Literal["pending", "running", "done", "failed"]


@dataclass
class JobRecord:
    shot_id: str
    platform: str
    status: Status = "pending"
    local_path: str | None = None
    task_id: str | None = None
    error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {"jobs": {}}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def upsert(self, record: JobRecord) -> None:
        record.updated_at = datetime.now(timezone.utc).isoformat()
        self._data.setdefault("jobs", {})[record.shot_id] = asdict(record)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, shot_id: str) -> JobRecord | None:
        raw = self._data.get("jobs", {}).get(shot_id)
        if not raw:
            return None
        return JobRecord(**raw)

    def all_done(self, shot_ids: list[str]) -> bool:
        for sid in shot_ids:
            rec = self.get(sid)
            if not rec or rec.status != "done" or not rec.local_path:
                return False
        return True

    def list_all(self) -> list[JobRecord]:
        jobs = self._data.get("jobs", {})
        return [JobRecord(**raw) for raw in jobs.values()]

    def reload(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._data = {"jobs": {}}
