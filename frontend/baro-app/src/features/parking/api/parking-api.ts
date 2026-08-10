/** 주차 세션/구역 현황 API 래퍼. */
import { getJson } from '@/services/http-client';

import type { ParkingSession, ParkingZoneSummary } from './types';

type ParkingSessionsResult = {
  sessions: ParkingSession[];
};

/** GET /api/parking-sessions/me — 내 차량들의 현재 주차 세션(위치 등)을 조회한다. */
export async function getMyParkingSessions(accessToken: string): Promise<ParkingSession[]> {
  const result = await getJson<ParkingSessionsResult>('/api/parking-sessions/me', accessToken);
  return result.sessions;
}

/** GET /api/parking-zones/summary — 층별/구역별 주차 현황 요약을 조회한다. */
export async function getParkingZoneSummary(accessToken: string): Promise<ParkingZoneSummary> {
  return getJson<ParkingZoneSummary>('/api/parking-zones/summary', accessToken);
}
