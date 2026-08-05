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

export type ParkingFloorKey = 'B1' | 'B2' | 'B3';

export type ParkingFloorLayout = {
  mainLayout: (string | null)[][];
  sideByRow: (string | null)[];
};

export type ParkingStatusDisplay = {
  congestionLevel: CongestionLevel;
  congestionLabel: string;
  occupiedLabel: string;
  availableLabel: string;
  violationLabel: string;
  cells: SpotCell[];
};

// 관리자 웹 주차장 현황과 동일한 물리 배치다. 구역 번호가 추가되거나 변경되면
// admin-web의 floorZoneLayout과 이 함수를 함께 갱신해야 한다.
export function floorZoneLayout(floor: ParkingFloorKey): ParkingFloorLayout {
  const floorDigit = floor.slice(1);
  const number = (value: number) => `${floor}-${String(value).padStart(2, '0')}`;
  const special = (type: string, sequence: number) =>
    `${type}${floorDigit}-${String(sequence).padStart(2, '0')}`;

  return {
    mainLayout: [
      [number(17), number(18), number(19), number(20)],
      [number(13), number(14), number(15), number(16)],
      [number(9), number(10), number(11), number(12)],
      [special('D', 2), special('EV', 2), number(7), number(8)],
      [special('D', 1), special('EV', 1), number(5), number(6)],
      [number(1), number(2), number(3), number(4)],
    ],
    sideByRow: [null, number(21), number(22), number(23), number(24), null],
  };
}

function floorZoneNumbers(floor: ParkingFloorKey): Set<string> {
  const { mainLayout, sideByRow } = floorZoneLayout(floor);
  return new Set(
    [...mainLayout.flat(), ...sideByRow]
      .filter((value): value is string => value !== null)
      .map((value) => value.trim()),
  );
}

function toSpotCellKind(spot: ParkingSpotSummary, myZoneNumbers: ReadonlySet<string>): SpotCellKind {
  if (spot.occupancyStatus === 'VIOLATION') return 'violation';
  if (myZoneNumbers.has(spot.zoneNumber.trim())) return 'mine';
  if (spot.occupancyStatus === 'OCCUPIED') return 'occupied';
  return 'empty';
}

// 화면에서 표시할 문자열/칸 상태로 변환
export function toParkingStatusDisplay(
  summary: ParkingZoneSummary,
  myZoneNumbers: readonly string[],
  floor?: ParkingFloorKey,
): ParkingStatusDisplay {
  const myZoneNumberSet = new Set(myZoneNumbers.map((zoneNumber) => zoneNumber.trim()));
  const expectedZoneNumbers = floor ? floorZoneNumbers(floor) : null;
  const spots = expectedZoneNumbers
    ? summary.spots.filter((spot) => expectedZoneNumbers.has(spot.zoneNumber.trim()))
    : summary.spots;
  const occupiedSpots = spots.filter((spot) => spot.occupancyStatus !== 'EMPTY').length;
  const availableSpots = spots.length - occupiedSpots;
  const violationCount = spots.filter((spot) => spot.occupancyStatus === 'VIOLATION').length;
  const congestionRate = spots.length === 0 ? 0 : Math.round((occupiedSpots * 100) / spots.length);
  const congestionLevel: CongestionLevel =
    congestionRate >= 70 ? 'HIGH' : congestionRate >= 40 ? 'MEDIUM' : 'LOW';

  return {
    congestionLevel,
    congestionLabel: `혼잡도 ${CONGESTION_LEVEL_LABEL[congestionLevel]} · ${congestionRate}%`,
    occupiedLabel: `주차 중 ${occupiedSpots}`,
    availableLabel: `비어 있음 ${availableSpots}`,
    violationLabel: `위반 ${violationCount}`,
    cells: spots.map((spot) => ({
      spotCode: spot.zoneNumber.trim(),
      kind: toSpotCellKind(spot, myZoneNumberSet),
      spotType: spot.zoneType,
    })),
  };
}
