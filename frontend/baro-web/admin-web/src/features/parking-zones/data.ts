import type { CellVariant, FloorKey, ParkingSpot, SpotStatus, SpotType } from './types';

const FLOOR_LABELS: Record<FloorKey, string> = {
  B1: '지하 1층',
  B2: '지하 2층',
  B3: '지하 3층',
};

export const FLOOR_KEYS: FloorKey[] = ['B1', 'B2', 'B3'];

export function floorLabel(floor: FloorKey): string {
  return FLOOR_LABELS[floor];
}

// baro-app(frontend/baro-app/src/features/parking/mocks/parking-floor-overview.mock.ts)의
// 층별 주차 칸 번호·위치·유형·상태를 그대로 가져온다. 자리(배열 인덱스=그리드 위치)는
// 고정이며, 실제 칸이 없는 자리는 null로 남겨 그 자리만 빈 배경으로 표시한다.
type RawSpot = { code: string; status: SpotStatus; type: SpotType } | null;

function spot(code: string, status: SpotStatus, type: SpotType = 'GENERAL'): RawSpot {
  return { code, status, type };
}

export const MAIN_SPOTS_PER_FLOOR = 24;
export const SIDE_SPOTS_PER_FLOOR = 6;
export const SLOTS_PER_FLOOR = MAIN_SPOTS_PER_FLOOR + SIDE_SPOTS_PER_FLOOR;

const B1_MAIN: RawSpot[] = [
  spot('B1-01', 'OCCUPIED'),
  spot('B1-02', 'VIOLATION'),
  spot('B1-03', 'OCCUPIED'),
  spot('B1-04', 'OCCUPIED'),
  spot('B1-05', 'OCCUPIED'),
  spot('B1-06', 'EMPTY'),
  spot('B1-07', 'OCCUPIED'),
  spot('B1-08', 'OCCUPIED'),
  spot('B1-09', 'EMPTY'),
  spot('B1-10', 'OCCUPIED'),
  spot('B1-11', 'EMPTY'),
  spot('B1-12', 'OCCUPIED'),
  spot('B1-13', 'EMPTY'),
  spot('B1-14', 'OCCUPIED'),
  spot('B1-15', 'EMPTY'),
  spot('B1-16', 'OCCUPIED'),
  spot('B1-EV1', 'OCCUPIED', 'EV_CHARGING'),
  spot('B1-EV2', 'OCCUPIED', 'EV_CHARGING'),
  spot('B1-17', 'EMPTY'),
  spot('B1-18', 'VIOLATION'),
  spot('B1-D1', 'OCCUPIED', 'DISABLED'),
  spot('B1-D2', 'OCCUPIED', 'DISABLED'),
  spot('B1-19', 'OCCUPIED'),
  spot('B1-20', 'MINE'),
];

const B1_SIDE: RawSpot[] = [
  spot('B1-S1', 'OCCUPIED'),
  spot('B1-S2', 'EMPTY'),
  spot('B1-S3', 'OCCUPIED'),
  spot('B1-S4', 'OCCUPIED'),
  null,
  null,
];

const B2_MAIN: RawSpot[] = [
  spot('B2-01', 'OCCUPIED'),
  spot('B2-02', 'EMPTY'),
  spot('B2-03', 'OCCUPIED'),
  spot('B2-04', 'EMPTY'),
  spot('B2-05', 'EMPTY'),
  spot('B2-06', 'OCCUPIED'),
  spot('B2-07', 'EMPTY'),
  spot('B2-08', 'OCCUPIED'),
  spot('B2-09', 'EMPTY'),
  spot('B2-10', 'EMPTY'),
  spot('B2-11', 'OCCUPIED'),
  spot('B2-12', 'EMPTY'),
  spot('B2-13', 'OCCUPIED'),
  spot('B2-14', 'EMPTY'),
  spot('B2-15', 'OCCUPIED'),
  spot('B2-16', 'EMPTY'),
  spot('B2-EV1', 'EMPTY', 'EV_CHARGING'),
  spot('B2-EV2', 'EMPTY', 'EV_CHARGING'),
  spot('B2-17', 'OCCUPIED'),
  spot('B2-18', 'EMPTY'),
  spot('B2-D1', 'EMPTY', 'DISABLED'),
  spot('B2-D2', 'OCCUPIED', 'DISABLED'),
  spot('B2-19', 'EMPTY'),
  spot('B2-20', 'OCCUPIED'),
];

const B2_SIDE: RawSpot[] = [
  spot('B2-S1', 'OCCUPIED'),
  spot('B2-S2', 'OCCUPIED'),
  spot('B2-S3', 'VIOLATION'),
  spot('B2-S4', 'VIOLATION'),
  spot('B2-S5', 'EMPTY'),
  spot('B2-S6', 'OCCUPIED'),
];

