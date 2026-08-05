import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { getMoveRequestDetail } from '@/features/move-request/api/move-request-api';
import type { MoveRequestDetail, MoveResponseResult } from '@/features/move-request/api/types';
import { useAuth } from '@/providers/auth-provider';
import { subscribeAuthenticatedQueryRefresh } from '@/services/authenticated-query-refresh';

// 서버가 상태 변화를 push해줄 방법이 없어서(REST GET/POST뿐), RESPONDED로 대기하는 동안은
// 이 주기로 다시 조회해서 백엔드가 이동을 확인해 COMPLETED로 바꿨는지 스스로 확인한다.
const POLL_INTERVAL_MS = 10_000;

export function useMoveRequestDetail(requestId: number | null) {
  const { accessToken, status } = useAuth();
  const [detail, setDetail] = useState<MoveRequestDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const isMountedRef = useRef(true);
  const hasLoadedRef = useRef(false);
  const focusedRef = useRef(false);
  const appStateRef = useRef(AppState.currentState);
  const inFlightRequestIdRef = useRef<number | null>(null);
  const loadSequenceRef = useRef(0);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadDetail = useCallback(
    async (options: { showLoading: boolean }) => {
      if (status !== 'authenticated' || !accessToken || requestId === null) return;
      if (inFlightRequestIdRef.current === requestId) return;
      inFlightRequestIdRef.current = requestId;
      const loadSequence = ++loadSequenceRef.current;

      if (options.showLoading) setIsLoading(true);
      else setIsRefreshing(true);

      try {
        const result = await getMoveRequestDetail(requestId, accessToken);
        if (!isMountedRef.current || loadSequence !== loadSequenceRef.current) return;
        setDetail(result);
        setError(null);
        hasLoadedRef.current = true;
      } catch (requestError: unknown) {
        if (!isMountedRef.current || loadSequence !== loadSequenceRef.current) return;

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
        if (loadSequence === loadSequenceRef.current) inFlightRequestIdRef.current = null;
        if (isMountedRef.current && loadSequence === loadSequenceRef.current) {
          if (options.showLoading) setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    },
    [status, accessToken, requestId],
  );

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken || requestId === null) {
      loadSequenceRef.current += 1;
      inFlightRequestIdRef.current = null;
      setDetail(null);
      setError(null);
      setIsLoading(false);
      setIsRefreshing(false);
      hasLoadedRef.current = false;
      return;
    }

    hasLoadedRef.current = false;
    loadDetail({ showLoading: true });
  }, [status, accessToken, requestId, loadDetail]);

  const refetch = useCallback(
    () => loadDetail({ showLoading: !hasLoadedRef.current }),
    [loadDetail],
  );

  useFocusEffect(
    useCallback(() => {
      focusedRef.current = true;
      if (hasLoadedRef.current) void loadDetail({ showLoading: false });
      return () => {
        focusedRef.current = false;
      };
    }, [loadDetail]),
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      const becameActive = appStateRef.current !== 'active' && nextState === 'active';
      appStateRef.current = nextState;
      if (becameActive && focusedRef.current) void loadDetail({ showLoading: false });
    });
    return () => subscription.remove();
  }, [loadDetail]);

  useEffect(
    () => subscribeAuthenticatedQueryRefresh(() => {
      if (focusedRef.current) void loadDetail({ showLoading: false });
    }),
    [loadDetail],
  );

  useEffect(() => {
    // RESPONDED(이동 대기)와 REMINDER_SENT(재알림까지 나간 상태) 둘 다, 서버가 COMPLETED/NEED_ADMIN으로
    // 바꿔줘도 알려줄 방법이 없어서 계속 다시 확인해야 한다.
    if (detail?.requestStatus !== 'RESPONDED' && detail?.requestStatus !== 'REMINDER_SENT') return;

    const interval = setInterval(() => {
      if (focusedRef.current && AppState.currentState === 'active') {
        void loadDetail({ showLoading: false });
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [detail?.requestStatus, loadDetail]);

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

  return { detail, isLoading, isRefreshing, error, refetch, applyResponse };
}
