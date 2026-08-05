import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';

import { getParkingZoneSummary } from '../api/parking-api';
import type { ParkingZoneSummary } from '../api/types';

export function useParkingZoneSummary() {
  const { data: summary, isLoading, isRefreshing, error, refetch } = useAuthenticatedQuery<ParkingZoneSummary | null>(
    getParkingZoneSummary,
    null,
    '주차 현황을 불러오지 못했습니다.',
    [],
    { pollIntervalMs: 30_000 },
  );

  return { summary, isLoading, isRefreshing, error, refetch };
}
