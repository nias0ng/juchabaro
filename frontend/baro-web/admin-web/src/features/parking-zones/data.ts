import type { CellVariant, CongestionLevel, FloorKey, OccupancyStatus, ParkingSpotSummary, ZoneType } from './types';

export const ZONE_TYPE_LABELS: Record<ZoneType, string> = {
  GENERAL: '일반',
  DISABLED: '장애인 구역',
  EV_CHARGING: '전기차 구역',
  AISLE: '통로',
  ENTRY_EXIT: '입출구',
};

export const ZONE_TYPE_OPTIONS = Object.keys(ZONE_TYPE_LABELS) as ZoneType[];

export function zoneTypeLabel(type: ZoneType): string {
  return ZONE_TYPE_LABELS[type];
}

export function zoneTypeTone(type: ZoneType) {
  if (type === 'EV_CHARGING') return 'success' as const;
  if (type === 'DISABLED') return 'info' as const;
  if (type === 'AISLE' || type === 'ENTRY_EXIT') return 'primary' as const;
  return 'neutral' as const;
}

export const OCCUPANCY_LABELS: Record<OccupancyStatus, string> = {
  EMPTY: '사용 가능',
  OCCUPIED: '사용 중',
  VIOLATION: '위반',
};

export const OCCUPANCY_OPTIONS = Object.keys(OCCUPANCY_LABELS) as OccupancyStatus[];

export function occupancyLabel(status: OccupancyStatus): string {
  return OCCUPANCY_LABELS[status];
}

export function occupancyTone(status: OccupancyStatus) {
  if (status === 'VIOLATION') return 'danger' as const;
  if (status === 'EMPTY') return 'success' as const;
  return 'warning' as const;
}

// 위반 > 장애인 구역 > 전기차 구역 > 사용 중 > 비어 있음 순으로 우선한다(baro-app과 동일한 우선순위).
export function toCellVariant(spot: { zoneType: ZoneType; occupancyStatus: OccupancyStatus }): CellVariant {
  if (spot.occupancyStatus === 'VIOLATION') return 'violation';
  if (spot.zoneType === 'DISABLED') return 'disabled';
  if (spot.zoneType === 'EV_CHARGING') return 'ev';
  if (spot.occupancyStatus === 'OCCUPIED') return 'occupied';
  return 'empty';
}

// 백엔드는 분(allowedMinutes) 단위로 주고받지만, 화면에는 시간 단위로 보여준다.
export function allowedTimeLabel(allowedMinutes: number | null): string {
  if (allowedMinutes === null) return '무제한';
  const hours = allowedMinutes / 60;
  const formatted = Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
  return `${formatted}시간`;
}

export function minutesToHours(allowedMinutes: number | null): number | '' {
  return allowedMinutes !== null ? allowedMinutes / 60 : '';
}

export function hoursToMinutes(hours: number): number {
  return Math.round(hours * 60);
}

export function findSpotSummary(spots: ParkingSpotSummary[], zoneId: number): ParkingSpotSummary | undefined {
  return spots.find((s) => s.zoneId === zoneId);
}

export const CONGESTION_LABELS: Record<CongestionLevel, string> = {
  LOW: '여유',
  MEDIUM: '보통',
  HIGH: '혼잡',
};

export function congestionLabel(level: CongestionLevel): string {
  return CONGESTION_LABELS[level];
}

export function congestionTone(level: CongestionLevel) {
  if (level === 'HIGH') return 'danger' as const;
  if (level === 'MEDIUM') return 'warning' as const;
  return 'success' as const;
}

// B1 실제 물리 배치를 그대로 복제해 B2/B3에 등록했다. 번호칸은 "{층}-01".."{층}-24",
// 특수 구역(장애인/EV)은 "D{층 번호}-01"처럼 층 번호를 붙인다(D1-01=B1, D2-01=B2, D3-01=B3).
export function floorZoneLayout(floor: FloorKey): { mainLayout: (string | null)[][]; sideByRow: (string | null)[] } {
  const floorDigit = floor.slice(1);
  const num = (n: number) => `${floor}-${String(n).padStart(2, '0')}`;
  const special = (type: string, seq: number) => `${type}${floorDigit}-${String(seq).padStart(2, '0')}`;

  const mainLayout: (string | null)[][] = [
    [num(17), num(18), num(19), num(20)],
    [num(13), num(14), num(15), num(16)],
    [num(9), num(10), num(11), num(12)],
    [special('D', 2), special('EV', 2), num(7), num(8)],
    [special('D', 1), special('EV', 1), num(5), num(6)],
    [num(1), num(2), num(3), num(4)],
  ];
  const sideByRow: (string | null)[] = [null, num(21), num(22), num(23), num(24), null];
  return { mainLayout, sideByRow };
}

