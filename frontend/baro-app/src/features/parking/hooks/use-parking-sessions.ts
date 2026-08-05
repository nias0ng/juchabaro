import { useQuery } from '@tanstack/react-query';

import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

import { getMyParkingSessions } from '../api/parking-api';

export function useParkingSessions() {
  const { accessToken, status } = useAuth();

  const query = useQuery({
    queryKey: queryKeys.parking.sessions(),
    queryFn: () => getMyParkingSessions(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  return {
    sessions: query.data ?? [],
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
