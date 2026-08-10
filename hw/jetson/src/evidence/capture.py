"""Incident 정지 이미지 crop·JPEG encoding과 durable spool 배선.

OPEN을 확정한 frame의 raw RGB pixels만 사용한다. 통행로처럼 큰 polygon 전체를
crop 기준으로 삼지 않고 차량 bbox를 anchor로 제한된 주변 문맥을 포함한다.
Overlay 합성, 영상 보존, Backend 전송은 이 모듈의 책임이 아니다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import math
from pathlib import Path
import sqlite3
import time

import cv2
import numpy as np

from src.camera.models import CapturedFrame
from src.diagnostics import (
    DiagnosticEvent,
    DiagnosticEventType,
    DiagnosticSeverity,
    DiagnosticsSink,
    NullDiagnosticsSink,
    emit_best_effort,
)
from src.evidence.capture_models import EvidenceCaptureIntent, EvidenceCropKind
from src.evidence.models import (
    EvidenceId,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.evidence.spool import (
    EvidenceRecoveryReport,
    EvidenceSpool,
)
from src.parking.models import ZoneDefinition
from src.parking.zone_registry import SPOT_ZONE_TYPES, ZoneRegistry
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import BoundingBox, TrackingBatch


logger = logging.getLogger(__name__)

ConnectionFactory = Callable[[], sqlite3.Connection]
_TARGET_ASPECT_RATIO = 16 / 9
_LARGE_CONTEXT_RULES = frozenset({"OUT_OF_ZONE", "AISLE_BLOCK"})
_INCOMPLETE_CAPTURE_STATES = frozenset(
    {EvidenceState.RESERVED, EvidenceState.WRITING}
)
# 영속 delivery retry와 별개인 process-local filesystem 재조정 pacing이다.
_PENDING_RETRY_BASE_SECONDS = 1.0
_PENDING_RETRY_MAX_SECONDS = 30.0


@dataclass(frozen=True)
class _PendingCapture:
    """Frame을 다시 만들 수 없는 capture의 bounded runtime retry 상태."""

    intent: EvidenceCaptureIntent
    attempt_count: int
    next_attempt_at: float


class EvidenceCaptureError(RuntimeError):
    """현재 frame으로 요청된 evidence를 안전하게 만들 수 없다."""


@dataclass(frozen=True, kw_only=True)
class EvidenceCapturePolicy:
    """파일럿 실측 전 사용하는 정지 이미지 제안값."""

    output_width: int = 1280
    output_height: int = 720
    fallback_width: int = 960
    fallback_height: int = 540
    context_margin_ratio: float = 0.15
    detail_margin_ratio: float = 0.25
    context_min_frame_width_ratio: float = 0.48
    detail_min_frame_width_ratio: float = 0.30
    context_soft_max_frame_width_ratio: float = 0.70
    pair_soft_max_frame_width_ratio: float = 0.85
    small_zone_max_frame_width_ratio: float = 0.65
    small_zone_max_frame_height_ratio: float = 0.75
    jpeg_quality: int = 80
    jpeg_target_bytes: int = 512 * 1024
    jpeg_hard_max_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        dimensions = (
            self.output_width,
            self.output_height,
            self.fallback_width,
            self.fallback_height,
        )
        if any(value <= 0 for value in dimensions):
            raise ValueError("evidence output dimensions must be positive")
        if not math.isclose(
            self.output_width / self.output_height,
            _TARGET_ASPECT_RATIO,
        ):
            raise ValueError("primary evidence output must use a 16:9 ratio")
        if not math.isclose(
            self.fallback_width / self.fallback_height,
            _TARGET_ASPECT_RATIO,
        ):
            raise ValueError("fallback evidence output must use a 16:9 ratio")
        ratios = (
            self.context_margin_ratio,
            self.detail_margin_ratio,
            self.context_min_frame_width_ratio,
            self.detail_min_frame_width_ratio,
            self.context_soft_max_frame_width_ratio,
            self.pair_soft_max_frame_width_ratio,
            self.small_zone_max_frame_width_ratio,
            self.small_zone_max_frame_height_ratio,
        )
        if any(not 0.0 < value <= 1.0 for value in ratios):
            raise ValueError("evidence crop ratios must be in (0, 1]")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 1 and 100")
        if not 0 < self.jpeg_target_bytes <= self.jpeg_hard_max_bytes:
            raise ValueError("JPEG byte limits are invalid")


@dataclass(frozen=True)
class CropWindow:
    """보정 완료 frame 안의 half-open pixel crop."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


