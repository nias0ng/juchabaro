import type { ParkingSession, ParkingSessionStatus } from '../api/types';

// 최신 입차순으로 대표 차량 정리
export function pickPrimarySession(sessions: ParkingSession[]): ParkingSession | null {
  if (sessions.length === 0) return null;

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
};

// 화면에서 표시할 문자열로 변환
export function toVehicleStatusDisplay(session: ParkingSession): VehicleStatusDisplay {
  return {
    status: session.status,
    statusLabel: session.status === 'VIOLATION' ? '위반 중' : '정상 주차 중',
    statusTime: `${formatTime(session.enteredAt)} 입차`,
    plateNumber: session.plateNumber,
    location: `${session.floor} · ${session.zoneNumber}`,
  };
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}
