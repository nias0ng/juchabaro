#!/usr/bin/env python3
"""녹화된 파일럿 영상을 새 모듈 파이프라인(camera→tracking→session→parking→
outbox)에 흘려보내 사건 전이 로그와 구역 방문 전이 로그를 만든다(465/T-17).

`ai/tracking/replay_pilot_video.py`(옛 baseline용)를 대체하지 않는다 — 그
스크립트와 `ai/tracking/jetson_vehicle_tracking_baseline.py`의 폐기는 T-23의
범위다. 이 스크립트는 실제 FastAPI 앱이 카메라 루프에서 쓰게 될 것과 같은
`src.*` 프로덕션 조립기(`src.application.monitoring_factory`)를 그대로 불러,
파일럿 영상으로 §4.7의 임계값을 산출할 수 있는 리플레이 경로를 연다.

**왜 사건 로그만으로는 부족한가.** 확정 전이가 outbox까지 가려면 백엔드
입차 이벤트가 만든 `ParkingSession`과의 correlation이 필요하다. 세 종류
전부가 그렇다:

* `ParkingTransition`(PARKED/UNPARKED) — `parking_episode_tracker.py`는
  `parking_session_id`가 있을 때만 `publication_revision`을 1로 올리고,
  `pipeline._parking_transitions()`는 revision이 오를 때만 전이를 만든다.
* `IncidentTransition` — `Incident.__post_init__`이 `publication_revision > 0`인
  Incident에 `entryAttempt`나 session correlation을 요구한다.
* `SessionExitTransition` — 정의상 `parking_session_id`가 필요하다.

파일럿 영상 리플레이에는 백엔드 입차 이벤트가 없어 session이 하나도 없으므로
`--out-events`는 이 리플레이에서 비어 있다(실측 확인: `tests/replay/
test_zone_visit_determinism.py::test_events_file_stays_empty_without_backend_session`).
옛 docstring은 이
결과를 `restricted_zone` 규칙의 `confirmable=False` 하나로만 설명했는데, 실제
차단 지점은 그보다 앞단인 session correlation이라 규칙과 무관하게 세 전이
모두에 걸린다. §4.7의 임계값 산출은 확정된 사건이 아니라 ZoneVisit의
ENTERING→INSIDE 오탐 횟수를 사람이 라벨링한 정답과 비교해 측정하므로,
`--out-zone-visits`가 실제로 쓰는 산출물이다. `--out-events`는 향후 게이트
이벤트를 리플레이에 주입하게 될 때를 대비해 그대로 남겨 둔다.

**임계값 플래그에 임의 기본값을 두지 않는다.** `config/settings.py`가 실측
전 값에 기본값을 두지 않는 것과 같은 이유다(§4.7) — 이 스크립트가 바로 그
실측 도구이므로, 숨은 숫자가 있으면 측정값 자체가 오염된다. 코드 어딘가에
이미 확립된 기본값이 있는 값(`--entry-zone-min-overlap-ratio`,
`--incident-confirm-seconds`, `--incident-clear-seconds`,
`--parking-confirm-seconds`)만 그 값을 그대로 재사용하고, 나머지는 필수
플래그다.

레포 루트에서 `hw/jetson`으로 이동한 뒤 모듈로 실행한다(README의 `python -m
uvicorn src.main:app`과 같은 이유 — `src`/`scripts`를 패키지로 해석하려면
`hw/jetson`이 사실상의 루트여야 한다):

    cd hw/jetson
    python -m scripts.replay_pilot_video \\
        --video ../../docs/video/video1.mp4 \\
        --zones-file config/zone_definition.pilot.json \\
        --calibration ../../ai/tracking/camera_calibration.json \\
        --model-path ../../ai/training/runs/.../weights/best.pt \\
        --zone-entry-confirm-seconds 3.0 --zone-exit-confirm-seconds 3.0 \\
        --parking-confirm-seconds 5.0 --parking-move-confirm-seconds 0.5 \\
        --absence-confirmation-seconds 5.0 \\
        --trusted-sample-max-gap-seconds 1.0 \\
        --motion-window-seconds 0.75 \\
        --motion-min-observation-span-seconds 0.20 \\
        --motion-max-sample-gap-seconds 0.50 \\
        --motion-stationary-threshold 0.03 \\
        --motion-moving-threshold 0.10 \\
        --motion-min-samples 3 \\
        --motion-min-trend-consistency 0.60 \\
        --reidentification-max-gap-seconds 4.0 \\
        --reidentification-min-score 0.42 \\
        --reidentification-ambiguity-margin 0.08 \\
        --assignment-min-overlap-ratio 0.5 --assignment-ambiguous-margin 0.05 \\
        --bad-parking-min-primary-overlap-ratio 0.75 \\
        --bad-parking-min-secondary-overlap-ratio 0.25 \\
        --out-of-zone-min-spot-overlap-ratio 0.50 \\
        --blocking-relation-confirm-seconds 3.0 --blocking-relation-clear-seconds 3.0 \\
        --out-events out/video1_events.jsonl \\
        --out-zone-visits out/video1_zone_visits.jsonl

위 5.0초 PARKED와 0.5초 movement 값은 현재 Pipeline Viewer 판정 테스트의
명시적 override다. 일반 배포의 PARKED 값 600초를 바꾸는 기본값이 아니다.

**실제 실행은 재현되지 않는다.** 위 예시는 결정론 테스트(`tests/replay/`,
`tests/application/`)처럼 uuid4()를 몽키패치하지 않으므로, 같은 영상으로 두
번 돌려도 `zoneVisitId`/`physicalVehicleId`는 실행마다 새로 뽑는 난수라 매번
다르다. 회귀 확인차 두 실행의 `--out-zone-visits`를 diff한다면 그 두 필드는
빼고 `zoneId`/`state`/`observedAt`만 비교하거나, diff 전에 두 필드를 지운다.
`--out-events`의 `deliveryId`는 그 예외다 — `JsonlPublicationPreparer`가
집계 identity에서 결정론적으로 만든다(`src/replay/publication_preparer.py`).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
from pathlib import Path

from src.application.monitoring_factory import (
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.application.monitoring_pipeline import MonitoringPipeline
from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE
from src.camera.frame_source import (
    CropFrameSource,
    EndOfVideo,
    RemapFrameSource,
    VideoFileFrameSource,
    calibration_fingerprint,
)
from src.parking.zone_registry import ZoneRegistry, ZoneRegistryError
from src.replay.publication_preparer import JsonlPublicationPreparer
from src.replay.zone_visit_publisher import DedupingZoneVisitPublisher, ZoneVisitJsonlPublisher
from src.storage.database import connect_database, open_database
from src.tracking.adapters.ultralytics_bytetrack import UltralyticsVehicleTracker

LOGGER = logging.getLogger("replay_pilot_video")


class ReplayArgumentError(RuntimeError):
    """리플레이 인자 검증에 실패했다."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--zones-file", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, default=None)
    parser.add_argument("--camera-id", default="PILOT-VIDEO")
    parser.add_argument(
        "--model-path", required=True,
        help="YOLO 가중치 경로. 기본값을 두지 않는다 — 'ai/training/yolo26n.pt'는 README가 문서화한 "
        "cwd(hw/jetson)에서 실제로 존재하지 않는 경로였다.",
    )
    parser.add_argument("--out-events", type=Path, required=True, help="확정된 사건 전이 JSONL(프로덕션 outbox 포맷).")
    parser.add_argument(
        "--out-zone-visits", type=Path, required=True,
        help="ZoneVisit 상태 전이 JSONL — §4.7 임계값 산출은 이 파일을 쓴다.",
    )
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--end-seconds", type=float, default=None)
    parser.add_argument(
        "--zone-entry-confirm-seconds", type=float, required=True,
        help="구역 진입 확인시간(초). 기본값을 두지 않는다 — config/settings.py와 같은 이유(§4.7).",
    )
    parser.add_argument(
        "--zone-exit-confirm-seconds", type=float, required=True,
        help="구역 이탈 확인시간(초). 기본값을 두지 않는다 — config/settings.py와 같은 이유(§4.7).",
    )
    parser.add_argument(
        "--parking-move-confirm-seconds", type=float, required=True,
        help="주차 후 이동 확인시간(초). .env.example이 '개발 편의용 임시값'이라 명시한 값이라 "
        "여기에 숨겨 두지 않는다(§4.7).",
    )
    parser.add_argument(
        "--absence-confirmation-seconds", type=float, required=True,
        help="부재 확정 시간(초). .env.example이 '파일럿 리플레이로 재조정한다'고 적은 값이라 "
        "그 리플레이 도구인 이 스크립트가 기본값을 두지 않는다.",
    )
    parser.add_argument(
        "--trusted-sample-max-gap-seconds", type=float, required=True,
        help="연속 관측으로 인정할 최대 프레임 간격(초). 영상 fps에 직접 매인 값이라 "
        "기본값을 두지 않는다(.env.example의 1.0은 5fps 파일럿 임시값).",
    )
    parser.add_argument(
        "--motion-window-seconds", type=float, required=True,
        help="MotionEstimator bbox evidence 시간 창(초). provisional 값을 명시한다.",
    )
    parser.add_argument(
        "--motion-min-observation-span-seconds", type=float, required=True,
        help="motion 판정에 필요한 최소 관측 span(초).",
    )
    parser.add_argument(
        "--motion-max-sample-gap-seconds", type=float, required=True,
        help="motion history를 연속으로 인정할 최대 sample 간격(초).",
    )
    parser.add_argument(
        "--motion-stationary-threshold", type=float, required=True,
        help="STATIONARY 최대 변위. median bbox diagonal 대비 비율이다.",
    )
    parser.add_argument(
        "--motion-moving-threshold", type=float, required=True,
        help="MOVING 최소 변위. median bbox diagonal 대비 비율이다.",
    )
    parser.add_argument(
        "--motion-min-samples", type=int, required=True,
        help="motion 판정에 필요한 최소 bbox sample 수.",
    )
    parser.add_argument(
        "--motion-min-trend-consistency", type=float, required=True,
        help="MOVING에 필요한 displacement/trend 방향·크기 일치도(0~1).",
    )
    parser.add_argument(
        "--reidentification-max-gap-seconds", type=float, required=True,
        help="끊긴 TrackSegment를 같은 PhysicalVehicle 후보로 볼 최대 시간(초).",
    )
    parser.add_argument(
        "--reidentification-min-score", type=float, required=True,
        help="EntityResolver geometry 전역 배정의 최소 수락 점수.",
    )
    parser.add_argument(
        "--reidentification-ambiguity-margin", type=float, required=True,
        help="최적 1:1 identity 배정을 확정할 최소 전역 점수차.",
    )
    parser.add_argument(
        "--assignment-min-overlap-ratio", type=float, required=True,
        help="주차 위치 배정 최소 겹침 비율. 코드·설정 어디에도 확립된 기본값이 없어 필수다.",
    )
    parser.add_argument(
        "--assignment-ambiguous-margin", type=float, required=True,
        help="배정 모호 판정 여유값. 코드·설정 어디에도 확립된 기본값이 없어 필수다.",
    )
    parser.add_argument(
        "--bad-parking-min-primary-overlap-ratio", type=float, required=True,
        help="정상 주차로 인정할 1위 주차면 최소 포함률. 파일럿 실측값을 필수로 받는다.",
    )
    parser.add_argument(
        "--bad-parking-min-secondary-overlap-ratio",
        type=float,
        required=True,
        help="BAD_PARKING으로 보는 두 번째 주차면의 최소 차량 포함 비율.",
    )
    parser.add_argument(
        "--out-of-zone-min-spot-overlap-ratio",
        type=float,
        required=True,
        help="OUT_OF_ZONE이 아니기 위한 전체 주차면 union의 최소 차량 포함 비율.",
    )
    parser.add_argument(
        "--blocking-relation-confirm-seconds", type=float, required=True,
        help="이중주차 차단 관계 확정 시간(초). docs §14에 TBD로 남은 값이라 필수다.",
    )
    parser.add_argument(
        "--blocking-relation-clear-seconds", type=float, required=True,
        help="이중주차 차단 관계 해소 시간(초). docs §14에 TBD로 남은 값이라 필수다.",
    )
    parser.add_argument(
        "--parking-confirm-seconds", type=float, default=600.0,
        help="주차 확정 시간(초). .env.example이 '요구사항 값'이라 명시한 600.0을 그대로 쓴다.",
    )
    parser.add_argument(
        "--entry-zone-min-overlap-ratio", type=float, default=0.40,
        help="입출차 구역 매칭 최소 겹침 비율. EntryMatchCoordinator의 기존 기본값을 그대로 쓴다.",
    )
    parser.add_argument(
        "--incident-confirm-seconds", type=float, default=0.0,
        help="사건 확정 지연(초). InMemoryIncidentReducer의 기존 기본값을 그대로 쓴다.",
    )
    parser.add_argument(
        "--incident-clear-seconds", type=float, default=0.0,
        help="사건 해소 지연(초). InMemoryIncidentReducer의 기존 기본값을 그대로 쓴다.",
    )
    parser.add_argument("--min-overlap-ratio", type=float, default=0.40)
    parser.add_argument("--tracker-config", default="bytetrack.yaml")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--remap-balance", type=float, default=DEFAULT_REMAP_BALANCE)
    parser.add_argument(
        "--crop-left-px", type=int, default=0,
        help="remap 이후 프레임에서 왼쪽 여백을 잘라낼 픽셀 수. 기본 0(자르지 않음).",
    )
    parser.add_argument(
        "--crop-right-px", type=int, default=0,
        help="remap 이후 프레임에서 오른쪽 여백을 잘라낼 픽셀 수. 기본 0(자르지 않음).",
    )
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    """리플레이 실행 전 필수 옵션과 수치 범위를 검증한다.

    `ai/tracking/replay_pilot_video.py`의 같은 검증과 같은 이유다 — 보정 없는
    리플레이는 모델이 remap 보정된 프레임으로 학습됐다는 전제를 조용히
    깨뜨려 위반 판정 전체를 틀리게 만든다.

    임계값의 단위·범위 검증은 여기서 중복하지 않는다 —
    `MonitoringPolicy`를 받는 각 domain owner가 이미 자신의 값을 검증하고
    `ValueError`로 거부한다(`monitoring_factory.py` docstring 참고).
    """

    if not (0.0 <= args.remap_balance <= 1.0):
        raise ReplayArgumentError("remap-balance는 0~1 범위여야 합니다.")
    if args.calibration is None:
        raise ReplayArgumentError(
            "리플레이에는 --calibration이 필요합니다(모델이 remap 보정된 프레임으로 학습됨)."
        )
    if not args.calibration.is_file():
        raise ReplayArgumentError(f"calibration 파일을 찾을 수 없습니다: {args.calibration}")
    verify_zone_calibration(args)


