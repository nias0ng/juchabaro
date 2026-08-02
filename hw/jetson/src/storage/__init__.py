"""Jetson durable state를 위한 SQLite 영속 기반.

연결 정책, schema migration, transaction boundary와 domain repository가 공유할
최소 primitive를 소유한다. camera frame, detection과 TrackSegment는 이 경계를
넘지 않는다.
"""

from .database import (
    StorageConfigurationError,
    StorageIntegrityError,
    connect_database,
    open_database,
    quick_check,
)
from .codecs import (
    datetime_from_epoch_microseconds,
    datetime_to_epoch_microseconds,
    uuid_from_text,
    uuid_to_text,
)
from .migration_runner import (
    MigrationApplyError,
    MigrationChecksumMismatch,
    MigrationHistoryError,
    MigrationRunner,
)
from .models import (
    AcceptedInputRecord,
    DeliveryReceiptRecord,
    OutboxRecord,
    PendingHandoffRecord,
    PendingHandoffState,
    PublicationApplicationStatus,
    TombstoneRecord,
)
from .repositories import (
    AcceptedInputConflictError,
    AcceptedInputRepository,
    AcceptanceResult,
    OptimisticConcurrencyError,
    OutboxConflictError,
    OutboxEnqueueResult,
    OutboxRepository,
    optimistic_update,
)
from .unit_of_work import TransactionStateError, UnitOfWork

__all__ = [
    "AcceptedInputConflictError",
    "AcceptedInputRecord",
    "AcceptedInputRepository",
    "AcceptanceResult",
    "DeliveryReceiptRecord",
    "MigrationApplyError",
    "MigrationChecksumMismatch",
    "MigrationHistoryError",
    "MigrationRunner",
    "OptimisticConcurrencyError",
    "OutboxConflictError",
    "OutboxEnqueueResult",
    "OutboxRecord",
    "OutboxRepository",
    "PendingHandoffRecord",
    "PendingHandoffState",
    "PublicationApplicationStatus",
    "StorageConfigurationError",
    "StorageIntegrityError",
    "TransactionStateError",
    "TombstoneRecord",
    "UnitOfWork",
    "connect_database",
    "datetime_from_epoch_microseconds",
    "datetime_to_epoch_microseconds",
    "open_database",
    "optimistic_update",
    "quick_check",
    "uuid_from_text",
    "uuid_to_text",
]
