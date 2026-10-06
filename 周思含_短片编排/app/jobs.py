from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.config import load_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ShotJob:
    job_id: str
    batch_id: str
    shot_id: str
    platform: str  # feiying | chanjing
    status: str = "queued"  # queued|running|done|failed|cancelled
    progress: float = 0.0
    message: str = ""
    output_path: str = ""
    error: str = ""
    dry_run: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()


@dataclass
class BatchJob:
    batch_id: str
    script_path: str
    title: str
    status: str = "queued"
    dry_run: bool = False
    only_missing: bool = True
    shot_jobs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"batches": {}, "shots": {}})

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert_batch(self, batch: BatchJob) -> None:
        with self._lock:
            data = self._read()
            batch.updated_at = _now()
            data.setdefault("batches", {})[batch.batch_id] = asdict(batch)
            self._write(data)

    def upsert_shot(self, job: ShotJob) -> None:
        with self._lock:
            data = self._read()
            job.touch()
            data.setdefault("shots", {})[job.job_id] = asdict(job)
            self._write(data)

    def get_shot(self, job_id: str) -> ShotJob | None:
        with self._lock:
            raw = self._read().get("shots", {}).get(job_id)
        return ShotJob(**raw) if raw else None

    def get_batch(self, batch_id: str) -> BatchJob | None:
        with self._lock:
            raw = self._read().get("batches", {}).get(batch_id)
        return BatchJob(**raw) if raw else None

    def list_batches(self, limit: int = 30) -> list[dict]:
        with self._lock:
            batches = list(self._read().get("batches", {}).values())
        batches.sort(key=lambda b: b.get("created_at", ""), reverse=True)
        return batches[:limit]

    def batch_detail(self, batch_id: str) -> dict | None:
        with self._lock:
            data = self._read()
            batch = data.get("batches", {}).get(batch_id)
            if not batch:
                return None
            shots = [
                data["shots"][jid]
                for jid in batch.get("shot_jobs", [])
                if jid in data.get("shots", {})
            ]
        return {"batch": batch, "shots": shots}


_store: JobStore | None = None
_worker_started = False
_queue: list[str] = []
_q_lock = threading.Lock()
_handlers: dict[str, Callable[[ShotJob], None]] = {}


def get_store() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore(load_settings().jobs_dir / "queue.json")
    return _store


def register_handler(platform: str, fn: Callable[[ShotJob], None]) -> None:
    _handlers[platform] = fn


def enqueue_shot(job: ShotJob) -> None:
    store = get_store()
    store.upsert_shot(job)
    with _q_lock:
        _queue.append(job.job_id)
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def loop() -> None:
        store = get_store()
        while True:
            job_id = None
            with _q_lock:
                if _queue:
                    job_id = _queue.pop(0)
            if not job_id:
                time.sleep(0.4)
                continue
            job = store.get_shot(job_id)
            if not job or job.status in {"cancelled", "done"}:
                continue
            job.status = "running"
            job.progress = 0.05
            job.message = "开始生成"
            store.upsert_shot(job)
            try:
                handler = _handlers.get(job.platform)
                if not handler:
                    raise RuntimeError(f"无生成器: {job.platform}")
                handler(job)
                job = store.get_shot(job_id) or job
                if job.status != "cancelled":
                    job.status = "done"
                    job.progress = 1.0
                    job.message = "完成"
                    store.upsert_shot(job)
            except Exception as e:
                job = store.get_shot(job_id) or job
                job.status = "failed"
                job.error = str(e)
                job.message = "失败"
                store.upsert_shot(job)
            _refresh_batch_status(job.batch_id)

    threading.Thread(target=loop, daemon=True).start()


def _refresh_batch_status(batch_id: str) -> None:
    store = get_store()
    detail = store.batch_detail(batch_id)
    if not detail:
        return
    shots = detail["shots"]
    batch = BatchJob(**detail["batch"])
    if any(s["status"] == "running" or s["status"] == "queued" for s in shots):
        batch.status = "running"
    elif any(s["status"] == "failed" for s in shots) and all(
        s["status"] in {"done", "failed", "cancelled"} for s in shots
    ):
        batch.status = "partial" if any(s["status"] == "done" for s in shots) else "failed"
    elif all(s["status"] == "done" for s in shots):
        batch.status = "done"
    elif all(s["status"] == "cancelled" for s in shots):
        batch.status = "cancelled"
    else:
        batch.status = "running"
    store.upsert_batch(batch)


def new_ids() -> tuple[str, str]:
    return uuid.uuid4().hex[:10], uuid.uuid4().hex[:12]
