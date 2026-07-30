import { useCallback, useEffect, useState } from 'react';

import { getMoveRequestDetail } from '@/features/move-request/api/move-request-api';
import type { MoveRequestDetail } from '@/features/move-request/api/types';
import { useAuth } from '@/providers/auth-provider';

export function useMoveRequestDetail(requestId: number | null) {
  const { accessToken, status } = useAuth();
  const [detail, setDetail] = useState<MoveRequestDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  // fetch 이펙트를 다시 돌리기 위한 트리거. 값 자체는 의미 없고 바뀌기만 하면 된다.
  const [refetchTick, setRefetchTick] = useState(0);

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken || requestId === null) {
      setDetail(null);
      setError(null);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    getMoveRequestDetail(requestId, accessToken)
      .then((result) => {
        if (isMounted) setDetail(result);
      })
      .catch((requestError: unknown) => {
        if (!isMounted) return;

        setDetail(null);
        setError(
          requestError instanceof Error
            ? requestError
            : new Error('이동 요청 정보를 불러오지 못했습니다.'),
        );
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [status, accessToken, requestId, refetchTick]);

  const refetch = useCallback(() => {
    setRefetchTick((tick) => tick + 1);
  }, []);

  return { detail, isLoading, error, refetch };
}