def verify_zone_calibration(args: argparse.Namespace) -> None:
    """zones 파일이 `--calibration`/`--remap-balance`와 같은 좌표계에서 찍혔는지 확인한다.

    `ai/tracking/jetson_vehicle_tracking_baseline.py`의 같은 이름 함수와 같은
    이유다 — remap은 1080p/balance 0.5에서 폴리곤을 최대 133px 옮기므로, 다른
    보정 설정으로 찍은 zones 파일을 조용히 쓰면 위반 판정이 전부 틀어진다.

    비교 대상은 구역 정의 snapshot의 `calibrationReference`다. 464의 구역
    포맷 개편으로 zones 파일 최상위의 옛 `"calibration"` 지문 dict는 사라졌고
    (`ZoneRegistry`가 최상위 키를 정확히 `zoneDefinitionVersion`/
    `calibrationReference`/`zones`로 제한한다), 런타임에서도 이 문자열이
    권위를 갖는다 — `MonitoringPipeline`이 프레임의 `calibration_id`와
    `ZoneRegistry.calibration_reference`를 비교해 `full_area_observed`를
    판단하므로, 여기서 미리 막지 않으면 모든 프레임이 조용히 부분 관측으로
    격하되어 §4.7 산출값이 통째로 틀어진다. `RemapFrameSource`가 프레임에
    찍는 값이 `calibration_fingerprint(...)["calibrationSha256"]`이라 기대값도
    같은 함수에서 뽑는다.
    """

    try:
        zones = ZoneRegistry.from_file(args.zones_file)
    except ZoneRegistryError as exc:
        raise ReplayArgumentError(f"구역 정의 파일을 읽을 수 없습니다({args.zones_file}): {exc}") from exc

    expected = calibration_fingerprint(args.calibration, args.remap_balance)["calibrationSha256"]
    recorded = zones.calibration_reference
    # 대소문자를 정규화하지 않는다 — 런타임 권위(MonitoringPipeline의
    # `frame.calibration_id == calibration_reference`, monitoring_pipeline.py)가
    # 대소문자 구분 정확 일치이므로, 여기서 `.lower()`로 느슨하게 비교하면
    # zones 파일에 대문자 hex가 섞여 있을 때 이 guard는 통과하고 런타임에서만
    # 조용히 실패해(모든 프레임이 부분 관측으로 격하) 이 함수의 존재 이유를 무력화한다.
    if recorded != expected:
        raise ReplayArgumentError(
            f"zones 파일의 좌표계가 현재 보정 설정과 다릅니다. zones-file의 "
            f"calibrationReference={recorded}, 현재 --calibration에서 계산한 값={expected}. "
            "같은 설정으로 zones 파일을 다시 만들거나 --calibration/--remap-balance를 "
            "zones 파일에 맞추세요."
        )


