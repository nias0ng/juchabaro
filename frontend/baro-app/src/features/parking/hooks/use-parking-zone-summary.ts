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
    // 백그라운드 갱신 실패는 이미 화면에 표시된 데이터를 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    error: query.data === undefined ? query.error : null,
    refetch: query.refetch,
  };
}
