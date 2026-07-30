import { useEffect, useState } from 'react';

import { getMoveRequestDetail } from '@/features/resident/api/move-request-api';
import type { MoveRequestDetail } from '@/features/resident/api/types';
import { useAuth } from '@/providers/auth-provider';

export function useMoveRequestDetail(requestId: number | null) {
  const { accessToken, status } = useAuth();
  const [detail, setDetail] = useState<MoveRequestDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

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
  }, [status, accessToken, requestId]);

  return { detail, isLoading, error };
}