def build_policy(args: argparse.Namespace) -> MonitoringPolicy:
    """CLI 인자를 그대로 `MonitoringPolicy`로 옮긴다(값 해석 없음)."""

    return MonitoringPolicy(
        zone_entry_confirm_seconds=args.zone_entry_confirm_seconds,
        zone_exit_confirm_seconds=args.zone_exit_confirm_seconds,
        entry_zone_min_overlap_ratio=args.entry_zone_min_overlap_ratio,
        parking_confirm_seconds=args.parking_confirm_seconds,
        parking_move_confirm_seconds=args.parking_move_confirm_seconds,
        absence_confirmation_seconds=args.absence_confirmation_seconds,
        trusted_sample_max_gap_seconds=args.trusted_sample_max_gap_seconds,
        reidentification_max_gap_seconds=(
            args.reidentification_max_gap_seconds
        ),
        reidentification_min_score=args.reidentification_min_score,
        reidentification_ambiguity_margin=(
            args.reidentification_ambiguity_margin
        ),
        incident_confirm_seconds=args.incident_confirm_seconds,
        incident_clear_seconds=args.incident_clear_seconds,
        zone_presence_min_overlap_ratio=args.min_overlap_ratio,
        assignment_min_overlap_ratio=args.assignment_min_overlap_ratio,
        assignment_ambiguous_margin=args.assignment_ambiguous_margin,
        bad_parking_min_primary_overlap_ratio=(
            args.bad_parking_min_primary_overlap_ratio
        ),
        bad_parking_min_secondary_overlap_ratio=(
            args.bad_parking_min_secondary_overlap_ratio
        ),
        out_of_zone_min_spot_overlap_ratio=(
            args.out_of_zone_min_spot_overlap_ratio
        ),
        blocking_relation_confirm_seconds=args.blocking_relation_confirm_seconds,
        blocking_relation_clear_seconds=args.blocking_relation_clear_seconds,
        motion_window_seconds=args.motion_window_seconds,
        motion_min_observation_span_seconds=(
            args.motion_min_observation_span_seconds
        ),
        motion_max_sample_gap_seconds=args.motion_max_sample_gap_seconds,
        motion_stationary_threshold=args.motion_stationary_threshold,
        motion_moving_threshold=args.motion_moving_threshold,
        motion_min_samples=args.motion_min_samples,
        motion_min_trend_consistency=args.motion_min_trend_consistency,
    )


