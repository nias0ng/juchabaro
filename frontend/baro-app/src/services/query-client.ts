/** 앱 전역에서 공유하는 React Query 클라이언트. 재시도/캐시 정책을 여기서 한 번만 정의한다. */
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
      refetchOnWindowFocus: false,
      retry: shouldRetry,
    },
    mutations: {
      retry: false,
    },
  },
});
