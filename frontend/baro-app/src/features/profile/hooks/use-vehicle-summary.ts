import { useQuery } from '@tanstack/react-query';

import { getVehicles } from '@/features/vehicle/api/vehicle-api';
import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

/**
 * 마이페이지에 보여줄 차량 요약(대수, 대표 차량)을 조회한다.
 * API: GET /api/vehicles
 */
export function useVehicleSummary() {
  const { accessToken, status } = useAuth();

  const query = useQuery({
    queryKey: queryKeys.vehicles.summary(),
    queryFn: () => getVehicles(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  const vehicles = query.data ?? [];

  return {
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    refetch: query.refetch,
    vehicleCount: vehicles.length,
    // 서버에 대표 차량 필드가 없어 목록의 첫 번째 차량을 대표 문구에 사용한다.
    primaryVehicle: vehicles[0] ?? null,
  };
}
