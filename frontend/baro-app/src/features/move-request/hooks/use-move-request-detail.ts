import { useCallback, useEffect, useRef, useState } from 'react';

import { getMoveRequestDetail } from '@/features/move-request/api/move-request-api';
import type { MoveRequestDetail, MoveResponseResult } from '@/features/move-request/api/types';
import { useAuth } from '@/providers/auth-provider';

// 서버가 상태 변화를 push해줄 방법이 없어서(REST GET/POST뿐), RESPONDED로 대기하는 동안은
// 이 주기로 다시 조회해서 백엔드가 이동을 확인해 COMPLETED로 바꿨는지 스스로 확인한다.
const POLL_INTERVAL_MS = 10_000;

export function useMoveRequestDetail(requestId: number | null) {
  const { accessToken, status } = useAuth();
  const [detail, setDetail] = useState<MoveRequestDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  // fetch 이펙트를 다시 돌리기 위한 트리거. 값 자체는 의미 없고 바뀌기만 하면 된다.
  const [refetchTick, setRefetchTick] = useState(0);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadDetail = useCallback(
    async (options: { showLoading: boolean }) => {
      if (status !== 'authenticated' || !accessToken || requestId === null) return;

      if (options.showLoading) setIsLoading(true);

      try {
        const result = await getMoveRequestDetail(requestId, accessToken);
        if (!isMountedRef.current) return;
        setDetail(result);
        setError(null);
      } catch (requestError: unknown) {
        if (!isMountedRef.current) return;

        // 백그라운드 폴링 실패는 화면을 비우지 않고 조용히 넘어간다. 다음 폴링에서 다시 시도된다.
        if (options.showLoading) {
          setDetail(null);
          setError(
            requestError instanceof Error
              ? requestError
              : new Error('이동 요청 정보를 불러오지 못했습니다.'),
          );
        }
      } finally {
        if (isMountedRef.current && options.showLoading) setIsLoading(false);
      }
    },
    [status, accessToken, requestId],
  );

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken || requestId === null) {
      setDetail(null);
      setError(null);
      setIsLoading(false);
      return;
    }

    loadDetail({ showLoading: true });
  }, [status, accessToken, requestId, refetchTick, loadDetail]);

  useEffect(() => {
    // RESPONDED(이동 대기)와 REMINDER_SENT(재알림까지 나간 상태) 둘 다, 서버가 COMPLETED/NEED_ADMIN으로
    // 바꿔줘도 알려줄 방법이 없어서 계속 다시 확인해야 한다.
    if (detail?.requestStatus !== 'RESPONDED' && detail?.requestStatus !== 'REMINDER_SENT') return;

    const interval = setInterval(() => {
      loadDetail({ showLoading: false });
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [detail?.requestStatus, loadDetail]);

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
