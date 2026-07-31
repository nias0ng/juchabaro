import { useEffect, useState } from 'react';

import { getMoveRequests } from '@/features/move-request/api/move-request-api';
import type { MoveRequestScope, MoveRequestSummary } from '@/features/move-request/api/types';
import { useAuth } from '@/providers/auth-provider';

export function useMoveRequests(scope: MoveRequestScope) {
  const { accessToken, status } = useAuth();
  const [moveRequests, setMoveRequests] = useState<MoveRequestSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken) {
      setMoveRequests([]);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    getMoveRequests(scope, accessToken)
      .then((result) => {
        if (isMounted) setMoveRequests(result.moveRequests);
      })
      .catch((requestError: unknown) => {
        if (!isMounted) return;
        setMoveRequests([]);
        setError(
          requestError instanceof Error ? requestError : new Error('이동 요청 내역을 불러오지 못했습니다.'),
        );
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [scope, status, accessToken]);

  return { moveRequests, isLoading, error };
}
