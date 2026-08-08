import { useIsFocused } from '@react-navigation/native';
import { useQuery } from '@tanstack/react-query';

import { getMoveRequestDetail } from '@/features/move-request/api/move-request-api';
import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

// 서버가 상태 변화를 push해줄 방법이 없어서(REST GET/POST뿐), RESPONDED/REMINDER_SENT로 대기하는 동안은
// 이 화면에 머무는 동안만 이 주기로 다시 조회해서 백엔드가 상태를 바꿨는지 스스로 확인한다.
const POLL_INTERVAL_MS = 10_000;

/**
 * 이동 요청 상세를 조회하고, 대기 상태(RESPONDED/REMINDER_SENT)인 동안엔 주기적으로 재조회한다.
 * API: GET /api/move-requests/{requestId}
 */
export function useMoveRequestDetail(requestId: number | null) {
  const { accessToken, status } = useAuth();
  const isFocused = useIsFocused();

  const query = useQuery({
    queryKey: queryKeys.moveRequests.detail(requestId ?? -1),
    queryFn: () => getMoveRequestDetail(requestId!, accessToken!),
    enabled: status === 'authenticated' && !!accessToken && requestId !== null,
    refetchInterval: (q) => {
      if (!isFocused) return false;
      const requestStatus = q.state.data?.requestStatus;
      return requestStatus === 'RESPONDED' || requestStatus === 'REMINDER_SENT' ? POLL_INTERVAL_MS : false;
    },
    refetchIntervalInBackground: false,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  return {
    detail: query.data ?? null,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    // 백그라운드 갱신 실패는 이미 화면에 표시된 데이터를 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    error: query.data === undefined ? query.error : null,
    refetch: query.refetch,
  };
}
