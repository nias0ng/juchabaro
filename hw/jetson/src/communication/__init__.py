"""Backend wire adapter와 local delivery workflow 사이의 경계."""

from .outbox import PreparedPublication, SQLiteOutboxWriter

__all__ = ["PreparedPublication", "SQLiteOutboxWriter"]
