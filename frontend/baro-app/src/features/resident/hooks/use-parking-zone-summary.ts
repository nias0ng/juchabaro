import { useEffect, useState } from 'react';

import { getParkingZoneSummary } from '@/features/resident/api/parking-api';
import type { ParkingZoneSummary } from '@/features/resident/api/types';
import { useAuth } from '@/providers/auth-provider';

export function useParkingZoneSummary() {
  const { accessToken, status } = useAuth();
  const [summary, setSummary] = useState<ParkingZoneSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken) {
      setSummary(null);
      setError(null);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    getParkingZoneSummary(accessToken)
      .then((result) => {
        if (isMounted) setSummary(result);
      })
      .catch((requestError: unknown) => {
        if (!isMounted) return;

        setSummary(null);
        setError(
          requestError instanceof Error
            ? requestError
            : new Error('주차 현황을 불러오지 못했습니다.'),
        );
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [status, accessToken]);

  return { summary, isLoading, error };
}
