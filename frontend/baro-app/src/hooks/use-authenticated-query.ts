import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { useAuth } from '@/providers/auth-provider';
import { subscribeAuthenticatedQueryRefresh } from '@/services/authenticated-query-refresh';

type UseAuthenticatedQueryResult<T> = {
  data: T;
  isLoading: boolean;
  isRefreshing: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
};

type UseAuthenticatedQueryOptions = {
  refreshOnFocus?: boolean;
  refreshOnAppActive?: boolean;
  pollIntervalMs?: number;
};

/** 인증 조회의 최초 로딩, 화면 복귀, 앱 복귀, 수동 새로고침과 선택적 폴링을 함께 관리한다. */
export function useAuthenticatedQuery<T>(
  fetcher: (accessToken: string) => Promise<T>,
  fallbackValue: T,
  errorMessage: string,
  deps: unknown[] = [],
  options: UseAuthenticatedQueryOptions = {},
): UseAuthenticatedQueryResult<T> {
  const { accessToken, status } = useAuth();
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const fallbackValueRef = useRef(fallbackValue);
  fallbackValueRef.current = fallbackValue;
  const errorMessageRef = useRef(errorMessage);
  errorMessageRef.current = errorMessage;

  const {
    refreshOnFocus = true,
    refreshOnAppActive = true,
    pollIntervalMs,
  } = options;

  const [data, setData] = useState<T>(fallbackValue);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const mountedRef = useRef(true);
  const hasLoadedRef = useRef(false);
  const focusedRef = useRef(false);
  const appStateRef = useRef(AppState.currentState);
  const generationRef = useRef(0);
  const requestIdRef = useRef(0);
  const inFlightRef = useRef<{
    generation: number;
    requestId: number;
    promise: Promise<void>;
  } | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
    };
  }, []);

  const load = useCallback(async (showInitialLoading = false): Promise<void> => {
    if (status !== 'authenticated' || !accessToken) return;

    const generation = generationRef.current;
    const existingRequest = inFlightRef.current;
    if (existingRequest?.generation === generation) return existingRequest.promise;

    const requestId = ++requestIdRef.current;
    const isInitial = showInitialLoading || !hasLoadedRef.current;

    if (isInitial) setIsLoading(true);
    else setIsRefreshing(true);
    setError(null);

    const promise = (async () => {
      try {
        const result = await fetcherRef.current(accessToken);
        if (!mountedRef.current || requestId !== requestIdRef.current) return;
        setData(result);
        hasLoadedRef.current = true;
      } catch (requestError: unknown) {
        if (!mountedRef.current || requestId !== requestIdRef.current) return;

        // 백그라운드 갱신 실패는 이미 화면에 표시된 데이터를 지우지 않는다.
        if (isInitial) {
          setData(fallbackValueRef.current);
          setError(
            requestError instanceof Error
              ? requestError
              : new Error(errorMessageRef.current),
          );
          hasLoadedRef.current = true;
        }
      } finally {
        if (inFlightRef.current?.requestId === requestId) inFlightRef.current = null;
        if (!mountedRef.current || requestId !== requestIdRef.current) return;
        setIsLoading(false);
        setIsRefreshing(false);
      }
    })();

    inFlightRef.current = { generation, requestId, promise };
    return promise;
  }, [accessToken, status]);

  useEffect(() => {
    generationRef.current += 1;
    requestIdRef.current += 1;
    inFlightRef.current = null;

    if (status !== 'authenticated' || !accessToken) {
      hasLoadedRef.current = false;
      setData(fallbackValueRef.current);
      setError(null);
      setIsLoading(false);
      setIsRefreshing(false);
      return;
    }

    hasLoadedRef.current = false;
    setData(fallbackValueRef.current);
    void load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps는 호출부가 전달하는 명시적 의존성 목록이다.
  }, [status, accessToken, load, ...deps]);

  const refetch = useCallback(() => load(false), [load]);

  useFocusEffect(
    useCallback(() => {
      focusedRef.current = true;
      if (refreshOnFocus && hasLoadedRef.current) void refetch();

      const interval = pollIntervalMs
        ? setInterval(() => {
            if (AppState.currentState === 'active') void refetch();
          }, pollIntervalMs)
        : null;

      return () => {
        focusedRef.current = false;
        if (interval) clearInterval(interval);
      };
    }, [pollIntervalMs, refetch, refreshOnFocus]),
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      const becameActive = appStateRef.current !== 'active' && nextState === 'active';
      appStateRef.current = nextState;
      if (becameActive && focusedRef.current && refreshOnAppActive) void refetch();
    });
    return () => subscription.remove();
  }, [refetch, refreshOnAppActive]);

  useEffect(
    () => subscribeAuthenticatedQueryRefresh(() => {
      if (focusedRef.current) void refetch();
    }),
    [refetch],
  );

  return { data, isLoading, isRefreshing, error, refetch };
}
