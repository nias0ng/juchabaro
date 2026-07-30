"""
여러 프레임의 OCR 후보를 전체 번호판 단위로 투표해 최종 판정한다.

파이프라인 위치:
    plate_text → aggregator의 PlateDecision → pipeline의 PlateReadResult 변환

주요 기능:
    - 번호판 형식과 OCR confidence에 따른 후보 선별
    - 정규화된 전체 번호판 문자열의 정확 일치 투표
    - 유효 프레임 수·득표율·차순위와의 격차에 따른 성공 여부 판정
    - 실패 원인을 ReadStatus와 진단값으로 표현

담당하지 않는 기능:
    - 문자열 정규화와 번호판 형식 판정
    - OCR confidence를 이용한 문자열 추측 교정
    - 프레임별 OCR 후보 생성

OCR confidence는 후보의 최소 품질 조건과 진단값으로만 사용한다.
소수 후보의 높은 confidence가 더 많이 관측된 번호판을 뒤집지는 않는다.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from numbers import Real
from typing import Sequence

from ..errors import OcrComponentError
from ..types import OcrCandidate, PlateDecision, ReadStatus


# [예외]


class AggregationError(OcrComponentError, ValueError):
    """OCR 후보 또는 집계 설정이 투표 입력 계약을 만족하지 않는 경우."""


# [집계 정책]


@dataclass(frozen=True, slots=True)
class AggregationPolicy:
    """
    여러 프레임의 번호판 후보를 확정하기 위한 최소 조건.

    입력:
        ``min_rec_score``는 후보로 인정할 최소 OCR confidence다.
        ``min_valid_frames``는 최소 유효 프레임 수다.
        ``min_vote_ratio``는 유효 프레임 중 최다 후보의 최소 비율이며,
        ``min_margin_ratio``는 차순위 후보와의 최소 비율 차이다.

    실패:
        점수·비율 값이 0~1 범위를 벗어나거나 개수 값이 1 미만이면
        AggregationError가 발생한다.
    """

    min_rec_score: float = 0.40
    min_valid_frames: int = 2
    min_vote_ratio: float = 0.60
    min_margin_ratio: float = 0.20

    def __post_init__(self) -> None:
        """설정값이 집계 계산에 사용할 수 있는 범위인지 검증한다."""

        object.__setattr__(
            self,
            "min_rec_score",
            _validated_probability(
                "min_rec_score",
                self.min_rec_score,
            ),
        )
        _validate_positive_integer(
            "min_valid_frames",
            self.min_valid_frames,
        )
        object.__setattr__(
            self,
            "min_vote_ratio",
            _validated_probability(
                "min_vote_ratio",
                self.min_vote_ratio,
            ),
        )
        object.__setattr__(
            self,
            "min_margin_ratio",
            _validated_probability(
                "min_margin_ratio",
                self.min_margin_ratio,
            ),
        )


def _validated_probability(name: str, value: float) -> float:
    """설정값이 유한한 0~1 범위인지 검사하고 float로 반환한다."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise AggregationError(
            f"{name}은 0~1 범위의 유한한 수여야 합니다."
        )

    numeric_value = float(value)
    if (
        not math.isfinite(numeric_value)
        or not 0.0 <= numeric_value <= 1.0
    ):
        raise AggregationError(
            f"{name}은 0~1 범위의 유한한 수여야 합니다."
        )

    return numeric_value


def _validate_positive_integer(name: str, value: int) -> None:
    """설정값이 bool이 아닌 1 이상의 정수인지 검사한다."""

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        raise AggregationError(f"{name}은 1 이상의 정수여야 합니다.")


# [후보 입력 검증]


