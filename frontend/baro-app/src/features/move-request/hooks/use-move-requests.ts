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
    error: query.error,
    refetch: query.refetch,
  };
}