export function floorZoneNumbers(floor: FloorKey): string[] {
  const { mainLayout, sideByRow } = floorZoneLayout(floor);
  return [...mainLayout.flat(), ...sideByRow].filter((v): v is string => v !== null);
}

// GET /api/zones 응답에 floor 필드가 오지 않아서(백엔드 미구현), zoneNumber 패턴으로 층을
// 역추론한다. "B2-07"처럼 번호칸이면 그 층, "D3-01"/"EV2-01"/"AISLE1-01"/"ENTRY3-01"/
// "EXIT2-01"처럼 특수 구역이면 이름 뒤에 붙은 층 번호로 판단한다.
export function zoneFloorOf(zoneNumber: string): FloorKey | null {
  const trimmed = zoneNumber.trim();
  const mainMatch = /^B([123])-\d{2}$/.exec(trimmed);
  if (mainMatch) return `B${mainMatch[1]}` as FloorKey;

  const specialMatch = /^(?:D|EV|AISLE|ENTRY|EXIT)([123])-\d{2}$/.exec(trimmed);
  if (specialMatch) return `B${specialMatch[1]}` as FloorKey;

  return null;
}

// 구역 목록은 물리 배치 순서(번호칸 B{층}-01..24 → 장애인 D{층}-01,02 → 전기차
// EV{층}-01,02 → 입구 ENTRY{층}-01 → 출구 EXIT{층}-01)로 보여준다. 백엔드가 이 순서로
// 정렬해서 내려준다는 보장이 없어 화면에서 직접 정렬한다.
const ZONE_PREFIX_ORDER = ['B', 'D', 'EV', 'ENTRY', 'EXIT'] as const;

function zoneSortKey(zoneNumber: string): [number, number, string] {
  const trimmed = zoneNumber.trim();
  const match = /^([A-Z]+)\d*-(\d+)$/.exec(trimmed);
  if (!match) return [ZONE_PREFIX_ORDER.length, 0, trimmed];
  const [, prefix, seq] = match;
  const prefixIndex = ZONE_PREFIX_ORDER.indexOf(prefix as (typeof ZONE_PREFIX_ORDER)[number]);
  return [prefixIndex === -1 ? ZONE_PREFIX_ORDER.length : prefixIndex, Number(seq), trimmed];
}

export function compareZoneNumbers(a: string, b: string): number {
  const [rankA, seqA, strA] = zoneSortKey(a);
  const [rankB, seqB, strB] = zoneSortKey(b);
  if (rankA !== rankB) return rankA - rankB;
  if (seqA !== seqB) return seqA - seqB;
  return strA.localeCompare(strB);
}

// 백엔드 GET /api/parking-zones/summary가 층 구분 없이 전체를 한 번에 반환하기 때문에,
// 혼잡도는 응답의 최상위 값을 그대로 쓰지 않고 해당 층 구역만 걸러서 화면에서 직접 계산한다.
export function computeFloorCongestion(
  floor: FloorKey,
  spots: ParkingSpotSummary[],
): { rate: number; level: CongestionLevel } | null {
  const zoneNumbers = new Set(floorZoneNumbers(floor));
  const floorSpots = spots.filter((s) => zoneNumbers.has(s.zoneNumber.trim()));
  if (floorSpots.length === 0) return null;

  const occupied = floorSpots.filter((s) => s.occupancyStatus !== 'EMPTY').length;
  const rate = Math.round((occupied / floorSpots.length) * 100);
  const level: CongestionLevel = rate >= 70 ? 'HIGH' : rate >= 40 ? 'MEDIUM' : 'LOW';
  return { rate, level };
}
