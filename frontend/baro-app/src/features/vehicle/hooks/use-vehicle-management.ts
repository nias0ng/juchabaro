import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { getMyParkingSessions } from '@/features/parking/api/parking-api';
import { formatParkingLocation } from '@/features/parking/utils/parking-session';
import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';
import { queryKeys } from '@/services/query-keys';

import type { VehicleResult } from '../api/types';

import { deleteVehicle, getVehicleDetail, getVehicles } from '../api/vehicle-api';

async function fetchVehiclesWithDetails(accessToken: string): Promise<VehicleResult[]> {
  const [result, parkingSessions] = await Promise.all([
    getVehicles(accessToken),
    // 위치(주차 구역/자리)는 차량 API에 없어서, 홈 화면과 같은 "현재 주차 세션" 조회로 vehicleId를 매칭해 채운다.
    // 실패해도 위치만 못 채울 뿐 차량 목록 자체는 보여줘야 하니 조용히 빈 배열로 넘어간다.
    getMyParkingSessions(accessToken).catch(() => []),
  ]);

  const parkingSpotByVehicleId = new Map(
    parkingSessions.flatMap((session) =>
      session.floor || session.zoneNumber
        ? [[session.vehicleId, formatParkingLocation(session.floor, session.zoneNumber)] as const]
        : [],
    ),
  );

  // 목록 조회엔 등록일(createdAt) 등이 없어서, 카드에 채워 보여주려고 차량별로 상세를 추가 조회한다.
  // 한 대라도 상세 조회가 실패하면 그 차량만 목록 값 그대로 두고, 전체 목록 표시는 막지 않는다.
  return Promise.all(
    result.map(async (vehicle) => {
      const parkingSpotCode = parkingSpotByVehicleId.get(vehicle.vehicleId) ?? vehicle.parkingSpotCode ?? null;

      try {
        const detail = await getVehicleDetail(vehicle.vehicleId, accessToken);
        return { ...vehicle, parkingSpotCode, createdAt: detail.createdAt, updatedAt: detail.updatedAt };
      } catch {
        return { ...vehicle, parkingSpotCode };
      }
    }),
  );
}

/**
 * 차량 목록 조회와 삭제 상태를 함께 관리한다.
 * 차량 등록 후 이 화면으로 돌아왔을 때도 최신 목록이 보이도록 focus될 때(캐시가 stale이면) 다시 조회한다.
 */
export function useVehicleManagement() {
  const { accessToken, status: authStatus } = useAuth();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: queryKeys.vehicles.management(),
    queryFn: () => fetchVehiclesWithDetails(accessToken!),
    enabled: authStatus === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  const [deleteTargetVehicle, setDeleteTargetVehicle] = useState<VehicleResult | null>(null);
  const [deleteErrorMessage, setDeleteErrorMessage] = useState<string>();

  const deleteMutation = useMutation({
    mutationFn: (vehicleId: number) => deleteVehicle(vehicleId, accessToken!),
    onSuccess: (_data, vehicleId) => {
      // 재조회가 끝날 때까지 삭제한 차량이 목록에 잠깐 남아있지 않도록, 캐시에서 먼저 제거하고
      // invalidate로 백그라운드 재검증한다.
      queryClient.setQueryData<VehicleResult[]>(queryKeys.vehicles.management(), (prev) =>
        prev?.filter((vehicle) => vehicle.vehicleId !== vehicleId),
      );
      queryClient.setQueryData<VehicleResult[]>(queryKeys.vehicles.summary(), (prev) =>
        prev?.filter((vehicle) => vehicle.vehicleId !== vehicleId),
      );
      setDeleteTargetVehicle(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.vehicles.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.parking.sessions() });
    },
    onError: (error) => {
      setDeleteErrorMessage(error instanceof ApiError ? error.message : '차량 삭제에 실패했습니다.');
    },
  });

  const openDeleteModal = (vehicle: VehicleResult) => {
    setDeleteErrorMessage(undefined);
    setDeleteTargetVehicle(vehicle);
  };

  /** 삭제 진행 중에는 취소로 모달을 닫을 수 없다 — 요청이 중단되지 않도록 막는다. */
  const closeDeleteModal = () => {
    if (deleteMutation.isPending) return;
    setDeleteTargetVehicle(null);
    setDeleteErrorMessage(undefined);
  };

  const confirmDelete = () => {
    if (!deleteTargetVehicle || deleteMutation.isPending) return;
    setDeleteErrorMessage(undefined);
    deleteMutation.mutate(deleteTargetVehicle.vehicleId);
  };

  return {
    // 백그라운드 갱신 실패는 이미 표시된 목록을 오류 화면으로 바꾸지 않는다 — 캐시가 없을 때만 error로 취급한다.
    status: query.isLoading ? 'loading' : query.data === undefined && query.isError ? 'error' : 'success',
    isRefreshing: query.isFetching && !query.isLoading,
    vehicles: query.data ?? [],
    // 백그라운드 갱신 실패는 이미 화면에 표시된 목록을 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    listErrorMessage:
      query.data === undefined && query.error
        ? query.error instanceof ApiError
          ? query.error.message
          : '차량 목록을 불러오지 못했습니다.'
        : undefined,
    refetch: query.refetch,
    deleteTargetVehicle,
    isDeleting: deleteMutation.isPending,
    deleteErrorMessage,
    openDeleteModal,
    closeDeleteModal,
    confirmDelete,
  };
}

export type VehicleManagementController = ReturnType<typeof useVehicleManagement>;
