import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';
import { getMoveRequests } from '@/features/move-request/api/move-request-api';
import type { MoveRequestListItem, MoveRequestScope } from '@/features/move-request/api/types';

async function fetchMoveRequestListItems(scope: MoveRequestScope, accessToken: string): Promise<MoveRequestListItem[]> {
  const result = await getMoveRequests(scope, accessToken);
  return result.moveRequests;
}

export function useMoveRequests(scope: MoveRequestScope) {
  const {
    data: moveRequests,
    isLoading,
    isRefreshing,
    error,
    refetch,
  } = useAuthenticatedQuery<MoveRequestListItem[]>(
    (accessToken) => fetchMoveRequestListItems(scope, accessToken),
    [],
    '이동 요청 내역을 불러오지 못했습니다.',
    [scope],
    { pollIntervalMs: 15_000 },
  );

  return { moveRequests, isLoading, isRefreshing, error, refetch };
}
