import { useIsFocused } from '@react-navigation/native';
import { useQuery } from '@tanstack/react-query';

import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

import { getMyParkingSessions } from '../api/parking-api';
import { getLatestSessionsByVehicle } from '../utils/parking-session';

// 시연용 폴링 주기: 1초 / 기존 폴링 주기: 20초
const ACTIVE_SCREEN_REFETCH_INTERVAL_MS = 1_000;

/**
 * 내 차량들의 현재 주차 세션을 조회하고, 차량별 최신 세션만 남긴다.
 * API: GET /api/parking-sessions/me
 */
export function useParkingSessions() {
  const { accessToken, status } = useAuth();
  const isFocused = useIsFocused();

  const query = useQuery({
    queryKey: queryKeys.parking.sessions(),
    queryFn: () => getMyParkingSessions(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
    refetchInterval: isFocused ? ACTIVE_SCREEN_REFETCH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
  useRefetchOnFocus(query.refetch, query.isStale);
  const sessions = getLatestSessionsByVehicle(query.data ?? []);

  return {
    sessions,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    // 백그라운드 갱신 실패는 이미 화면에 표시된 데이터를 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    error: query.data === undefined ? query.error : null,
    refetch: query.refetch,
  };
}
