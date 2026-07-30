import { useEffect, useState } from 'react';

import { getMyParkingSessions } from '../api/parking-api';
import type { ParkingSession } from '../api/types';
import { useAuth } from '@/providers/auth-provider';

export function useParkingSessions() {
  const { accessToken, status } = useAuth();
  const [sessions, setSessions] = useState<ParkingSession[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    // 로그인 상태가 아직 확정되지 않았거나 토큰이 없으면 호출할 게 없다.
    if (status !== 'authenticated' || !accessToken) {
      setSessions([]);
      setError(null);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    getMyParkingSessions(accessToken)
      .then((result) => {
        if (isMounted) setSessions(result);
      })
      .catch((requestError: unknown) => {
        if (!isMounted) return;

        setSessions([]);
        setError(
          requestError instanceof Error
            ? requestError
            : new Error('주차 세션을 불러오지 못했습니다.'),
        );
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [status, accessToken]);

  return { sessions, isLoading, error };
}
