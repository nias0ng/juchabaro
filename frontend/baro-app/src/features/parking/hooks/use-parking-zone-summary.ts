import { useIsFocused } from '@react-navigation/native';
import { useQuery } from '@tanstack/react-query';

import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

import { getParkingZoneSummary } from '../api/parking-api';

// 시연용 폴링 주기: 1초 / 기존 폴링 주기: 20초
const ACTIVE_SCREEN_REFETCH_INTERVAL_MS = 1_000;

/**
 * 층별/구역별 주차 현황 요약을 조회한다.
 * API: GET /api/parking-zones/summary
 */
export function useParkingZoneSummary() {
  const { accessToken, status } = useAuth();
  const isFocused = useIsFocused();

  const query = useQuery({
    queryKey: queryKeys.parking.zoneSummary(),
    queryFn: () => getParkingZoneSummary(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
    refetchInterval: isFocused ? ACTIVE_SCREEN_REFETCH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
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
