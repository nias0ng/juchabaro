import { deleteJson, getJson } from '@/services/http-client';

import { deleteVehicleMock, getVehiclesMock } from '@/features/auth/api/vehicle-api.mock';
import type { VehicleResult } from '@/features/auth/api/vehicle-types';

// TODO(vehicle-api): 백엔드 /vehicles 명세가 확정되면 이 값을 false로 전환하고 실제 API를 검증한다.
const useMockVehicles = __DEV__ && process.env.EXPO_PUBLIC_USE_MOCK_VEHICLES === 'true';

/**
 * 차량 등록(POST)은 features/auth에 있고, 조회/삭제는 입주민 전용 기능이라 features/resident에 둔다.
 * 목 사용 시 등록(auth)과 같은 저장소(vehicle-api.mock)를 공유해야 방금 등록한 차량이 목록에 바로 보인다.
 * TODO(vehicle-api): 백엔드 /vehicles 목록·삭제 명세가 확정되면 요청/응답 필드를 다시 확인해야 함
 */
export function getVehicles(accessToken: string): Promise<VehicleResult[]> {
  if (useMockVehicles) {
    return getVehiclesMock();
  }

  return getJson<VehicleResult[]>('/vehicles', accessToken);
}

export function deleteVehicle(vehicleId: number, accessToken: string): Promise<void> {
  if (useMockVehicles) {
    return deleteVehicleMock(vehicleId);
  }

  return deleteJson<void>(`/vehicles/${vehicleId}`, accessToken);
}
