import { useCallback, useEffect, useState } from 'react';

import { getMoveRequestDetail } from '@/features/move-request/api/move-request-api';
import type { MoveRequestDetail, MoveResponseResult } from '@/features/move-request/api/types';
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

  // 응답 제출 직후, 서버 재조회(refetch) 왕복을 기다리지 않고 방금 받은 결과로 바로 반영한다.
  // refetch로만 갱신하면 mock/네트워크 지연만큼 카운트다운이 이미 흐른 채로 시작해버린다.
  const applyResponse = useCallback((result: MoveResponseResult) => {
    setDetail((prev) => {
      if (!prev) return prev;

      return {
        ...prev,
        requestStatus: result.requestStatus,
        dueAt: result.dueAt,
        responses: [
          ...prev.responses,
          {
            responseId: result.responseId,
            responseType: result.responseType,
            estimatedMinutes: result.estimatedMinutes,
            respondedAt: result.respondedAt,
          },
        ],
      };
    });
  }, []);

  return { detail, isLoading, error, refetch, applyResponse };
}
