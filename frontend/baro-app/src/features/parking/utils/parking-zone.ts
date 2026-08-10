import type {
  CongestionLevel,
  ParkingSpotSummary,
  ParkingZoneSummary,
  ParkingZoneType,
} from '../api/types';

export type SpotCellKind = 'empty' | 'occupied' | 'mine';

export type SpotCell = {
  spotCode: string;
  kind: SpotCellKind;
  spotType: ParkingZoneType;
};

// AISLE(통로) zone은 주차 칸 코드가 아니라서 "AISLE1-01" 같은 원본 코드를 그대로 보여주면
// 사용자가 혼란스러워한다. 화면에 구역 번호를 보여주는 모든 곳에서 이 함수를 거친다.
export function toDisplayZoneNumber(zoneNumber: string | null): string | null {
  if (!zoneNumber?.trim()) return null;
  return zoneNumber.trim().toUpperCase().startsWith('AISLE') ? '통로주차' : zoneNumber;
}

export const PARKING_FLOORS = ['B1', 'B2', 'B3'] as const;

export type ParkingFloorKey = (typeof PARKING_FLOORS)[number];

export type ParkingFloorLayout = {
  mainLayout: (string | null)[][];
  sideByRow: (string | null)[];
};

export type ParkingStatusDisplay = {
  congestionLevel: CongestionLevel;
  congestionRateLabel: string;
  occupiedLabel: string;
  availableCount: number;
  availableLabel: string;
  violationLabel: string;
  cells: SpotCell[];
};

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
  if (myZoneNumbers.has(spot.zoneNumber.trim())) return 'mine';
  if (spot.occupancyStatus === 'EMPTY') return 'empty';
  return 'occupied';
}

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
    congestionRateLabel: `${congestionRate}%`,
    occupiedLabel: `주차 중 ${occupiedSpots}`,
    availableCount: availableSpots,
    availableLabel: `비어 있음 ${availableSpots}`,
    violationLabel: `위반 ${violationCount}`,
    cells: spots.map((spot) => ({
      spotCode: spot.zoneNumber.trim(),
      kind: toSpotCellKind(spot, myZoneNumberSet),
      spotType: spot.zoneType,
    })),
  };
}
