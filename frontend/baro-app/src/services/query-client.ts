import { QueryClient } from '@tanstack/react-query';

import { ApiError } from './api-error';

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      gcTime: 5 * 60_000,
      refetchOnReconnect: true,
      // Expo Router 스택에는 이전 화면들도 마운트된 채 남아있어, 기본값(true)이면 앱 활성화 시
      // 현재 보이는 화면뿐 아니라 뒤에 쌓인 모든 stale 쿼리까지 한꺼번에 재요청된다.
      // 실제 포커스된 화면만 재요청하도록 useRefetchOnFocus에서 AppState를 직접 다룬다.
      refetchOnWindowFocus: false,
      retry: shouldRetry,
    },
    mutations: {
      retry: false,
    },
  },
});
