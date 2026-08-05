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
      retry: shouldRetry,
    },
    mutations: {
      retry: false,
    },
  },
});
