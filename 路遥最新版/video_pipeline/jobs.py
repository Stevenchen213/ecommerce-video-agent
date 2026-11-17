"""镜头生成任务状态：jobs/state.json（按 shot_id 记录 running / done / failed）。

pipeline.py 用它做三件事：
- 记录每个镜头的生成状态，供 `status` 命令和 Web 端查看
- 失败时保留错误信息，方便 `retry` 单镜重跑
- 保存 fingerprint（文案 + 数字人 + 声音的哈希）：内容没变就不重复调用付费 API
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Literal

JobStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class JobRecord:
    shot_id: str
    platform: str
    status: JobStatus = "pending"
    local_path: str | None = None
    task_id: str | None = None
    error: str | None = None
    fingerprint: str | None = None
    updated_at: float = field(default_factory=time.time)


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self.reload()

    def reload(self) -> None:
        self._jobs = {}
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # 状态文件损坏不影响出片，下次写入时覆盖
        known = {f.name for f in fields(JobRecord)}
        for item in data.get("jobs", []):
            rec = JobRecord(**{k: v for k, v in item.items() if k in known})
            self._jobs[rec.shot_id] = rec

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"jobs": [asdict(j) for j in self._jobs.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, shot_id: str) -> JobRecord | None:
        return self._jobs.get(shot_id)

    def upsert(self, record: JobRecord) -> JobRecord:
        with self._lock:
            old = self._jobs.get(record.shot_id)
            # running / failed 时不清掉上一次成功的 fingerprint 以外的信息
            if old and record.fingerprint is None and record.status != "done":
                record.fingerprint = old.fingerprint
            record.updated_at = time.time()
            self._jobs[record.shot_id] = record
            self._save()
            return record

    def list_all(self) -> list[JobRecord]:
        return list(self._jobs.values())
