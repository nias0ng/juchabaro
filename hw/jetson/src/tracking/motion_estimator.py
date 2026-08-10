"""시간적 bbox evidence를 PhysicalVehicle별 삼상태 motion 신호로 정규화한다.

주차·이동 확정 시간과 ParkingEpisode lifecycle은 parking 계층의 책임이다.
이 모듈은 zone, assignment, parking, incident 상태를 보지 않고 bbox와 관측
시각만 사용한다. 판단 근거가 부족하거나 상충하면 안전하게 UNKNOWN을 내보낸다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import hypot
from statistics import median

from src.domain.models import require_aware, require_positive
from src.tracking.models import (
    BoundingBox,
    MotionEstimate,
    MotionEstimateReason,
    MotionSignal,
    PhysicalVehicleId,
)


# 리플레이로 재조정해야 하는 provisional 기본값이다. 화면 좌표가 아닌
# 차량 bbox 대각선 대비 이동량을 사용하므로 카메라 해상도에는 종속되지 않는다.
_DEFAULT_WINDOW_SECONDS = 0.75
_DEFAULT_MIN_OBSERVATION_SPAN_SECONDS = 0.20
_DEFAULT_MAX_SAMPLE_GAP_SECONDS = 0.50
_DEFAULT_STATIONARY_THRESHOLD = 0.03
_DEFAULT_MOVING_THRESHOLD = 0.10
_DEFAULT_MIN_SAMPLES = 3
_DEFAULT_MIN_TREND_CONSISTENCY = 0.60


@dataclass(frozen=True)
class _TimedBoundingBox:
    observed_at: datetime
    bbox: BoundingBox


class MotionEstimator:
    """PhysicalVehicle별 시간 창에서 robust displacement와 trend를 계산한다.

    ``normalized_displacement``는 창의 앞·뒤 1/3 sample의 median center 간
    거리다. ``normalized_trend``는 모든 sample pair의 속도 median(Theil-Sen
    방식)을 같은 앞·뒤 구간에 투영한 거리다. 둘 다 창의 median bbox
    diagonal로 나눈다. ``trend_consistency``는 두 vector의 방향·크기 일치뿐
    아니라 이동이 여러 연속 sample 구간에 분산되어 지지되는지도 반영한다.
    따라서 단일 endpoint bbox spike만으로 MOVING을 확정하지 않는다.
    """

    def __init__(
        self,
        *,
        window_seconds: float = _DEFAULT_WINDOW_SECONDS,
        min_observation_span_seconds: float = _DEFAULT_MIN_OBSERVATION_SPAN_SECONDS,
        max_sample_gap_seconds: float = _DEFAULT_MAX_SAMPLE_GAP_SECONDS,
        stationary_threshold: float = _DEFAULT_STATIONARY_THRESHOLD,
        moving_threshold: float = _DEFAULT_MOVING_THRESHOLD,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
        min_trend_consistency: float = _DEFAULT_MIN_TREND_CONSISTENCY,
    ) -> None:
        require_positive(window_seconds, "window_seconds")
        require_positive(
            min_observation_span_seconds,
            "min_observation_span_seconds",
        )
        require_positive(max_sample_gap_seconds, "max_sample_gap_seconds")
        require_positive(stationary_threshold, "stationary_threshold")
        require_positive(moving_threshold, "moving_threshold")
        if min_observation_span_seconds > window_seconds:
            raise ValueError(
                "min_observation_span_seconds cannot exceed window_seconds"
            )
        if stationary_threshold >= moving_threshold:
            raise ValueError(
                "stationary_threshold must be smaller than moving_threshold"
            )
        if isinstance(min_samples, bool) or not isinstance(min_samples, int):
            raise TypeError("min_samples must be an integer")
        if min_samples < 3:
            raise ValueError("min_samples must be at least 3")
        if not 0.0 < min_trend_consistency <= 1.0:
            raise ValueError(
                "min_trend_consistency must be greater than 0 and at most 1"
            )

        self._window_seconds = window_seconds
        self._min_observation_span_seconds = min_observation_span_seconds
        self._max_sample_gap_seconds = max_sample_gap_seconds
        self._stationary_threshold = stationary_threshold
        self._moving_threshold = moving_threshold
        self._min_samples = min_samples
        self._min_trend_consistency = min_trend_consistency
        self._history: dict[
            PhysicalVehicleId,
            deque[_TimedBoundingBox],
        ] = {}

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        bbox: BoundingBox,
        observed_at: datetime,
    ) -> MotionEstimate:
        """관측을 시간 창에 추가하고 신뢰 가능한 경우에만 motion을 판정한다."""

        require_aware(observed_at, "observed_at")
        history = self._history.get(physical_vehicle_id)
        if history is None:
            history = deque()
            self._history[physical_vehicle_id] = history

        had_history = bool(history)
        latest_gap_seconds: float | None = None
        if history:
            latest_gap_seconds = (
                observed_at - history[-1].observed_at
            ).total_seconds()
            if latest_gap_seconds <= 0:
                raise ValueError(
                    "motion observations must be strictly increasing per PhysicalVehicle"
                )
            if latest_gap_seconds > self._max_sample_gap_seconds:
                history.clear()
                history.append(_TimedBoundingBox(observed_at=observed_at, bbox=bbox))
                return self._unknown_estimate(
                    physical_vehicle_id=physical_vehicle_id,
                    observed_at=observed_at,
                    reason=MotionEstimateReason.SAMPLE_GAP_EXCEEDED,
                    history=history,
                    latest_gap_seconds=latest_gap_seconds,
                )

        history.append(_TimedBoundingBox(observed_at=observed_at, bbox=bbox))
        cutoff = observed_at - timedelta(seconds=self._window_seconds)
        while len(history) > 1 and history[0].observed_at < cutoff:
            history.popleft()

        if len(history) == 1:
            return self._unknown_estimate(
                physical_vehicle_id=physical_vehicle_id,
                observed_at=observed_at,
                reason=(
                    MotionEstimateReason.FIRST_SAMPLE
                    if not had_history
                    else MotionEstimateReason.INSUFFICIENT_HISTORY
                ),
                history=history,
                latest_gap_seconds=latest_gap_seconds,
            )

        window_span_seconds = (
            history[-1].observed_at - history[0].observed_at
        ).total_seconds()
        if (
            len(history) < self._min_samples
            or window_span_seconds < self._min_observation_span_seconds
        ):
            return self._unknown_estimate(
                physical_vehicle_id=physical_vehicle_id,
                observed_at=observed_at,
                reason=MotionEstimateReason.INSUFFICIENT_HISTORY,
                history=history,
                latest_gap_seconds=latest_gap_seconds,
            )

        (
            normalized_displacement,
            normalized_trend,
            trend_consistency,
            reference_bbox_diagonal,
        ) = _motion_metrics(tuple(history))
        strongest_evidence = max(normalized_displacement, normalized_trend)
        weakest_evidence = min(normalized_displacement, normalized_trend)

        if strongest_evidence <= self._stationary_threshold:
            signal = MotionSignal.STATIONARY
            reason = MotionEstimateReason.STATIONARY_EVIDENCE
        elif (
            weakest_evidence >= self._moving_threshold
            and trend_consistency >= self._min_trend_consistency
        ):
            signal = MotionSignal.MOVING
            reason = MotionEstimateReason.MOVING_EVIDENCE
        else:
            signal = MotionSignal.UNKNOWN
            reason = MotionEstimateReason.AMBIGUOUS_EVIDENCE

        return MotionEstimate(
            physical_vehicle_id=physical_vehicle_id,
            signal=signal,
            reason=reason,
            observed_at=observed_at,
            sample_count=len(history),
            window_span_seconds=window_span_seconds,
            latest_sample_gap_seconds=latest_gap_seconds,
            normalized_displacement=normalized_displacement,
            normalized_trend=normalized_trend,
            trend_consistency=trend_consistency,
            reference_bbox_diagonal=reference_bbox_diagonal,
            stationary_threshold=self._stationary_threshold,
            moving_threshold=self._moving_threshold,
        )

    def pause(self, physical_vehicle_id: PhysicalVehicleId) -> None:
        """관측 신뢰 chain을 끊어 다음 관측부터 다시 warm-up하게 한다."""

        self._history.pop(physical_vehicle_id, None)

    def pause_all(self) -> None:
        """frame 전체가 신뢰 불가하거나 재시작할 때 모든 motion chain을 끊는다."""

        self._history.clear()

    def forget(self, physical_vehicle_id: PhysicalVehicleId) -> None:
        """PhysicalVehicle 종료가 commit된 뒤 관측 이력을 정리한다."""

        self._history.pop(physical_vehicle_id, None)

    def _unknown_estimate(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        observed_at: datetime,
        reason: MotionEstimateReason,
        history: deque[_TimedBoundingBox],
        latest_gap_seconds: float | None,
    ) -> MotionEstimate:
        window_span_seconds = (
            history[-1].observed_at - history[0].observed_at
        ).total_seconds()
        return MotionEstimate(
            physical_vehicle_id=physical_vehicle_id,
            signal=MotionSignal.UNKNOWN,
            reason=reason,
            observed_at=observed_at,
            sample_count=len(history),
            window_span_seconds=window_span_seconds,
            latest_sample_gap_seconds=latest_gap_seconds,
            normalized_displacement=None,
            normalized_trend=None,
            trend_consistency=None,
            reference_bbox_diagonal=None,
            stationary_threshold=self._stationary_threshold,
            moving_threshold=self._moving_threshold,
        )


def _motion_metrics(
    samples: tuple[_TimedBoundingBox, ...],
) -> tuple[float, float, float, float]:
    """Robust displacement, trend, agreement, bbox scale을 계산한다."""

    centers = tuple(_center(sample.bbox) for sample in samples)
    diagonals = tuple(_diagonal(sample.bbox) for sample in samples)
    reference_diagonal = median(diagonals)

    group_size = max(1, len(samples) // 3)
    early_samples = samples[:group_size]
    late_samples = samples[-group_size:]
    early_center = _median_center(early_samples)
    late_center = _median_center(late_samples)
    displacement_vector = (
        late_center[0] - early_center[0],
        late_center[1] - early_center[1],
    )
    normalized_displacement = (
        hypot(*displacement_vector) / reference_diagonal
    )

    x_velocities: list[float] = []
    y_velocities: list[float] = []
    for left_index, left in enumerate(samples[:-1]):
        left_center = centers[left_index]
        for right_index in range(left_index + 1, len(samples)):
            right = samples[right_index]
            elapsed_seconds = (right.observed_at - left.observed_at).total_seconds()
            right_center = centers[right_index]
            x_velocities.append(
                (right_center[0] - left_center[0]) / elapsed_seconds
            )
            y_velocities.append(
                (right_center[1] - left_center[1]) / elapsed_seconds
            )

    trend_velocity = (median(x_velocities), median(y_velocities))
    early_time = median(sample.observed_at.timestamp() for sample in early_samples)
    late_time = median(sample.observed_at.timestamp() for sample in late_samples)
    projection_seconds = late_time - early_time
    trend_vector = (
        trend_velocity[0] * projection_seconds,
        trend_velocity[1] * projection_seconds,
    )
    normalized_trend = hypot(*trend_vector) / reference_diagonal
    trend_consistency = min(
        _vector_consistency(displacement_vector, trend_vector),
        _temporal_support(samples, trend_vector),
    )
    return (
        normalized_displacement,
        normalized_trend,
        trend_consistency,
        reference_diagonal,
    )


def _center(bbox: BoundingBox) -> tuple[float, float]:
    return ((bbox.x1 + bbox.x2) / 2.0, (bbox.y1 + bbox.y2) / 2.0)


def _diagonal(bbox: BoundingBox) -> float:
    return hypot(bbox.x2 - bbox.x1, bbox.y2 - bbox.y1)


def _median_center(
    samples: tuple[_TimedBoundingBox, ...],
) -> tuple[float, float]:
    centers = tuple(_center(sample.bbox) for sample in samples)
    return (
        median(center[0] for center in centers),
        median(center[1] for center in centers),
    )


def _vector_consistency(
    displacement_vector: tuple[float, float],
    trend_vector: tuple[float, float],
) -> float:
    displacement_magnitude = hypot(*displacement_vector)
    trend_magnitude = hypot(*trend_vector)
    strongest_magnitude = max(displacement_magnitude, trend_magnitude)
    if strongest_magnitude == 0:
        return 1.0
    if displacement_magnitude == 0 or trend_magnitude == 0:
        return 0.0

    magnitude_agreement = min(displacement_magnitude, trend_magnitude) / strongest_magnitude
    cosine_similarity = (
        displacement_vector[0] * trend_vector[0]
        + displacement_vector[1] * trend_vector[1]
    ) / (displacement_magnitude * trend_magnitude)
    return magnitude_agreement * max(0.0, min(1.0, cosine_similarity))


def _temporal_support(
    samples: tuple[_TimedBoundingBox, ...],
    trend_vector: tuple[float, float],
) -> float:
    """이동 evidence가 한 endpoint가 아니라 여러 시간 구간에 있는지 측정한다.

    각 연속 center step을 robust trend 방향에 투영한다. 양의 투영이 둘보다
    적으면 단일 spike로 간주한다. 그 외에는 양의 이동이 전체 구간 중 얼마나
    자주 나타나는지와, 한 step에 과도하게 집중되지 않았는지를 함께 본다.
    일정 속도 이동은 1에 가깝고 마지막 한 frame만 튀면 0이 된다.
    """

    trend_magnitude = hypot(*trend_vector)
    if trend_magnitude == 0:
        return 0.0
    trend_direction = (
        trend_vector[0] / trend_magnitude,
        trend_vector[1] / trend_magnitude,
    )
    centers = tuple(_center(sample.bbox) for sample in samples)
    forward_velocities = []
    for index, (previous, current) in enumerate(
        zip(centers[:-1], centers[1:], strict=True)
    ):
        step = (current[0] - previous[0], current[1] - previous[1])
        projection = (
            step[0] * trend_direction[0]
            + step[1] * trend_direction[1]
        )
        if projection > 0:
            elapsed_seconds = (
                samples[index + 1].observed_at - samples[index].observed_at
            ).total_seconds()
            forward_velocities.append(projection / elapsed_seconds)

    interval_count = len(samples) - 1
    forward_count = len(forward_velocities)
    if forward_count < 2:
        return 0.0

    participation = forward_count / interval_count
    total_forward_velocity = sum(forward_velocities)
    concentration = max(forward_velocities) / total_forward_velocity
    uniform_concentration = 1.0 / forward_count
    distribution = (
        (1.0 - concentration) / (1.0 - uniform_concentration)
        if forward_count > 1
        else 0.0
    )
    return min(participation, max(0.0, min(1.0, distribution)))
