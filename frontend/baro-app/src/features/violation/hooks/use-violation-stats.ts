import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';

import { getViolationStats } from '../api/violation-api';
import type { ViolationStats } from '../api/types';

export function useViolationStats() {
  const { data, isLoading, isRefreshing, error, refetch } = useAuthenticatedQuery<ViolationStats | null>(
    getViolationStats,
    null,
    '위반 통계를 불러오지 못했습니다.',
    [],
    { pollIntervalMs: 30_000 },
  );

  return {
    stats: data,
    isLoading,
    isRefreshing,
    error,
    refetch,
  };
}
