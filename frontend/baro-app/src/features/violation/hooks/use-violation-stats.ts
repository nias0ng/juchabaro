import { useQuery } from '@tanstack/react-query';

import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

import { getViolationStats } from '../api/violation-api';

/**
 * 이동 요청 기반 위반 통계를 조회한다.
 * API: GET /api/move-requests/stats
 */
export function useViolationStats() {
  const { accessToken, status } = useAuth();

  const query = useQuery({
    queryKey: queryKeys.violation.stats(),
    queryFn: () => getViolationStats(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  return {
    stats: query.data ?? null,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    // 백그라운드 갱신 실패는 이미 화면에 표시된 데이터를 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    error: query.data === undefined ? query.error : null,
    refetch: query.refetch,
  };
}