def _validate_candidates(
    candidates: tuple[OcrCandidate, ...],
) -> None:
    """후보별 프레임과 confidence 계약 및 프레임 중복을 검사한다."""

    seen_frame_indices: set[int] = set()

    for candidate in candidates:
        if not isinstance(candidate, OcrCandidate):
            raise AggregationError(
                "candidates의 모든 항목은 OcrCandidate여야 합니다."
            )

        frame_index = candidate.frame_index
        if (
            isinstance(frame_index, bool)
            or not isinstance(frame_index, int)
            or frame_index < 0
        ):
            raise AggregationError(
                "candidate.frame_index는 0 이상의 정수여야 합니다."
            )
        if frame_index in seen_frame_indices:
            raise AggregationError(
                f"frame_index {frame_index}의 OCR 후보가 중복되었습니다."
            )
        seen_frame_indices.add(frame_index)

        if not isinstance(candidate.raw_text, str):
            raise AggregationError(
                "candidate.raw_text는 문자열이어야 합니다."
            )
        if not isinstance(candidate.normalized_text, str):
            raise AggregationError(
                "candidate.normalized_text는 문자열이어야 합니다."
            )
        if not isinstance(candidate.valid_format, bool):
            raise AggregationError(
                "candidate.valid_format은 bool이어야 합니다."
            )

        if (
            isinstance(candidate.rec_score, bool)
            or not isinstance(candidate.rec_score, Real)
        ):
            raise AggregationError(
                "candidate.rec_score는 0~1 범위의 "
                "유한한 수여야 합니다."
            )

        rec_score = float(candidate.rec_score)
        if (
            not math.isfinite(rec_score)
            or not 0.0 <= rec_score <= 1.0
        ):
            raise AggregationError(
                "candidate.rec_score는 0~1 범위의 "
                "유한한 수여야 합니다."
            )


# [판정 결과 생성]


def _empty_decision(
    status: ReadStatus,
    message: str,
) -> PlateDecision:
    """투표할 수 있는 후보가 없을 때 공통 진단값의 판정을 만든다."""

    return PlateDecision(
        status=status,
        plate_number=None,
        valid_frames=0,
        vote_count=0,
        vote_ratio=0.0,
        mean_rec_score=0.0,
        error_message=message,
    )


def _voted_decision(
    *,
    status: ReadStatus,
    winner: str,
    valid_frames: int,
    vote_count: int,
    vote_ratio: float,
    mean_rec_score: float,
    error_message: str | None,
) -> PlateDecision:
    """투표 진단값을 보존하면서 성공 또는 모호 판정을 만든다."""

    return PlateDecision(
        status=status,
        plate_number=winner if status is ReadStatus.SUCCESS else None,
        valid_frames=valid_frames,
        vote_count=vote_count,
        vote_ratio=vote_ratio,
        mean_rec_score=mean_rec_score,
        error_message=error_message,
    )


# [번호판 투표와 최종 판정]


