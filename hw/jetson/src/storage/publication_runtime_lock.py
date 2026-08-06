"""하나의 Jetson DB에 대한 outbound publication runtime을 단일화한다."""

from __future__ import annotations

import errno
import fcntl
from pathlib import Path
from typing import BinaryIO


class PublicationRuntimeAlreadyActiveError(RuntimeError):
    """동일한 durable queue를 소유한 publication runtime이 이미 실행 중이다."""


class PublicationRuntimeLock:
    """Process 종료로 자동 해제되는 non-blocking file lock."""

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        self._handle: BinaryIO | None = None

    @property
    def is_acquired(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise PublicationRuntimeAlreadyActiveError(
                    "another Jetson publication runtime already owns "
                    f"{self._path}"
                ) from error
            raise
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
