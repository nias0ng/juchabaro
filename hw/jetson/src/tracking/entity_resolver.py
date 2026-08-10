"""일시적인 트랙 구간들을 Jetson 내부 물리 차량으로 연결한다.

``PassthroughEntityResolver``는 활성 segment를 1:1로 매핑하는 명시적
fallback이다. 실제 application composition은 ``GeometricEntityResolver``를
사용해 짧게 끊긴 여러 TrackSegment를 같은 PhysicalVehicle로 재결합한다.

ByteTrack이 track_buffer를 넘겨 segment 종료를 확정하면 연결만
해제한다. 현재 frame의 미관측은 segment 종료로 추론하지 않는다.
``PassthroughEntityResolver``는 종료 뒤 새 segment를 기존 PhysicalVehicle에
재식별하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from uuid import uuid4

from src.domain.models import require_positive
from src.tracking.models import (
    BoundingBox,
    IdentityResolution,
    IdentityResolutionBatch,
    IdentityResolutionOutcome,
    IdentityResolutionReason,
    PhysicalVehicleId,
    TrackObservation,
    TrackSegmentId,
)


class PassthroughEntityResolver:
    """활성 track_segment_id와 UUID physical_vehicle_id를 1:1로 유지하는 통과 구현."""

    def __init__(self) -> None:
        self._active_ids: dict[TrackSegmentId, PhysicalVehicleId] = {}

    def resolve_frame(
        self,
        observations: tuple[TrackObservation, ...],
        *,
        ended_track_segment_ids: set[TrackSegmentId],
    ) -> IdentityResolutionBatch:
        """한 frame을 기존 1:1 규칙으로 결정한다."""

        self.end_track_segments(ended_track_segment_ids)
        existing_segment_ids = set(self._active_ids)
        by_segment: dict[TrackSegmentId, IdentityResolution] = {}
        for observation in sorted(
            observations,
            key=lambda item: int(item.track_segment_id),
        ):
            physical_vehicle_id = self.resolve(observation)
            existing = observation.track_segment_id in existing_segment_ids
            by_segment[observation.track_segment_id] = IdentityResolution(
                track_segment_id=observation.track_segment_id,
                outcome=(
                    IdentityResolutionOutcome.CONTINUED
                    if existing
                    else IdentityResolutionOutcome.CREATED
                ),
                physical_vehicle_id=physical_vehicle_id,
                reason=(
                    None
                    if existing
                    else IdentityResolutionReason.NO_ELIGIBLE_CANDIDATE
                ),
            )
        return IdentityResolutionBatch(
            tuple(by_segment[item.track_segment_id] for item in observations)
        )

    def resolve(self, observation: TrackObservation) -> PhysicalVehicleId:
        """이번 프레임에 관측된 track_segment_id의 physical_vehicle_id를 반환한다."""

        track_segment_id = observation.track_segment_id
        physical_vehicle_id = self._active_ids.get(track_segment_id)
        if physical_vehicle_id is None:
            physical_vehicle_id = PhysicalVehicleId(uuid4())
            self._active_ids[track_segment_id] = physical_vehicle_id
        return physical_vehicle_id

    def end_track_segments(
        self,
        ended_track_segment_ids: set[TrackSegmentId],
    ) -> None:
        """Adapter가 확정한 segment 연결만 해제한다.

        연결 해제는 반환값이 없으며 차량의 출차·RETIRED를
        의미하지 않는다.
        """

        for track_segment_id in sorted(ended_track_segment_ids):
            self._active_ids.pop(track_segment_id, None)

    def forget_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> None:
        """상위 owner가 종료를 commit한 차량의 모든 segment를 해제한다.

        NOT_PRESENT 확정이 ByteTrack removed 보고보다 먼저 올 수 있다.
        이 연결을 남기면 같은 segment ID가 재등장했을 때 이미 종료된
        PhysicalVehicle identity가 다시 살아난다.
        """

        attached_segment_ids = tuple(
            sorted(
                track_segment_id
                for track_segment_id, attached_vehicle_id in self._active_ids.items()
                if attached_vehicle_id == physical_vehicle_id
            )
        )
        for track_segment_id in attached_segment_ids:
            del self._active_ids[track_segment_id]

    def reset_track_segments(self) -> None:
        """Tracker runtime이 교체되면 숫자 segment ID 세대를 초기화한다."""

        self._active_ids.clear()


@dataclass(frozen=True)
class _IdentityHistory:
    latest: TrackObservation
    creation_order: int
    previous: TrackObservation | None = None


@dataclass(frozen=True)
class _CandidateScore:
    physical_vehicle_id: PhysicalVehicleId
    score: float
    gap_seconds: float
    center_distance_ratio: float
    predicted_iou: float
    area_ratio: float
    creation_order: int


@dataclass(frozen=True)
class _Assignment:
    selected: dict[TrackSegmentId, _CandidateScore]
    score_units: int


_SCORE_SCALE = 1_000_000


class GeometricEntityResolver:
    """시간·bbox 연속성으로 runtime TrackSegment를 재식별한다.

    Zone·Parking·Incident 결과나 Backend session identity는 사용하지 않는다.
    durable bbox checkpoint가 아직 없으므로 이 구현은 의도적으로
    ``RestartAwareEntityResolver``를 구현하지 않는다.
    """

    # 파일럿 export로 재조정해야 하는 provisional geometry safety gate다.
    # domain state나 zone 결과가 아니라 bbox 물리 일관성만 제한한다.
    _MIN_AREA_RATIO = 0.35
    _MAX_AREA_RATIO = 2.85
    _MIN_ASPECT_RATIO = 0.45
    _MAX_ASPECT_RATIO = 2.20
    _MIN_PREDICTED_IOU = 0.02
    _MAX_NEAR_CENTER_RATIO = 0.75
    _PREDICTION_HORIZON_SECONDS = 1.0

    def __init__(
        self,
        *,
        max_gap_seconds: float = 1.0,
        minimum_score: float = 0.42,
        ambiguity_margin: float = 0.08,
    ) -> None:
        require_positive(max_gap_seconds, "max_gap_seconds")
        _require_probability(minimum_score, "minimum_score")
        _require_probability(ambiguity_margin, "ambiguity_margin")
        self._max_gap_seconds = max_gap_seconds
        self._minimum_score = minimum_score
        self._ambiguity_margin = ambiguity_margin
        self._segment_to_vehicle: dict[TrackSegmentId, PhysicalVehicleId] = {}
        self._vehicle_to_segment: dict[PhysicalVehicleId, TrackSegmentId] = {}
        self._histories: dict[PhysicalVehicleId, _IdentityHistory] = {}
        self._next_creation_order = 0

    def resolve_frame(
        self,
        observations: tuple[TrackObservation, ...],
        *,
        ended_track_segment_ids: set[TrackSegmentId],
    ) -> IdentityResolutionBatch:
        """현재 frame 전체를 순서 독립적인 1:1 PhysicalVehicle로 결정한다.

        한 관측의 검증 실패가 앞선 관측의 binding/history만 남기지 않도록
        frame 전체가 성공한 뒤에만 상태 변경을 확정한다.
        """

        segment_snapshot = self._segment_to_vehicle.copy()
        vehicle_snapshot = self._vehicle_to_segment.copy()
        history_snapshot = self._histories.copy()
        creation_order_snapshot = self._next_creation_order
        try:
            return self._resolve_frame_mutating(
                observations,
                ended_track_segment_ids=ended_track_segment_ids,
            )
        except Exception:
            self._segment_to_vehicle = segment_snapshot
            self._vehicle_to_segment = vehicle_snapshot
            self._histories = history_snapshot
            self._next_creation_order = creation_order_snapshot
            raise

    def _resolve_frame_mutating(
        self,
        observations: tuple[TrackObservation, ...],
        *,
        ended_track_segment_ids: set[TrackSegmentId],
    ) -> IdentityResolutionBatch:
        """복사된 frame transaction 안에서 실제 resolver 상태를 갱신한다."""

        segment_ids = tuple(item.track_segment_id for item in observations)
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("identity frame cannot repeat a TrackSegment id")
        if set(segment_ids).intersection(ended_track_segment_ids):
            raise ValueError("a TrackSegment cannot be observed and ended together")

        self.end_track_segments(ended_track_segment_ids)
        by_segment: dict[TrackSegmentId, IdentityResolution] = {}
        occupied_vehicle_ids: set[PhysicalVehicleId] = set()
        new_observations: list[TrackObservation] = []

        for observation in sorted(
            observations,
            key=lambda item: int(item.track_segment_id),
        ):
            physical_vehicle_id = self._segment_to_vehicle.get(
                observation.track_segment_id
            )
            if physical_vehicle_id is None:
                new_observations.append(observation)
                continue
            if physical_vehicle_id in occupied_vehicle_ids:
                by_segment[observation.track_segment_id] = IdentityResolution(
                    track_segment_id=observation.track_segment_id,
                    outcome=IdentityResolutionOutcome.UNRESOLVED,
                    physical_vehicle_id=None,
                    candidate_count=1,
                    reason=IdentityResolutionReason.CANDIDATE_ALREADY_OCCUPIED,
                )
                continue
            occupied_vehicle_ids.add(physical_vehicle_id)
            self._remember(physical_vehicle_id, observation)
            by_segment[observation.track_segment_id] = IdentityResolution(
                track_segment_id=observation.track_segment_id,
                outcome=IdentityResolutionOutcome.CONTINUED,
                physical_vehicle_id=physical_vehicle_id,
            )

        available_vehicle_ids = tuple(
            sorted(
                (
                    physical_vehicle_id
                    for physical_vehicle_id in self._histories
                    if physical_vehicle_id not in occupied_vehicle_ids
                ),
                key=lambda item: self._histories[item].creation_order,
            )
        )
        occupied_history_ids = tuple(
            sorted(
                occupied_vehicle_ids.intersection(self._histories),
                key=lambda item: self._histories[item].creation_order,
            )
        )
        scores_by_segment: dict[TrackSegmentId, tuple[_CandidateScore, ...]] = {}
        occupied_scores_by_segment: dict[
            TrackSegmentId, tuple[_CandidateScore, ...]
        ] = {}
        accepted_by_segment: dict[TrackSegmentId, tuple[_CandidateScore, ...]] = {}

        for observation in new_observations:
            available_scores = self._scores_for(
                observation,
                available_vehicle_ids,
            )
            occupied_scores = self._scores_for(
                observation,
                occupied_history_ids,
            )
            scores_by_segment[observation.track_segment_id] = available_scores
            occupied_scores_by_segment[observation.track_segment_id] = occupied_scores
            accepted_by_segment[observation.track_segment_id] = tuple(
                item for item in available_scores if item.score >= self._minimum_score
            )

        assignment = _maximum_weight_assignment(accepted_by_segment)
        safe_selected: dict[TrackSegmentId, _CandidateScore] = {}
        assignment_margin_by_segment: dict[TrackSegmentId, float] = {}
        required_margin_units = round(self._ambiguity_margin * _SCORE_SCALE)
        for track_segment_id, candidate in assignment.selected.items():
            alternative = _maximum_weight_assignment(
                accepted_by_segment,
                forbidden_edges=frozenset(
                    {(track_segment_id, candidate.physical_vehicle_id)}
                ),
            )
            margin_units = assignment.score_units - alternative.score_units
            if margin_units >= required_margin_units:
                safe_selected[track_segment_id] = candidate
                assignment_margin_by_segment[track_segment_id] = (
                    margin_units / _SCORE_SCALE
                )

        for observation in new_observations:
            track_segment_id = observation.track_segment_id
            available_scores = scores_by_segment[track_segment_id]
            occupied_scores = occupied_scores_by_segment[track_segment_id]
            accepted = accepted_by_segment[track_segment_id]
            chosen = safe_selected.get(track_segment_id)
            if chosen is not None:
                resolution = self._reidentify(
                    observation,
                    chosen,
                    candidate_count=(
                        len(available_scores) + len(occupied_scores)
                    ),
                    assignment_margin=assignment_margin_by_segment[
                        track_segment_id
                    ],
                )
            elif accepted:
                resolution = _unresolved_resolution(
                    observation,
                    (*available_scores, *occupied_scores),
                    reason=IdentityResolutionReason.AMBIGUOUS_CANDIDATES,
                )
            else:
                accepted_occupied = tuple(
                    item
                    for item in occupied_scores
                    if item.score >= self._minimum_score
                )
                if accepted_occupied:
                    resolution = _unresolved_resolution(
                        observation,
                        (*available_scores, *occupied_scores),
                        reason=(
                            IdentityResolutionReason.CANDIDATE_ALREADY_OCCUPIED
                        ),
                    )
                else:
                    resolution = self._create(
                        observation,
                        scored_candidates=(*available_scores, *occupied_scores),
                    )
            by_segment[track_segment_id] = resolution

        return IdentityResolutionBatch(
            tuple(by_segment[item.track_segment_id] for item in observations)
        )

    def end_track_segments(
        self,
        ended_track_segment_ids: set[TrackSegmentId],
    ) -> None:
        """확정 종료된 segment 연결만 해제하고 identity history는 유지한다."""

        for track_segment_id in sorted(ended_track_segment_ids):
            physical_vehicle_id = self._segment_to_vehicle.pop(
                track_segment_id,
                None,
            )
            if (
                physical_vehicle_id is not None
                and self._vehicle_to_segment.get(physical_vehicle_id)
                == track_segment_id
            ):
                del self._vehicle_to_segment[physical_vehicle_id]

    def forget_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> None:
        """종료 commit된 PhysicalVehicle의 연결과 재식별 근거를 제거한다."""

        track_segment_id = self._vehicle_to_segment.pop(
            physical_vehicle_id,
            None,
        )
        if track_segment_id is not None:
            self._segment_to_vehicle.pop(track_segment_id, None)
        self._histories.pop(physical_vehicle_id, None)

    def reset_track_segments(self) -> None:
        """Tracker 숫자 ID 세대만 폐기하고 runtime identity history는 유지한다."""

        self._segment_to_vehicle.clear()
        self._vehicle_to_segment.clear()

    def _scores_for(
        self,
        observation: TrackObservation,
        physical_vehicle_ids: tuple[PhysicalVehicleId, ...],
    ) -> tuple[_CandidateScore, ...]:
        scores = tuple(
            score
            for physical_vehicle_id in physical_vehicle_ids
            if (
                score := self._score_candidate(
                    observation,
                    physical_vehicle_id,
                )
            )
            is not None
        )
        return tuple(
            sorted(
                scores,
                key=lambda item: (-item.score, item.creation_order),
            )
        )

    def _score_candidate(
        self,
        observation: TrackObservation,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> _CandidateScore | None:
        history = self._histories[physical_vehicle_id]
        gap_seconds = (
            observation.observed_at - history.latest.observed_at
        ).total_seconds()
        if gap_seconds < 0.0 or gap_seconds > self._max_gap_seconds:
            return None

        latest_bbox = history.latest.bbox
        predicted_bbox = _predict_bbox(
            history,
            gap_seconds=min(gap_seconds, self._PREDICTION_HORIZON_SECONDS),
        )
        center_distance_ratio = min(
            _normalized_center_distance(observation.bbox, latest_bbox),
            _normalized_center_distance(observation.bbox, predicted_bbox),
        )
        predicted_iou = max(
            _intersection_over_union(observation.bbox, latest_bbox),
            _intersection_over_union(observation.bbox, predicted_bbox),
        )
        area_ratio = _area(observation.bbox) / _area(latest_bbox)
        aspect_ratio = _aspect_ratio(observation.bbox) / _aspect_ratio(latest_bbox)
        if not self._MIN_AREA_RATIO <= area_ratio <= self._MAX_AREA_RATIO:
            return None
        if not self._MIN_ASPECT_RATIO <= aspect_ratio <= self._MAX_ASPECT_RATIO:
            return None
        if (
            predicted_iou < self._MIN_PREDICTED_IOU
            and center_distance_ratio > self._MAX_NEAR_CENTER_RATIO
        ):
            return None

        center_similarity = max(
            0.0,
            1.0 - center_distance_ratio / self._MAX_NEAR_CENTER_RATIO,
        )
        area_similarity = math.exp(-abs(math.log(area_ratio)))
        aspect_similarity = math.exp(-abs(math.log(aspect_ratio)))
        time_similarity = max(0.0, 1.0 - gap_seconds / self._max_gap_seconds)
        score = (
            0.40 * center_similarity
            + 0.25 * predicted_iou
            + 0.15 * area_similarity
            + 0.10 * aspect_similarity
            + 0.10 * time_similarity
        )
        return _CandidateScore(
            physical_vehicle_id=physical_vehicle_id,
            score=min(1.0, max(0.0, score)),
            gap_seconds=gap_seconds,
            center_distance_ratio=center_distance_ratio,
            predicted_iou=predicted_iou,
            area_ratio=area_ratio,
            creation_order=history.creation_order,
        )

    def _reidentify(
        self,
        observation: TrackObservation,
        candidate: _CandidateScore,
        *,
        candidate_count: int,
        assignment_margin: float,
    ) -> IdentityResolution:
        self._bind(candidate.physical_vehicle_id, observation.track_segment_id)
        self._remember(candidate.physical_vehicle_id, observation)
        return IdentityResolution(
            track_segment_id=observation.track_segment_id,
            outcome=IdentityResolutionOutcome.REIDENTIFIED,
            physical_vehicle_id=candidate.physical_vehicle_id,
            candidate_count=candidate_count,
            score=candidate.score,
            score_margin=assignment_margin,
            gap_seconds=candidate.gap_seconds,
            center_distance_ratio=candidate.center_distance_ratio,
            predicted_iou=candidate.predicted_iou,
            area_ratio=candidate.area_ratio,
        )

    def _create(
        self,
        observation: TrackObservation,
        *,
        scored_candidates: tuple[_CandidateScore, ...],
    ) -> IdentityResolution:
        physical_vehicle_id = PhysicalVehicleId(uuid4())
        self._bind(physical_vehicle_id, observation.track_segment_id)
        self._remember(physical_vehicle_id, observation)
        best, runner_up = _best_two(scored_candidates)
        return IdentityResolution(
            track_segment_id=observation.track_segment_id,
            outcome=IdentityResolutionOutcome.CREATED,
            physical_vehicle_id=physical_vehicle_id,
            candidate_count=len(scored_candidates),
            score=None if best is None else best.score,
            runner_up_score=None if runner_up is None else runner_up.score,
            score_margin=(
                None
                if best is None
                else best.score - (0.0 if runner_up is None else runner_up.score)
            ),
            gap_seconds=None if best is None else best.gap_seconds,
            center_distance_ratio=(
                None if best is None else best.center_distance_ratio
            ),
            predicted_iou=None if best is None else best.predicted_iou,
            area_ratio=None if best is None else best.area_ratio,
            reason=(
                IdentityResolutionReason.NO_ELIGIBLE_CANDIDATE
                if best is None
                else IdentityResolutionReason.BELOW_MIN_SCORE
            ),
        )

    def _bind(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        track_segment_id: TrackSegmentId,
    ) -> None:
        previous_segment_id = self._vehicle_to_segment.get(physical_vehicle_id)
        if previous_segment_id is not None and previous_segment_id != track_segment_id:
            self._segment_to_vehicle.pop(previous_segment_id, None)
        previous_vehicle_id = self._segment_to_vehicle.get(track_segment_id)
        if previous_vehicle_id is not None and previous_vehicle_id != physical_vehicle_id:
            self._vehicle_to_segment.pop(previous_vehicle_id, None)
        self._segment_to_vehicle[track_segment_id] = physical_vehicle_id
        self._vehicle_to_segment[physical_vehicle_id] = track_segment_id

    def _remember(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        observation: TrackObservation,
    ) -> None:
        history = self._histories.get(physical_vehicle_id)
        if history is not None and observation.observed_at < history.latest.observed_at:
            raise ValueError("identity observations must be monotonic per vehicle")
        if history is None:
            self._histories[physical_vehicle_id] = _IdentityHistory(
                latest=observation,
                creation_order=self._next_creation_order,
            )
            self._next_creation_order += 1
        elif observation.observed_at == history.latest.observed_at:
            self._histories[physical_vehicle_id] = _IdentityHistory(
                latest=observation,
                creation_order=history.creation_order,
                previous=history.previous,
            )
        else:
            self._histories[physical_vehicle_id] = _IdentityHistory(
                latest=observation,
                creation_order=history.creation_order,
                previous=history.latest,
            )


def _unresolved_resolution(
    observation: TrackObservation,
    candidates: tuple[_CandidateScore, ...],
    *,
    reason: IdentityResolutionReason,
) -> IdentityResolution:
    best, runner_up = _best_two(candidates)
    return IdentityResolution(
        track_segment_id=observation.track_segment_id,
        outcome=IdentityResolutionOutcome.UNRESOLVED,
        physical_vehicle_id=None,
        candidate_count=len(candidates),
        score=None if best is None else best.score,
        runner_up_score=None if runner_up is None else runner_up.score,
        score_margin=(
            None
            if best is None
            else best.score - (0.0 if runner_up is None else runner_up.score)
        ),
        gap_seconds=None if best is None else best.gap_seconds,
        center_distance_ratio=None if best is None else best.center_distance_ratio,
        predicted_iou=None if best is None else best.predicted_iou,
        area_ratio=None if best is None else best.area_ratio,
        reason=reason,
    )


def _best_two(
    candidates: tuple[_CandidateScore, ...],
) -> tuple[_CandidateScore | None, _CandidateScore | None]:
    ordered = sorted(
        candidates,
        key=lambda item: (-item.score, item.creation_order),
    )
    return (
        None if not ordered else ordered[0],
        None if len(ordered) < 2 else ordered[1],
    )


def _maximum_weight_assignment(
    accepted_by_segment: dict[TrackSegmentId, tuple[_CandidateScore, ...]],
    *,
    forbidden_edges: frozenset[
        tuple[TrackSegmentId, PhysicalVehicleId]
    ] = frozenset(),
) -> _Assignment:
    row_ids = tuple(
        sorted(
            (
                track_segment_id
                for track_segment_id, candidates in accepted_by_segment.items()
                if candidates
            ),
            key=int,
        )
    )
    if not row_ids:
        return _Assignment(selected={}, score_units=0)
    candidate_creation_orders = {
        item.physical_vehicle_id: item.creation_order
        for track_segment_id in row_ids
        for item in accepted_by_segment[track_segment_id]
    }
    candidate_ids = tuple(
        sorted(
            {
                item.physical_vehicle_id
                for track_segment_id in row_ids
                for item in accepted_by_segment[track_segment_id]
            },
            key=lambda item: candidate_creation_orders[item],
        )
    )
    candidate_index = {
        physical_vehicle_id: index
        for index, physical_vehicle_id in enumerate(candidate_ids)
    }
    score_lookup = {
        (track_segment_id, item.physical_vehicle_id): item
        for track_segment_id in row_ids
        for item in accepted_by_segment[track_segment_id]
    }
    invalid_cost = 10**15
    costs: list[list[int]] = []
    for track_segment_id in row_ids:
        row = [invalid_cost] * len(candidate_ids) + [0] * len(row_ids)
        for item in accepted_by_segment[track_segment_id]:
            edge = (track_segment_id, item.physical_vehicle_id)
            if edge in forbidden_edges:
                continue
            row[candidate_index[item.physical_vehicle_id]] = -round(
                item.score * _SCORE_SCALE
            )
        costs.append(row)
    assigned_columns = _hungarian_min_cost(costs)
    selected: dict[TrackSegmentId, _CandidateScore] = {}
    score_units = 0
    for row_index, column_index in enumerate(assigned_columns):
        if column_index >= len(candidate_ids):
            continue
        track_segment_id = row_ids[row_index]
        physical_vehicle_id = candidate_ids[column_index]
        candidate = score_lookup.get((track_segment_id, physical_vehicle_id))
        if candidate is not None:
            if (track_segment_id, physical_vehicle_id) in forbidden_edges:
                continue
            selected[track_segment_id] = candidate
            score_units += round(candidate.score * _SCORE_SCALE)
    return _Assignment(selected=selected, score_units=score_units)


def _hungarian_min_cost(costs: list[list[int]]) -> tuple[int, ...]:
    """행 수 이하의 열을 가진 cost matrix를 deterministic하게 최소화한다."""

    row_count = len(costs)
    if row_count == 0:
        return ()
    column_count = len(costs[0])
    if column_count < row_count or any(len(row) != column_count for row in costs):
        raise ValueError("Hungarian matrix must be rectangular with rows <= columns")
    potentials_rows = [0] * (row_count + 1)
    potentials_columns = [0] * (column_count + 1)
    column_match = [0] * (column_count + 1)
    previous_column = [0] * (column_count + 1)
    for row_index in range(1, row_count + 1):
        column_match[0] = row_index
        current_column = 0
        minimum = [math.inf] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[current_column] = True
            current_row = column_match[current_column]
            delta = math.inf
            next_column = 0
            for column_index in range(1, column_count + 1):
                if used[column_index]:
                    continue
                reduced = (
                    costs[current_row - 1][column_index - 1]
                    - potentials_rows[current_row]
                    - potentials_columns[column_index]
                )
                if reduced < minimum[column_index]:
                    minimum[column_index] = reduced
                    previous_column[column_index] = current_column
                if minimum[column_index] < delta:
                    delta = minimum[column_index]
                    next_column = column_index
            for column_index in range(column_count + 1):
                if used[column_index]:
                    potentials_rows[column_match[column_index]] += delta
                    potentials_columns[column_index] -= delta
                else:
                    minimum[column_index] -= delta
            current_column = next_column
            if column_match[current_column] == 0:
                break
        while True:
            next_column = previous_column[current_column]
            column_match[current_column] = column_match[next_column]
            current_column = next_column
            if current_column == 0:
                break
    assigned_columns = [-1] * row_count
    for column_index in range(1, column_count + 1):
        if column_match[column_index] != 0:
            assigned_columns[column_match[column_index] - 1] = column_index - 1
    return tuple(assigned_columns)


def _predict_bbox(history: _IdentityHistory, *, gap_seconds: float) -> BoundingBox:
    latest = history.latest.bbox
    previous = history.previous
    if previous is None or gap_seconds <= 0.0:
        return latest
    history_seconds = (
        history.latest.observed_at - previous.observed_at
    ).total_seconds()
    if history_seconds <= 0.0:
        return latest
    latest_center = _center(latest)
    previous_center = _center(previous.bbox)
    dx = (latest_center[0] - previous_center[0]) / history_seconds * gap_seconds
    dy = (latest_center[1] - previous_center[1]) / history_seconds * gap_seconds
    # 짧은 frame 간 bbox jitter를 1초 속도로 과대 외삽하지 않는다. 이 한계를
    # 넘는 관측은 velocity 근거가 없다고 보고 마지막 bbox를 그대로 사용한다.
    if math.hypot(dx, dy) > 1.5 * _diagonal(latest):
        return latest
    width = latest.x2 - latest.x1
    height = latest.y2 - latest.y1
    x1 = min(max(latest.x1 + dx, 0.0), 1.0 - width)
    y1 = min(max(latest.y1 + dy, 0.0), 1.0 - height)
    return BoundingBox(x1=x1, y1=y1, x2=x1 + width, y2=y1 + height)


def _normalized_center_distance(first: BoundingBox, second: BoundingBox) -> float:
    first_center = _center(first)
    second_center = _center(second)
    distance = math.hypot(
        first_center[0] - second_center[0],
        first_center[1] - second_center[1],
    )
    scale = max((_diagonal(first) + _diagonal(second)) / 2.0, 1e-9)
    return distance / scale


def _intersection_over_union(first: BoundingBox, second: BoundingBox) -> float:
    x1 = max(first.x1, second.x1)
    y1 = max(first.y1, second.y1)
    x2 = min(first.x2, second.x2)
    y2 = min(first.y2, second.y2)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = _area(first) + _area(second) - intersection
    return 0.0 if union <= 0.0 else intersection / union


def _center(bbox: BoundingBox) -> tuple[float, float]:
    return ((bbox.x1 + bbox.x2) / 2.0, (bbox.y1 + bbox.y2) / 2.0)


def _area(bbox: BoundingBox) -> float:
    return (bbox.x2 - bbox.x1) * (bbox.y2 - bbox.y1)


def _aspect_ratio(bbox: BoundingBox) -> float:
    return (bbox.x2 - bbox.x1) / (bbox.y2 - bbox.y1)


def _diagonal(bbox: BoundingBox) -> float:
    return math.hypot(bbox.x2 - bbox.x1, bbox.y2 - bbox.y1)


def _require_probability(value: float, name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
