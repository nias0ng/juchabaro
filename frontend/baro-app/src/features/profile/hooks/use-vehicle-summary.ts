import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';
import { getVehicles } from '@/features/vehicle/api/vehicle-api';
import type { VehicleResult } from '@/features/vehicle/api/types';

export function useVehicleSummary() {
  const { data: vehicles, isLoading, isRefreshing, refetch } = useAuthenticatedQuery<VehicleResult[]>(
    getVehicles,
    [],
    '차량 정보를 불러오지 못했습니다.',
  );

  return {
    isLoading,
    isRefreshing,
    refetch,
    vehicleCount: vehicles.length,
    // 서버에 대표 차량 필드가 없어 목록의 첫 번째 차량을 대표 문구에 사용한다.
    primaryVehicle: vehicles[0] ?? null,
  };
}
