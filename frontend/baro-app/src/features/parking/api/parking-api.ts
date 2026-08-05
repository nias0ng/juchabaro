import { getJson } from '@/services/http-client';

import type { ParkingSession, ParkingZoneSummary } from './types';

type ParkingSessionsResult = {
  sessions: ParkingSession[];
};

export async function getMyParkingSessions(accessToken: string): Promise<ParkingSession[]> {
  const result = await getJson<ParkingSessionsResult>('/api/parking-sessions/me', accessToken);
  return result.sessions;
}

export async function getParkingZoneSummary(accessToken: string): Promise<ParkingZoneSummary> {
  return getJson<ParkingZoneSummary>('/api/parking-zones/summary', accessToken);
}
