import { useEffect, useState } from 'react';

import { getMyParkingSessions } from '@/features/resident/api/parking-api';
import type { ParkingSession } from '@/features/resident/api/types';
import { useAuth } from '@/providers/auth-provider';

export function useParkingSessions() {
  const { accessToken, status } = useAuth();
  const [sessions, setSessions] = useState<ParkingSession[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // 로그인 상태가 아직 확정되지 않았거나 토큰이 없으면 호출할 게 없다.
    if (status !== 'authenticated' || !accessToken) {
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);

    getMyParkingSessions(accessToken)
      .then((result) => {
        if (isMounted) setSessions(result);
      })
      .catch(() => {
        if (isMounted) setSessions([]);
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [status, accessToken]);

  return { sessions, isLoading };
}
