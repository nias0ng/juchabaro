import type { CongestionLevel, ParkingSpot, ParkingZoneSummary, SpotType } from '../api/types';

const CONGESTION_LEVEL_LABEL: Record<CongestionLevel, string> = {
  LOW: '여유',
  MEDIUM: '보통',
  HIGH: '혼잡',
};

// 지도 미리보기 칸 하나의 렌더링용 상태. '내 차'는 spotCode 비교로 프론트에서 판단한다.
export type SpotCellKind = 'empty' | 'occupied' | 'violation' | 'mine';

export type SpotCell = {
  spotCode: string;
  kind: SpotCellKind;
  spotType: SpotType;
};

export type ParkingStatusDisplay = {
  congestionLevel: CongestionLevel;
  congestionLabel: string;
  occupiedLabel: string;
  availableLabel: string;
  violationLabel: string;
  cells: SpotCell[];
};

function toSpotCellKind(spot: ParkingSpot, mySpotCodes: ReadonlySet<string>): SpotCellKind {
  if (spot.status === 'VIOLATION') return 'violation';
  if (mySpotCodes.has(spot.spotCode)) return 'mine';
  if (spot.status === 'OCCUPIED') return 'occupied';
  return 'empty';
}

// 화면에서 표시할 문자열/칸 상태로 변환
export function toParkingStatusDisplay(
  summary: ParkingZoneSummary,
  mySpotCodes: readonly string[],
): ParkingStatusDisplay {
  const mySpotCodeSet = new Set(mySpotCodes);

  return {
    congestionLevel: summary.congestionLevel,
    congestionLabel: `혼잡도 ${CONGESTION_LEVEL_LABEL[summary.congestionLevel]} · ${summary.congestionRate}%`,
    occupiedLabel: `주차 중 ${summary.occupiedSpots}`,
    availableLabel: `비어 있음 ${summary.availableSpots}`,
    violationLabel: `위반 ${summary.violationCount}`,
    cells: summary.spots.map((spot) => ({
      spotCode: spot.spotCode,
      kind: toSpotCellKind(spot, mySpotCodeSet),
      spotType: spot.spotType,
    })),
  };
}