def build_pipeline(
    args: argparse.Namespace,
    *,
    database_path: Path,
    events_handle,
) -> tuple[MonitoringPipeline, ZoneVisitJsonlPublisher]:
    """CLI 인자로 MonitoringPipeline과 ZoneVisit 발행기를 조립한다.

    `database_path`는 호출자가 만들어 둔 SQLite 파일이어야 한다 —
    `MonitoringPipeline`이 프레임마다 `connection_factory()`로 새 connection을
    열고 닫으므로 `:memory:`는 쓸 수 없다(프레임마다 빈 DB가 새로 생긴다).
    """

    inner = VideoFileFrameSource(
        camera_id=args.camera_id, path=args.video, start_seconds=args.start_seconds, end_seconds=args.end_seconds
    )
    frame_source = RemapFrameSource(inner=inner, calibration_path=str(args.calibration), balance=args.remap_balance)
    frame_source = CropFrameSource(
        inner=frame_source, crop_left_px=args.crop_left_px, crop_right_px=args.crop_right_px
    )

    detector = UltralyticsVehicleTracker(
        model_path=args.model_path, tracker_config=args.tracker_config, confidence=args.confidence
    )

    pipeline = build_monitoring_pipeline(
        zones=ZoneRegistry.from_file(args.zones_file),
        policy=build_policy(args),
        dependencies=MonitoringDependencies(
            camera_id=args.camera_id,
            frame_source=frame_source,
            detector=detector,
            publication_preparer=JsonlPublicationPreparer(events_handle=events_handle),
            connection_factory=lambda: connect_database(database_path),
        ),
    )
    zone_visit_publisher = ZoneVisitJsonlPublisher(path=args.out_zone_visits)
    return pipeline, zone_visit_publisher


