import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';

import { getMyParkingSessions } from '../api/parking-api';
import type { ParkingSession } from '../api/types';

export function useParkingSessions() {
  const { data: sessions, isLoading, isRefreshing, error, refetch } = useAuthenticatedQuery<ParkingSession[]>(
    getMyParkingSessions,
    [],
    '주차 세션을 불러오지 못했습니다.',
    [],
    { pollIntervalMs: 30_000 },
  );

  return { sessions, isLoading, isRefreshing, error, refetch };
}
