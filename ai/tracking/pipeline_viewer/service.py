"""Jetson Pipeline Viewer의 입력 검증과 실제 workflow 실행을 담당한다.

Viewer는 ``hw/jetson/src``의 운영 component를 직접 import한다. 입차 이벤트는
실제 API payload와 ``EntryEventIntake``를 통과하고, 영상은 실제 camera·tracking
adapter와 ``build_monitoring_pipeline``으로 처리한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Any, Callable
from uuid import UUID, uuid4


VIEWER_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = VIEWER_DIR.parents[2]
JETSON_ROOT = REPOSITORY_ROOT / "hw" / "jetson"
if str(JETSON_ROOT) not in sys.path:
    sys.path.insert(0, str(JETSON_ROOT))


from src.api.entry_events_router import EntryEventPayload  # noqa: E402
from src.application.entry_event_intake import EntryEventIntake  # noqa: E402
from src.application.monitoring_factory import (  # noqa: E402
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE  # noqa: E402
from src.camera.frame_source import (  # noqa: E402
    EPOCH,
    EndOfVideo,
    RemapFrameSource,
    VideoFileFrameSource,
    calibration_fingerprint,
)
from src.parking.zone_registry import ZoneRegistry  # noqa: E402
from src.replay.publication_preparer import JsonlPublicationPreparer  # noqa: E402
from src.session.entry_match_coordinator import EntryMatchCoordinator  # noqa: E402
from src.storage.database import connect_database, open_database  # noqa: E402
from src.tracking.adapters.ultralytics_bytetrack import (  # noqa: E402
    UltralyticsVehicleTracker,
)
from src.tracking.motion_estimator import MotionEstimator  # noqa: E402

from .tracing import FrameTrace, TraceCollector, parse_entry_attempt_id  # noqa: E402


DEFAULT_CAMERA_ID = "PIPELINE-VIEWER"
DEFAULT_MODEL_PATH = JETSON_ROOT / "model" / "yolov8s.pt"
DEFAULT_ZONES_PATH = JETSON_ROOT / "config" / "zone_definition.pilot.json"
DEFAULT_CALIBRATION_PATH = REPOSITORY_ROOT / "ai" / "tracking" / "camera_calibration.json"
ALLOWED_VIDEO_SUFFIXES = frozenset({".mp4", ".avi", ".mov", ".mkv"})


class ViewerInputError(ValueError):
    """Viewer 실행 전에 발견한 외부 입력·설정 오류."""


@dataclass(frozen=True, slots=True)
class ViewerPaths:
    model: Path = DEFAULT_MODEL_PATH
    zones: Path = DEFAULT_ZONES_PATH
    calibration: Path = DEFAULT_CALIBRATION_PATH


@dataclass(frozen=True, slots=True)
class ViewerPolicy:
    """화면에 모두 노출하는 monitoring 및 tracker 판단값."""

    zone_entry_confirm_seconds: float = 1.0
    zone_exit_confirm_seconds: float = 5.0
    entry_zone_min_overlap_ratio: float = 0.40
    # Viewer 판정 테스트의 명시적 override다. 일반 배포의 600초 정책은
    # Settings/배포 계층이 계속 소유하며 이 기본값으로 바꾸지 않는다.
    parking_confirm_seconds: float = 5.0
    parking_move_confirm_seconds: float = 0.5
    absence_confirmation_seconds: float = 5.0
    trusted_sample_max_gap_seconds: float = 1.0
    # geometry-only runtime re-identification의 provisional 기준이다. 모델과
    # zone/parking 결론은 이 점수에 포함하지 않으며 replay로 재조정한다.
    reidentification_max_gap_seconds: float = 4.0
    reidentification_min_score: float = 0.42
    reidentification_ambiguity_margin: float = 0.08
    incident_confirm_seconds: float = 0.0
    incident_clear_seconds: float = 0.0
    zone_presence_min_overlap_ratio: float = 0.40
    assignment_min_overlap_ratio: float = 0.50
    assignment_ambiguous_margin: float = 0.05
    bad_parking_min_primary_overlap_ratio: float = 0.75
    blocking_relation_confirm_seconds: float = 1.0
    blocking_relation_clear_seconds: float = 1.0
    entry_match_window_seconds: float = 10.0
    # bbox diagonal로 정규화한 time-window motion evidence의 provisional 값.
    # 운영값으로 승격하기 전에 영상별 replay로 재조정한다.
    motion_window_seconds: float = 0.75
    motion_min_observation_span_seconds: float = 0.20
    motion_max_sample_gap_seconds: float = 0.50
    motion_stationary_threshold: float = 0.03
    motion_moving_threshold: float = 0.10
    motion_min_samples: int = 3
    motion_min_trend_consistency: float = 0.60
    # 모델 confidence 분포를 수집하기 위한 Viewer 진단용 provisional 기본값.
    # 운영 threshold로 승격하기 전 영상별 precision/recall 재평가가 필요하다.
    confidence: float = 0.01
    tracker_config: str = "bytetrack.yaml"
    remap_balance: float = DEFAULT_REMAP_BALANCE

    def to_monitoring_policy(self) -> MonitoringPolicy:
        return MonitoringPolicy(
            zone_entry_confirm_seconds=self.zone_entry_confirm_seconds,
            zone_exit_confirm_seconds=self.zone_exit_confirm_seconds,
            entry_zone_min_overlap_ratio=self.entry_zone_min_overlap_ratio,
            parking_confirm_seconds=self.parking_confirm_seconds,
            parking_move_confirm_seconds=self.parking_move_confirm_seconds,
            absence_confirmation_seconds=self.absence_confirmation_seconds,
            trusted_sample_max_gap_seconds=self.trusted_sample_max_gap_seconds,
            motion_window_seconds=self.motion_window_seconds,
            motion_min_observation_span_seconds=(
                self.motion_min_observation_span_seconds
            ),
            motion_max_sample_gap_seconds=self.motion_max_sample_gap_seconds,
            motion_stationary_threshold=self.motion_stationary_threshold,
            motion_moving_threshold=self.motion_moving_threshold,
            motion_min_samples=self.motion_min_samples,
            motion_min_trend_consistency=self.motion_min_trend_consistency,
            reidentification_max_gap_seconds=(
                self.reidentification_max_gap_seconds
            ),
            reidentification_min_score=self.reidentification_min_score,
            reidentification_ambiguity_margin=(
                self.reidentification_ambiguity_margin
            ),
            incident_confirm_seconds=self.incident_confirm_seconds,
            incident_clear_seconds=self.incident_clear_seconds,
            zone_presence_min_overlap_ratio=self.zone_presence_min_overlap_ratio,
            assignment_min_overlap_ratio=self.assignment_min_overlap_ratio,
            assignment_ambiguous_margin=self.assignment_ambiguous_margin,
            bad_parking_min_primary_overlap_ratio=(
                self.bad_parking_min_primary_overlap_ratio
            ),
            blocking_relation_confirm_seconds=(
                self.blocking_relation_confirm_seconds
            ),
            blocking_relation_clear_seconds=self.blocking_relation_clear_seconds,
        )


@dataclass(frozen=True, slots=True)
class VideoUpload:
    file_name: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ViewerRunRequest:
    entry_event_json: str
    idempotency_key: str
    video: VideoUpload
    paths: ViewerPaths = field(default_factory=ViewerPaths)
    policy: ViewerPolicy = field(default_factory=ViewerPolicy)
    end_seconds: float | None = None


@dataclass(slots=True)
class ViewerRun:
    request_signature: str
    workspace: Path
    video_path: Path
    database_path: Path
    events_path: Path
    entry_payload: EntryEventPayload
    entry_created: bool
    frames: tuple[FrameTrace, ...]
    aliases: dict[Any, str]
    video_fps: float
    video_duration_seconds: float
    zones: tuple[Any, ...]
    model_path: Path
    detection_confidence_threshold: float
    tracker_config: str
    policy_snapshot_json: str
    error_type: str | None = None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_type is None


ProgressCallback = Callable[[int, int | None], None]


def default_paths() -> ViewerPaths:
    return ViewerPaths()


def build_allow_example(*, tracking_id: UUID | None = None) -> str:
    """영상 00:00에 맞춘 현재 legacy wire의 synthetic ALLOW 예시 JSON."""

    payload = {
        "trackingId": str(tracking_id or uuid4()),
        "recognizedPlateNumber": "12가3456",
        "entryTime": EPOCH.isoformat(),
        "accessDecision": "ALLOW",
        "registered": True,
        "vehicleId": 1,
        "isDisabledVehicle": False,
        "isElectric": False,
        "vehicleStatus": "REGISTERED",
        "sessionId": 1,
        "duplicateRequest": False,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def default_idempotency_key(entry_event_json: str) -> str:
    payload = parse_entry_event(entry_event_json)
    return f"viewer-entry-{payload.tracking_id}-r0"


def parse_entry_event(raw_json: str) -> EntryEventPayload:
    """실제 FastAPI payload 모델로 JSON과 영상 시작 시각 계약을 검증한다."""

    try:
        payload = EntryEventPayload.model_validate_json(raw_json)
    except Exception as exc:
        raise ViewerInputError(f"입차 이벤트 JSON이 실제 API 계약과 다릅니다: {exc}") from exc
    if payload.entry_time.astimezone(timezone.utc) != EPOCH:
        raise ViewerInputError(
            "영상 첫 프레임은 입차 순간이어야 합니다. "
            f"entryTime을 {EPOCH.isoformat()}로 맞추세요: "
            f"actual={payload.entry_time.isoformat()}"
        )
    return payload


def run_viewer_pipeline(
    request: ViewerRunRequest,
    *,
    progress_callback: ProgressCallback | None = None,
    workspace_parent: Path | None = None,
) -> ViewerRun:
    """입차 접수 후 실제 Jetson monitoring workflow로 영상을 처리한다."""

    payload, zones = _validate_request(request)
    workspace = Path(
        tempfile.mkdtemp(
            prefix="jetson-pipeline-viewer-",
            dir=None if workspace_parent is None else str(workspace_parent),
        )
    )
    video_suffix = Path(request.video.file_name).suffix.lower() or ".mp4"
    video_path = workspace / f"input{video_suffix}"
    database_path = workspace / "viewer.db"
    events_path = workspace / "events.jsonl"
    connection_factory = lambda: connect_database(database_path)
    try:
        video_path.write_bytes(request.video.content)
        open_database(database_path).close()
        entry_created = _receive_entry_event(
            payload,
            idempotency_key=request.idempotency_key,
            zones=zones,
            match_window_seconds=request.policy.entry_match_window_seconds,
            connection_factory=connection_factory,
        )
    except ValueError as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        raise ViewerInputError(
            f"입차 이벤트가 실제 EntryEventIntake 계약을 위반했습니다: {exc}"
        ) from exc
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    entry_attempt_id = parse_entry_attempt_id(payload.tracking_id)
    collector = TraceCollector(
        frames_directory=workspace / "frames",
        zones=zones.all(),
        entry_attempt_id=entry_attempt_id,
        connection_factory=connection_factory,
    )

    inner = VideoFileFrameSource(
        camera_id=DEFAULT_CAMERA_ID,
        path=video_path,
        start_seconds=0.0,
        end_seconds=request.end_seconds,
    )
    frame_source = RemapFrameSource(
        inner=inner,
        calibration_path=str(request.paths.calibration),
        balance=request.policy.remap_balance,
    )
    detector = UltralyticsVehicleTracker(
        model_path=str(request.paths.model),
        tracker_config=request.policy.tracker_config,
        confidence=request.policy.confidence,
        capture_detections=True,
    )

    error_type: str | None = None
    error_message: str | None = None
    pipeline = None
    opened = False
    try:
        with events_path.open("w", encoding="utf-8", newline="\n") as events_handle:
            pipeline = build_monitoring_pipeline(
                zones=zones,
                policy=request.policy.to_monitoring_policy(),
                dependencies=MonitoringDependencies(
                    camera_id=DEFAULT_CAMERA_ID,
                    frame_source=frame_source,
                    detector=detector,
                    publication_preparer=JsonlPublicationPreparer(
                        events_handle=events_handle
                    ),
                    connection_factory=connection_factory,
                    motion_estimator=MotionEstimator(
                        window_seconds=request.policy.motion_window_seconds,
                        min_observation_span_seconds=(
                            request.policy.motion_min_observation_span_seconds
                        ),
                        max_sample_gap_seconds=(
                            request.policy.motion_max_sample_gap_seconds
                        ),
                        stationary_threshold=(
                            request.policy.motion_stationary_threshold
                        ),
                        moving_threshold=request.policy.motion_moving_threshold,
                        min_samples=request.policy.motion_min_samples,
                        min_trend_consistency=(
                            request.policy.motion_min_trend_consistency
                        ),
                    ),
                ),
            )
            pipeline.open()
            opened = True
            total_frames = _analysis_frame_count(inner, request.end_seconds)
            while True:
                started = time.perf_counter()
                try:
                    pipeline.process_next_frame(frame_observer=collector.observe)
                except EndOfVideo:
                    break
                collector.set_last_elapsed_ms(
                    (time.perf_counter() - started) * 1000.0
                )
                if progress_callback is not None:
                    progress_callback(len(collector.frames), total_frames)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)
    finally:
        if pipeline is not None and opened:
            try:
                pipeline.close()
            except Exception as exc:
                if error_type is None:
                    error_type = type(exc).__name__
                    error_message = str(exc)

    return ViewerRun(
        request_signature=_request_signature(request),
        workspace=workspace,
        video_path=video_path,
        database_path=database_path,
        events_path=events_path,
        entry_payload=payload,
        entry_created=entry_created,
        frames=tuple(collector.frames),
        aliases=collector.aliases,
        video_fps=inner.fps,
        video_duration_seconds=inner.duration_seconds,
        zones=zones.all(),
        model_path=request.paths.model,
        detection_confidence_threshold=request.policy.confidence,
        tracker_config=request.policy.tracker_config,
        policy_snapshot_json=_policy_snapshot_json(request.policy),
        error_type=error_type,
        error_message=error_message,
    )


def cleanup_run(run: ViewerRun) -> None:
    """현재 session이 소유한 viewer 임시 산출물을 제거한다."""

    shutil.rmtree(run.workspace, ignore_errors=True)


def _validate_request(
    request: ViewerRunRequest,
) -> tuple[EntryEventPayload, ZoneRegistry]:
    payload = parse_entry_event(request.entry_event_json)
    if not request.idempotency_key.strip():
        raise ViewerInputError("Idempotency-Key는 비어 있을 수 없습니다.")
    if not request.video.content:
        raise ViewerInputError("분석할 동영상이 비어 있습니다.")
    suffix = Path(request.video.file_name).suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise ViewerInputError(
            "지원하는 영상 확장자는 mp4, avi, mov, mkv입니다: "
            f"actual={suffix or '(none)'}"
        )
    for label, path in (
        ("YOLO 모델", request.paths.model),
        ("구역 정의", request.paths.zones),
        ("카메라 calibration", request.paths.calibration),
    ):
        if not path.is_file():
            raise ViewerInputError(f"{label} 파일을 찾을 수 없습니다: {path}")
    if request.end_seconds is not None and request.end_seconds <= 0:
        raise ViewerInputError("영상 종료 시각은 0초보다 커야 합니다.")
    if not 0.0 <= request.policy.remap_balance <= 1.0:
        raise ViewerInputError("remap balance는 0~1 범위여야 합니다.")

    zones = ZoneRegistry.from_file(request.paths.zones)
    fingerprint = calibration_fingerprint(
        request.paths.calibration,
        request.policy.remap_balance,
    )
    expected_reference = fingerprint.get("calibrationSha256")
    if zones.calibration_reference != expected_reference:
        raise ViewerInputError(
            "구역 정의와 calibration 좌표계가 다릅니다: "
            f"zones={zones.calibration_reference}, "
            f"calibration={expected_reference}"
        )
    # 실제 domain owner의 수치 검증을 실행 전에 한 번 통과시킨다.
    request.policy.to_monitoring_policy()
    MotionEstimator(
        window_seconds=request.policy.motion_window_seconds,
        min_observation_span_seconds=(
            request.policy.motion_min_observation_span_seconds
        ),
        max_sample_gap_seconds=request.policy.motion_max_sample_gap_seconds,
        stationary_threshold=request.policy.motion_stationary_threshold,
        moving_threshold=request.policy.motion_moving_threshold,
        min_samples=request.policy.motion_min_samples,
        min_trend_consistency=request.policy.motion_min_trend_consistency,
    )
    UltralyticsVehicleTracker(
        model_path=str(request.paths.model),
        tracker_config=request.policy.tracker_config,
        confidence=request.policy.confidence,
    )
    return payload, zones


def _receive_entry_event(
    payload: EntryEventPayload,
    *,
    idempotency_key: str,
    zones: ZoneRegistry,
    match_window_seconds: float,
    connection_factory: Callable[[], sqlite3.Connection],
) -> bool:
    intake = EntryEventIntake(
        EntryMatchCoordinator(zones=zones),
        match_window_seconds=match_window_seconds,
    )
    connection = connection_factory()
    try:
        return intake.receive(
            payload.to_entry_context(),
            idempotency_key=idempotency_key,
            connection=connection,
        )
    finally:
        connection.close()


def _analysis_frame_count(
    source: VideoFileFrameSource,
    end_seconds: float | None,
) -> int | None:
    if source.fps <= 0:
        return None
    duration = source.duration_seconds
    selected_duration = duration if end_seconds is None else min(duration, end_seconds)
    return max(1, int(selected_duration * source.fps))


def _request_signature(request: ViewerRunRequest) -> str:
    digest = hashlib.sha256()
    digest.update(request.entry_event_json.encode("utf-8"))
    digest.update(request.idempotency_key.encode("utf-8"))
    digest.update(request.video.file_name.encode("utf-8"))
    digest.update(request.video.content)
    digest.update(str(request.paths).encode("utf-8"))
    digest.update(str(request.policy).encode("utf-8"))
    digest.update(str(request.end_seconds).encode("utf-8"))
    return digest.hexdigest()


def _policy_snapshot_json(policy: ViewerPolicy) -> str:
    """실행에 실제 적용한 Viewer policy를 canonical JSON으로 고정한다."""

    return json.dumps(
        asdict(policy),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
