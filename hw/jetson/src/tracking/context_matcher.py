"""물리 차량을 Backend 입차 세션과 차량 자격 정보에 연결하는 모듈(383 미해결분, T-16).

`ai/tracking/entry_event_intake.py`(383)의 `EntryEventIntake`/`ViolationMonitor`
매칭 로직을 이관한다. 데이터흐름.md §2("tracking")가 명시한 그대로,
`TrackingPipeline.process()` 내부에서 `EntityResolver` 다음·
`MotionEstimator` 전에 호출된다("입차 세션과 물리 차량 연결"이 tracking
자신의 책임이다) — `parking.zone_registry`/`parking.geometry`는 순수
데이터·함수라 이관 대상이지, `parking`의 파이프라인 객체를 부르는 게
아니다.

매칭 기준은 383과 동일하다: 차량 bbox가 ENTRY_EXIT 구역과
`entry_zone_min_overlap_ratio` 이상 겹치는 상태에서, 대기 중인 `EntryContext`
중 `entry_time`이 현재 시각 이전인 것들 가운데 **가장 이른 것**(삽입 순서가
아니라 실제 촬영 시각 순 — 비동기 처리로 순서가 뒤바뀌어도 정확히 매칭하기
위함)을 고른다.

한 번 매칭된 물리 차량은 이후 프레임에서도 같은 `VehicleContext`를 그대로
반환한다(캐시) — 위반 판정이 여러 프레임에 걸쳐 같은 자격 정보를 참조해야
하기 때문이다. `forget()`으로 캐시를 지우는 시점은 `MotionEstimator.forget()`과
같다: 물리 차량이 소실·종료됐을 때.

멱등키(Idempotency-Key) 중복 처리도 `EntryEventIntake`와 동일한 방식이다 —
라즈베리파이가 네트워크 재시도로 같은 이벤트를 다시 보내도 대기열에 중복
적재되지 않는다.

**미해결(383에서 이어짐, 이 티켓 범위 밖)**: `entry_match_window_seconds` 안에
매칭 못 하면 대기 이벤트를 조용히 버린다. 실패를 라즈베리파이에 알릴 방법도,
재시도도 없다.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime

from src.communication.models import EntryContext
from src.parking.geometry import overlap_ratio
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.models import BoundingBox, ParkingSessionId, PhysicalVehicleId, VehicleContext, VehicleId


class ContextMatcher:
    """대기 중인 입차 결과를 물리 차량에 시간순으로 매칭한다.

    `api` 라우터(별도 스레드풀에서 동시 요청을 처리하는 동기 핸들러)와
    `tracking` 루프가 같은 인스턴스를 공유하므로, 모든 공개 메서드를 락으로
    보호한다 — 그렇지 않으면 같은 Idempotency-Key로 온 동시 요청이 둘 다
    "처음 본 키"로 통과해 대기열에 중복 적재될 수 있다.
    """

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        entry_zone_min_overlap_ratio: float = 0.40,
        entry_match_window_seconds: float = 10.0,
        max_remembered_idempotency_keys: int = 1000,
    ) -> None:
        if max_remembered_idempotency_keys < 1:
            raise ValueError(
                f"max_remembered_idempotency_keys는 1 이상이어야 합니다: {max_remembered_idempotency_keys}"
            )
        self._entry_zones: tuple[ParkingZone, ...] = tuple(
            zone for zone in zones.all() if zone.zone_type is ZoneType.ENTRY_EXIT
        )
        self._entry_zone_min_overlap_ratio = entry_zone_min_overlap_ratio
        self._entry_match_window_seconds = entry_match_window_seconds
        self._max_remembered_idempotency_keys = max_remembered_idempotency_keys
        self._pending: list[EntryContext] = []
        self._matched: dict[PhysicalVehicleId, VehicleContext] = {}
        # dict를 삽입 순서 유지되는 set처럼 쓴다(값은 안 씀) — 가장 오래된
        # 항목부터 버리는 경계 있는 캐시로, 무제한 메모리 증가를 막는다.
        self._seen_idempotency_keys: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def add_entry_context(self, entry_context: EntryContext, *, idempotency_key: str) -> bool:
        """입차 결과 하나를 매칭 대기열에 추가한다.

        반환값: 실제로 새로 추가했으면 True, 이미 처리한 idempotency_key라
        무시했으면 False.
        """

        with self._lock:
            if idempotency_key in self._seen_idempotency_keys:
                return False
            self._pending.append(entry_context)
            self._remember(idempotency_key)
            return True

    def prune_expired(self, now: datetime) -> None:
        """시간창을 넘긴 대기 이벤트를 버린다. 매칭 시도 여부와 무관하게 매
        프레임 호출해야 한다 — 그 구역 근처로 신규 트랙이 한동안 안 생기면
        오래된 미매칭 이벤트가 무한정 쌓인다."""

        with self._lock:
            self._pending = [
                entry_context
                for entry_context in self._pending
                if (now - entry_context.entry_time).total_seconds() <= self._entry_match_window_seconds
            ]

    def match(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        bbox: BoundingBox,
        now: datetime,
    ) -> VehicleContext | None:
        """물리 차량 하나에 대해 이번 프레임의 `VehicleContext`를 반환한다.

        이미 매칭된 적이 있으면 캐시된 값을 그대로 반환한다(재매칭 시도 안
        함). 아직 없고 bbox가 ENTRY_EXIT 구역과 충분히 겹치면 대기 이벤트
        중 가장 이른 것을 매칭한다. 매칭 못 하면 `None`이다 — 다음 프레임에
        재시도된다.
        """

        with self._lock:
            cached = self._matched.get(physical_vehicle_id)
            if cached is not None:
                return cached
            if not self._entry_zones:
                return None

            in_entry_zone = any(
                overlap_ratio(zone.polygon, bbox) >= self._entry_zone_min_overlap_ratio
                for zone in self._entry_zones
            )
            if not in_entry_zone:
                return None

            eligible = sorted(
                (entry_context for entry_context in self._pending if entry_context.entry_time <= now),
                key=lambda entry_context: entry_context.entry_time,
            )
            if not eligible:
                return None

            matched_context = eligible[0]
            self._pending.remove(matched_context)
            context = VehicleContext(
                parking_session_id=(
                    None if matched_context.session_id is None else ParkingSessionId(matched_context.session_id)
                ),
                vehicle_id=None if matched_context.vehicle_id is None else VehicleId(matched_context.vehicle_id),
                is_electric=matched_context.is_electric,
                is_disabled_vehicle=matched_context.is_disabled_vehicle,
            )
            self._matched[physical_vehicle_id] = context
            return context

    def forget(self, physical_vehicle_id: PhysicalVehicleId) -> None:
        """소실·종료된 물리 차량의 매칭 캐시를 지운다."""

        with self._lock:
            self._matched.pop(physical_vehicle_id, None)

    def _remember(self, idempotency_key: str) -> None:
        self._seen_idempotency_keys[idempotency_key] = None
        if len(self._seen_idempotency_keys) > self._max_remembered_idempotency_keys:
            self._seen_idempotency_keys.popitem(last=False)
