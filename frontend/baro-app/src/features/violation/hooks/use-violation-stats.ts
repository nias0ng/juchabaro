import { useQuery } from '@tanstack/react-query';

import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

import { getViolationStats } from '../api/violation-api';

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
    error: query.error,
    refetch: query.refetch,
  };
}
