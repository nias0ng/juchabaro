import { useQuery } from '@tanstack/react-query';

import { getMoveRequests } from '@/features/move-request/api/move-request-api';
import type { MoveRequestListItem, MoveRequestScope } from '@/features/move-request/api/types';
import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

async function fetchMoveRequestListItems(scope: MoveRequestScope, accessToken: string): Promise<MoveRequestListItem[]> {
  const result = await getMoveRequests(scope, accessToken);
  return result.moveRequests;
}

export function useMoveRequests(scope: MoveRequestScope) {
  const { accessToken, status } = useAuth();

  const query = useQuery({
    queryKey: queryKeys.moveRequests.list(scope),
    queryFn: () => fetchMoveRequestListItems(scope, accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  return {
    moveRequests: query.data ?? [],
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    // 백그라운드 갱신 실패는 이미 화면에 표시된 데이터를 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    error: query.data === undefined ? query.error : null,
    refetch: query.refetch,
  };
}