class PlateAggregator:
    """
    프레임별 OCR 후보를 전체 번호판의 정확 일치 다수결로 집계한다.

    confidence 기준을 통과한 유효 형식 후보만 투표하며, 각 프레임은
    후보 하나만 제공할 수 있다. 득표수가 같은 최상위 후보는 OCR
    confidence로 해소하지 않고 모호한 결과로 남긴다.

    입력:
        OcrCandidate의 시퀀스. 모든 프레임 인덱스는 고유해야 하고
        confidence는 유한한 0~1 값이어야 한다.

    출력:
        최종 상태, 확정 번호판 또는 투표 진단값을 가진 PlateDecision.

    실패:
        후보 입력 계약이 잘못되면 AggregationError가 발생한다.
    """

    def __init__(
        self,
        policy: AggregationPolicy | None = None,
    ) -> None:
        self._policy = policy or AggregationPolicy()

    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> PlateDecision:
        """
        후보를 상태별로 선별한 뒤 전체 번호판 단위 투표를 수행한다.

        입력:
            프레임별 문자열 정규화와 형식 검사가 끝난 후보 시퀀스.

        출력:
            성공 시 전체 번호판을 포함하고, 실패 시 원인 상태와
            가능한 범위의 투표 진단값을 포함한 PlateDecision.

        실패:
            후보 타입·필드·프레임 중복 또는 confidence 계약을 위반하면
            AggregationError가 발생한다.
        """

        try:
            candidate_tuple = tuple(candidates)
        except TypeError as exc:
            raise AggregationError(
                "candidates는 OcrCandidate 시퀀스여야 합니다."
            ) from exc

        _validate_candidates(candidate_tuple)

        # 구두점만 인식한 결과도 정규화 이후에는 빈 OCR 결과로 본다.
        non_empty = [
            candidate
            for candidate in candidate_tuple
            if candidate.normalized_text
        ]
        if not non_empty:
            return _empty_decision(
                ReadStatus.OCR_EMPTY,
                "모든 프레임의 정규화된 OCR 문자열이 비어 있습니다.",
            )

        formatted = [
            candidate
            for candidate in non_empty
            if candidate.valid_format
        ]
        if not formatted:
            return _empty_decision(
                ReadStatus.INVALID_FORMAT,
                "현재 지원하는 일반 번호판 형식을 만족한 후보가 없습니다.",
            )

        eligible = [
            candidate
            for candidate in formatted
            if candidate.rec_score >= self._policy.min_rec_score
        ]
        if not eligible:
            return _empty_decision(
                ReadStatus.LOW_SCORE,
                "형식이 유효한 후보가 최소 OCR confidence "
                f"{self._policy.min_rec_score:.3f}에 미달했습니다.",
            )

        counts = Counter(
            candidate.normalized_text
            for candidate in eligible
        )
        scores: defaultdict[str, list[float]] = defaultdict(list)
        for candidate in eligible:
            scores[candidate.normalized_text].append(
                float(candidate.rec_score)
            )

        # confidence는 순위를 바꾸지 않는다. 문자열 정렬은 동률 상태의
        # 진단값을 실행마다 동일하게 만들기 위한 결정적 기준일 뿐이다.
        ranked = sorted(
            counts,
            key=lambda plate_number: (
                -counts[plate_number],
                plate_number,
            ),
        )
        winner = ranked[0]
        vote_count = counts[winner]
        valid_frames = len(eligible)
        vote_ratio = vote_count / valid_frames
        winner_scores = scores[winner]
        mean_rec_score = math.fsum(winner_scores) / len(winner_scores)

        second_vote_count = (
            counts[ranked[1]]
            if len(ranked) > 1
            else 0
        )
        # 비율을 두 번 나눈 뒤 빼면 3/5 - 2/5가 0.2보다 아주 작게
        # 표현될 수 있으므로, 득표수 차이를 먼저 구해 한 번만 나눈다.
        margin_ratio = (
            vote_count - second_vote_count
        ) / valid_frames

        common = {
            "winner": winner,
            "valid_frames": valid_frames,
            "vote_count": vote_count,
            "vote_ratio": vote_ratio,
            "mean_rec_score": mean_rec_score,
        }

        # 최상위 동률은 confidence로 깨지 않는다. 같은 수의 독립
        # 관측이므로 어느 번호판도 확정할 근거가 충분하지 않다.
        if (
            len(ranked) > 1
            and counts[ranked[0]] == counts[ranked[1]]
        ):
            return _voted_decision(
                status=ReadStatus.AMBIGUOUS,
                error_message=(
                    "최다 득표 번호판 후보가 동률입니다."
                ),
                **common,
            )

        if valid_frames < self._policy.min_valid_frames:
            return _voted_decision(
                status=ReadStatus.AMBIGUOUS,
                error_message=(
                    f"유효 프레임 {valid_frames}개가 최소 요구값 "
                    f"{self._policy.min_valid_frames}개에 미달했습니다."
                ),
                **common,
            )

        if vote_ratio < self._policy.min_vote_ratio:
            return _voted_decision(
                status=ReadStatus.AMBIGUOUS,
                error_message=(
                    f"최다 후보 득표율 {vote_ratio:.3f}이 최소 요구값 "
                    f"{self._policy.min_vote_ratio:.3f}에 미달했습니다."
                ),
                **common,
            )

        if margin_ratio < self._policy.min_margin_ratio:
            return _voted_decision(
                status=ReadStatus.AMBIGUOUS,
                error_message=(
                    "최다 후보와 차순위 후보의 득표율 차이 "
                    f"{margin_ratio:.3f}이 최소 요구값 "
                    f"{self._policy.min_margin_ratio:.3f}에 "
                    "미달했습니다."
                ),
                **common,
            )

        return _voted_decision(
            status=ReadStatus.SUCCESS,
            error_message=None,
            **common,
        )