const B3_MAIN: RawSpot[] = [
  spot('B3-01', 'EMPTY'),
  spot('B3-02', 'EMPTY'),
  spot('B3-03', 'OCCUPIED'),
  spot('B3-04', 'EMPTY'),
  spot('B3-05', 'OCCUPIED'),
  spot('B3-06', 'EMPTY'),
  spot('B3-07', 'EMPTY'),
  spot('B3-08', 'OCCUPIED'),
  spot('B3-09', 'EMPTY'),
  spot('B3-10', 'EMPTY'),
  spot('B3-11', 'OCCUPIED'),
  spot('B3-12', 'EMPTY'),
  spot('B3-13', 'EMPTY'),
  spot('B3-14', 'OCCUPIED'),
  spot('B3-15', 'EMPTY'),
  spot('B3-16', 'EMPTY'),
  spot('B3-EV1', 'OCCUPIED', 'EV_CHARGING'),
  spot('B3-EV2', 'EMPTY', 'EV_CHARGING'),
  spot('B3-17', 'EMPTY'),
  spot('B3-18', 'OCCUPIED'),
  spot('B3-D2', 'EMPTY', 'DISABLED'),
  spot('B3-D1', 'EMPTY', 'DISABLED'),
  spot('B3-19', 'EMPTY'),
  spot('B3-20', 'EMPTY'),
];

const B3_SIDE: RawSpot[] = [
  spot('B3-S1', 'EMPTY'),
  spot('B3-S2', 'OCCUPIED'),
  spot('B3-S3', 'EMPTY'),
  spot('B3-S4', 'EMPTY'),
  spot('B3-S5', 'EMPTY'),
  spot('B3-S6', 'EMPTY'),
];

const RAW_FLOORS: Record<FloorKey, { main: RawSpot[]; side: RawSpot[] }> = {
  B1: { main: B1_MAIN, side: B1_SIDE },
  B2: { main: B2_MAIN, side: B2_SIDE },
  B3: { main: B3_MAIN, side: B3_SIDE },
};

function toParkingSpot(raw: RawSpot, floor: FloorKey, isSide: boolean): ParkingSpot | null {
  if (!raw) return null;
  return {
    ...raw,
    floor,
    isSide,
    lastOccupiedAt: raw.status === 'EMPTY' ? '-' : '2026.07.22 10:15',
  };
}

export type ParkingFloor = {
  key: FloorKey;
  label: string;
  main: (ParkingSpot | null)[];
  side: (ParkingSpot | null)[];
};

export const FLOORS: ParkingFloor[] = FLOOR_KEYS.map((key) => ({
  key,
  label: floorLabel(key),
  main: RAW_FLOORS[key].main.map((raw) => toParkingSpot(raw, key, false)),
  side: RAW_FLOORS[key].side.map((raw) => toParkingSpot(raw, key, true)),
}));

// 층별로 항상 main 24칸 + side 6칸 = 30자리 순서로 이어 붙인다(일부 자리는 null).
// 이 고정 순서 덕분에 층 인덱스만으로 해당 층의 30자리를 그대로 잘라낼 수 있다.
export const INITIAL_SPOTS: (ParkingSpot | null)[] = FLOORS.flatMap((floor) => [...floor.main, ...floor.side]);

export function computeZoneStats(spots: ParkingSpot[]) {
  return {
    total: spots.length,
    general: spots.filter((s) => s.type === 'GENERAL').length,
    disabled: spots.filter((s) => s.type === 'DISABLED').length,
    ev: spots.filter((s) => s.type === 'EV_CHARGING').length,
  };
}

// 위반 > 장애인 구역 > 전기차 구역 > 사용 중(MINE 포함) > 비어 있음 순으로 우선한다(baro-app과 동일한 우선순위,
// 다만 관리자 웹에서는 MINE을 별도 표시 없이 OCCUPIED와 동일하게 그린다).
export function toCellVariant(spot: ParkingSpot): CellVariant {
  if (spot.status === 'VIOLATION') return 'violation';
  if (spot.type === 'DISABLED') return 'disabled';
  if (spot.type === 'EV_CHARGING') return 'ev';
  if (spot.status === 'OCCUPIED' || spot.status === 'MINE') return 'occupied';
  return 'empty';
}

export function statusLabel(status: SpotStatus): string {
  if (status === 'VIOLATION') return '위반';
  if (status === 'EMPTY') return '사용 가능';
  return '사용 중';
}

// 허용 시간은 구역별로 따로 입력받는 값이 아니라 유형에서 그대로 정해진다.
export function allowedTimeLabel(type: SpotType): string {
  return type === 'EV_CHARGING' ? '최대 14시간' : '-';
}
