import { useCallback, useState } from 'react';
import { useFocusEffect } from '@react-navigation/native';

import { getMyParkingSessions } from '@/features/parking/api/parking-api';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

import type { VehicleResult } from '../api/types';

import { deleteVehicle, getVehicleDetail, getVehicles } from '../api/vehicle-api';

type VehicleListStatus = 'loading' | 'success' | 'error';

/**
 * 차량 목록 조회와 삭제 상태를 함께 관리한다.
 * 차량 등록 후 이 화면으로 돌아왔을 때도 최신 목록이 보이도록 focus될 때마다 다시 조회한다.
 */
export function useVehicleManagement() {
  const { accessToken, status: authStatus } = useAuth();

  const [status, setStatus] = useState<VehicleListStatus>('loading');
  const [vehicles, setVehicles] = useState<VehicleResult[]>([]);
  const [listErrorMessage, setListErrorMessage] = useState<string>();

  const [deleteTargetVehicle, setDeleteTargetVehicle] = useState<VehicleResult | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteErrorMessage, setDeleteErrorMessage] = useState<string>();

  const fetchVehicles = useCallback(async () => {
    // 세션 복원이 끝나기 전에는 로그인 여부를 알 수 없어 조회를 보류한다.
    if (authStatus === 'loading') return;

    if (!accessToken) {
      setStatus('error');
      setListErrorMessage('로그인이 필요합니다.');
      return;
    }

    setStatus('loading');
    setListErrorMessage(undefined);

    try {
      const [result, parkingSessions] = await Promise.all([
        getVehicles(accessToken),
        // 위치(주차 구역/자리)는 차량 API에 없어서, 홈 화면과 같은 "현재 주차 세션" 조회로 vehicleId를 매칭해 채운다.
        // 실패해도 위치만 못 채울 뿐 차량 목록 자체는 보여줘야 하니 조용히 빈 배열로 넘어간다.
        getMyParkingSessions(accessToken).catch(() => []),
      ]);

      const parkingSpotByVehicleId = new Map(
        parkingSessions.map((session) => [session.vehicleId, `${session.floor} · ${session.zoneNumber}`]),
      );

      // 목록 조회엔 등록일(createdAt) 등이 없어서, 카드에 채워 보여주려고 차량별로 상세를 추가 조회한다.
      // 한 대라도 상세 조회가 실패하면 그 차량만 목록 값 그대로 두고, 전체 목록 표시는 막지 않는다.
      const withDetails = await Promise.all(
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

      setVehicles(withDetails);
      setStatus('success');
    } catch (error) {
      setListErrorMessage(error instanceof ApiError ? error.message : '차량 목록을 불러오지 못했습니다.');
      setStatus('error');
    }
  }, [accessToken, authStatus]);

  useFocusEffect(
    useCallback(() => {
      fetchVehicles();
    }, [fetchVehicles]),
  );

  const openDeleteModal = useCallback((vehicle: VehicleResult) => {
    setDeleteErrorMessage(undefined);
    setDeleteTargetVehicle(vehicle);
  }, []);

  /** 삭제 진행 중에는 취소로 모달을 닫을 수 없다 — 요청이 중단되지 않도록 막는다. */
  const closeDeleteModal = useCallback(() => {
    if (isDeleting) return;
    setDeleteTargetVehicle(null);
    setDeleteErrorMessage(undefined);
  }, [isDeleting]);

  const confirmDelete = useCallback(async () => {
    if (!deleteTargetVehicle || isDeleting || !accessToken) return;

    setIsDeleting(true);
    setDeleteErrorMessage(undefined);

    try {
      await deleteVehicle(deleteTargetVehicle.vehicleId, accessToken);
      setVehicles((prev) => prev.filter((vehicle) => vehicle.vehicleId !== deleteTargetVehicle.vehicleId));
      setDeleteTargetVehicle(null);
    } catch (error) {
      setDeleteErrorMessage(error instanceof ApiError ? error.message : '차량 삭제에 실패했습니다.');
    } finally {
      setIsDeleting(false);
    }
  }, [deleteTargetVehicle, isDeleting, accessToken]);

  return {
    status,
    vehicles,
    listErrorMessage,
    refetch: fetchVehicles,
    deleteTargetVehicle,
    isDeleting,
    deleteErrorMessage,
    openDeleteModal,
    closeDeleteModal,
    confirmDelete,
  };
}

export type VehicleManagementController = ReturnType<typeof useVehicleManagement>;
