"""클릭 좌표를 검증된 zones 페이로드로 바꾸는 순수 로직.

cv2 창·마우스 콜백은 annotate_zones.py에 두고 여기는 GUI를 모른다. 그래서
좌표 정규화와 계약 검증 전체를 자동 테스트로 고정할 수 있다.
"""

from __future__ import annotations

from typing import Any

from jetson_vehicle_tracking_baseline import (
    IGNORED_ZONE_TYPES_FOR_PARKING,
    BaselineError,
    ZoneType,
)

# 허용 점유 시간이 필수인 구역 (구역 계약 스펙 §5.3, FR-EV-009).
_ALLOWED_MINUTES_REQUIRED = frozenset({ZoneType.EV_FAST, ZoneType.EV_SLOW})
# 차를 세우는 칸이 아니라 판정용 참조 도형이라 허용 시간 개념이 없다.
_ALLOWED_MINUTES_FORBIDDEN = frozenset({ZoneType.AISLE}) | IGNORED_ZONE_TYPES_FOR_PARKING


class ZoneAnnotator:
    """폴리곤 클릭을 모아 zones 페이로드를 만든다.

    zoneId는 백엔드가 발급하는 값이지만 아직 POST를 한 적이 없는 로컬 파일에는
    발급처가 없다. 그래서 1부터 순번으로 붙이고 payload에 source="local"을 넣어
    서버 발급이 아님을 표시한다(설계 문서 §2.4(a)).
    """

    def __init__(
        self, *, frame_width: int, frame_height: int, camera_code: str, calibration: dict[str, Any]
    ) -> None:
        if frame_width <= 0 or frame_height <= 0:
            raise BaselineError(f"프레임 크기가 올바르지 않습니다: {frame_width}x{frame_height}")
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._camera_code = camera_code
        self._calibration = calibration
        self._pending: list[tuple[int, int]] = []
        self._zones: list[dict[str, Any]] = []

    @property
    def pending_points(self) -> list[tuple[int, int]]:
        """아직 확정하지 않은 폴리곤의 픽셀 좌표들."""

        return list(self._pending)

    @property
    def zones(self) -> list[dict[str, Any]]:
        """확정된 구역들."""

        return list(self._zones)

    def add_point(self, px: int, py: int) -> None:
        """폴리곤 정점을 픽셀 좌표로 추가한다."""

        if not (0 <= px < self._frame_width and 0 <= py < self._frame_height):
            raise BaselineError(
                f"클릭 좌표가 프레임 밖입니다: ({px}, {py}), 프레임 {self._frame_width}x{self._frame_height}"
            )
        self._pending.append((int(px), int(py)))

    def undo_point(self) -> None:
        """마지막 정점을 취소한다. 정점이 없으면 아무 일도 하지 않는다."""

        if self._pending:
            self._pending.pop()

    def undo_zone(self) -> None:
        """마지막으로 확정한 구역을 취소한다. zone_number를 다시 쓸 수 있게 된다."""

        if self._zones:
            self._zones.pop()

    def commit(
        self, *, zone_type: ZoneType, zone_number: str, allowed_minutes: float | None
    ) -> None:
        """현재 폴리곤을 구역으로 확정한다.

        파일을 쓰고 나서 실패하면 클릭 작업이 날아가므로 여기서 전부 막는다.
        """

        if len(self._pending) < 3:
            raise BaselineError(f"폴리곤은 정점이 3개 이상이어야 합니다(현재 {len(self._pending)}개).")
        zone_number = zone_number.strip()
        if not zone_number:
            raise BaselineError("zone_number가 비어 있습니다.")
        if any(zone["zoneNumber"] == zone_number for zone in self._zones):
            # 계약 스펙 §6.1에서 zone_number는 전역 UNIQUE다 — 시드 POST가 중복을
            # 409로 거부하고, 그 전 단계인 여기서도 미리 막지 않으면 오버레이·로그가
            # 어느 구역을 가리키는지 라벨이 모호해진다. (ZoneRegistry.__init__의
            # dict는 zone_number가 아니라 zone_id로 키를 잡으므로 이 중복과는 무관하다.)
            raise BaselineError(f"이미 사용한 zone_number입니다: {zone_number}")
        if zone_type in _ALLOWED_MINUTES_REQUIRED and allowed_minutes is None:
            raise BaselineError(f"{zone_type.value} 구역은 allowed_minutes가 필수입니다.")
        if zone_type in _ALLOWED_MINUTES_FORBIDDEN and allowed_minutes is not None:
            raise BaselineError(f"{zone_type.value} 구역에는 allowed_minutes를 지정할 수 없습니다.")
        if allowed_minutes is not None and allowed_minutes <= 0:
            raise BaselineError(f"allowed_minutes는 양수여야 합니다: {allowed_minutes}")

        self._zones.append(
            {
                "zoneId": len(self._zones) + 1,
                "zoneNumber": zone_number,
                "zoneType": zone_type.value,
                "allowedMinutes": allowed_minutes,
                "polygon": [
                    [round(px / self._frame_width, 6), round(py / self._frame_height, 6)]
                    for px, py in self._pending
                ],
            }
        )
        self._pending.clear()

    def payload(self) -> dict[str, Any]:
        """ZoneRegistry.from_file이 읽는 형태로 직렬화한다."""

        if not self._zones:
            # ZoneRegistry.from_file이 빈 목록을 거부하므로 여기서 먼저 막는다.
            raise BaselineError("확정된 구역이 없습니다. 최소 하나는 찍어야 합니다.")
        return {
            "source": "local",
            "cameraCode": self._camera_code,
            "calibration": self._calibration,
            "zones": [dict(zone) for zone in self._zones],
        }