def run(args: argparse.Namespace) -> int:
    """영상 → 추적 → 판정 루프를 끝까지 돌리고 두 JSONL 로그를 채운다.

    `result.parking_result.zone_visit_updates`는 (차량, 구역) 쌍이 추적되는
    모든 프레임에 그 방문을 그대로 반환한다(`zone_visit_tracker.py`의
    `_advance_inside` 참고) — 한 구역에 20프레임 머무르면 거의 같은 레코드가
    20줄 나온다는 뜻이다. `DedupingZoneVisitPublisher`로 visit_id별 실제 상태
    전이만 걸러 발행하고, 로그의 "방문 전이 N건"도 그 걸러진 건수를 센다.

    durable state는 실행마다 새로 만든 임시 SQLite 파일에 담고 끝나면 지운다
    — 이 리플레이는 실행 간 상태를 이어받을 이유가 없고, 남겨 두면 다음
    실행이 이전 실행의 active aggregate를 복원해 산출값을 오염시킨다.
    """

    frames = 0
    total_zone_visits = 0
    workspace = Path(tempfile.mkdtemp(prefix="replay-pilot-"))
    try:
        database_path = workspace / "replay.db"
        # migration을 한 번 적용해 두면 이후 프레임별 connection은
        # connect_database()만으로 충분하다.
        open_database(database_path).close()

        args.out_events.parent.mkdir(parents=True, exist_ok=True)
        with args.out_events.open("w", encoding="utf-8", newline="\n") as events_handle:
            pipeline, zone_visit_publisher = build_pipeline(
                args, database_path=database_path, events_handle=events_handle
            )
            deduped_publisher = DedupingZoneVisitPublisher(zone_visit_publisher)

            pipeline.open()
            zone_visit_publisher.open()
            try:
                while True:
                    try:
                        result = pipeline.process_next_frame()
                    except EndOfVideo:
                        break
                    total_zone_visits += deduped_publisher.publish_all(
                        result.parking_result.zone_visit_updates
                    )
                    frames += 1
                    if frames % 300 == 0:
                        LOGGER.info("%d 프레임 처리, 방문 전이 %d건", frames, total_zone_visits)
            finally:
                zone_visit_publisher.close()
                pipeline.close()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    LOGGER.info(
        "완료: %d 프레임, 방문 전이 %d건 → %s / %s", frames, total_zone_visits, args.out_events, args.out_zone_visits
    )
    if total_zone_visits == 0:
        LOGGER.warning(
            "구역 방문 전이가 0건입니다. zones-file 폴리곤이 영상과 맞는지, "
            "min-overlap-ratio(%.2f)가 너무 높지 않은지 확인하세요.",
            args.min_overlap_ratio,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    validate_args(args)
    return run(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReplayArgumentError as exc:
        LOGGER.error("%s", exc)
        sys.exit(1)
