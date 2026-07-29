import { getJson } from '@/services/http-client';

import { getMyParkingSessionsMock, getParkingZoneSummaryMock } from './parking-api.mock';
import type { ParkingSession, ParkingZoneSummary } from './types';

// TODO(parking-api): 백엔드에서 /api/parking-sessions/me, /api/parking-zones/summary가 실제로 배포되면 이 값을 false로 바꾼다.
const useMockParking = __DEV__ && process.env.EXPO_PUBLIC_USE_MOCK_PARKING === 'true';

type ParkingSessionsResult = {
  sessions: ParkingSession[];
};

export async function getMyParkingSessions(accessToken: string): Promise<ParkingSession[]> {
  if (useMockParking) {
    return getMyParkingSessionsMock();
  }

  const result = await getJson<ParkingSessionsResult>('/api/parking-sessions/me', accessToken);
  return result.sessions;
}

export async function getParkingZoneSummary(accessToken: string): Promise<ParkingZoneSummary> {
  if (useMockParking) {
    return getParkingZoneSummaryMock();
  }

  return getJson<ParkingZoneSummary>('/api/parking-zones/summary', accessToken);
}
