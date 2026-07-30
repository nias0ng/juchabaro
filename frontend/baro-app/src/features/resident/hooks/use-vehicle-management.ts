import { useCallback, useState } from 'react';
import { useFocusEffect } from '@react-navigation/native';

import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

import type { VehicleResult } from '@/features/auth/api/vehicle-types';

import { deleteVehicle, getVehicles } from '../api/vehicle-api';

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
      const result = await getVehicles(accessToken);
      setVehicles(result);
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