@dataclass(frozen=True)
class _FloatRect:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2

    def union(self, other: "_FloatRect") -> "_FloatRect":
        return _FloatRect(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2),
        )


class IncidentEvidenceRenderer:
    """rule별 anchor를 선택하고 16:9 JPEG 한 장을 만든다."""

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        policy: EvidenceCapturePolicy | None = None,
    ) -> None:
        self._zones = zones
        self._policy = policy or EvidenceCapturePolicy()

    def plan_crop(
        self,
        frame: CapturedFrame,
        batch: TrackingBatch,
        intent: EvidenceCaptureIntent,
    ) -> CropWindow:
        """차량을 잃지 않으면서 rule에 맞는 제한된 16:9 문맥을 고른다."""

        snapshots = {
            snapshot.physical_vehicle_id: snapshot
            for snapshot in batch.vehicles
        }
        subject = snapshots.get(intent.physical_vehicle_id)
        if subject is None:
            raise EvidenceCaptureError(
                "incident subject is not visible in the confirmation frame"
            )

        base = _bbox_rect(subject.bbox, frame.width, frame.height)
        has_pair = False
        if (
            intent.crop_kind is EvidenceCropKind.CONTEXT
            and intent.victim_physical_vehicle_id is not None
        ):
            victim = snapshots.get(intent.victim_physical_vehicle_id)
            if victim is not None:
                base = base.union(
                    _bbox_rect(victim.bbox, frame.width, frame.height)
                )
                has_pair = True

        if intent.crop_kind is EvidenceCropKind.CONTEXT:
            zone = (
                self._zones.get_or_none(intent.zone_id)
                if intent.zone_id is not None
                else None
            )
            if self._should_include_zone(
                zone,
                rule_code=intent.rule_code,
                frame_width=frame.width,
                frame_height=frame.height,
            ):
                assert zone is not None
                base = base.union(
                    _polygon_rect(zone, frame.width, frame.height)
                )

        return self._expand_to_window(
            base,
            frame_width=frame.width,
            frame_height=frame.height,
            detail=intent.crop_kind is EvidenceCropKind.DETAIL,
            has_pair=has_pair,
        )

    def render_jpeg(
        self,
        frame: CapturedFrame,
        batch: TrackingBatch,
        intent: EvidenceCaptureIntent,
    ) -> bytes:
        """RGB frame에서 raw crop을 만들고 512KiB 목표로 JPEG를 압축한다."""

        image = np.asarray(frame.image)
        if (
            image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or image.shape[1] != frame.width
            or image.shape[0] != frame.height
        ):
            raise EvidenceCaptureError(
                "CapturedFrame.image must be RGB uint8 with declared dimensions"
            )
        window = self.plan_crop(frame, batch, intent)
        crop = np.ascontiguousarray(
            image[window.y1 : window.y2, window.x1 : window.x2]
        )
        if crop.size == 0:
            raise EvidenceCaptureError("planned evidence crop is empty")

        attempts: list[bytes] = []
        output_sizes = (
            (self._policy.output_width, self._policy.output_height),
            (self._policy.fallback_width, self._policy.fallback_height),
        )
        for output_width, output_height in output_sizes:
            canvas = _letterbox(crop, output_width, output_height)
            bgr = cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)
            for quality in _quality_steps(self._policy.jpeg_quality):
                encoded_ok, encoded = cv2.imencode(
                    ".jpg",
                    bgr,
                    [cv2.IMWRITE_JPEG_QUALITY, quality],
                )
                if not encoded_ok:
                    raise EvidenceCaptureError("OpenCV could not encode JPEG")
                payload = encoded.tobytes()
                attempts.append(payload)
                if len(payload) <= self._policy.jpeg_target_bytes:
                    return payload

        smallest = min(attempts, key=len)
        if len(smallest) > self._policy.jpeg_hard_max_bytes:
            raise EvidenceCaptureError(
                "encoded evidence exceeds the 2MiB hard limit"
            )
        return smallest

    def _should_include_zone(
        self,
        zone: ZoneDefinition | None,
        *,
        rule_code: str,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        if zone is None or zone.zone_type not in SPOT_ZONE_TYPES:
            return False
        if rule_code in _LARGE_CONTEXT_RULES or rule_code == "DOUBLE_PARKING":
            return False
        rect = _polygon_rect(zone, frame_width, frame_height)
        return (
            rect.width
            <= frame_width * self._policy.small_zone_max_frame_width_ratio
            and rect.height
            <= frame_height * self._policy.small_zone_max_frame_height_ratio
        )

    def _expand_to_window(
        self,
        base: _FloatRect,
        *,
        frame_width: int,
        frame_height: int,
        detail: bool,
        has_pair: bool,
    ) -> CropWindow:
        policy = self._policy
        margin = (
            policy.detail_margin_ratio
            if detail
            else policy.context_margin_ratio
        )
        minimum_width = frame_width * (
            policy.detail_min_frame_width_ratio
            if detail
            else policy.context_min_frame_width_ratio
        )
        soft_maximum_width = frame_width * (
            policy.pair_soft_max_frame_width_ratio
            if has_pair
            else policy.context_soft_max_frame_width_ratio
        )

        desired_width = max(base.width * (1 + 2 * margin), minimum_width)
        if base.width <= soft_maximum_width:
            desired_width = min(desired_width, soft_maximum_width)
        desired_height = base.height * (1 + 2 * margin)
        if desired_width / max(desired_height, 1.0) < _TARGET_ASPECT_RATIO:
            desired_width = desired_height * _TARGET_ASPECT_RATIO
        else:
            desired_height = desired_width / _TARGET_ASPECT_RATIO

        if frame_width / frame_height >= _TARGET_ASPECT_RATIO:
            maximum_height = float(frame_height)
            maximum_width = maximum_height * _TARGET_ASPECT_RATIO
        else:
            maximum_width = float(frame_width)
            maximum_height = maximum_width / _TARGET_ASPECT_RATIO

        if base.width > maximum_width or base.height > maximum_height:
            return CropWindow(0, 0, frame_width, frame_height)
        if desired_width > maximum_width or desired_height > maximum_height:
            desired_width = maximum_width
            desired_height = maximum_height

        x1 = _place_axis(
            center=base.center_x,
            size=desired_width,
            limit=float(frame_width),
        )
        y1 = _place_axis(
            center=base.center_y,
            size=desired_height,
            limit=float(frame_height),
        )
        x2 = x1 + desired_width
        y2 = y1 + desired_height
        return CropWindow(
            max(0, math.floor(x1)),
            max(0, math.floor(y1)),
            min(frame_width, math.ceil(x2)),
            min(frame_height, math.ceil(y2)),
        )


class EvidenceCaptureCoordinator:
    """commit 뒤 capture intent를 종결하거나 ID별 재조정 대상으로 보존한다."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        zones: ZoneRegistry,
        spool_path: Path,
        spool_cap_bytes: int,
        filesystem_floor_ratio: float,
        capture_stop_free_ratio: float,
        policy: EvidenceCapturePolicy | None = None,
        diagnostics_sink: DiagnosticsSink | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(monotonic_clock):
            raise ValueError("monotonic_clock must be callable")
        self._connection_factory = connection_factory
        self._renderer = IncidentEvidenceRenderer(zones=zones, policy=policy)
        self._spool_path = spool_path
        self._spool_cap_bytes = spool_cap_bytes
        self._filesystem_floor_ratio = filesystem_floor_ratio
        self._capture_stop_free_ratio = capture_stop_free_ratio
        self._pending_captures: dict[EvidenceId, _PendingCapture] = {}
        self._monotonic_clock = monotonic_clock
        self._diagnostics_sink = (
            diagnostics_sink
            if diagnostics_sink is not None
            else NullDiagnosticsSink()
        )

    def recover(self) -> EvidenceRecoveryReport:
        """Backend publisher가 꺼진 배포에서도 중단된 local capture를 복구한다."""

        connection = self._connection_factory()
        try:
            report = EvidenceSpool(
                connection=connection,
                root=self._spool_path,
                spool_cap_bytes=self._spool_cap_bytes,
                filesystem_floor_ratio=self._filesystem_floor_ratio,
                capture_stop_free_ratio=self._capture_stop_free_ratio,
            ).recover()
            self._pending_captures.clear()
            return report
        finally:
            connection.close()

    def flush_pending(self) -> None:
        """소스 종료 시 후속 frame 없이도 보류 capture를 한 번 재조정한다."""

        if not self._pending_captures:
            return
        pending_intents = tuple(
            pending.intent for pending in self._pending_captures.values()
        )
        try:
            connection = self._connection_factory()
        except Exception as error:
            logger.exception("종료 전 Evidence 보류 상태를 열지 못했습니다.")
            for intent in pending_intents:
                self._observe_capture(
                    intent,
                    intents=pending_intents,
                    result="CAPTURE_FLUSH_FAILED",
                    severity=DiagnosticSeverity.ERROR,
                    error=error,
                )
            return

        try:
            try:
                spool = EvidenceSpool(
                    connection=connection,
                    root=self._spool_path,
                    spool_cap_bytes=self._spool_cap_bytes,
                    filesystem_floor_ratio=self._filesystem_floor_ratio,
                    capture_stop_free_ratio=self._capture_stop_free_ratio,
                )
            except Exception as error:
                logger.exception("종료 전 Evidence spool을 열지 못했습니다.")
                self._fail_without_spool(
                    connection,
                    pending_intents,
                    error=error,
                )
                self._remember_incomplete(connection, pending_intents)
                return
            self._reconcile_pending(connection, spool, force=True)
        finally:
            connection.close()

    def capture(
        self,
        frame: CapturedFrame,
        batch: TrackingBatch,
        intents: tuple[EvidenceCaptureIntent, ...],
    ) -> None:
        """각 예약을 종결하고 일시적 미종결 상태는 다음 호출에서
        재조정한다.
        """

        if not intents:
            if not self._pending_captures or not self._has_due_pending():
                return

        for intent in intents:
            self._observe_capture(
                intent,
                intents=intents,
                result="CAPTURE_REQUESTED",
            )

        try:
            connection = self._connection_factory()
        except Exception as error:
            logger.exception(
                "Evidence DB 연결을 열지 못해 다음 frame에서 재조정합니다."
            )
            now = self._monotonic_clock()
            due_pending = tuple(
                pending.intent
                for pending in self._pending_captures.values()
                if pending.next_attempt_at <= now
            )
            deferred_intents = self._merge_intents(due_pending, intents)
            for intent in deferred_intents:
                self._defer_pending(intent)
                self._observe_capture(
                    intent,
                    intents=deferred_intents,
                    result="CAPTURE_RECOVERY_PENDING",
                    severity=DiagnosticSeverity.ERROR,
                    error=error,
                )
            return

        try:
            pending_intents = tuple(
                pending.intent for pending in self._pending_captures.values()
            )
            all_intents = self._merge_intents(pending_intents, intents)
            try:
                spool = EvidenceSpool(
                    connection=connection,
                    root=self._spool_path,
                    spool_cap_bytes=self._spool_cap_bytes,
                    filesystem_floor_ratio=self._filesystem_floor_ratio,
                    capture_stop_free_ratio=self._capture_stop_free_ratio,
                )
            except Exception as error:
                logger.exception("Evidence spool을 열지 못했습니다.")
                finalization_errors = self._fail_without_spool(
                    connection,
                    all_intents,
                    error=error,
                )
                incomplete_ids = self._remember_incomplete(
                    connection,
                    all_intents,
                )
                if finalization_errors or incomplete_ids:
                    logger.error(
                        "Evidence spool 초기화 실패 뒤 미종결 예약을 "
                        "보류합니다: %s",
                        ", ".join(incomplete_ids),
                    )
                return

            self._reconcile_pending(connection, spool)

            finalization_errors: list[Exception] = []
            for intent in intents:
                try:
                    self._capture_one(
                        connection,
                        spool,
                        frame,
                        batch,
                        intent,
                        intents=intents,
                    )
                except Exception as error:
                    finalization_errors.append(error)
                    logger.exception(
                        "Evidence capture를 종결하지 못했습니다: %s",
                        intent.evidence_id,
                    )
                    self._observe_capture(
                        intent,
                        intents=intents,
                        result="CAPTURE_FINALIZATION_FAILED",
                        severity=DiagnosticSeverity.ERROR,
                        error=error,
                    )

            incomplete_ids = self._remember_incomplete(connection, intents)
            if finalization_errors or incomplete_ids:
                logger.error(
                    "Evidence capture 미종결 예약을 다음 frame으로 이관합니다: %s",
                    ", ".join(incomplete_ids),
                )
        finally:
            connection.close()

    def _capture_one(
        self,
        connection: sqlite3.Connection,
        spool: EvidenceSpool,
        frame: CapturedFrame,
        batch: TrackingBatch,
        intent: EvidenceCaptureIntent,
        *,
        intents: tuple[EvidenceCaptureIntent, ...],
    ) -> None:
        """한 intent를 종결하되 재현 불가능한 frame 오류는 FAILED로
        보존한다.
        """

        try:
            payload = self._renderer.render_jpeg(frame, batch, intent)
        except Exception as error:
            message = _capture_error_text(error)
            spool.fail_reservation(
                intent.evidence_id,
                error=message,
                disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
                now=intent.captured_at,
            )
            logger.warning(
                "Evidence capture를 완료하지 못했습니다(%s): %s",
                intent.evidence_id,
                message,
            )
            self._observe_capture(
                intent,
                intents=intents,
                result="CAPTURE_FAILED",
                severity=DiagnosticSeverity.ERROR,
                error=error,
            )
            return

        try:
            stored = spool.store_jpeg(
                intent.evidence_id,
                payload,
                now=intent.captured_at,
            )
        except Exception as error:
            logger.exception(
                "Evidence JPEG를 durable spool에 기록하지 못했습니다: %s",
                intent.evidence_id,
            )
            self._finalize_store_failure(
                connection,
                spool,
                intent,
                error=error,
            )
            self._observe_capture(
                intent,
                intents=intents,
                result="SPOOL_STORE_FAILED",
                severity=DiagnosticSeverity.ERROR,
                error=error,
            )
            return

        if stored.state in _INCOMPLETE_CAPTURE_STATES:
            raise EvidenceCaptureError(
                f"evidence {intent.evidence_id} remained {stored.state.value}"
            )
        self._observe_capture(
            intent,
            intents=intents,
            result="CAPTURE_READY",
            byte_size=stored.byte_size,
        )

    @staticmethod
    def _finalize_store_failure(
        connection: sqlite3.Connection,
        spool: EvidenceSpool,
        intent: EvidenceCaptureIntent,
        *,
        error: Exception,
    ) -> None:
        """저장 오류 지점에 따라 RESERVED 또는 WRITING을 즉시 종결한다."""

        artifact = EvidenceArtifactRepository(connection).get(intent.evidence_id)
        if artifact is None:
            raise EvidenceCaptureError(
                f"unknown evidence identity: {intent.evidence_id}"
            ) from error
        if artifact.state is EvidenceState.RESERVED:
            spool.fail_reservation(
                intent.evidence_id,
                error=_capture_error_text(error),
                disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
                now=intent.captured_at,
            )
            return
        if artifact.state is EvidenceState.WRITING:
            reconciled = spool.reconcile_interrupted_write(
                intent.evidence_id,
            )
            if reconciled.state in _INCOMPLETE_CAPTURE_STATES:
                raise EvidenceCaptureError(
                    f"evidence {intent.evidence_id} remained "
                    f"{reconciled.state.value} after reconciliation"
                ) from error

    @staticmethod
    def _merge_intents(
        pending: tuple[EvidenceCaptureIntent, ...],
        current: tuple[EvidenceCaptureIntent, ...],
    ) -> tuple[EvidenceCaptureIntent, ...]:
        merged = {intent.evidence_id: intent for intent in pending}
        merged.update({intent.evidence_id: intent for intent in current})
        return tuple(merged.values())

    def _reconcile_pending(
        self,
        connection: sqlite3.Connection,
        spool: EvidenceSpool,
        *,
        force: bool = False,
    ) -> None:
        """이전 frame에서 남은 RESERVED/WRITING을 ID별로 재조정한다."""

        repository = EvidenceArtifactRepository(connection)
        now = self._monotonic_clock()
        pending_records = tuple(
            pending
            for pending in self._pending_captures.values()
            if force or pending.next_attempt_at <= now
        )
        pending_intents = tuple(pending.intent for pending in pending_records)
        for pending in pending_records:
            intent = pending.intent
            try:
                artifact = repository.get(intent.evidence_id)
                if artifact is None:
                    self._pending_captures.pop(intent.evidence_id, None)
                    error = EvidenceCaptureError(
                        f"unknown evidence identity: {intent.evidence_id}; "
                        "pending retry abandoned"
                    )
                    logger.error("%s", error)
                    self._observe_capture(
                        intent,
                        intents=pending_intents,
                        result="CAPTURE_RECOVERY_ABANDONED",
                        severity=DiagnosticSeverity.ERROR,
                        error=error,
                    )
                    continue
                if artifact.state is EvidenceState.RESERVED:
                    artifact = spool.fail_reservation(
                        intent.evidence_id,
                        error=(
                            "capture failed: source frame was not retained after "
                            "metadata connection failure"
                        ),
                    )
                elif artifact.state is EvidenceState.WRITING:
                    artifact = spool.reconcile_interrupted_write(
                        intent.evidence_id,
                    )
                if artifact.state in _INCOMPLETE_CAPTURE_STATES:
                    raise EvidenceCaptureError(
                        f"evidence {intent.evidence_id} remained "
                        f"{artifact.state.value} after reconciliation"
                    )
            except Exception as error:
                self._defer_pending(intent)
                logger.exception(
                    "보류 Evidence capture를 재조정하지 못했습니다: %s",
                    intent.evidence_id,
                )
                self._observe_capture(
                    intent,
                    intents=pending_intents,
                    result="CAPTURE_FINALIZATION_FAILED",
                    severity=DiagnosticSeverity.ERROR,
                    error=error,
                )
                continue

            self._pending_captures.pop(intent.evidence_id, None)
            self._observe_capture(
                intent,
                intents=pending_intents,
                result=f"CAPTURE_RECOVERED_{artifact.state.value}",
                severity=(
                    DiagnosticSeverity.ERROR
                    if artifact.state is EvidenceState.FAILED
                    else DiagnosticSeverity.WARNING
                ),
                byte_size=artifact.byte_size,
            )

    def _fail_without_spool(
        self,
        connection: sqlite3.Connection,
        intents: tuple[EvidenceCaptureIntent, ...],
        *,
        error: Exception,
    ) -> list[Exception]:
        """Spool이 열리지 않아도 RESERVED metadata를 개별 transaction으로
        종결한다.
        """

        repository = EvidenceArtifactRepository(connection)
        failures: list[Exception] = []
        for intent in intents:
            try:
                with UnitOfWork(connection):
                    artifact = repository.get(intent.evidence_id)
                    if artifact is None:
                        raise EvidenceCaptureError(
                            f"unknown evidence identity: {intent.evidence_id}"
                        )
                    if artifact.state is EvidenceState.RESERVED:
                        repository.mark_capture_failed(
                            intent.evidence_id,
                            failed_at=intent.captured_at,
                            error=_capture_error_text(error),
                        )
                    elif artifact.state is EvidenceState.WRITING:
                        raise EvidenceCaptureError(
                            f"evidence {intent.evidence_id} requires WRITING recovery"
                        )
            except Exception as finalization_error:
                failures.append(finalization_error)
                logger.exception(
                    "Spool 초기화 실패 뒤 Evidence 예약을 종결하지 "
                    "못했습니다: %s",
                    intent.evidence_id,
                )
                self._observe_capture(
                    intent,
                    intents=intents,
                    result="CAPTURE_FINALIZATION_FAILED",
                    severity=DiagnosticSeverity.ERROR,
                    error=finalization_error,
                )
            else:
                self._observe_capture(
                    intent,
                    intents=intents,
                    result="SPOOL_OPEN_FAILED",
                    severity=DiagnosticSeverity.ERROR,
                    error=error,
                )
        return failures

    def _remember_incomplete(
        self,
        connection: sqlite3.Connection,
        intents: tuple[EvidenceCaptureIntent, ...],
    ) -> tuple[str, ...]:
        repository = EvidenceArtifactRepository(connection)
        incomplete: list[str] = []
        for intent in intents:
            artifact = repository.get(intent.evidence_id)
            if artifact is None:
                raise EvidenceCaptureError(
                    f"unknown evidence identity: {intent.evidence_id}"
                )
            if artifact.state in _INCOMPLETE_CAPTURE_STATES:
                incomplete.append(str(intent.evidence_id))
                self._defer_pending(intent)
            else:
                self._pending_captures.pop(intent.evidence_id, None)
        return tuple(incomplete)

    def _has_due_pending(self) -> bool:
        now = self._monotonic_clock()
        return any(
            pending.next_attempt_at <= now
            for pending in self._pending_captures.values()
        )

    def _defer_pending(self, intent: EvidenceCaptureIntent) -> None:
        current = self._pending_captures.get(intent.evidence_id)
        attempt_count = 1 if current is None else current.attempt_count + 1
        exponent = min(attempt_count - 1, 10)
        delay = min(
            _PENDING_RETRY_BASE_SECONDS * (2**exponent),
            _PENDING_RETRY_MAX_SECONDS,
        )
        self._pending_captures[intent.evidence_id] = _PendingCapture(
            intent=intent,
            attempt_count=attempt_count,
            next_attempt_at=self._monotonic_clock() + delay,
        )

    def _observe_capture(
        self,
        intent: EvidenceCaptureIntent,
        *,
        intents: tuple[EvidenceCaptureIntent, ...],
        result: str,
        severity: DiagnosticSeverity = DiagnosticSeverity.INFO,
        byte_size: int | None = None,
        error: Exception | None = None,
    ) -> None:
        reserved_count = sum(
            candidate.incident_id == intent.incident_id
            for candidate in intents
        )
        expected_count = 2 if intent.rule_code == "DOUBLE_PARKING" else 1
        emit_best_effort(
            self._diagnostics_sink,
            DiagnosticEvent(
                event_type=(
                    DiagnosticEventType.EVIDENCE_PUBLICATION_EVALUATED
                ),
                occurred_at=intent.captured_at,
                severity=severity,
                attributes={
                    "byteSize": byte_size,
                    "cropKind": intent.crop_kind.value,
                    "errorType": (
                        type(error).__name__ if error is not None else None
                    ),
                    "evidenceId": str(intent.evidence_id),
                    "expectedCropCount": expected_count,
                    "incidentId": str(intent.incident_id),
                    "phase": "CAPTURE",
                    "physicalVehicleId": str(intent.physical_vehicle_id),
                    "reservedCropCount": reserved_count,
                    "result": result,
                    "ruleCode": intent.rule_code,
                    "victimPhysicalVehicleId": (
                        str(intent.victim_physical_vehicle_id)
                        if intent.victim_physical_vehicle_id is not None
                        else None
                    ),
                    "zoneId": (
                        int(intent.zone_id)
                        if intent.zone_id is not None
                        else None
                    ),
                },
            ),
        )


def _bbox_rect(bbox: BoundingBox, width: int, height: int) -> _FloatRect:
    return _FloatRect(
        bbox.x1 * width,
        bbox.y1 * height,
        bbox.x2 * width,
        bbox.y2 * height,
    )


def _polygon_rect(
    zone: ZoneDefinition,
    width: int,
    height: int,
) -> _FloatRect:
    xs = tuple(point[0] * width for point in zone.polygon)
    ys = tuple(point[1] * height for point in zone.polygon)
    return _FloatRect(min(xs), min(ys), max(xs), max(ys))


def _place_axis(*, center: float, size: float, limit: float) -> float:
    return min(max(center - size / 2, 0.0), max(limit - size, 0.0))


def _letterbox(image: np.ndarray, width: int, height: int) -> np.ndarray:
    scale = min(width / image.shape[1], height / image.shape[0])
    resized_width = max(1, min(width, round(image.shape[1] * scale)))
    resized_height = max(1, min(height, round(image.shape[0] * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(
        image,
        (resized_width, resized_height),
        interpolation=interpolation,
    )
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x = (width - resized_width) // 2
    y = (height - resized_height) // 2
    canvas[y : y + resized_height, x : x + resized_width] = resized
    return canvas


def _quality_steps(start: int) -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            quality
            for quality in (start, 75, 70, 65, 60)
            if quality <= start
        )
    )


def _capture_error_text(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    return f"capture failed: {message}"[:500]
