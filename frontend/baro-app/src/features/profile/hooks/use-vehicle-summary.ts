import { useEffect, useState } from 'react';

import { getVehicles } from '@/features/vehicle/api/vehicle-api';
import type { VehicleResult } from '@/features/vehicle/api/types';
import { useAuth } from '@/providers/auth-provider';

export function useVehicleSummary() {
  const { accessToken, status } = useAuth();
  const [vehicles, setVehicles] = useState<VehicleResult[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken) {
      setVehicles([]);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);

    getVehicles(accessToken)
      .then((result) => {
        if (isMounted) setVehicles(result);
      })
      .catch(() => {
        if (isMounted) setVehicles([]);
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [status, accessToken]);

  return {
    isLoading,
    vehicleCount: vehicles.length,
    // 백엔드에 "대표 차량" 지정 필드가 없어 목록의 첫 차량을 임시로 대표 차량처럼 보여준다.
    primaryVehicle: vehicles[0] ?? null,
  };
}
