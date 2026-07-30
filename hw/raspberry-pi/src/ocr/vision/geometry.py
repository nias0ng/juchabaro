"""
YOLO anchor의 번호판 4점 좌표를 프레임별로 추정하고 원근 보정한다.

파이프라인 위치:
    plate_detector → geometry → plate_preprocessor

주요 기능:
    - 좌상→우상→우하→좌하 순서의 4점 좌표 검증
    - 두 anchor 사이의 좌표 보간과 제한적인 외삽
    - 단일 anchor 검출 시 인접 프레임에 한정한 좌표 재사용
    - 번호판의 자연스러운 가로·세로 크기를 유지한 perspective warp

담당하지 않는 기능:
    - YOLO keypoint 순서의 임의 재정렬
    - 번호판 화질 향상
    - OCR 추론과 문자열 판정
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence, cast

import cv2
import numpy as np

from ..errors import OcrComponentError
from ..image_validation import is_nonempty_bgr_uint8_image
from ..types import (
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    Quad,
    QuadSource,
    RectifiedPlate,
)


class GeometryError(ValueError):
    """장면상의 번호판 좌표를 사용할 수 없는 경우."""


class GeometryProcessingError(OcrComponentError, RuntimeError):
    """Geometry 입력·OpenCV·내부 반환 계약이 깨진 경우."""


# [기하 처리 설정]


@dataclass(frozen=True, slots=True)
class GeometryConfig:
    """
    번호판 4점 검증과 좌표 추정에 사용하는 운영 기준.

    현재 면적·변 길이·종횡비는 명백히 잘못된 좌표를 거르는 초기값이다.
    실제 카메라 설치 거리와 번호판 크기 분포를 수집한 뒤 재조정해야 한다.

    실패:
        값이 유한하지 않거나 각 허용 범위가 잘못되면 ValueError가 발생한다.
    """

    bounds_tolerance_px: float = 2.0
    min_quad_area_px: float = 100.0
    min_edge_length_px: float = 5.0
    min_aspect_ratio: float = 1.2
    max_aspect_ratio: float = 8.0
    max_extrapolation_frames: int = 1
    single_anchor_reuse_radius: int = 1

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.bounds_tolerance_px)
            or self.bounds_tolerance_px < 0.0
        ):
            raise ValueError(
                "bounds_tolerance_px는 0 이상의 유한한 값이어야 합니다."
            )

        positive_values = (
            self.min_quad_area_px,
            self.min_edge_length_px,
            self.min_aspect_ratio,
            self.max_aspect_ratio,
        )
        if not all(
            math.isfinite(value) and value > 0.0
            for value in positive_values
        ):
            raise ValueError("기하 검증 기준값은 0보다 큰 유한한 값이어야 합니다.")
        if self.min_aspect_ratio >= self.max_aspect_ratio:
            raise ValueError("최소 종횡비는 최대 종횡비보다 작아야 합니다.")
        if self.max_extrapolation_frames < 0:
            raise ValueError("max_extrapolation_frames는 0 이상이어야 합니다.")
        if self.single_anchor_reuse_radius < 0:
            raise ValueError("single_anchor_reuse_radius는 0 이상이어야 합니다.")


# [4점 좌표 검증]


class PlateGeometry:
    """
    검출된 번호판 4점을 burst 전체로 확장하고 각 crop을 정면화한다.

    YOLO pose가 반환하는 점 순서는 반드시 좌상→우상→우하→좌하로
    학습되어 있어야 한다. 잘못된 순서를 자동으로 재정렬하지 않으므로
    모델 학습 계약 오류가 조용히 가려지지 않는다.

    입력:
        pipeline 진입 검증을 통과한 시간순 CapturedFrame 시퀀스와
        최대 2개의 DetectedPlate anchor.

    출력:
        프레임별 EstimatedQuad 또는 원근 보정된 RectifiedPlate.

    실패:
        좌표나 anchor 구성이 잘못되거나 유효한 anchor가 하나도 없으면
        GeometryError가 발생한다.
    """

    def __init__(
        self,
        config: GeometryConfig | None = None,
    ) -> None:
        self._config = config or GeometryConfig()

    def estimate_quads(
        self,
        frames: Sequence[CapturedFrame],
        detections: Sequence[DetectedPlate],
    ) -> tuple[EstimatedQuad, ...]:
        """
        최대 두 anchor의 좌표로 사용할 수 있는 프레임의 4점을 추정한다.

        입력:
            연속 frame_index를 가진 시간순 BGR 프레임과 서로 다른
            프레임에서 얻은 DetectedPlate 1~2개.

        출력:
            frame_index 순으로 정렬된 유효한 EstimatedQuad tuple.
            두 anchor 사이는 pointwise 선형 보간하고 바깥쪽 외삽과
            단일 anchor 재사용 범위는 GeometryConfig 설정을 따른다.

        실패:
            detection의 anchor 구성이나 내부 반환 계약이 잘못되면
            GeometryProcessingError가 발생한다. 모든 anchor가 장면상
            부적합하면 거부 사유를 담은 GeometryError가 발생한다.
            Burst 입력 계약은 pipeline 경계에서 한 번 검증하며 여기서
            반복하지 않는다.
        """

        frame_tuple = tuple(frames)
        frame_by_index = {
            frame.frame_index: frame
            for frame in frame_tuple
        }
        supplied_detections = tuple(detections)

        if not 1 <= len(supplied_detections) <= 2:
            raise GeometryProcessingError(
                "번호판 anchor 검출 결과는 1개 또는 2개여야 합니다."
            )

        detection_indices = tuple(
            detection.frame_index
            for detection in supplied_detections
        )
        if len(set(detection_indices)) != len(detection_indices):
            raise GeometryProcessingError(
                "같은 프레임의 anchor 검출 결과가 중복되었습니다."
            )
        if any(index not in frame_by_index for index in detection_indices):
            raise GeometryProcessingError(
                "anchor frame_index가 촬영 burst에 포함되어 있지 않습니다: "
                f"actual={detection_indices}"
            )

        usable_anchors: list[tuple[int, Quad]] = []
        rejected_reasons: list[str] = []

        for detection in supplied_detections:
            frame = frame_by_index[detection.frame_index]
            try:
                quad = self._validate_quad(detection.quad, frame)
            except GeometryError as exc:
                rejected_reasons.append(
                    f"frame_index={detection.frame_index}: {exc}"
                )
            else:
                usable_anchors.append((detection.frame_index, quad))

        if not usable_anchors:
            detail = "; ".join(rejected_reasons)
            raise GeometryError(
                f"사용할 수 있는 번호판 anchor가 없습니다: {detail}"
            )

        usable_anchors.sort(key=lambda item: item[0])
        if len(usable_anchors) == 1:
            estimates = self._estimate_from_one_anchor(
                frame_tuple,
                usable_anchors[0],
            )
        else:
            estimates = self._estimate_from_two_anchors(
                frame_tuple,
                usable_anchors[0],
                usable_anchors[1],
            )

        if not estimates:
            # 유효한 anchor 자신은 항상 포함되므로 내부 invariant 오류다.
            raise GeometryProcessingError(
                "프레임에 적용할 수 있는 번호판 좌표가 없습니다."
            )

        return tuple(sorted(estimates, key=lambda estimate: estimate.frame_index))

    def rectify(
        self,
        frame: CapturedFrame,
        estimate: EstimatedQuad,
    ) -> RectifiedPlate:
        """
        번호판 4점을 직사각형으로 perspective warp한다.

        입력:
            BGR uint8 HxWx3 CapturedFrame과 같은 frame_index의
            EstimatedQuad. 점 순서는 좌상→우상→우하→좌하다.

        출력:
            원래 번호판의 긴 변·짧은 변 길이로 계산한 RectifiedPlate.

        실패:
            장면상의 좌표가 유효하지 않으면 GeometryError가 발생한다.
            입력 계약 위반이나 OpenCV 원근 변환 실패는
            GeometryProcessingError가 발생한다.
        """

        if not isinstance(frame, CapturedFrame):
            raise GeometryProcessingError(
                "frame은 CapturedFrame이어야 합니다."
            )
        if (
            isinstance(frame.frame_index, bool)
            or not isinstance(frame.frame_index, int)
        ):
            raise GeometryProcessingError(
                "frame_index는 bool이 아닌 정수여야 합니다."
            )
        if not is_nonempty_bgr_uint8_image(frame.image):
            raise GeometryProcessingError(
                "frame.image는 비어 있지 않은 BGR uint8 "
                "HxWx3 배열이어야 합니다."
            )

        if frame.frame_index != estimate.frame_index:
            raise GeometryProcessingError(
                "프레임과 추정 좌표의 frame_index가 다릅니다: "
                f"frame={frame.frame_index}, estimate={estimate.frame_index}"
            )

        quad = self._validate_quad(estimate.quad, frame)
        top_left, top_right, bottom_right, bottom_left = quad

        width = max(
            math.dist(top_left, top_right),
            math.dist(bottom_left, bottom_right),
        )
        height = max(
            math.dist(top_left, bottom_left),
            math.dist(top_right, bottom_right),
        )

        # 좌표는 픽셀 중심을 가리키므로 양 끝점 사이 거리에 한 픽셀을 더한다.
        target_width = max(2, round(width) + 1)
        target_height = max(2, round(height) + 1)
        source = np.asarray(quad, dtype=np.float32)
        destination = np.asarray(
            (
                (0.0, 0.0),
                (float(target_width - 1), 0.0),
                (float(target_width - 1), float(target_height - 1)),
                (0.0, float(target_height - 1)),
            ),
            dtype=np.float32,
        )

        try:
            transform = cv2.getPerspectiveTransform(source, destination)
            rectified = cv2.warpPerspective(
                frame.image,
                transform,
                (target_width, target_height),
                flags=cv2.INTER_LINEAR,
            )
        except cv2.error as exc:
            raise GeometryProcessingError(
                f"번호판 원근 보정에 실패했습니다: frame_index={frame.frame_index}"
            ) from exc

        if not is_nonempty_bgr_uint8_image(rectified):
            raise GeometryProcessingError(
                f"원근 보정 결과가 유효하지 않습니다: frame_index={frame.frame_index}"
            )

        return RectifiedPlate(
            frame_index=frame.frame_index,
            image=rectified,
            quad_estimate=estimate,
        )

    def _validate_quad(
        self,
        quad: Quad,
        frame: CapturedFrame,
    ) -> Quad:
        """
        고정된 TL→TR→BR→BL 좌표 순서와 기하·이미지 경계를 검증한다.

        유효한 좌표는 float tuple로 정규화해 반환한다.
        """

        points = self._normalize_quad_coordinates(quad)
        points = self._validate_bounds_and_clip(points, frame)
        self._validate_order_and_convexity(points)
        self._validate_area_edges_and_aspect(points)
        return points

    @staticmethod
    def _normalize_quad_coordinates(quad: Quad) -> Quad:
        """네 꼭짓점을 유한한 float ``(x, y)`` 좌표로 정규화한다."""

        try:
            if len(quad) != 4:
                raise GeometryProcessingError(
                    "번호판 좌표는 꼭짓점 4개여야 합니다."
                )
            if any(len(point) != 2 for point in quad):
                raise GeometryProcessingError(
                    "각 번호판 꼭짓점은 (x, y) 두 값이어야 합니다."
                )
            points = tuple(
                (float(point[0]), float(point[1]))
                for point in quad
            )
        except GeometryProcessingError:
            raise
        except (TypeError, ValueError, IndexError) as exc:
            raise GeometryProcessingError(
                "번호판 좌표를 (x, y) 숫자로 변환할 수 없습니다."
            ) from exc

        if not all(
            math.isfinite(value)
            for point in points
            for value in point
        ):
            raise GeometryProcessingError(
                "번호판 좌표는 유한한 숫자여야 합니다."
            )

        return cast(Quad, points)

    def _validate_bounds_and_clip(
        self,
        points: Quad,
        frame: CapturedFrame,
    ) -> Quad:
        """프레임 경계를 검사하고 허용 오차 안의 좌표만 경계로 자른다."""

        image_height, image_width = frame.image.shape[:2]
        tolerance = self._config.bounds_tolerance_px
        if any(
            x < -tolerance
            or x > image_width - 1 + tolerance
            or y < -tolerance
            or y > image_height - 1 + tolerance
            for x, y in points
        ):
            raise GeometryError("번호판 좌표가 원본 프레임 경계를 벗어납니다.")

        # YOLO resize 복원 과정의 작은 오차를 설정된 허용치 안에서 자른다.
        points = tuple(
            (
                min(max(x, 0.0), float(image_width - 1)),
                min(max(y, 0.0), float(image_height - 1)),
            )
            for x, y in points
        )

        return cast(Quad, points)

    @staticmethod
    def _validate_order_and_convexity(points: Quad) -> None:
        """TL→TR→BR→BL 의미 순서와 볼록 사각형 조건을 검증한다."""

        top_left, top_right, bottom_right, bottom_left = points
        top_mid_y = (top_left[1] + top_right[1]) / 2.0
        bottom_mid_y = (bottom_left[1] + bottom_right[1]) / 2.0
        left_mid_x = (top_left[0] + bottom_left[0]) / 2.0
        right_mid_x = (top_right[0] + bottom_right[0]) / 2.0
        if top_mid_y >= bottom_mid_y or left_mid_x >= right_mid_x:
            raise GeometryError(
                "번호판 좌표 순서는 좌상→우상→우하→좌하여야 합니다."
            )

        cross_products: list[float] = []
        for index in range(4):
            current = points[index]
            following = points[(index + 1) % 4]
            next_following = points[(index + 2) % 4]
            cross_products.append(
                (following[0] - current[0])
                * (next_following[1] - following[1])
                - (following[1] - current[1])
                * (next_following[0] - following[0])
            )

        # 이미지 좌표계에서 TL→TR→BR→BL은 양의 회전 방향이다.
        if any(value <= 1e-6 for value in cross_products):
            raise GeometryError("번호판 좌표가 유효한 볼록 사각형이 아닙니다.")

    def _validate_area_edges_and_aspect(
        self,
        points: Quad,
    ) -> None:
        """사각형 면적, 네 변 길이와 종횡비 운영 기준을 검증한다."""

        top_left, top_right, bottom_right, bottom_left = points
        signed_twice_area = sum(
            points[index][0] * points[(index + 1) % 4][1]
            - points[(index + 1) % 4][0] * points[index][1]
            for index in range(4)
        )
        area = signed_twice_area / 2.0
        if area < self._config.min_quad_area_px:
            raise GeometryError(
                "번호판 사각형 면적이 최소 기준보다 작습니다: "
                f"area={area:.2f}"
            )

        top_width = math.dist(top_left, top_right)
        bottom_width = math.dist(bottom_left, bottom_right)
        left_height = math.dist(top_left, bottom_left)
        right_height = math.dist(top_right, bottom_right)
        edge_lengths = (
            top_width,
            bottom_width,
            left_height,
            right_height,
        )
        if min(edge_lengths) < self._config.min_edge_length_px:
            raise GeometryError(
                "번호판 사각형의 변 길이가 최소 기준보다 작습니다."
            )

        width = max(top_width, bottom_width)
        height = max(left_height, right_height)
        aspect_ratio = width / height
        if not (
            self._config.min_aspect_ratio
            <= aspect_ratio
            <= self._config.max_aspect_ratio
        ):
            raise GeometryError(
                "번호판 종횡비가 허용 범위를 벗어납니다: "
                f"aspect_ratio={aspect_ratio:.3f}"
            )

    # [Anchor 좌표 보간]

    def _estimate_from_one_anchor(
        self,
        frames: tuple[CapturedFrame, ...],
        anchor: tuple[int, Quad],
    ) -> list[EstimatedQuad]:
        """단일 anchor 좌표를 설정된 반경의 인접 프레임에만 재사용한다."""

        anchor_index, anchor_quad = anchor
        estimates: list[EstimatedQuad] = []

        for frame in frames:
            distance = abs(frame.frame_index - anchor_index)
            if distance > self._config.single_anchor_reuse_radius:
                continue

            try:
                quad = self._validate_quad(anchor_quad, frame)
            except GeometryError:
                # 재사용 좌표가 해당 프레임 검증을 실패해도 나머지는 진행한다.
                continue

            source = (
                QuadSource.DETECTED
                if frame.frame_index == anchor_index
                else QuadSource.REUSED
            )
            estimates.append(
                EstimatedQuad(
                    frame_index=frame.frame_index,
                    quad=quad,
                    source=source,
                    source_anchor_indices=(anchor_index,),
                )
            )

        return estimates

    def _estimate_from_two_anchors(
        self,
        frames: tuple[CapturedFrame, ...],
        earlier: tuple[int, Quad],
        later: tuple[int, Quad],
    ) -> list[EstimatedQuad]:
        """두 anchor의 같은 의미 꼭짓점을 시간축에서 선형 보간한다."""

        earlier_index, earlier_quad = earlier
        later_index, later_quad = later
        interval = later_index - earlier_index
        if interval <= 0:
            raise GeometryProcessingError(
                "두 anchor의 시간순 인덱스가 올바르지 않습니다."
            )

        estimates: list[EstimatedQuad] = []
        for frame in frames:
            index = frame.frame_index
            if index < earlier_index:
                if (
                    earlier_index - index
                    > self._config.max_extrapolation_frames
                ):
                    continue
                source = QuadSource.EXTRAPOLATED
            elif index > later_index:
                if (
                    index - later_index
                    > self._config.max_extrapolation_frames
                ):
                    continue
                source = QuadSource.EXTRAPOLATED
            elif index == earlier_index:
                source = QuadSource.DETECTED
            elif index == later_index:
                source = QuadSource.DETECTED
            else:
                source = QuadSource.INTERPOLATED

            if index == earlier_index:
                candidate = earlier_quad
                source_indices = (earlier_index,)
            elif index == later_index:
                candidate = later_quad
                source_indices = (later_index,)
            else:
                alpha = (index - earlier_index) / interval
                candidate = cast(
                    Quad,
                    tuple(
                        (
                            earlier_point[0]
                            + alpha * (later_point[0] - earlier_point[0]),
                            earlier_point[1]
                            + alpha * (later_point[1] - earlier_point[1]),
                        )
                        for earlier_point, later_point in zip(
                            earlier_quad,
                            later_quad,
                            strict=True,
                        )
                    ),
                )
                source_indices = (earlier_index, later_index)

            try:
                validated_quad = self._validate_quad(candidate, frame)
            except GeometryError:
                # 보간·외삽 좌표 하나의 실패가 나머지 프레임을 막지 않게 한다.
                continue

            estimates.append(
                EstimatedQuad(
                    frame_index=index,
                    quad=validated_quad,
                    source=source,
                    source_anchor_indices=source_indices,
                )
            )

        return estimates
