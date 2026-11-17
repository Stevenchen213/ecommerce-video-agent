from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import shutil


class Storage(ABC):
    @abstractmethod
    def ensure_dir(self, path: Path) -> Path: ...

    @abstractmethod
    def put_file(self, src: Path, dest: Path) -> Path: ...

    @abstractmethod
    def exists(self, path: Path) -> bool: ...


class LocalStorage(Storage):
    def ensure_dir(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def put_file(self, src: Path, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        return dest

    def exists(self, path: Path) -> bool:
        return path.exists()


class ObjectStoragePlaceholder(Storage):
    """预留 OSS/S3：后续实现 upload/download，Assembler 仍只吃本地 path。"""

    def __init__(self, local_fallback: LocalStorage | None = None):
        self.local = local_fallback or LocalStorage()

    def ensure_dir(self, path: Path) -> Path:
        return self.local.ensure_dir(path)

    def put_file(self, src: Path, dest: Path) -> Path:
        # TODO: upload to cloud, return local cache path
        return self.local.put_file(src, dest)

    def exists(self, path: Path) -> bool:
        return self.local.exists(path)
