import { useEffect } from 'react';

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

  // TODO(#임시): 실제 zoneNumber 포맷 확인용. 원인 파악되면 제거한다.
  useEffect(() => {
    if (summary) {
      console.info('[DEBUG] zoneNumbers =', summary.spots.map((spot) => `${spot.zoneNumber} (${spot.zoneType})`));
    }
  }, [summary]);

  return { summary, isLoading, isRefreshing, error, refetch };
}
