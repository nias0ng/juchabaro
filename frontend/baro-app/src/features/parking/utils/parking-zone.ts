import type {
  CongestionLevel,
  ParkingSpotSummary,
  ParkingZoneSummary,
  ParkingZoneType,
} from '../api/types';

const CONGESTION_LEVEL_LABEL: Record<CongestionLevel, string> = {
  LOW: '여유',
  MEDIUM: '보통',
  HIGH: '혼잡',
};

// 지도 컴포넌트 내부에서는 주차면 번호를 spotCode로 표현한다.
export type SpotCellKind = 'empty' | 'occupied' | 'violation' | 'mine';

export type SpotCell = {
  spotCode: string;
  kind: SpotCellKind;
  spotType: ParkingZoneType;
};

export type ParkingStatusDisplay = {
  congestionLevel: CongestionLevel;
  congestionLabel: string;
  occupiedLabel: string;
  availableLabel: string;
  violationLabel: string;
  cells: SpotCell[];
};

function toSpotCellKind(spot: ParkingSpotSummary, myZoneNumbers: ReadonlySet<string>): SpotCellKind {
  if (spot.occupancyStatus === 'VIOLATION') return 'violation';
  if (myZoneNumbers.has(spot.zoneNumber)) return 'mine';
  if (spot.occupancyStatus === 'OCCUPIED') return 'occupied';
  return 'empty';
}

// 화면에서 표시할 문자열/칸 상태로 변환
export function toParkingStatusDisplay(
  summary: ParkingZoneSummary,
  myZoneNumbers: readonly string[],
): ParkingStatusDisplay {
  const myZoneNumberSet = new Set(myZoneNumbers);

  return {
    congestionLevel: summary.congestionLevel,
    congestionLabel: `혼잡도 ${CONGESTION_LEVEL_LABEL[summary.congestionLevel]} · ${summary.congestionRate}%`,
    occupiedLabel: `주차 중 ${summary.occupiedSpots}`,
    availableLabel: `비어 있음 ${summary.availableSpots}`,
    violationLabel: `위반 ${summary.violationCount}`,
    cells: summary.spots.map((spot) => ({
      spotCode: spot.zoneNumber,
      kind: toSpotCellKind(spot, myZoneNumberSet),
      spotType: spot.zoneType,
    })),
  };
}
