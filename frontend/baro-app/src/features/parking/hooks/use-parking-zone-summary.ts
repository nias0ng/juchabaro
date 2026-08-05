import { useQuery } from '@tanstack/react-query';

import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

import { getParkingZoneSummary } from '../api/parking-api';

export function useParkingZoneSummary() {
  const { accessToken, status } = useAuth();

  const query = useQuery({
    queryKey: queryKeys.parking.zoneSummary(),
    queryFn: () => getParkingZoneSummary(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  return {
    summary: query.data ?? null,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
