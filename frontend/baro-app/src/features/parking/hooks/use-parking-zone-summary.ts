import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';

import { getParkingZoneSummary } from '../api/parking-api';
import type { ParkingZoneSummary } from '../api/types';

export function useParkingZoneSummary() {
  const { data: summary, isLoading, error } = useAuthenticatedQuery<ParkingZoneSummary | null>(
    getParkingZoneSummary,
    null,
    '주차 현황을 불러오지 못했습니다.',
  );

  return { summary, isLoading, error };
}
