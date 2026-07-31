"""Jetson 위반 판정 베이스라인의 순수 로직 테스트.

`jetson_vehicle_tracking_baseline.py`가 프로덕션 코드와 이 테스트 모음을 한
파일에 담고 있었다(4,264줄 중 2,269줄이 테스트). 판정 상태 기계를 수정할 때
결함이 반복해서 빠져나간 원인이 그 크기였으므로 테스트를 분리한다(409).

카메라·모델 없이 도는 순수 로직 테스트다. `conftest.py`가 `ai/tracking`을
`sys.path`에 넣으므로 베이스라인을 모듈명 그대로 import한다.

`_home_zone_overlap`/`_polygon_area`는 비공개 함수지만 여기서 직접 부른다 —
이 파일은 베이스라인의 화이트박스 테스트이고, 두 함수의 경계 동작(스팟형
구역 선택, shoelace 면적)은 공개 API만으로는 좁혀서 검증할 수 없다.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from jetson_vehicle_tracking_baseline import (
    BaselineError,
    BoundingBox,
    CapturedFrame,
    EntryEvent,
    NormalizedPolygon,
    ParkingZone,
    UltralyticsVehicleTracker,
    VehicleBox,
    ViolationEvent,
    ViolationMonitor,
    ViolationStatus,
    ZoneOverlap,
    ZoneRegistry,
    ZoneType,
    _home_zone_overlap,
    _polygon_area,
    classify_violation,
    classify_zone_overlaps,
    overlap_ratio,
    to_jsonable,
    zone_coverage_ratio,
)


class _FakeImage:
    """테스트에서 프레임 크기만 흉내 내는 최소 이미지 스텁."""

    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape


class BaselineLogicTests(unittest.TestCase):
    """카메라·모델 없이 실행하는 순수 판정 로직 회귀 테스트."""

    _ZONE_IDS: dict[str, int] = {}

    @classmethod
    def make_zone(
        cls,
        zone_number: str,
        zone_type: ZoneType,
        points: Sequence[tuple[float, float]],
        *,
        allowed_minutes: float | None = None,
    ) -> ParkingZone:
        """테스트용 구역 하나. zone_id는 zone_number당 하나로 안정적으로 발급한다.

        같은 zone_number면 항상 같은 zone_id가 나와야 한다 — 테스트가 여러
        레지스트리를 만들어도 구역 동일성이 유지되어야 하기 때문이다.
        """

        zone_id = cls._ZONE_IDS.setdefault(zone_number, len(cls._ZONE_IDS) + 1)
        return ParkingZone(
            zone_id=zone_id,
            zone_number=zone_number,
            zone_type=zone_type,
            polygon=NormalizedPolygon(tuple(points)),
            allowed_minutes=allowed_minutes,
        )

    def test_polygon_area_of_square(self) -> None:
        polygon = NormalizedPolygon(((0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)))
        self.assertAlmostEqual(_polygon_area(polygon.points), 0.04)

    def test_overlap_ratio_full_containment(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.2, 0.2, 0.4, 0.4)
        self.assertAlmostEqual(overlap_ratio(zone.polygon, bbox), 1.0)

    def test_overlap_ratio_no_overlap(self) -> None:
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)])
        bbox = BoundingBox(0.5, 0.5, 0.7, 0.7)
        self.assertEqual(overlap_ratio(zone.polygon, bbox), 0.0)

    def test_overlap_ratio_half_overlap(self) -> None:
        zone = self.make_zone("GEN-02", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)])
        bbox = BoundingBox(0.1, 0.0, 0.3, 0.2)
        self.assertAlmostEqual(overlap_ratio(zone.polygon, bbox), 0.5)

    def test_zone_coverage_ratio_full_containment_regardless_of_bbox_size(self) -> None:
        """리뷰에서 발견된 회귀 시나리오: 작은 구역을 훨씬 큰 바운딩박스가 완전히
        덮어도(트럭이 오토바이 스팟을 덮는 경우), 구역 자기 면적 기준이므로
        100%로 나와야 한다 — 기존 overlap_ratio(차체 기준)로는 7.1%밖에 안 됐다."""
        moto_spot = self.make_zone("GEN-MOTO", ZoneType.GENERAL, [(0.10, 0.10), (0.15, 0.10), (0.15, 0.20), (0.10, 0.20)])
        truck_bbox = BoundingBox(0.06, 0.05, 0.40, 0.25)  # moto_spot을 완전히 포함
        self.assertAlmostEqual(zone_coverage_ratio(moto_spot, truck_bbox), 1.0)

    def test_zone_coverage_ratio_partial_overlap(self) -> None:
        spot = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        intruding_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)  # spot 안쪽 0.15 + 바깥쪽 0.04
        self.assertAlmostEqual(zone_coverage_ratio(spot, intruding_bbox), 0.75)

    def test_zone_coverage_ratio_no_overlap(self) -> None:
        spot = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        far_bbox = BoundingBox(0.50, 0.50, 0.70, 0.70)
        self.assertEqual(zone_coverage_ratio(spot, far_bbox), 0.0)

    def test_restricted_zone_flagged_after_min_dwell(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.RESTRICTED_ZONE)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "DIS-01")

    def test_observing_before_min_dwell(self) -> None:
        zone = self.make_zone("EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=100.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)

    def test_ev_overstay_flagged_after_allowed_minutes_exceeded(self) -> None:
        """EV 충전구역에 allowed_minutes(구역별 허용 점유 시간, 분)를 넘겨 정차하면
        RESTRICTED_ZONE이 아니라 EV_OVERSTAY로 판정한다(요구사항 정의서.md:25,
        ERD.md:119-125, ERD.md의 parking_zones.allowed_minutes)."""
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=120.0
        )
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(
            overlaps, dwell_seconds=120.0 * 60.0, min_dwell_seconds=600.0
        )
        self.assertEqual(status, ViolationStatus.EV_OVERSTAY)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "EV-01")

    def test_ev_overstay_not_flagged_before_allowed_minutes_exceeded(self) -> None:
        """allowed_minutes를 아직 안 넘겼으면(최소 정차 시간은 넘겼어도) 여전히
        RESTRICTED_ZONE이다 — EV_OVERSTAY는 등록 여부 판정을 대체하지 않고,
        시간 초과일 때만 더 구체적인 상태로 대체한다."""
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=120.0
        )
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.RESTRICTED_ZONE)

    def test_ev_overstay_boundary_at_exact_allowed_minutes(self) -> None:
        """경계값 테스트: dwell_seconds가 allowed_minutes*60과 정확히 같으면
        EV_OVERSTAY로 확정하고, 그 직전(1ms 미만)에는 아직 RESTRICTED_ZONE이다
        (다른 경계값들과 동일하게 `>=` 기준 — OUT_OF_ZONE 317번 MR 리뷰에서
        요청받았던 경계값 검증 패턴을 그대로 적용)."""
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=2.0
        )
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)

        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=119.999, min_dwell_seconds=10.0)
        self.assertEqual(status, ViolationStatus.RESTRICTED_ZONE)

        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=120.0, min_dwell_seconds=10.0)
        self.assertEqual(status, ViolationStatus.EV_OVERSTAY)

    def test_ev_overstay_bypasses_min_dwell_gate_when_allowed_minutes_is_smaller(self) -> None:
        """운영 설정 실수 대비 문서화 테스트: `min_dwell_seconds`(정착 확정 시간)가
        어떤 EV 구역의 `allowed_minutes*60`보다 크게 설정되면, 그 구역은
        min_dwell_seconds에 도달하기 전이라도 EV_OVERSTAY로 확정된다
        (allowed_minutes는 min_dwell_seconds보다 크게 설정하는 게 정상
        사용법이다).

        기대값이 바뀐 이유(319 리뷰 C-1): 예전에는 최소 정차 시간 게이트가
        EV 시간 초과 판정보다 앞서서 이 설정에서 OBSERVING으로 '지연'됐다.
        그런데 게이트가 쓰는 dwell_seconds는 "연속 무이동 시간"이라 미세 이동이
        min_dwell_seconds보다 잦으면 영영 게이트를 못 넘어, 2시간을 점유해도
        EV_OVERSTAY가 발화하지 않는다(현장 상시 발생). 그래서 EV 시간 초과
        판정을 게이트 앞으로 옮겼다 — 허용 시간을 넘긴 점유는 그 자체로
        "정착했다"는 판단에 충분하기 때문이다.

        그 결과 여기서 검증하던 '지연'은 더 이상 일어나지 않는다. 운영값
        (allowed_minutes 60~120분 > min_dwell_seconds 10분)에서는 애초에
        도달할 수 없는 조합이고, 이 조합 자체가 설정 오류다 — 설정 검증은
        별도 지적사항(I-1)에서 다룬다. 테스트는 지우지 않고 "이 설정에서
        게이트가 무력화된다"는 현재 동작을 그대로 고정해 둔다.
        """
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=2.0
        )  # allowed_minutes*60 = 120초
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)

        # allowed_minutes(120초)는 넘었고 min_dwell_seconds(600초)는 미달 — 게이트보다
        # EV 시간 초과가 앞서므로 지연 없이 EV_OVERSTAY로 확정된다
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=200.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.EV_OVERSTAY)

        # 둘 다 넘으면 당연히 EV_OVERSTAY
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.EV_OVERSTAY)

        # 허용 시간에 미달하면 게이트가 정상 작동해 여전히 OBSERVING이다 —
        # 게이트 자체가 없어진 게 아니라 EV 시간 초과만 앞으로 나온 것이다.
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=100.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)

    def test_ev_overstay_not_flagged_when_allowed_minutes_unset(self) -> None:
        """allowed_minutes가 설정 안 된 EV 구역은 아무리 오래 정차해도 여전히
        RESTRICTED_ZONE이다(허용 시간 기준이 없으면 시간 초과를 판단할 수 없음)."""
        zone = self.make_zone("EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=100000.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.RESTRICTED_ZONE)

    def test_ev_overstay_applies_to_ev_slow_zone(self) -> None:
        """완속 충전구역(EV_SLOW)도 급속(EV_FAST)과 똑같이 시간 초과를 판정한다.

        기존 테스트가 EV_FAST만 다뤄서, EV 구역 집합에서 EV_SLOW를 빼도 전부
        통과하는 상태였다(319 리뷰 §8).
        """
        zone = self.make_zone(
            "EV-02", ZoneType.EV_SLOW, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=120.0
        )
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, hit_zone, _ratio = classify_violation(
            overlaps, dwell_seconds=7300.0, min_dwell_seconds=600.0
        )
        self.assertEqual(status, ViolationStatus.EV_OVERSTAY)
        self.assertEqual(hit_zone.zone_number, "EV-02")

    def test_zone_registry_from_file_accepts_all_zone_types(self) -> None:
        """zones 파일이 담을 수 있는 zone_type 6종을 고정하고, 백엔드 현행 구현이
        쓰는 EV_CHARGING은 거부한다는 것을 명시한다.

        `GET /api/hw/parking-zones`가 아직 Not started라 실제 응답과 대조하는
        테스트는 만들 수 없다(319 리뷰 C-2). 그 API가 생기기 전까지 이 테스트가
        계약의 유일한 기계적 고정점이다.
        """
        expected = ["GENERAL", "DISABLED", "EV_FAST", "EV_SLOW", "AISLE", "ENTRY_EXIT"]
        self.assertEqual(sorted(item.value for item in ZoneType), sorted(expected))

        square = [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]]
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": index + 1,
                                "zoneNumber": f"Z-{index}",
                                "zoneType": value,
                                "polygon": square,
                            }
                            for index, value in enumerate(expected)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = ZoneRegistry.from_file(path)
            self.assertEqual(len(registry.all()), len(expected))

            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {"zoneId": 1, "zoneNumber": "EV-01", "zoneType": "EV_CHARGING", "polygon": square}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_ev_overstay_not_applicable_to_disabled_zone(self) -> None:
        """장애인 구역(DISABLED)은 EV_OVERSTAY 대상이 아니다 — allowed_minutes가
        설정돼 있어도(예: 백엔드가 일괄 기본값을 넣은 경우) 무시하고 RESTRICTED_ZONE."""
        zone = self.make_zone(
            "DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=1.0
        )
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=100000.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.RESTRICTED_ZONE)

    def test_out_of_zone_flagged_after_min_dwell_with_no_zone_overlap(self) -> None:
        """등록된 구역 어디에도 겹치지 않고 스팟 침범도 아니면, 최소 정차
        시간 이후 OUT_OF_ZONE으로 판정한다(요구사항 정의서.md:25, ERD.md:119-125)."""
        status, zone_hit, ratio = classify_violation([], dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OUT_OF_ZONE)
        self.assertIsNone(zone_hit)
        self.assertEqual(ratio, 0.0)

    def test_out_of_zone_observing_before_min_dwell(self) -> None:
        """구역 겹침이 전혀 없어도, 최소 정차 시간을 채우기 전에는 다른
        위반들과 동일하게 OBSERVING으로만 표시하고 OUT_OF_ZONE으로 확정하지 않는다."""
        status, zone_hit, _ratio = classify_violation([], dwell_seconds=100.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)
        self.assertIsNone(zone_hit)

    def test_out_of_zone_boundary_at_exact_min_dwell(self) -> None:
        """dwell_seconds가 min_dwell_seconds와 정확히 같으면(리뷰 반영, 경계값
        테스트), 다른 위반 판정들과 동일하게 '미달'이 아니므로 OUT_OF_ZONE으로 확정한다."""
        status, _zone, _ratio = classify_violation([], dwell_seconds=600.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OUT_OF_ZONE)

        status, _zone, _ratio = classify_violation([], dwell_seconds=599.999, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)

    def test_out_of_zone_not_flagged_when_intruded_zone_present(self) -> None:
        """구역 겹침(overlaps)은 없어도 spot_intrusion_ratio 기준 침범(intruded_zone)이
        있으면, 그건 OUT_OF_ZONE이 아니라 LINE_CROSS 판정으로 이어져야 한다."""
        gen = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        intruded_zone = ZoneOverlap(gen, 0.5)
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, intruded_zone=intruded_zone
        )
        self.assertEqual(status, ViolationStatus.LINE_CROSS)

    def test_out_of_zone_not_flagged_when_blocked_zone_present(self) -> None:
        """리뷰 반영(I-5): intruded_zone과 대칭 — overlaps가 비어도 blocked_zone이
        있으면 OUT_OF_ZONE이 아니라 DOUBLE_PARK여야 한다."""
        gen = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=ZoneOverlap(gen, 0.5)
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)

    def test_out_of_zone_not_flagged_when_in_ignored_zone(self) -> None:
        """리뷰 반영(C-1): 판정 제외 구역(ENTRY_EXIT 등) 안에 있다는 신호가
        오면, overlaps가 비어 있어도 OUT_OF_ZONE이 아니라 기존과 동일하게
        NONE으로 유지한다."""
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, in_ignored_zone=True
        )
        self.assertEqual(status, ViolationStatus.NONE)

    def test_out_of_zone_not_flagged_when_intrusion_deferred(self) -> None:
        """리뷰 반영(C-2): 다른 트랙의 정착 미확정으로 침범 판정이 보류
        중이라는 신호가 오면, overlaps가 비어 있어도 OUT_OF_ZONE으로
        확정하지 않고 기존과 동일하게 NONE으로 유지한다."""
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, deferred_intrusion=True
        )
        self.assertEqual(status, ViolationStatus.NONE)

    def test_line_cross_uses_intruded_zone(self) -> None:
        """LINE_CROSS는 이제 classify_zone_overlaps의 len(overlaps)>=2가 아니라
        호출부가 넘겨주는 intruded_zone(빈 스팟 침범)으로 판정한다."""
        gen1 = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        gen2 = self.make_zone("GEN-02", ZoneType.GENERAL, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.3), (0.2, 0.3)])
        bbox = BoundingBox(0.1, 0.0, 0.3, 0.3)
        overlaps = classify_zone_overlaps(bbox, [gen1], min_overlap_ratio=0.40)  # 내 홈(GEN-01)만
        intruded_zone = ZoneOverlap(gen2, 0.5)  # GEN-02를 50% 침범(구역 면적 기준)
        status, zone, ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, intruded_zone=intruded_zone
        )
        self.assertEqual(status, ViolationStatus.LINE_CROSS)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-02")
        self.assertAlmostEqual(ratio, 0.5)

    def test_monitor_line_cross_when_intruded_spot_is_empty(self) -> None:
        """차 한 대가 혼자 두 스팟에 걸쳐 주차했는데, 침범한 쪽 스팟이 비어있으면
        DOUBLE_PARK가 아니라 LINE_CROSS로 판정한다(피해자가 없으므로)."""
        gen1 = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        gen2 = self.make_zone("GEN-02", ZoneType.GENERAL, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.3), (0.2, 0.3)])
        registry = ZoneRegistry([gen1, gen2])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        straddling_bbox = BoundingBox(0.1, 0.0, 0.3, 0.3)  # GEN-01/GEN-02 각각 50%

        monitor.update(
            [VehicleBox(track_id=1, bbox=straddling_bbox, confidence=0.9, frame_id=0, captured_at=base_time)]
        )
        events_at_min_dwell = monitor.update(  # 정차 시간이 처음 5초를 넘기는 프레임에서 이벤트가 발행된다
            [VehicleBox(track_id=1, bbox=straddling_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6))]
        )
        events_after = monitor.update(  # 같은 상태가 계속되면 중복 발행하지 않는다
            [VehicleBox(track_id=1, bbox=straddling_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12))]
        )
        self.assertEqual(len(events_at_min_dwell), 1)
        self.assertEqual(events_at_min_dwell[0].status, ViolationStatus.LINE_CROSS)
        self.assertIn(events_at_min_dwell[0].zone_number, ("GEN-01", "GEN-02"))  # 홈이 아닌 쪽이 침범 구역으로 보고됨
        self.assertEqual(events_after, [])

    def test_aisle_block_takes_priority_over_restricted_zone(self) -> None:
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        disabled = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.2, 0.2, 0.5, 0.5)
        overlaps = classify_zone_overlaps(bbox, [aisle, disabled], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "AISLE-01")

    def test_home_zone_overlap_picks_spot_type_ignoring_aisle(self) -> None:
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        spot = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        overlaps = classify_zone_overlaps(bbox, [aisle, spot], min_overlap_ratio=0.40)
        home = _home_zone_overlap(overlaps)
        assert home is not None
        self.assertEqual(home.zone.zone_number, "GEN-01")

    def test_home_zone_overlap_none_when_only_aisle(self) -> None:
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        overlaps = classify_zone_overlaps(bbox, [aisle], min_overlap_ratio=0.40)
        self.assertIsNone(_home_zone_overlap(overlaps))

    def test_home_zone_overlap_none_when_no_overlaps(self) -> None:
        self.assertIsNone(_home_zone_overlap([]))

    def test_double_park_priority_between_aisle_and_restricted(self) -> None:
        victim_spot = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.6, 0.6), (0.9, 0.6), (0.9, 0.9), (0.6, 0.9)])
        blocked_zone = ZoneOverlap(victim_spot, 0.9)

        # 통행로 겹침이 있으면 이중주차보다 AISLE_BLOCK이 우선한다.
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        overlaps = classify_zone_overlaps(BoundingBox(0.2, 0.2, 0.5, 0.5), [aisle], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)

        # 전용구역 겹침만 있으면 이중주차가 그보다 우선한다(막힌 차량이 실존 피해자이므로).
        disabled = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        overlaps = classify_zone_overlaps(BoundingBox(0.2, 0.2, 0.5, 0.5), [disabled], min_overlap_ratio=0.40)
        status, zone, ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-01")  # 이제 피해 차량이 점유한 구역이 실제로 실린다
        self.assertAlmostEqual(ratio, 0.9)

        # 구역 겹침이 전혀 없어도 다른 차량의 홈 구역을 침범했으면 이중주차로 판정한다.
        status, zone, ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-01")
        self.assertAlmostEqual(ratio, 0.9)

        # 최소 정차 시간 미달이면 겹침이 있어도 아직 OBSERVING이다.
        status, zone, _ratio = classify_violation(
            [], dwell_seconds=10.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.OBSERVING)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-01")  # OBSERVING 중에도 어떤 구역이 위험한지 확인 가능

    def test_aisle_block_takes_priority_over_ev_overstay(self) -> None:
        """통행 방해가 EV 충전구역 시간 초과보다 우선한다(319 최종 리뷰, 사람 판단).

        기대값이 바뀐 이유: 이 브랜치가 한때 EV_OVERSTAY를 최상위로 올렸는데,
        점유 시계가 단조 증가하므로 한 번 열린 EV_OVERSTAY가 매 프레임 계속 이기고
        중복 판정 키 (status, zone_id)도 안 바뀌어, 그 뒤에 새로 시작된
        AISLE_BLOCK이 주차 세션 내내 영구히 보고되지 않았다(모니터 수준으로
        재현 확인 — test_monitor_aisle_block_reported_after_ev_overstay_opened).
        통행로 막힘은 소방 진입로·비상 통행 문제라 몇 시간을 놓칠 수 없어서
        우선순위를 원래대로 되돌렸다. 게이트 우회만 남긴다.

        따라서 통행로를 막고 있는 동안에는 EV_OVERSTAY가 가려지고, 차가 통행로에서
        빠지면 시간 초과는 그대로 남아 있으므로 그때 EV_OVERSTAY가 보고된다.
        """
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        ev_zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], allowed_minutes=2.0
        )
        bbox = BoundingBox(0.2, 0.2, 0.5, 0.5)
        overlaps = classify_zone_overlaps(bbox, [aisle, ev_zone], min_overlap_ratio=0.40)

        status, zone_hit, _ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, occupancy_seconds=700.0
        )
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "AISLE-01")

        # 시간 초과가 성립하든 안 하든 통행로가 걸려 있으면 AISLE_BLOCK이다.
        status, _zone_hit, _ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, occupancy_seconds=60.0
        )
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)

        # 통행로에서 빠지면 가려져 있던 시간 초과가 그대로 보고된다.
        ev_only = classify_zone_overlaps(bbox, [ev_zone], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(
            ev_only, dwell_seconds=700.0, min_dwell_seconds=600.0, occupancy_seconds=700.0
        )
        self.assertEqual(status, ViolationStatus.EV_OVERSTAY)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "EV-01")

    def test_double_park_takes_priority_over_ev_overstay(self) -> None:
        """이중주차가 EV 충전구역 시간 초과보다 우선한다(319 최종 리뷰, 사람 판단).

        기대값이 바뀐 이유는 위 test_aisle_block_takes_priority_over_ev_overstay와
        같다 — EV_OVERSTAY를 최상위로 올리면 한 번 열린 뒤 새로 시작된 DOUBLE_PARK가
        영구히 가려진다. 남의 스팟을 침범하고 있는 동안에는 DOUBLE_PARK로 보고되고,
        침범을 그치면 EV_OVERSTAY가 보고된다.
        """
        victim_spot = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.6, 0.6), (0.9, 0.6), (0.9, 0.9), (0.6, 0.9)])
        blocked_zone = ZoneOverlap(victim_spot, 0.9)
        ev_zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], allowed_minutes=2.0
        )
        overlaps = classify_zone_overlaps(BoundingBox(0.2, 0.2, 0.5, 0.5), [ev_zone], min_overlap_ratio=0.40)

        status, zone_hit, _ratio = classify_violation(
            overlaps,
            dwell_seconds=700.0,
            min_dwell_seconds=600.0,
            blocked_zone=blocked_zone,
            occupancy_seconds=700.0,
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "GEN-01")

        # 시간 초과가 성립하든 안 하든 남의 스팟을 침범 중이면 DOUBLE_PARK이다.
        status, _zone_hit, _ratio = classify_violation(
            overlaps,
            dwell_seconds=700.0,
            min_dwell_seconds=600.0,
            blocked_zone=blocked_zone,
            occupancy_seconds=60.0,
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)

        # 침범을 그치면 가려져 있던 시간 초과가 그대로 보고된다.
        status, zone_hit, _ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, occupancy_seconds=700.0
        )
        self.assertEqual(status, ViolationStatus.EV_OVERSTAY)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "EV-01")

    def test_monitor_aisle_block_reported_after_ev_overstay_opened(self) -> None:
        """319 최종 리뷰 회귀: EV_OVERSTAY가 이미 열린 뒤에 새로 시작된 통행 방해도
        보고돼야 한다.

        EV_OVERSTAY를 우선순위 최상위로 올렸을 때 발견된 결함이다. 점유 시계는
        단조 증가하므로 한 번 시간 초과가 성립하면 매 프레임 EV_OVERSTAY가 계속
        이기고, 중복 판정 키 (status, zone_id)도 (EV_OVERSTAY, EV-01)에서 안 바뀌어
        새 이벤트가 나가지 않는다 — 그 결과 그 뒤에 차가 통행로를 막기 시작해도
        주차 세션이 끝날 때까지 AISLE_BLOCK이 영구히 보고되지 않았다.

        홈 구역(`_home_zone_overlap`)은 스팟형 구역만 보므로 차가 통행로 쪽으로
        옮겨가도 홈은 EV-01로 유지되고 점유 시계는 리셋되지 않는다 — 즉 시간 초과가
        계속 성립하는 상태로 통행로 겹침이 새로 생기는, 정확히 문제가 되는 배치다.
        """
        ev_zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)], allowed_minutes=1.0
        )
        aisle = self.make_zone("AISLE-1", ZoneType.AISLE, [(0.4, 0.0), (1.0, 0.0), (1.0, 0.4), (0.4, 0.4)])
        monitor = ViolationMonitor(
            ZoneRegistry([ev_zone, aisle]),
            min_overlap_ratio=0.40,
            min_dwell_seconds=10.0,
            movement_epsilon=0.01,
        )
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
        # EV-01 안에만 있는 위치(통행로 겹침 0).
        inside_ev = BoundingBox(0.05, 0.05, 0.35, 0.35)
        # EV-01과 AISLE-1에 각각 절반씩(0.5 >= min_overlap_ratio) 걸치는 위치.
        # 홈 구역은 여전히 EV-01뿐이다 — 통행로는 스팟형이 아니다.
        over_aisle = BoundingBox(0.25, 0.05, 0.55, 0.35)

        def frame(seconds: int, bbox: BoundingBox) -> list[ViolationEvent]:
            return monitor.update([
                VehicleBox(
                    track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                    captured_at=base_time + timedelta(seconds=seconds),
                )
            ])

        self.assertEqual(frame(0, inside_ev), [])  # 최소 정차 시간 미달
        restricted_events = frame(10, inside_ev)
        self.assertEqual([event.status for event in restricted_events], [ViolationStatus.RESTRICTED_ZONE])
        self.assertEqual(restricted_events[0].zone_number, "EV-01")

        overstay_events = frame(61, inside_ev)  # allowed_minutes 1.0 = 60초 초과
        self.assertEqual([event.status for event in overstay_events], [ViolationStatus.EV_OVERSTAY])
        self.assertEqual(overstay_events[0].zone_number, "EV-01")

        # 여기서부터가 회귀 대상: 시간 초과가 계속 성립하는 채로 통행로를 막기 시작한다.
        aisle_events = frame(70, over_aisle)
        self.assertEqual([event.status for event in aisle_events], [ViolationStatus.AISLE_BLOCK])
        self.assertEqual(aisle_events[0].zone_number, "AISLE-1")
        # 점유 시계는 리셋되지 않았다(홈 구역이 EV-01로 유지) — 즉 EV_OVERSTAY가
        # 여전히 성립하는데도 AISLE_BLOCK이 이겼다는 뜻이다.
        self.assertGreaterEqual(aisle_events[0].occupancy_seconds, 60.0)

        self.assertEqual(frame(80, over_aisle), [])  # 같은 사건이 계속 열려 있으므로 중복 발행 없음

        # 통행로에서 빠지면 가려져 있던 EV_OVERSTAY가 다시 보고된다.
        back_events = frame(300, inside_ev)
        self.assertEqual([event.status for event in back_events], [ViolationStatus.EV_OVERSTAY])
        self.assertEqual(back_events[0].zone_number, "EV-01")

    def test_monitor_double_park_flags_whoever_intrudes_regardless_of_arrival_order(self) -> None:
        """리뷰에서 발견된 회귀: 먼저 온 차가 실제로 옆 칸(나중에 온 차의 자리)을
        침범했다면, 시간순이 아니라 누가 실제로 침범했는지로 판정해야 한다.
        옛 로직은 '나중에 온 차만 가해자'였어서, 제대로 주차한 나중 차가 억울하게
        잡히고 실제 침범자(먼저 온 차)는 절대 안 잡혔다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.20, 0.0), (0.40, 0.0), (0.40, 0.3), (0.20, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        # 먼저 온 차(track 1)가 자기 칸(GEN-A)을 벗어나 GEN-B로 침범해서 나쁘게 주차
        intruder_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)
        # 나중에 온 차(track 2)는 자기 칸(GEN-B) 안에 올바르게 주차
        victim_bbox = BoundingBox(0.24, 0.0, 0.38, 0.3)

        monitor.update([VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        # track 2(피해자)는 아직 정착 전(리뷰 반영: 이 프레임엔 GEN-B 점유 여부가
        # 불확실하므로 LINE_CROSS로 잘못 보고되면 안 되고, 아무 이벤트도 없어야 한다)
        events_before_victim_settles = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
            ]
        )
        self.assertEqual(events_before_victim_settles, [])

        events = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 1)  # 먼저 왔지만 실제로 침범한 쪽(track 1)이 잡힌다
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-B")  # 침범당한 구역이 실제로 실린다

    def test_monitor_no_line_cross_to_double_park_flap_while_victim_settles(self) -> None:
        """리뷰에서 발견된 회귀: 침입자가 피해자보다 먼저 정착 완료(min_dwell 도달)
        하면, 피해자가 아직 정착 전인 짧은 구간 동안 그 구역이 "비어있는 것"으로
        오인되어 LINE_CROSS 이벤트가 먼저 발행됐다가, 피해자가 정착하는 순간
        DOUBLE_PARK로 다시 발행되는 이벤트 중복(플래핑)이 있었다. 이제는 아직
        아무도 정착하지 못한 구역은 판정을 보류해서, LINE_CROSS 없이 DOUBLE_PARK
        하나만 발행돼야 한다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.20, 0.0), (0.40, 0.0), (0.40, 0.3), (0.20, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        intruder_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)  # GEN-A가 홈, GEN-B를 20% 침범
        victim_bbox = BoundingBox(0.24, 0.0, 0.38, 0.3)

        monitor.update([VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=0, captured_at=base_time)])

        # 침입자는 정착 완료(dwell 6≥5), 피해자는 방금 등장(dwell 0<5) — GEN-B
        # 점유 여부가 아직 불확실한 구간. LINE_CROSS가 잘못 발행되면 안 된다.
        events_while_victim_unsettled = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
            ]
        )
        self.assertEqual(events_while_victim_unsettled, [])

        events_after_victim_settles = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
            ]
        )
        self.assertEqual(len(events_after_victim_settles), 1)  # DOUBLE_PARK 딱 한 번만 발행(LINE_CROSS 거치지 않음)
        self.assertEqual(events_after_victim_settles[0].track_id, 1)
        self.assertEqual(events_after_victim_settles[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events_after_victim_settles[0].zone_number, "GEN-B")

    def test_monitor_double_park_catches_large_vehicle_intruding_small_spot(self) -> None:
        """리뷰에서 발견된 회귀: 가해 차량이 피해 차량보다 훨씬 크면(트럭이 오토바이
        스팟을 덮는 경우), 옛 방식(차량 대 차량 비교, 가해 차량 자신이 분모)은
        가해 차량 면적이 커서 비율이 낮게 나와 못 잡았다. 이제는 피해 차량이
        점유한 구역 면적이 분모라 가해 차량 크기와 무관하게 잡힌다."""
        moto_spot = self.make_zone("GEN-MOTO", ZoneType.GENERAL, [(0.10, 0.10), (0.15, 0.10), (0.15, 0.20), (0.10, 0.20)])
        registry = ZoneRegistry([moto_spot])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        moto_bbox = BoundingBox(0.10, 0.10, 0.15, 0.20)  # 자기 스팟에 정확히 주차
        truck_bbox = BoundingBox(0.06, 0.05, 0.40, 0.25)  # 몸집이 훨씬 큰 트럭이 스팟을 완전히 덮음

        monitor.update([VehicleBox(track_id=1, bbox=moto_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=moto_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=truck_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 2)
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-MOTO")

    def test_monitor_double_park_not_flagged_when_victim_has_no_home_zone(self) -> None:
        """피해 후보가 어떤 스팟 구역과도 40% 이상 안 겹치는 애매한 위치에 있으면
        (홈 구역이 없으면), 그 차를 기준으로 다른 차를 이중주차로 판정하지 않는다.

        (리뷰 반영, I-3) 두 차량 다 등록 구역(GEN-A)과 전혀 안 겹치는 위치라
        각자 독립적으로 정착 시점에 OUT_OF_ZONE이 한 번씩 발행된다(track 1은
        6초째, track 2는 자신의 정착 시점인 12초째) — 루프의 마지막
        `update()` 반환값만 보면 track 2 것만 보이므로, 전체 프레임에 걸쳐
        발행된 이벤트를 다 모아서 정확히 단정한다. 핵심은 어느 프레임에서도
        DOUBLE_PARK는 절대 나오면 안 된다는 것이다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        registry = ZoneRegistry([spot_a])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        ambiguous_bbox = BoundingBox(0.50, 0.50, 0.70, 0.70)  # 어떤 구역과도 안 겹침
        overlapping_bbox = BoundingBox(0.55, 0.55, 0.75, 0.75)  # ambiguous_bbox와 상당히 겹침

        monitor.update([VehicleBox(track_id=1, bbox=ambiguous_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        all_events: list[ViolationEvent] = []
        for seconds in (6, 12):
            all_events.extend(
                monitor.update(
                    [
                        VehicleBox(track_id=1, bbox=ambiguous_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                        VehicleBox(track_id=2, bbox=overlapping_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    ]
                )
            )

        self.assertEqual(
            [(event.track_id, event.status) for event in all_events],
            [(1, ViolationStatus.OUT_OF_ZONE), (2, ViolationStatus.OUT_OF_ZONE)],
        )

    def test_monitor_double_park_respects_custom_threshold(self) -> None:
        """spot_intrusion_ratio를 높이면 약한 침범(20%)은 더 이상 안 잡힌다 —
        임계값이 실제로 동작함을 확인."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.20, 0.0), (0.40, 0.0), (0.40, 0.3), (0.20, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.40)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        intruder_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)  # GEN-B를 20%만 침범(0.40 임계값 미달)
        victim_bbox = BoundingBox(0.24, 0.0, 0.38, 0.3)

        monitor.update([VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        self.assertEqual(events, [])

    def test_monitor_double_park_correctly_parked_vehicle_not_blamed_when_sharing_home_zone(self) -> None:
        """리뷰에서 발견된 Critical 회귀: 두 차량의 홈 구역 판정이 우연히 같은
        스팟(경계선 근처 타이)으로 겹칠 때, 그 스팟에 제대로(거의 전부) 주차한
        차량까지 침범자로 몰리면 안 된다 — 점유율이 더 낮은 쪽(track 1, 경계선에
        걸친 차)만 침범자여야 하고, 점유율이 더 높은 쪽(track 2, 자기 자리에
        똑바로 주차)은 절대 잡히면 안 된다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.3), (0.2, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        straddler_bbox = BoundingBox(0.14, 0.0, 0.26, 0.3)  # GEN-A/GEN-B 경계에 걸쳐 있음(사실상 타이)
        correct_bbox = BoundingBox(0.28, 0.0, 0.38, 0.3)  # GEN-B 안에 온전히 들어간 정상 주차

        monitor.update([VehicleBox(track_id=1, bbox=straddler_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])
        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=straddler_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=correct_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        flagged_ids = {event.track_id for event in events}
        self.assertNotIn(2, flagged_ids, "제대로 주차한 차량은 절대 침범자로 잡히면 안 된다")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 1)
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-B")

    def test_monitor_double_park_only_lower_occupancy_side_blamed_when_sharing_one_spot(self) -> None:
        """한 스팟을 두 차가 나눠 점유하는 상황(진짜 겹주차)에서는, 그 스팟을 거의
        온전히 차지한 차(occupancy ratio ~1.0)가 아니라 절반만 걸친 차(occupancy
        ratio ~0.5)만 침범자로 잡혀야 한다 — 둘 다 잡히거나 둘 다 안 잡히면 안 된다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([spot_a])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        mostly_inside_bbox = BoundingBox(0.02, 0.02, 0.28, 0.28)  # 스팟 안에 거의 전부(ratio ~1.0)
        half_inside_bbox = BoundingBox(0.15, 0.0, 0.45, 0.3)  # 스팟에 절반만(ratio ~0.5)

        monitor.update([VehicleBox(track_id=1, bbox=mostly_inside_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])
        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=mostly_inside_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=half_inside_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 2)  # 점유율이 더 낮은 쪽만 침범자
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-A")

    def test_entry_exit_zone_ignored_for_parking_violation(self) -> None:
        entry = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.2, 0.2, 0.5, 0.5)
        overlaps = classify_zone_overlaps(bbox, [entry], min_overlap_ratio=0.40)
        self.assertEqual(overlaps, [])

    def test_monitor_emits_violation_once_then_suppresses_duplicates(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        first = VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)
        second = VehicleBox(
            track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=2)
        )
        third = VehicleBox(
            track_id=1, bbox=bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=4)
        )

        events_first = monitor.update([first])
        events_second = monitor.update([second])
        events_third = monitor.update([third])

        self.assertEqual(len(events_first), 0)  # 최소 정차 시간(1초) 미달로 아직 OBSERVING
        self.assertEqual(len(events_second), 1)
        self.assertEqual(events_second[0].status, ViolationStatus.RESTRICTED_ZONE)
        self.assertEqual(len(events_third), 0)  # 같은 위반이 계속 열려 있으므로 중복 발행하지 않음

    def test_monitor_ev_overstay_escalates_from_restricted_zone_without_duplicate(self) -> None:
        """전기차 구역에 정착하면 먼저 RESTRICTED_ZONE이 발행되고(등록 여부 확인 필요),
        allowed_minutes를 넘기면 같은 트랙 상태가 자동으로 EV_OVERSTAY로 한 번만
        갱신 발행된다(같은 물리적 상황에 대해 중복 발행되지 않음)."""
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=0.05
        )  # 0.05분 = 3초, 테스트를 짧게 유지하기 위한 값
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        events_at = {}
        for seconds in (0, 2, 4, 6):
            events_at[seconds] = monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds))]
            )

        self.assertEqual(len(events_at[0]), 0)  # 최소 정차 시간(1초) 미달, OBSERVING
        self.assertEqual([e.status for e in events_at[2]], [ViolationStatus.RESTRICTED_ZONE])  # 정착 -> RESTRICTED_ZONE
        self.assertEqual([e.status for e in events_at[4]], [ViolationStatus.EV_OVERSTAY])  # allowed_minutes(3초) 초과 -> EV_OVERSTAY로 갱신
        self.assertEqual(len(events_at[6]), 0)  # 같은 EV_OVERSTAY가 계속 열려있으므로 중복 없음

    def test_monitor_ev_overstay_survives_brief_occlusion_beyond_track_grace(self) -> None:
        """리뷰 반영(C-1/319): track_grace_seconds(짧게 유지, 다른 차의 스팟 회전을
        위해)를 넘기는 순간적 가림이 있어도, dwell_reunification_seconds 이내
        재등장이면 정차 시작 시각이 리셋되지 않아 EV_OVERSTAY가 정확한 누적
        시간에 발행된다 — 수정 전에는 3초짜리 가림 한 번으로 dwell이 통째로
        리셋돼 RESTRICTED_ZONE이 중복 발행되고 EV_OVERSTAY는 가림이 끝난
        시점부터 다시 카운트가 시작돼 지연/누락됐다(재현으로 확인됨)."""
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=1.0
        )  # 1분 = 60초
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry,
            min_overlap_ratio=0.40,
            min_dwell_seconds=10.0,
            movement_epsilon=0.01,
            track_grace_seconds=2.0,
        )
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        other_bbox = BoundingBox(0.60, 0.60, 0.80, 0.80)  # 항상 존재하는 무관한 차량(카메라가 계속 프레임을 처리한다는 뜻)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        all_events: list[tuple[int, ViolationStatus]] = []

        def step(seconds: float, include_track_1: bool) -> None:
            dets = [VehicleBox(track_id=99, bbox=other_bbox, confidence=0.9, frame_id=0, captured_at=base_time + timedelta(seconds=seconds))]
            if include_track_1:
                dets.append(
                    VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=0, captured_at=base_time + timedelta(seconds=seconds))
                )
            for event in monitor.update(dets):
                all_events.append((event.track_id, event.status))

        step(0, include_track_1=True)
        step(10, include_track_1=True)  # dwell=10s -> RESTRICTED_ZONE 발행

        # track_grace_seconds(2초)를 넘기는 3초짜리 가림 — 다른 차(99)는 계속 탐지되어
        # update()는 계속 호출된다(카메라 자체는 죽지 않음). track 1만 잠깐 안 보인다.
        step(11, include_track_1=False)
        step(12, include_track_1=False)
        step(13, include_track_1=False)
        # (319 리뷰 재검토, C-1) 보관함은 dict가 아니라 리스트다 — 재결합을
        # track_id가 아니라 위치로 판단하므로 키가 필요없다.
        self.assertEqual([s.track_id for s in monitor._reunification_archive], [1])
        self.assertNotIn(1, monitor._tracks)

        step(14, include_track_1=True)  # 재등장 - stationary_since는 t=0 그대로 이어져야 함

        step(59, include_track_1=True)  # dwell=59s, 아직 60초 미달
        step(60, include_track_1=True)  # dwell=60s -> EV_OVERSTAY 발행

        track_1_events = [item for item in all_events if item[0] == 1]
        self.assertEqual(
            track_1_events,
            [
                (1, ViolationStatus.RESTRICTED_ZONE),
                (1, ViolationStatus.EV_OVERSTAY),
            ],
        )

    def test_monitor_ev_overstay_not_masked_by_higher_ratio_overlapping_restricted_zone(self) -> None:
        """리뷰 반영(I-4/319): 정상 배치라면 전용구역끼리 겹치지 않아야 하지만, 캘리브레이션
        오차 등으로 겹치는 경우 겹침 비율이 더 높은 쪽(DISABLED)만 보면 실제로 시간
        초과 중인 EV 충전구역이 영구히 가려진다 — 겹치는 전용구역 전체에서
        시간 초과 여부를 확인해야 한다."""
        disabled_zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)])
        ev_zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)], allowed_minutes=1.0
        )
        registry = ZoneRegistry([disabled_zone, ev_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.30, min_dwell_seconds=1.0, movement_epsilon=0.01)
        bbox = BoundingBox(0.0, 0.0, 0.4, 0.4)  # DISABLED와 EV 충전구역 둘 다에 높은 비율로 겹침
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        events_at = {}
        for seconds in (0, 2, 65):
            events_at[seconds] = monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds))]
            )

        self.assertEqual([(e.status, e.zone_number) for e in events_at[2]], [(ViolationStatus.RESTRICTED_ZONE, "DIS-01")])
        self.assertEqual([(e.status, e.zone_number) for e in events_at[65]], [(ViolationStatus.EV_OVERSTAY, "EV-01")])

    def test_ev_overstay_clock_survives_sub_threshold_jitter(self) -> None:
        """같은 구역 안에서 미세 이동이 일어나도 EV 점유 시계가 리셋되지 않는다
        (319 리뷰 C-1, 최우선).

        수정 전에는 앵커 대비 movement_epsilon을 넘는 이동 한 번에
        stationary_since가 0으로 돌아가, EV_OVERSTAY -> RESTRICTED_ZONE으로
        강등 재발행된 뒤 다시 EV_OVERSTAY가 발행됐다(재현 확인). 같은 차·같은
        자리에 대한 중복 발행이라 FR-PARK-010 위반이다.
        """
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)], allowed_minutes=1.0
        )
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, movement_epsilon=0.01
        )
        anchor = BoundingBox(0.05, 0.05, 0.25, 0.25)
        nudged = BoundingBox(0.064, 0.064, 0.264, 0.264)  # 앵커 대비 0.014 > movement_epsilon
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[ViolationStatus] = []
        for seconds, bbox in ((0, anchor), (10, anchor), (61, anchor), (71, nudged), (85, nudged), (135, nudged)):
            for event in monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                            captured_at=base_time + timedelta(seconds=seconds))]
            ):
                seen.append(event.status)

        self.assertEqual(seen, [ViolationStatus.RESTRICTED_ZONE, ViolationStatus.EV_OVERSTAY])

    def test_open_violation_survives_sub_threshold_jitter(self) -> None:
        """미세 이동으로 정차 시계가 리셋돼도 '이미 발행한 사건'은 유지된다.

        open_violation 리셋을 moved가 아니라 홈 구역 변경에 연동한 결과다
        (319 리뷰 C-1). 홈 구역이 그대로면 같은 사건이 계속되는 중이다.
        """
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, movement_epsilon=0.01
        )
        anchor = BoundingBox(0.05, 0.05, 0.25, 0.25)
        nudged = BoundingBox(0.064, 0.064, 0.264, 0.264)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[ViolationStatus] = []
        for seconds, bbox in ((0, anchor), (10, anchor), (20, nudged), (40, nudged)):
            for event in monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                            captured_at=base_time + timedelta(seconds=seconds))]
            ):
                seen.append(event.status)

        self.assertEqual(seen, [ViolationStatus.RESTRICTED_ZONE])

    def test_aisle_block_reissued_when_vehicle_moves_to_another_aisle(self) -> None:
        """같은 위반 종류로 구역만 옮기면 새 사건으로 발행된다(319 리뷰 C-1 2차).

        중복 판정 키가 status 단독이면 AISLE-1을 막던 차가 AISLE-2로 이동해도
        status가 그대로 AISLE_BLOCK이라 새 이벤트가 나가지 않고, 서버는 영영
        AISLE-1이 막혀 있다고 알게 된다. 홈 구역은 스팟형 구역만 고르므로
        (`_home_zone_overlap`) 통행로만 걸친 차는 홈 구역이 계속 None이고,
        "홈 구역 변경" 기반 리셋으로는 이 경우를 닫을 수 없다 — 그래서 키를
        (status, zone_id)로 바꿨다.
        """
        aisle_1 = self.make_zone("AISLE-1", ZoneType.AISLE, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        aisle_2 = self.make_zone("AISLE-2", ZoneType.AISLE, [(0.6, 0.0), (0.9, 0.0), (0.9, 0.3), (0.6, 0.3)])
        registry = ZoneRegistry([aisle_1, aisle_2])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, movement_epsilon=0.01
        )
        in_aisle_1 = BoundingBox(0.05, 0.05, 0.25, 0.25)
        in_aisle_2 = BoundingBox(0.65, 0.05, 0.85, 0.25)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[tuple[ViolationStatus, str | None]] = []
        for seconds, bbox in ((0, in_aisle_1), (10, in_aisle_1), (20, in_aisle_2), (30, in_aisle_2), (40, in_aisle_2)):
            for event in monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                            captured_at=base_time + timedelta(seconds=seconds))]
            ):
                seen.append((event.status, event.zone_number))

        self.assertEqual(
            seen,
            [
                (ViolationStatus.AISLE_BLOCK, "AISLE-1"),
                (ViolationStatus.AISLE_BLOCK, "AISLE-2"),
            ],
        )

    def test_ev_overstay_clock_survives_home_zone_flapping(self) -> None:
        """두 스팟에 걸쳐 선 차의 홈 구역이 뒤바뀌어도 점유 시계가 살아남는다
        (319 리뷰 C-1 2차).

        `_home_zone_overlap`은 겹침 비율 1등 스팟만 고르므로, 걸쳐 선 차는
        movement_epsilon 안에서 가만히 있어도 bbox 흔들림만으로 1등이 매 프레임
        뒤바뀔 수 있다. 점유 시계 리셋을 "홈 구역이 바뀌었다"만으로 판단하면
        그때마다 시계가 0이 되어 걸쳐 선 차에는 EV_OVERSTAY가 영영 발화하지
        못한다 — C-1이 없애려던 문제를 다른 경로로 재생산하는 것이다. 그래서
        리셋 조건에 "실제로 움직였다(moved)"를 AND로 걸었다.

        같은 시나리오가 (status, zone_id) 중복 판정 키도 흔들기 때문에, 이벤트가
        각 상태마다 한 번씩만 나가는지도 함께 고정한다.
        """
        ev_left = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)], allowed_minutes=1.0
        )
        ev_right = self.make_zone(
            "EV-02", ZoneType.EV_FAST, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.2), (0.2, 0.2)], allowed_minutes=1.0
        )
        registry = ZoneRegistry([ev_left, ev_right])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, movement_epsilon=0.01
        )
        # 두 구역 경계(x=0.2)에 걸쳐 세우고, 겹침 비율 1등이 뒤바뀔 만큼만 흔든다.
        # 두 bbox의 중심 거리는 0.004로 movement_epsilon(0.01) 미만이라 moved는 False다.
        leans_left = BoundingBox(0.098, 0.05, 0.298, 0.15)  # EV-01 0.51 / EV-02 0.49
        leans_right = BoundingBox(0.102, 0.05, 0.302, 0.15)  # EV-01 0.49 / EV-02 0.51
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[ViolationStatus] = []
        for index, seconds in enumerate((0, 10, 20, 30, 40, 50, 60, 70, 80)):
            bbox = leans_left if index % 2 == 0 else leans_right
            for event in monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                            captured_at=base_time + timedelta(seconds=seconds))]
            ):
                seen.append(event.status)

        self.assertEqual(seen, [ViolationStatus.RESTRICTED_ZONE, ViolationStatus.EV_OVERSTAY])

    def test_no_duplicate_events_when_home_zone_flaps_without_movement(self) -> None:
        """홈 구역 flapping만으로는 같은 사건이 중복 발행되지 않는다(319 리뷰 C-1 2차).

        중복 판정 키에 zone_id를 넣은 결과, 겹침 비율 1등이 흔들림만으로 뒤바뀌면
        키가 매 프레임 요동쳐 같은 자리에 대해 이벤트가 무한히 중복 발행될 수 있다.
        그래서 zone_id 변경은 "마지막 판정 이후 실제로 움직였을 때"만 인정한다.
        시간 요소를 빼고 키 안정성만 보기 위해 EV가 아닌 DISABLED 구역을 쓴다.
        """
        left = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)])
        right = self.make_zone("DIS-02", ZoneType.DISABLED, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.2), (0.2, 0.2)])
        registry = ZoneRegistry([left, right])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, movement_epsilon=0.01
        )
        leans_left = BoundingBox(0.098, 0.05, 0.298, 0.15)
        leans_right = BoundingBox(0.102, 0.05, 0.302, 0.15)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[ViolationStatus] = []
        for index, seconds in enumerate((0, 10, 20, 30, 40, 50, 60, 70, 80, 90)):
            bbox = leans_left if index % 2 == 0 else leans_right
            for event in monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                            captured_at=base_time + timedelta(seconds=seconds))]
            ):
                seen.append(event.status)

        self.assertEqual(seen, [ViolationStatus.RESTRICTED_ZONE])

    def test_occupancy_clock_starts_when_home_zone_acquired_without_movement(self) -> None:
        """홈 구역을 첫 프레임이 아니라 나중에 획득해도 점유 시계가 시작된다
        (319 리뷰 C-1 3차).

        점유 시계 리셋에 걸어둔 moved 조건이 시계의 '리셋'뿐 아니라 '시작'까지
        막고 있었다. 겹침 비율이 min_overlap_ratio 아래에서 시작해 탐지 노이즈로
        위로 올라가는 흔한 경우(차는 movement_epsilon 안에서 가만히 있다), 홈 구역을
        획득하는 그 프레임의 moved가 False라서 occupied_zone_id가 영구히 None으로
        남았다. 그러면 occupancy_seconds가 영영 0.0이고, EV_OVERSTAY는 이제 이
        시계로만 발화하므로 아무리 오래 점유해도 발화하지 못한다 — C-1이 없애려던
        실패 유형을 그대로 재생산한 것이다.

        그래서 moved는 시계의 '전환'에만 요구하고 '시작'(occupied_zone_id is None)에는
        요구하지 않는다. 시계가 한 번 시작된 뒤의 변경은 여전히 moved를 요구하므로
        flapping 방어는 그대로다.
        """
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)], allowed_minutes=1.0
        )
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, movement_epsilon=0.01
        )
        # bbox 면적 0.02 고정. below는 구역과 0.0074(비율 0.37)만 겹쳐 min_overlap_ratio
        # 미달이라 홈 구역이 없고, above는 0.0082(비율 0.41)로 홈 구역이 생긴다.
        # 두 bbox의 중심 거리는 0.008로 movement_epsilon(0.01) 미만이라 moved는 False다.
        below_threshold = BoundingBox(0.126, 0.05, 0.326, 0.15)
        above_threshold = BoundingBox(0.118, 0.05, 0.318, 0.15)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[ViolationEvent] = []
        for seconds, bbox in ((0, below_threshold), (10, above_threshold), (40, above_threshold), (71, above_threshold)):
            for event in monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                            captured_at=base_time + timedelta(seconds=seconds))]
            ):
                seen.append(event)

        self.assertEqual(
            [event.status for event in seen],
            [ViolationStatus.RESTRICTED_ZONE, ViolationStatus.EV_OVERSTAY],
        )
        # 점유 시계는 홈 구역을 획득한 t=10부터 흐른다 — t=71이면 61초로 허용 60초 초과.
        self.assertAlmostEqual(seen[-1].occupancy_seconds, 61.0)

    def test_violation_event_carries_occupancy_and_dwell_clocks_separately(self) -> None:
        """이벤트가 정차 시계와 점유 시계를 둘 다 실어보낸다(319 리뷰 C-1 2차).

        EV_OVERSTAY는 occupancy_seconds로 발화하는데 이벤트가 dwell_seconds만
        실어보내면, 운영 임계값(60~120분)에서 발화 조건과 보고값이 시간 단위로
        어긋난다. dwell_seconds의 의미("연속 무이동 시간")는 그대로 두고
        occupancy_seconds를 추가해 서버가 무엇으로 판정됐는지 알 수 있게 한다.
        """
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)], allowed_minutes=1.0
        )
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, movement_epsilon=0.01
        )
        anchor = BoundingBox(0.05, 0.05, 0.25, 0.25)
        nudged = BoundingBox(0.064, 0.064, 0.264, 0.264)  # 앵커 대비 0.014 > movement_epsilon
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        overstay_events: list[ViolationEvent] = []
        # t=30에 미세 이동이 있어 정차 시계는 30초에 리셋되지만 점유 시계는 이어진다.
        for seconds, bbox in ((0, anchor), (10, anchor), (30, nudged), (65, nudged)):
            for event in monitor.update(
                [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=seconds,
                            captured_at=base_time + timedelta(seconds=seconds))]
            ):
                if event.status is ViolationStatus.EV_OVERSTAY:
                    overstay_events.append(event)

        self.assertEqual(len(overstay_events), 1)
        event = overstay_events[0]
        self.assertAlmostEqual(event.occupancy_seconds, 65.0)  # 발화 근거: 허용 시간 60초 초과
        self.assertAlmostEqual(event.dwell_seconds, 35.0)  # 정차 시계는 t=30 리셋 이후라 임계값 미만
        payload = to_jsonable(event)
        self.assertAlmostEqual(payload["occupancy_seconds"], 65.0)
        self.assertAlmostEqual(payload["dwell_seconds"], 35.0)

    def test_ev_overstay_not_reset_by_track_id_change(self) -> None:
        """추적기가 같은 차에 새 track_id를 붙여도 점유 시계가 이어진다
        (319 리뷰 C-1).

        ByteTrack은 track_buffer(기본 30프레임 = 5fps에서 약 6초)를 넘겨 사라진
        트랙을 잊고 재등장 시 새 번호를 발급한다. 번호로만 재결합하면 그
        시점부터 영영 못 잇는다 — 위치로 재식별한다.
        """
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)], allowed_minutes=1.0
        )
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0,
            movement_epsilon=0.01, track_grace_seconds=2.0,
        )
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        other = BoundingBox(0.60, 0.60, 0.80, 0.80)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        def step(seconds: float, track_ids: tuple[int, ...]) -> list[ViolationEvent]:
            dets = []
            for track_id in track_ids:
                dets.append(
                    VehicleBox(
                        track_id=track_id,
                        bbox=bbox if track_id != 99 else other,
                        confidence=0.9,
                        frame_id=int(seconds),
                        captured_at=base_time + timedelta(seconds=seconds),
                    )
                )
            return monitor.update(dets)

        step(0, (1, 99))
        first = step(10, (1, 99))
        self.assertEqual([e.status for e in first if e.track_id == 1], [ViolationStatus.RESTRICTED_ZONE])

        # track 1이 8초간 사라진다 — track_grace_seconds(2초)도 ByteTrack의
        # track_buffer(약 6초)도 넘긴다. 다른 차(99)는 계속 보여 update()는 돈다.
        for seconds in (11, 13, 15, 17):
            step(seconds, (99,))

        # 같은 자리에 새 번호(2)로 재등장
        step(18, (2, 99))
        later = step(61, (2, 99))
        self.assertEqual([e.status for e in later if e.track_id == 2], [ViolationStatus.EV_OVERSTAY])

    def test_track_not_reunified_when_reappearing_elsewhere(self) -> None:
        """다른 자리에서 재등장하면 재결합하지 않는다 — 차량 교체 오탐 방어.

        위치 기반 재결합의 위험은 A가 나간 자리에 B가 들어왔을 때 B가 A의
        점유 시계를 물려받는 것이다. 중심점이 movement_epsilon을 넘게 다르면
        같은 차로 보지 않는다.
        """
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0,
            movement_epsilon=0.01, track_grace_seconds=2.0,
        )
        here = BoundingBox(0.05, 0.05, 0.25, 0.25)
        far = BoundingBox(0.60, 0.60, 0.80, 0.80)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        monitor.update([VehicleBox(track_id=1, bbox=here, confidence=0.9, frame_id=0, captured_at=base_time)])
        for seconds in (5, 6):
            monitor.update(
                [VehicleBox(track_id=98, bbox=far, confidence=0.9, frame_id=int(seconds),
                            captured_at=base_time + timedelta(seconds=seconds))]
            )
        self.assertNotIn(1, monitor._tracks)

        # 전혀 다른 자리에서 새 번호로 등장 -> 이어받지 않는다.
        events = monitor.update(
            [VehicleBox(track_id=2, bbox=BoundingBox(0.30, 0.30, 0.50, 0.50), confidence=0.9,
                        frame_id=7, captured_at=base_time + timedelta(seconds=7))]
        )
        self.assertEqual(events, [])
        self.assertEqual(monitor._tracks[2].stationary_since, base_time + timedelta(seconds=7))

    def test_reunification_preserves_moved_since_last_decision(self) -> None:
        """재결합은 moved_since_last_decision(sticky 플래그)까지 보존한다
        (319 리뷰 C-1 2/2).

        이 플래그는 "마지막 판정 이후 차가 실제로 움직였는가"라는 사실이고,
        트랙이 잠깐 안 보였다는 것이 그 사실을 무효화하지는 않는다. 재결합
        시점에 초기화하면 아래 시나리오에서 이벤트가 통째로 유실된다:
        DIS-01에서 RESTRICTED_ZONE이 발행된 차가 DIS-02로 옮겨 정차 시간을
        채우는 도중 가려졌다 재등장하는 경우, 중복 판정 키의 zone_id 변경을
        믿을 근거(플래그)가 사라져 status/zone_id가 (RESTRICTED_ZONE, DIS-01)에
        머물고 서버는 영영 DIS-01이 점유됐다고 알게 된다.

        반대 방향(오발행) 위험은 없다: 플래그는 앵커 대비 movement_epsilon을
        넘는 실제 이동에서만 세워지고, 같은 구역 안에서 움직인 경우에는
        zone_id가 같아 zone_changed가 False로 남는다.
        """
        zone_1 = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        zone_2 = self.make_zone("DIS-02", ZoneType.DISABLED, [(0.5, 0.0), (0.8, 0.0), (0.8, 0.3), (0.5, 0.3)])
        registry = ZoneRegistry([zone_1, zone_2])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0,
            movement_epsilon=0.01, track_grace_seconds=2.0,
        )
        at_1 = BoundingBox(0.05, 0.05, 0.25, 0.25)
        at_2 = BoundingBox(0.55, 0.05, 0.75, 0.25)
        elsewhere = BoundingBox(0.85, 0.85, 0.95, 0.95)  # 어느 구역과도 안 겹치는 무관한 차량
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[tuple[int, ViolationStatus, str | None, float]] = []

        def step(seconds: float, track_id: int | None, bbox: BoundingBox | None) -> None:
            captured_at = base_time + timedelta(seconds=seconds)
            dets = [VehicleBox(track_id=99, bbox=elsewhere, confidence=0.9, frame_id=int(seconds), captured_at=captured_at)]
            if track_id is not None and bbox is not None:
                dets.append(
                    VehicleBox(track_id=track_id, bbox=bbox, confidence=0.9, frame_id=int(seconds), captured_at=captured_at)
                )
            for event in monitor.update(dets):
                if event.track_id != 99:
                    seen.append((event.track_id, event.status, event.zone_number, event.dwell_seconds))

        step(0, 1, at_1)
        step(10, 1, at_1)  # dwell=10s -> RESTRICTED_ZONE(DIS-01) 발행, 플래그는 여기서 clear된다
        step(11, 1, at_2)  # DIS-02로 이동 -> 플래그 set, 정차 시계 리셋(아직 OBSERVING)
        step(14, None, None)  # track_grace_seconds(2초) 초과 -> 보관함으로 이동
        step(16, None, None)
        self.assertNotIn(1, monitor._tracks)

        step(17, 2, at_2)  # 같은 자리에 새 번호로 재등장 -> 위치로 재결합
        reunified = monitor._tracks[2]
        self.assertTrue(reunified.moved_since_last_decision)  # 보존됐다
        self.assertEqual(reunified.stationary_since, base_time + timedelta(seconds=11))
        self.assertEqual(reunified.open_violation_zone_id, zone_1.zone_id)

        step(22, 2, at_2)  # dwell=11s -> DIS-02에서 새 사건으로 발행돼야 한다

        self.assertEqual(
            seen,
            [
                (1, ViolationStatus.RESTRICTED_ZONE, "DIS-01", 10.0),
                (2, ViolationStatus.RESTRICTED_ZONE, "DIS-02", 11.0),
            ],
        )

    def test_reunification_archive_entry_discarded_when_same_track_reappears_elsewhere(self) -> None:
        """같은 track_id가 다른 위치에서 재등장하면 그 보관 항목을 버린다
        (319 리뷰 재검토, C-1 Important 1).

        트래커는 persist=True로 돌고 reset하지 않으므로 track_id는 프로세스
        수명 동안 단조 증가한다 — 즉 track_id 일치는 "같은 트래커 트랙"과
        동의어이고, 그 트랙이 다른 위치에서 관측됐다는 것은 그 차가 보관된
        자리를 떠났다는 양(+)의 증거다. 항목을 남겨두면 유령이 되어, 뒤에 그
        자리에 들어온 무관한 차가 앞차의 번호판·점유 시계·open_violation을
        통째로 물려받는다. 그러면 42초만 서 있던 차가 앞차의 번호판으로
        occupancy 61초의 EV_OVERSTAY로 보고된다(재현 확인) — 조작된 위반이다.
        """
        zone = self.make_zone(
            "EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)], allowed_minutes=1.0
        )  # 1분 = 60초
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0,
            movement_epsilon=0.01, track_grace_seconds=2.0,
        )
        spot = BoundingBox(0.05, 0.05, 0.25, 0.25)  # 충전구역 안의 자리 S
        away = BoundingBox(0.50, 0.50, 0.70, 0.70)  # 구역 밖, 자리 S와 멀다
        filler = BoundingBox(0.85, 0.85, 0.95, 0.95)  # update()가 계속 돌게 하는 무관한 차량
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        seen: list[tuple[int, ViolationStatus, str | None, float]] = []

        def step(seconds: float, vehicles: tuple[tuple[int, BoundingBox], ...]) -> None:
            captured_at = base_time + timedelta(seconds=seconds)
            dets = [VehicleBox(track_id=99, bbox=filler, confidence=0.9, frame_id=int(seconds), captured_at=captured_at)]
            for track_id, bbox in vehicles:
                dets.append(
                    VehicleBox(track_id=track_id, bbox=bbox, confidence=0.9, frame_id=int(seconds), captured_at=captured_at)
                )
            for event in monitor.update(dets):
                if event.track_id != 99:
                    seen.append((event.track_id, event.status, event.plate_number, event.occupancy_seconds))

        # 차량 A(track 1)가 자리 S를 t=0부터 점유하고 번호판이 연결된다.
        step(0, ((1, spot),))
        monitor.attach_plate(1, "12가3456")
        step(10, ((1, spot),))  # dwell=10s -> RESTRICTED_ZONE(번호판 포함) 발행

        # A가 t=13,15에 안 보인다 -> track_grace_seconds(2초) 초과로 자리 S 앵커째 보관.
        step(13, ())
        step(15, ())
        self.assertEqual([s.track_id for s in monitor._reunification_archive], [1])

        # ByteTrack이 track_buffer(약 6초) 안에서 A를 같은 id로 재획득했는데 위치가
        # 다르다 — A가 자리 S를 떠났다는 증거다. 보관 항목을 여기서 버려야 한다.
        step(17, ((1, away),))
        self.assertEqual(monitor._reunification_archive, [])  # 유령이 남지 않았다

        # 무관한 차량 B가 새 id로 자리 S에 도착한다. 물려받을 것이 없어야 한다.
        step(19, ((1, away), (2, spot)))
        state_b = monitor._tracks[2]
        self.assertIsNone(state_b.plate_number)
        self.assertEqual(state_b.stationary_since, base_time + timedelta(seconds=19))
        self.assertEqual(state_b.zone_occupied_since, base_time + timedelta(seconds=19))
        self.assertEqual(state_b.open_violation, ViolationStatus.NONE)

        step(29, ((1, away), (2, spot)))  # B dwell=10s -> 자기 번호판(None)으로 RESTRICTED_ZONE
        step(61, ((1, away), (2, spot)))  # B의 점유는 42초뿐 -> 허용 60초 미달, EV_OVERSTAY 없음

        b_events = [item for item in seen if item[0] == 2]
        self.assertEqual(b_events, [(2, ViolationStatus.RESTRICTED_ZONE, None, 10.0)])
        self.assertNotIn(ViolationStatus.EV_OVERSTAY, [item[1] for item in seen])
        self.assertNotIn("12가3456", [item[2] for item in b_events])

    def test_reunification_prefers_same_id_entry_and_never_leaves_it_behind(self) -> None:
        """같은 track_id 항목이 필터를 통과했으면 그것을 claim하고, 통과하지 못했으면
        다른 항목을 claim하더라도 같은 id 항목은 반드시 버린다.

        불변식: `_claim_reunifiable`을 지나면 보관함에 detection.track_id를 든
        항목이 없다(319 리뷰 재검토, C-1 Important 1).

        기대값이 바뀐 이유(319 최종 리뷰 Minor): 예전에는 같은 id 항목이 시간·거리
        필터를 통과했는데도 다른 항목이 조금 더 가까우면 그쪽을 claim했다 —
        그 증거("track_id 일치는 같은 트래커 트랙과 동의어")로 항목을 삭제하면서
        매칭에서는 무시한 셈이다. 결과는 그 차 자신의 번호판과 점유 시계를 버리고
        남의 상태를 물려받는 것, 즉 엉뚱한 번호판에 조작된 EV_OVERSTAY다.
        이제 같은 id 항목이 필터를 통과했으면 거리와 무관하게 그것을 claim한다.

        네 가지 배치를 고정한다 — (같은 id 항목이 필터 통과/미통과) ×
        (같은 id 항목이 더 가까운 항목보다 앞/뒤). 미통과 쪽 두 배치가 claim 대상과
        소비 대상이 서로 다른 인덱스인 경우이고, 그때 pop으로 인덱스가 밀리는
        보정 로직의 양방향을 그대로 태운다. 도달 조건은 "두 트랙이
        movement_epsilon 안에 겹친 채로 둘 다 삭제되는" 희귀한 배치지만,
        남기면 유령이 되는 것은 위 테스트와 같다.
        """
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.6, 0.6), (0.9, 0.6), (0.9, 0.9), (0.6, 0.9)])
        anchor_a = BoundingBox(0.05, 0.05, 0.25, 0.25)  # 중심 (0.15, 0.15)
        anchor_b = BoundingBox(0.054, 0.054, 0.254, 0.254)  # 중심 (0.154, 0.154) — 거리 0.0057 < ε
        far = BoundingBox(0.30, 0.30, 0.50, 0.50)  # 중심 (0.4, 0.4) — 두 앵커에서 ε 밖
        filler = BoundingBox(0.85, 0.85, 0.95, 0.95)
        base_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

        def archive_two_tracks(
            first_id: int, first_bbox: BoundingBox, second_id: int, second_bbox: BoundingBox
        ) -> ViolationMonitor:
            """두 트랙을 인자 순서대로 보관함에 넣는다(보관 순서 = 최초 탐지 순서)."""

            monitor = ViolationMonitor(
                ZoneRegistry([zone]), min_overlap_ratio=0.40, min_dwell_seconds=10.0,
                movement_epsilon=0.01, track_grace_seconds=2.0,
            )
            monitor.update([
                VehicleBox(track_id=99, bbox=filler, confidence=0.9, frame_id=0, captured_at=base_time),
                VehicleBox(track_id=first_id, bbox=first_bbox, confidence=0.9, frame_id=0, captured_at=base_time),
                VehicleBox(track_id=second_id, bbox=second_bbox, confidence=0.9, frame_id=0, captured_at=base_time),
            ])
            monitor.update([
                VehicleBox(track_id=99, bbox=filler, confidence=0.9, frame_id=3,
                           captured_at=base_time + timedelta(seconds=3))
            ])
            self.assertEqual(
                [s.track_id for s in monitor._reunification_archive], [first_id, second_id]
            )
            return monitor

        def reappear(monitor: ViolationMonitor, track_id: int, bbox: BoundingBox) -> None:
            monitor.update([
                VehicleBox(track_id=99, bbox=filler, confidence=0.9, frame_id=5,
                           captured_at=base_time + timedelta(seconds=5)),
                VehicleBox(track_id=track_id, bbox=bbox, confidence=0.9, frame_id=5,
                           captured_at=base_time + timedelta(seconds=5)),
            ])

        # ── 같은 id 항목이 필터를 통과한 경우: 더 가까운 항목이 있어도 그것을 claim한다.
        # (a) 같은 id 항목(track 1, 인덱스 0)이 더 가까운 항목(track 7, 인덱스 1)보다 앞.
        monitor = archive_two_tracks(1, anchor_a, 7, anchor_b)
        reappear(monitor, 1, anchor_b)
        self.assertEqual(monitor._tracks[1].last_bbox, anchor_a)  # 자기 항목(앵커 A)을 claim했다
        # 남은 항목은 track 7 — 다른 트래커 트랙이므로 불변식 대상이 아니다.
        self.assertEqual([s.track_id for s in monitor._reunification_archive], [7])

        # (b) 같은 id 항목(track 1, 인덱스 1)이 더 가까운 항목(track 7, 인덱스 0)보다 뒤.
        monitor = archive_two_tracks(7, anchor_b, 1, anchor_a)
        reappear(monitor, 1, anchor_b)
        self.assertEqual(monitor._tracks[1].last_bbox, anchor_a)
        self.assertEqual([s.track_id for s in monitor._reunification_archive], [7])

        # ── 같은 id 항목이 거리 필터에서 탈락한 경우: 다른 항목이 claim하고,
        #    같은 id 항목은 유령 방지를 위해 삭제된다(인덱스 시프트 보정 경로).
        # (c) 같은 id 항목(인덱스 0)이 claim 대상(인덱스 1)보다 앞 — 시프트 없음.
        monitor = archive_two_tracks(1, far, 7, anchor_b)
        reappear(monitor, 1, anchor_b)
        self.assertEqual(monitor._reunification_archive, [])
        self.assertEqual(monitor._tracks[1].last_bbox, anchor_b)  # track 7 항목을 claim했다

        # (d) 같은 id 항목(인덱스 1)이 claim 대상(인덱스 0)보다 뒤 —
        #     pop으로 인덱스가 한 칸 당겨지는 쪽이다.
        monitor = archive_two_tracks(7, anchor_b, 1, far)
        reappear(monitor, 1, anchor_b)
        self.assertEqual(monitor._reunification_archive, [])
        self.assertEqual(monitor._tracks[1].last_bbox, anchor_b)

    def test_monitor_out_of_zone_flagged_when_parked_outside_all_zones(self) -> None:
        """등록된 구역과 전혀 겹치지 않는 곳에 정착하면(요구사항 정의서.md:25), 최소 정차 시간
        이후 OUT_OF_ZONE 이벤트가 한 번 발행되고 중복 발행되지 않는다."""
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        outside_bbox = BoundingBox(0.6, 0.6, 0.8, 0.8)  # 등록 구역과 전혀 겹치지 않는 위치
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        first = VehicleBox(track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=1, captured_at=base_time)
        second = VehicleBox(
            track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=2)
        )
        third = VehicleBox(
            track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=4)
        )

        events_first = monitor.update([first])
        events_second = monitor.update([second])
        events_third = monitor.update([third])

        self.assertEqual(len(events_first), 0)  # 최소 정차 시간(1초) 미달로 아직 OBSERVING
        self.assertEqual(len(events_second), 1)
        self.assertEqual(events_second[0].status, ViolationStatus.OUT_OF_ZONE)
        self.assertIsNone(events_second[0].zone_id)
        self.assertEqual(len(events_third), 0)  # 같은 위반이 계속 열려 있으므로 중복 발행하지 않음

    def test_monitor_out_of_zone_transitions_to_aisle_block_after_moving(self) -> None:
        """리뷰 반영: 구역 외(OUT_OF_ZONE)에 정착해있던 차량이 이동해서 통행로에
        들어가면, 이전 OUT_OF_ZONE 상태는 자동으로 닫히고 AISLE_BLOCK이 새로
        (중복 없이 한 번만) 발행돼야 한다."""
        aisle = self.make_zone("AISLE-1", ZoneType.AISLE, [(0.5, 0.0), (0.9, 0.0), (0.9, 0.3), (0.5, 0.3)])
        registry = ZoneRegistry([aisle])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        outside_bbox = BoundingBox(0.0, 0.5, 0.2, 0.7)  # 등록 구역과 안 겹침
        aisle_bbox = BoundingBox(0.55, 0.05, 0.85, 0.25)  # AISLE 구역 안

        events_at = {}
        for seconds in (0, 2, 4):
            events_at[seconds] = monitor.update(
                [VehicleBox(track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds))]
            )
        self.assertEqual(len(events_at[0]), 0)  # 정착 전(1초 미달), OBSERVING
        self.assertEqual([e.status for e in events_at[2]], [ViolationStatus.OUT_OF_ZONE])  # 정착 -> OUT_OF_ZONE 1회 발행
        self.assertEqual(len(events_at[4]), 0)  # 같은 위반 계속 열려있으므로 중복 없음

        for seconds in (6, 8, 10):
            events_at[seconds] = monitor.update(
                [VehicleBox(track_id=1, bbox=aisle_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds))]
            )
        self.assertEqual(len(events_at[6]), 0)  # 이동 직후 정차 타이머 리셋, 1초 미달로 OBSERVING
        # 재정착 -> AISLE_BLOCK 1회 발행. 이전 OUT_OF_ZONE이 "자동으로 닫히는" 게
        # 아니라, 이번 프레임 판정(AISLE_BLOCK)이 열려 있는 사건(open_violation =
        # OUT_OF_ZONE)과 달라서 새 이벤트로 나가는 것이다. (319 리뷰 C-1 이후
        # open_violation 리셋은 이동이 아니라 홈 구역 변경 시점에만 일어나는데,
        # 여기서는 구역 밖 -> AISLE 이동이라 홈 구역은 양쪽 모두 None이다.)
        self.assertEqual([e.status for e in events_at[8]], [ViolationStatus.AISLE_BLOCK])
        self.assertEqual(len(events_at[10]), 0)  # 같은 위반 계속 열려있으므로 중복 없음

    def test_monitor_vehicle_inside_entry_exit_zone_is_not_out_of_zone(self) -> None:
        """리뷰 반영(C-1): 게이트(ENTRY_EXIT) 구역 안에 대기 중인 차량은 판정
        제외 구역 안에 있으므로 OUT_OF_ZONE이 아니어야 한다
        (`IGNORED_ZONE_TYPES_FOR_PARKING` 판정 제외 불변식, §5.1)."""
        ent = self.make_zone("ENT-1", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)])
        monitor = ViolationMonitor(ZoneRegistry([ent]), min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        at_gate = BoundingBox(0.1, 0.1, 0.4, 0.4)  # ENTRY_EXIT 안에 100% 포함

        monitor.update([VehicleBox(track_id=1, bbox=at_gate, confidence=0.9, frame_id=0, captured_at=base_time)])
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=at_gate, confidence=0.9, frame_id=1, captured_at=base_time + timedelta(seconds=2))]
        )
        self.assertNotIn(ViolationStatus.OUT_OF_ZONE, [e.status for e in events])

    def test_monitor_gate_overlap_uses_entry_zone_threshold_not_general_threshold(self) -> None:
        """리뷰 반영(N-1): "게이트 안에 있다" 판단은 §2.2 입차매칭과 같은
        entry_zone_min_overlap_ratio를 써야 한다. 몸겹침이 entry_zone_min_overlap_ratio는
        넘고(그래서 입차매칭은 성공) min_overlap_ratio(스팟 판정용, 더 높음)는 못 넘는
        차량이, 같은 프레임에서 "게이트에 있다(번호판 매칭 성공)"와 "구역 외 주차"라는
        모순된 판정을 동시에 받으면 안 된다."""
        ent = self.make_zone("ENT-1", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)])
        monitor = ViolationMonitor(
            ZoneRegistry([ent]),
            min_overlap_ratio=0.40,
            min_dwell_seconds=1.0,
            movement_epsilon=0.01,
            entry_zone_min_overlap_ratio=0.20,
        )
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        # ENT-1과 몸겹침 37.5% — entry_zone_min_overlap_ratio(0.20)는 넘지만
        # min_overlap_ratio(0.40)는 못 넘는 위치.
        gate_bbox = BoundingBox(0.35, 0.0, 0.75, 0.3)

        monitor.add_entry_event(EntryEvent(plate_number="12가3456", captured_at=base_time))
        monitor.update([VehicleBox(track_id=1, bbox=gate_bbox, confidence=0.9, frame_id=0, captured_at=base_time)])
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=gate_bbox, confidence=0.9, frame_id=1, captured_at=base_time + timedelta(seconds=2))]
        )
        self.assertNotIn(ViolationStatus.OUT_OF_ZONE, [e.status for e in events])

    def test_monitor_out_of_zone_not_flagged_while_neighbor_home_zone_pending(self) -> None:
        """리뷰 반영(C-2): 옆 트랙이 홈 구역에 정착하지 못해 그 구역이
        pending_home_zone_ids로 보류 중이면, 그 구역을 침범 기준 이상 덮고
        있는 다른 트랙도 OUT_OF_ZONE으로 잘못 확정되면 안 된다(판정 보류 유지)."""
        gen_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        monitor = ViolationMonitor(
            ZoneRegistry([gen_a]), min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15, movement_epsilon=0.01
        )
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        # track1: 매 프레임 살짝 위치가 바뀌어(움직임 감지) 계속 정착 실패 -> GEN-A가 pending으로 남음
        track1_positions = [BoundingBox(0.0, 0.0, 0.25, 0.25), BoundingBox(0.02, 0.02, 0.27, 0.27)]
        # track2: GEN-A 몸겹침은 40% 미만(overlaps=[])이지만, 구역 면적 기준으로는 침범 후보(>=15%)
        track2_bbox = BoundingBox(0.15, 0.0, 0.55, 0.3)

        events: list[ViolationEvent] = []
        for i, seconds in enumerate((0, 3, 6, 9, 12)):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=track1_positions[i % 2], confidence=0.9, frame_id=i, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=track2_bbox, confidence=0.9, frame_id=i, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )
            self.assertNotIn(ViolationStatus.OUT_OF_ZONE, [e.status for e in events if e.track_id == 2])

    def test_monitor_multi_vehicle_frame_does_not_mix_up_track_state(self) -> None:
        """한 프레임에 차량이 2대 이상 잡혀도, 마지막 차량이 아닌 다른 차량의
        상태(open_violation, plate_number)를 잘못 참조하면 안 된다."""

        restricted_zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        general_zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.6, 0.0), (0.9, 0.0), (0.9, 0.3), (0.6, 0.3)])
        registry = ZoneRegistry([restricted_zone, general_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        restricted_bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)

        for index in range(2):
            monitor.update(
                [
                    VehicleBox(
                        track_id=1,
                        bbox=restricted_bbox,
                        confidence=0.9,
                        frame_id=index + 1,
                        captured_at=base_time + timedelta(seconds=2 * index),
                    )
                ]
            )
        monitor.attach_plate(1, "11가1111")

        # track 1의 RESTRICTED_ZONE 위반이 이미 열려 있는 상태에서, 같은 프레임에
        # track 2(위반 없는 신규 차량)가 track 1보다 뒤에 detections에 들어온다.
        events = monitor.update(
            [
                VehicleBox(
                    track_id=1,
                    bbox=restricted_bbox,
                    confidence=0.9,
                    frame_id=3,
                    captured_at=base_time + timedelta(seconds=4),
                ),
                VehicleBox(
                    track_id=2,
                    bbox=BoundingBox(0.65, 0.05, 0.85, 0.25),
                    confidence=0.9,
                    frame_id=3,
                    captured_at=base_time + timedelta(seconds=4),
                ),
            ]
        )

        self.assertEqual(len(events), 0)  # track1의 위반은 이미 열려 있으므로 중복 발행되면 안 됨

    def test_slow_continuous_drift_never_reaches_min_dwell(self) -> None:
        """리뷰 반영: 매 프레임 이동량이 movement_epsilon 이하라도 누적 이동거리가 크면
        정지 상태로 오판하면 안 된다 (기존에는 last_bbox를 매 프레임 갱신해 이 문제가 있었음)."""

        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, movement_epsilon=0.01)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        events: list[ViolationEvent] = []
        for index, x1 in enumerate((0.100, 0.106, 0.112, 0.118)):
            detection = VehicleBox(
                track_id=1,
                bbox=BoundingBox(x1, 0.1, x1 + 0.2, 0.3),
                confidence=0.9,
                frame_id=index + 1,
                captured_at=base_time + timedelta(seconds=2 * index),
            )
            events.extend(monitor.update([detection]))

        self.assertEqual(len(events), 0)  # 계속 조금씩 움직이는 차량은 위반으로 확정되면 안 됨

    def test_tracker_rejects_zero_sized_frame(self) -> None:
        """리뷰 반영: 카메라가 순간적으로 빈 프레임을 반환하면 ZeroDivisionError 대신
        BaselineError로 처리되어야 한다."""

        tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)
        tracker._model = object()  # open() 없이 track()의 프레임 크기 검증만 확인
        frame = CapturedFrame(frame_id=1, captured_at=datetime.now(timezone.utc), image=_FakeImage((0, 0, 3)))
        with self.assertRaises(BaselineError):
            tracker.track(frame)

    def test_track_survives_brief_disappearance_within_grace_period(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0, 0), (1, 0), (1, 1), (0, 1)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, track_grace_seconds=5.0
        )
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        other_bbox = BoundingBox(0.5, 0.5, 0.6, 0.6)

        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        # 3초간 안 보임 — 유예 시간(5초) 이내라 트랙이 살아있어야 한다.
        # "지금 시각"을 전달하기 위해 이 프레임엔 다른 차량을 하나 넣는다.
        monitor.update(
            [
                VehicleBox(
                    track_id=99, bbox=other_bbox, confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertIn(1, monitor._tracks)

        # 다시 나타남 — 정차 시작 시각(base_time)이 유지되어 dwell이 끊기지 않아야 한다.
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=12))]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, ViolationStatus.RESTRICTED_ZONE)
        self.assertAlmostEqual(events[0].dwell_seconds, 12.0)

    def test_track_purged_after_grace_period_exceeded(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0, 0), (1, 0), (1, 1), (0, 1)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, track_grace_seconds=2.0
        )
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        other_bbox = BoundingBox(0.5, 0.5, 0.6, 0.6)

        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        # 유예 시간(2초)을 훨씬 넘겨서 사라짐 → 활성 트랙에서는 삭제된다.
        monitor.update(
            [
                VehicleBox(
                    track_id=99, bbox=other_bbox, confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=10),
                )
            ]
        )
        self.assertNotIn(1, monitor._tracks)

        # (리뷰 반영, C-1/319) dwell_reunification_seconds(기본 30초) 이내에
        # 같은 자리로 재등장하면 재결합 보관함에서 stationary_since를 이어받는다 —
        # 정차 시작(t=0)부터 재등장(t=11)까지 이미 min_dwell_seconds(10초)를
        # 채웠으므로 즉시 RESTRICTED_ZONE이 발행돼야 한다(dwell이 0으로
        # 리셋되지 않음).
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=11))]
        )
        self.assertEqual([(e.track_id, e.status) for e in events], [(1, ViolationStatus.RESTRICTED_ZONE)])

    def test_track_not_reunified_beyond_dwell_reunification_window(self) -> None:
        """재결합 보관 기간(dwell_reunification_seconds)마저 넘기면 완전히 새 트랙으로
        취급되어 dwell이 0부터 다시 시작한다 — 무한정 이어붙이지는 않는다는 한계."""
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0, 0), (1, 0), (1, 1), (0, 1)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry,
            min_overlap_ratio=0.40,
            min_dwell_seconds=10.0,
            track_grace_seconds=2.0,
            dwell_reunification_seconds=30.0,
        )
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        other_bbox = BoundingBox(0.5, 0.5, 0.6, 0.6)

        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)])
        monitor.update(
            [
                VehicleBox(
                    track_id=99, bbox=other_bbox, confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=40),
                )
            ]
        )
        self.assertEqual(monitor._reunification_archive, [])  # 이미 정리(prune)됐어야 함

        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=41))]
        )
        self.assertEqual(len(events), 0)  # dwell이 0부터 다시 시작해 min_dwell_seconds 미달

    def test_monitor_attach_plate_updates_track_state(self) -> None:
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=600.0)
        bbox = BoundingBox(0.1, 0.1, 0.2, 0.2)
        monitor.update(
            [VehicleBox(track_id=5, bbox=bbox, confidence=0.9, frame_id=1, captured_at=datetime.now(timezone.utc))]
        )
        monitor.attach_plate(5, "1234")
        self.assertEqual(monitor._tracks[5].plate_number, "1234")

    def test_track_snapshot_matches_dwell_used_by_update(self) -> None:
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        monitor = ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=10.0)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=start)])
        later = start + timedelta(seconds=4)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=later)])

        snapshot = monitor.track_snapshot(later)

        self.assertEqual(set(snapshot), {1})
        self.assertAlmostEqual(snapshot[1].dwell_seconds, 4.0)

    def test_track_snapshot_reports_open_violation(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        monitor = ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=1.0)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=start)])
        later = start + timedelta(seconds=5)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=later)])

        self.assertEqual(monitor.track_snapshot(later)[1].open_violation, ViolationStatus.RESTRICTED_ZONE)

    def test_track_snapshot_does_not_affect_judgment(self) -> None:
        """오버레이가 판정을 바꾸면 검증 도구가 검증 대상을 오염시킨다."""
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        monitor = ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=1.0)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=start)])
        later = start + timedelta(seconds=5)

        for _ in range(3):
            monitor.track_snapshot(later)
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=later)]
        )

        self.assertEqual([event.status for event in events], [ViolationStatus.RESTRICTED_ZONE])

    def test_entry_event_matches_new_track_in_entry_zone(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1234")

    def test_violation_event_carries_session_id_from_matched_entry_event(self) -> None:
        """입차에서 받은 sessionId가 위반 사건까지 닿아야 한다(431번).

        백엔드 API 명세는 POST /api/hw/parking-events에 sessionId를 필수로
        요구하므로, 이 연결이 끊기면 사건을 한 건도 보낼 수 없다.
        """
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        disabled_zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.5, 0.5), (0.9, 0.5), (0.9, 0.9), (0.5, 0.9)])
        monitor = ViolationMonitor(
            ZoneRegistry([entry_zone, disabled_zone]),
            min_overlap_ratio=0.40,
            min_dwell_seconds=1.0,
            entry_match_window_seconds=10.0,
        )
        base_time = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(
            EntryEvent(plate_number="1234", captured_at=base_time, session_id=55, vehicle_id=10)
        )
        # 입차 구역에서 매칭된 뒤 장애인 구역으로 이동해 정차한다.
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        parked_bbox = BoundingBox(0.6, 0.6, 0.8, 0.8)
        monitor.update(
            [VehicleBox(track_id=1, bbox=parked_bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=5))]
        )
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=parked_bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=20))]
        )

        self.assertEqual([event.status for event in events], [ViolationStatus.RESTRICTED_ZONE])
        self.assertEqual(events[0].session_id, 55)

    def test_violation_event_session_id_is_none_when_entry_never_matched(self) -> None:
        """매칭된 입차 이벤트가 없으면 세션을 알 수 없다 — 그래도 판정 자체는 나간다."""
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        monitor = ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=1.0)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=start)])
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=start + timedelta(seconds=5))]
        )

        self.assertEqual([event.status for event in events], [ViolationStatus.RESTRICTED_ZONE])
        self.assertIsNone(events[0].session_id)

    def test_entry_event_not_matched_outside_entry_zone(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.6, 0.6, 0.8, 0.8), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertIsNone(monitor._tracks[1].plate_number)

    def test_entry_event_expires_outside_time_window(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=20),  # 시간창(10초) 초과
                )
            ]
        )
        self.assertIsNone(monitor._tracks[1].plate_number)

    def test_multiple_entry_events_matched_fifo_in_order(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1111", captured_at=base_time))
        monitor.add_entry_event(EntryEvent(plate_number="2222", captured_at=base_time + timedelta(seconds=1)))

        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=2),
                )
            ]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1111")  # 먼저 들어온 이벤트부터 매칭

        monitor.update(
            [
                VehicleBox(
                    track_id=2, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertEqual(monitor._tracks[2].plate_number, "2222")

    def test_entry_event_matches_on_later_frame_when_event_arrives_late(self) -> None:
        """리뷰 반영: OCR 이벤트가 트랙 생성 이후에 도착해도, 다음 프레임에서 매칭돼야 한다."""

        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)

        # 트랙이 먼저 생기고, 이 시점엔 대기열이 비어 있어 매칭 실패.
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)])
        self.assertIsNone(monitor._tracks[1].plate_number)

        # 그 다음에야 OCR 이벤트가 도착(시간창 안).
        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))

        # 같은 트랙이 다음 프레임에도 여전히 구역 안에 있으면 재시도로 매칭돼야 한다.
        monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=1))]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1234")

    def test_entry_event_matches_once_zone_overlap_increases_on_later_frame(self) -> None:
        """리뷰 반영: 첫 프레임의 구역 겹침이 임계값 미만이어도, 다음 프레임에 임계값을 넘으면 매칭돼야 한다."""

        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))

        # 첫 프레임: 구역 겹침이 임계값(40%) 미만 (막 진입 중).
        low_overlap_bbox = BoundingBox(0.20, 0.20, 0.50, 0.50)
        monitor.update(
            [VehicleBox(track_id=1, bbox=low_overlap_bbox, confidence=0.9, frame_id=1, captured_at=base_time)]
        )
        self.assertIsNone(monitor._tracks[1].plate_number)

        # 다음 프레임: 완전히 진입해서 겹침이 임계값을 넘음 → 재시도로 매칭돼야 한다.
        high_overlap_bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=high_overlap_bbox, confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=1),
                )
            ]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1234")

    def test_entry_events_matched_in_captured_at_order_not_insertion_order(self) -> None:
        """리뷰 반영: add_entry_event 호출 순서가 아니라 captured_at 순으로 매칭돼야 한다."""

        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        # 나중에(시간상) 입차한 차의 이벤트를 먼저 추가하고, 더 이른 이벤트를 나중에 추가한다.
        monitor.add_entry_event(EntryEvent(plate_number="LATER", captured_at=base_time + timedelta(seconds=5)))
        monitor.add_entry_event(EntryEvent(plate_number="EARLIER", captured_at=base_time))

        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=6),
                )
            ]
        )
        # 삽입 순서(LATER가 먼저)가 아니라 촬영 시각 순(EARLIER가 더 이름)으로 매칭돼야 한다.
        self.assertEqual(monitor._tracks[1].plate_number, "EARLIER")

    def test_pending_entry_events_pruned_even_without_matching_attempt(self) -> None:
        """리뷰 반영: 매칭 시도가 한 번도 없어도(구역 근처에 트랙이 안 생겨도) 대기열이 계속 정리돼야 한다."""

        registry = ZoneRegistry([])  # ENTRY_EXIT 구역 자체가 없어서 매칭 시도가 전혀 발생하지 않는다.
        monitor = ViolationMonitor(registry, entry_match_window_seconds=5.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        self.assertEqual(len(monitor._pending_entry_events), 1)

        # 시간창(5초)을 넘긴 뒤에도, 아무 트랙도 없이 update()만 호출되면 정리돼야 한다.
        monitor.update(
            [
                VehicleBox(
                    track_id=99, bbox=BoundingBox(0.6, 0.6, 0.8, 0.8), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=10),
                )
            ]
        )
        self.assertEqual(len(monitor._pending_entry_events), 0)

    def test_zone_registry_from_file_parses_wire_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 12,
                                "zoneNumber": "GEN-01",
                                "zoneType": "GENERAL",
                                "allowedMinutes": None,
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = ZoneRegistry.from_file(path)
        zone = registry.get(12)
        self.assertEqual(zone.zone_type, ZoneType.GENERAL)
        self.assertEqual(zone.zone_number, "GEN-01")
        self.assertIsInstance(zone.zone_id, int)

    def test_zone_registry_from_file_rejects_legacy_snake_case(self) -> None:
        """구 포맷을 조용히 무시하면 빈 레지스트리로 돌아 판정이 전부 없어진다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zone_id": "GEN-01",
                                "zone_type": "GENERAL",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_zone_registry_from_file_rejects_empty_zones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(json.dumps({"zones": []}), encoding="utf-8")
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_zone_registry_from_file_parses_allowed_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "EV-01",
                                "zoneType": "EV_FAST",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                                "allowedMinutes": 120,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = ZoneRegistry.from_file(path)
        self.assertEqual(registry.get(1).allowed_minutes, 120.0)

    def test_zone_registry_from_file_defaults_allowed_minutes_to_none(self) -> None:
        """기존 zones 파일(allowedMinutes 필드 없음)과의 호환성 확인."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "GEN-01",
                                "zoneType": "GENERAL",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = ZoneRegistry.from_file(path)
        self.assertIsNone(registry.get(1).allowed_minutes)

    def test_zone_registry_from_file_rejects_non_positive_allowed_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "EV-01",
                                "zoneType": "EV_FAST",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                                "allowedMinutes": 0,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_zone_registry_from_file_rejects_non_finite_allowed_minutes(self) -> None:
        """리뷰 반영(I-3/319): json.loads는 표준이 아닌 NaN/Infinity를 float로 그대로
        파싱하는데, `<= 0` 검사만으로는 NaN이 통과해(NaN과의 비교는 항상 False)
        EV_OVERSTAY가 크래시 없이 영구적으로 발동하지 않는 조용한 실패로 이어진다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "EV-01",
                                "zoneType": "EV_FAST",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                                "allowedMinutes": float("nan"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_zone_registry_from_file_rejects_bool_allowed_minutes(self) -> None:
        """allowedMinutes에 bool이 오면 거부한다(319 리뷰 I-3).

        float(True)는 1.0이라 유한한 양수 검사를 통과한다 — 그러면 명백한
        설정 오기가 "1분 허용"이라는 엉뚱한 정책으로 조용히 적용된다.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "EV-01",
                                "zoneType": "EV_FAST",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                                "allowedMinutes": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_zone_registry_from_file_rejects_infinite_allowed_minutes(self) -> None:
        """allowedMinutes = Infinity도 NaN과 같은 이유로 거부한다(319 리뷰 I-3).

        json.loads가 비표준 Infinity 리터럴을 float('inf')로 파싱하는데,
        dwell >= inf는 항상 False라 EV_OVERSTAY가 조용히 영구 비활성화된다.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "EV-01",
                                "zoneType": "EV_FAST",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                                "allowedMinutes": float("inf"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_zone_registry_from_file_rejects_duplicate_zone_id(self) -> None:
        """zoneId 중복을 조용히 덮어쓰면 구역 하나가 판정에서 통째로 사라진다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "GEN-01",
                                "zoneType": "GENERAL",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                            },
                            {
                                "zoneId": 1,
                                "zoneNumber": "GEN-02",
                                "zoneType": "GENERAL",
                                "polygon": [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

    def test_zone_registry_from_file_rejects_duplicate_zone_number(self) -> None:
        """zoneNumber 중복은 zoneId가 달라도 오버레이·로그 라벨이 모호해진다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 1,
                                "zoneNumber": "GEN-01",
                                "zoneType": "GENERAL",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                            },
                            {
                                "zoneId": 2,
                                "zoneNumber": "GEN-01",
                                "zoneType": "GENERAL",
                                "polygon": [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)
