import { deleteJson, getJson, postJson } from '@/services/http-client';

import {
  deleteVehicleMock,
  getVehiclesMock,
  registerVehicleMock,
} from './vehicle-api.mock';
import type { RegisterVehicleRequest, VehicleResult } from './types';

// TODO(vehicle-api): 백엔드 /vehicles 명세가 확정되면 이 값을 false로 전환하고 실제 API를 검증한다.
const useMockVehicles = __DEV__ && process.env.EXPO_PUBLIC_USE_MOCK_VEHICLES === 'true';

/**
 * 차량 등록 API. 응답으로 저장된 차량 정보를 그대로 돌려받아 별도의 조회 호출 없이 등록 확인에 사용
 * TODO(vehicle-api): 백엔드 /vehicles 명세가 확정되면 요청/응답 필드를 다시 확인해야 함
 */
export function registerVehicle(
  request: RegisterVehicleRequest,
  accessToken?: string,
): Promise<VehicleResult> {
  if (useMockVehicles) {
    return registerVehicleMock(request);
  }

  return postJson<VehicleResult>('/vehicles', request, accessToken);
}

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
