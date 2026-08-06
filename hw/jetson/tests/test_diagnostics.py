"""비영속 진단 이벤트와 logging adapter 계약."""

from datetime import datetime, timezone
import json
import logging

import pytest

from src.diagnostics import (
    DiagnosticEvent,
    DiagnosticEventType,
    DiagnosticSeverity,
    LoggingDiagnosticsAdapter,
    emit_best_effort,
)


OCCURRED_AT = datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc)


def test_logging_adapter_emits_one_structured_json_record(caplog) -> None:
    target_logger = logging.getLogger("test.jetson.diagnostics")
    adapter = LoggingDiagnosticsAdapter(target_logger)
    event = DiagnosticEvent(
        event_type=DiagnosticEventType.IDENTITY_RESOLUTION_EVALUATED,
        occurred_at=OCCURRED_AT,
        severity=DiagnosticSeverity.WARNING,
        attributes={
            "cameraId": "cam-1",
            "score": 0.34,
            "physicalVehicleId": None,
        },
    )

    with caplog.at_level(logging.WARNING, logger=target_logger.name):
        adapter.emit(event)

    assert len(caplog.records) == 1
    prefix = "Jetson diagnostic event. "
    assert caplog.records[0].message.startswith(prefix)
    payload = json.loads(caplog.records[0].message.removeprefix(prefix))
    assert payload == {
        "attributes": {
            "cameraId": "cam-1",
            "physicalVehicleId": None,
            "score": 0.34,
        },
        "eventType": "IDENTITY_RESOLUTION_EVALUATED",
        "occurredAt": "2026-08-06T07:00:00+00:00",
        "severity": "WARNING",
    }


def test_diagnostic_event_rejects_non_scalar_or_non_finite_attributes() -> None:
    with pytest.raises(TypeError, match="JSON scalar"):
        DiagnosticEvent(
            event_type=DiagnosticEventType.DETECTION_FRAME_EVALUATED,
            occurred_at=OCCURRED_AT,
            attributes={"bbox": [0.1, 0.2, 0.3, 0.4]},  # type: ignore[dict-item]
        )

    with pytest.raises(ValueError, match="finite"):
        DiagnosticEvent(
            event_type=DiagnosticEventType.DETECTION_FRAME_EVALUATED,
            occurred_at=OCCURRED_AT,
            attributes={"inferenceMs": float("nan")},
        )


def test_sink_failure_is_logged_without_becoming_a_domain_error(caplog) -> None:
    class BrokenSink:
        def emit(self, event: DiagnosticEvent) -> None:
            del event
            raise RuntimeError("diagnostic storage unavailable")

    event = DiagnosticEvent(
        event_type=DiagnosticEventType.ENTRY_MATCH_EVALUATED,
        occurred_at=OCCURRED_AT,
    )

    with caplog.at_level(logging.ERROR, logger="src.diagnostics"):
        emit_best_effort(BrokenSink(), event)

    assert "Jetson diagnostic event 기록에 실패했습니다." in caplog.text
    assert "ENTRY_MATCH_EVALUATED" in caplog.text
