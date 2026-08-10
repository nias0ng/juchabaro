import { formatPlateNumberDisplay } from '@/features/vehicle/validation/register-car';

import type { ParkingSession, ParkingSessionStatus } from '../api/types';
import { toDisplayZoneNumber } from './parking-zone';

function isEvChargingSession(session: ParkingSession): session is ParkingSession & { dueAt: string } {
  return (
    session.status === 'PARKED' &&
    session.isElectric &&
    session.zoneType === 'EV_CHARGING' &&
    session.dueAt !== null
  );
}

// 테스트 과정에서 같은 차량의 종료되지 않은 세션이 중복으로 남아도 홈 카드가 세션 수만큼
// 늘어나지 않도록, 차량별 가장 최근 입차 세션 하나만 화면에 사용한다.
export function getLatestSessionsByVehicle(sessions: ParkingSession[]): ParkingSession[] {
  const latestByVehicle = new Map<number, ParkingSession>();

  for (const session of sessions) {
    const current = latestByVehicle.get(session.vehicleId);
    if (!current || new Date(session.enteredAt).getTime() > new Date(current.enteredAt).getTime()) {
      latestByVehicle.set(session.vehicleId, session);
    }
  }

  return [...latestByVehicle.values()];
}

// 전기차 충전 구역 이용 차량은 종료 시각이 가까운 순으로 우선하고, 그 외에는 최신 입차 차량을 표시한다.
export function pickPrimarySession(sessions: ParkingSession[]): ParkingSession | null {
  if (sessions.length === 0) return null;

  const evChargingSession = sessions
    .filter(isEvChargingSession)
    .sort((a, b) => new Date(a.dueAt).getTime() - new Date(b.dueAt).getTime())[0];
  if (evChargingSession) return evChargingSession;

  const sorted = [...sessions].sort(
    (a, b) => new Date(b.enteredAt).getTime() - new Date(a.enteredAt).getTime(),
  );

  return sorted[0];
}

export type VehicleStatusDisplay = {
  status: ParkingSessionStatus;
  statusLabel: string;
  statusTime: string;
  plateNumber: string;
  model?: string;
  location: string;
  isEvCharging: boolean;
  dueAt: string | null;
};

export function formatParkingLocation(
  floor: string | null,
  zoneNumber: string | null,
): string {
  const parts = [floor, toDisplayZoneNumber(zoneNumber)].filter(
    (value): value is string => Boolean(value?.trim()),
  );
  return parts.length > 0 ? parts.join(' · ') : '위치 확인 중';
}

// 화면에서 표시할 문자열로 변환
export function toVehicleStatusDisplay(session: ParkingSession): VehicleStatusDisplay {
  const isEvCharging = isEvChargingSession(session);

  return {
    status: session.status,
    statusLabel: session.status === 'VIOLATION' ? '위반 주차' : '정상 주차',
    statusTime: `${formatTime(session.enteredAt)} 입차`,
    plateNumber: formatPlateNumberDisplay(session.plateNumber),
    location: formatParkingLocation(session.floor, session.zoneNumber),
    isEvCharging,
    dueAt: isEvCharging ? session.dueAt : null,
  };
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}
