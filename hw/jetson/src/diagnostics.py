"""Jetson 내부 판단을 비영속 구조화 이벤트로 관측하는 경계.

진단 이벤트는 도메인 상태나 Backend 전송 계약이 아니다. Core는 이미 계산한
판단 근거만 ``DiagnosticsSink``에 전달하며, sink 실패가 frame 처리를 바꾸지
않도록 ``emit_best_effort``를 통해 호출한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import logging
import math
from types import MappingProxyType
from typing import Protocol, TypeAlias

from src.domain.models import require_aware


logger = logging.getLogger(__name__)

DiagnosticAttribute: TypeAlias = str | int | float | bool | None


class DiagnosticEventType(str, Enum):
    """운영 질문과 1:1로 대응하는 안정적인 진단 이벤트 이름."""

    DETECTION_FRAME_EVALUATED = "DETECTION_FRAME_EVALUATED"
    IDENTITY_RESOLUTION_EVALUATED = "IDENTITY_RESOLUTION_EVALUATED"
    ENTRY_MATCH_EVALUATED = "ENTRY_MATCH_EVALUATED"
    PARKING_ELIGIBILITY_EVALUATED = "PARKING_ELIGIBILITY_EVALUATED"
    EXIT_TRAVERSAL_EVALUATED = "EXIT_TRAVERSAL_EVALUATED"
    INCIDENT_PROJECTION_EVALUATED = "INCIDENT_PROJECTION_EVALUATED"
    EVIDENCE_PUBLICATION_EVALUATED = "EVIDENCE_PUBLICATION_EVALUATED"


class DiagnosticSeverity(str, Enum):
    """도메인 결과와 독립적인 진단 로그 중요도."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, kw_only=True)
class DiagnosticEvent:
    """민감정보와 큰 payload를 제외한 단일 판단 관측값.

    ``attributes``는 로그·JSON sink가 그대로 처리할 수 있는 scalar만 허용한다.
    bbox, 이미지, 요청 payload 같은 큰 값은 별도 evidence 계약의 책임이다.
    """

    event_type: DiagnosticEventType
    occurred_at: datetime
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO
    attributes: Mapping[str, DiagnosticAttribute] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, "occurred_at")
        copied = dict(self.attributes)
        for key, value in copied.items():
            if not isinstance(key, str) or not key:
                raise ValueError("diagnostic attribute keys must be non-empty strings")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise TypeError("diagnostic attributes must be JSON scalar values")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("diagnostic float attributes must be finite")
        object.__setattr__(self, "attributes", MappingProxyType(copied))

    def to_json(self) -> str:
        """로그 adapter가 사용하는 결정적 UTF-8 JSON 표현을 반환한다."""

        return json.dumps(
            {
                "attributes": dict(self.attributes),
                "eventType": self.event_type.value,
                "occurredAt": self.occurred_at.isoformat(),
                "severity": self.severity.value,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class DiagnosticsSink(Protocol):
    """비영속 진단 이벤트 소비 경계."""

    def emit(self, event: DiagnosticEvent) -> None:
        """이벤트를 소비하되 도메인 상태를 변경하지 않는다."""


class NullDiagnosticsSink:
    """진단 출력이 필요 없는 테스트·리플레이의 기본 adapter."""

    def emit(self, event: DiagnosticEvent) -> None:
        del event


class LoggingDiagnosticsAdapter:
    """진단 이벤트를 한 줄 JSON application log로 기록한다."""

    _LEVELS = {
        DiagnosticSeverity.INFO: logging.INFO,
        DiagnosticSeverity.WARNING: logging.WARNING,
        DiagnosticSeverity.ERROR: logging.ERROR,
    }

    def __init__(self, target_logger: logging.Logger | None = None) -> None:
        self._logger = target_logger if target_logger is not None else logger

    def emit(self, event: DiagnosticEvent) -> None:
        self._logger.log(
            self._LEVELS[event.severity],
            "Jetson diagnostic event. %s",
            event.to_json(),
        )


def emit_best_effort(
    sink: DiagnosticsSink,
    event: DiagnosticEvent,
) -> None:
    """진단 adapter 장애를 frame/domain 판단 실패로 전파하지 않는다."""

    try:
        sink.emit(event)
    except Exception:
        logger.exception(
            "Jetson diagnostic event 기록에 실패했습니다. eventType=%s",
            event.event_type.value,
        )
