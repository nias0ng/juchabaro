"""durable state와 outbox를 묶는 명시적 write transaction boundary."""

from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Type


class TransactionStateError(RuntimeError):
    """중첩·비활성 또는 외부에서 변경된 transaction 상태 오류."""


class UnitOfWork:
    """SQLite ``BEGIN IMMEDIATE``로 local write unit 하나를 직렬화한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active and self.connection.in_transaction

    def __enter__(self) -> "UnitOfWork":
        if self._active or self.connection.in_transaction:
            raise TransactionStateError("nested UnitOfWork transactions are not supported")
        self.connection.execute("BEGIN IMMEDIATE")
        self._active = True
        return self

    def commit(self) -> None:
        if not self.is_active:
            raise TransactionStateError("UnitOfWork is not active")
        try:
            self.connection.commit()
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
        finally:
            self._active = False

    def rollback(self) -> None:
        if not self._active:
            raise TransactionStateError("UnitOfWork is not active")
        try:
            if self.connection.in_transaction:
                self.connection.rollback()
        finally:
            self._active = False

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if not self._active:
            return False
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def require_write_transaction(connection: sqlite3.Connection) -> None:
    """합의한 consistency boundary 밖에서 repository가 쓰는 것을 거부한다."""

    if not connection.in_transaction:
        raise TransactionStateError("a write UnitOfWork is required")
