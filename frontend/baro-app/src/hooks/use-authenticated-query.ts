import { useEffect, useRef, useState } from 'react';

import { useAuth } from '@/providers/auth-provider';

type UseAuthenticatedQueryResult<T> = {
  data: T;
  isLoading: boolean;
  error: Error | null;
};

/**
 * accessToken이 필요한 조회 훅들의 공통 뼈대: 인증 상태 확인 → 로딩/에러 상태 관리 →
 * 언마운트 후 setState 방지. fetcher는 매 렌더마다 새로 만들어져도 되도록 ref로 감싸서
 * effect 의존성에는 넣지 않는다(그러면 매 렌더마다 재조회된다).
 */
export function useAuthenticatedQuery<T>(
  fetcher: (accessToken: string) => Promise<T>,
  fallbackValue: T,
  errorMessage: string,
  deps: unknown[] = [],
): UseAuthenticatedQueryResult<T> {
  const { accessToken, status } = useAuth();
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const [data, setData] = useState<T>(fallbackValue);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken) {
      setData(fallbackValue);
      setError(null);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    fetcherRef
      .current(accessToken)
      .then((result) => {
        if (isMounted) setData(result);
      })
      .catch((requestError: unknown) => {
        if (!isMounted) return;
        setData(fallbackValue);
        setError(requestError instanceof Error ? requestError : new Error(errorMessage));
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps는 호출부가 전달하는 명시적 의존성 목록이다.
  }, [status, accessToken, ...deps]);

  return { data, isLoading, error };
}
