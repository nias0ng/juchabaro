"""Publication process lock의 소유·해제 상태를 검증한다."""

import multiprocessing
from pathlib import Path

import pytest

from src.storage.publication_runtime_lock import (
    PublicationRuntimeAlreadyActiveError,
    PublicationRuntimeLock,
)


def _hold_lock(path: str, ready, release) -> None:
    lock = PublicationRuntimeLock(Path(path))
    lock.acquire()
    ready.set()
    release.wait(timeout=5.0)
    lock.release()


def test_only_one_publication_runtime_can_own_the_same_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".runtime.db.publication.lock"
    first = PublicationRuntimeLock(path)
    second = PublicationRuntimeLock(path)

    first.acquire()
    assert first.is_acquired is True
    with pytest.raises(PublicationRuntimeAlreadyActiveError):
        second.acquire()
    assert second.is_acquired is False

    first.release()
    second.acquire()
    assert second.is_acquired is True
    second.release()

    assert first.is_acquired is False
    assert second.is_acquired is False


def test_release_is_idempotent_and_lock_file_keeps_stable_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".runtime.db.publication.lock"
    lock = PublicationRuntimeLock(path)

    lock.acquire()
    lock.acquire()
    lock.release()
    lock.release()

    assert path.is_file()


def test_lock_excludes_another_process_until_owner_releases(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".runtime.db.publication.lock"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    owner = context.Process(
        target=_hold_lock,
        args=(str(path), ready, release),
    )
    owner.start()
    try:
        assert ready.wait(timeout=5.0)
        contender = PublicationRuntimeLock(path)
        with pytest.raises(PublicationRuntimeAlreadyActiveError):
            contender.acquire()

        release.set()
        owner.join(timeout=5.0)
        assert owner.exitcode == 0

        contender.acquire()
        contender.release()
    finally:
        release.set()
        owner.join(timeout=1.0)
        if owner.is_alive():
            owner.terminate()
            owner.join(timeout=5.0)
