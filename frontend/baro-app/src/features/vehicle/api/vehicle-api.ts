import { deleteJson, getJson, postJson } from '@/services/http-client';

import type {
  RegisterVehicleRequest,
  VehicleDetailResult,
  VehicleListResult,
  VehicleResult,
} from './types';

/** 차량 등록 API. 응답으로 저장된 차량 정보를 그대로 돌려받아 별도의 조회 호출 없이 등록 확인에 사용 */
export function registerVehicle(
  request: RegisterVehicleRequest,
  accessToken?: string,
): Promise<VehicleResult> {
  return postJson<VehicleResult>('/api/vehicles', request, accessToken);
}

export async function getVehicles(accessToken: string): Promise<VehicleResult[]> {
  // result가 배열이 아니라 { totalCount, vehicles } 객체로 온다.
  const { vehicles } = await getJson<VehicleListResult>('/api/vehicles', accessToken);
  return vehicles;
}

/** 목록 조회엔 없는 등록일(createdAt) 등을 채우기 위한 차량 한 대 상세 조회. */
export function getVehicleDetail(vehicleId: number, accessToken: string): Promise<VehicleDetailResult> {
  return getJson<VehicleDetailResult>(`/api/vehicles/${vehicleId}`, accessToken);
}

export function deleteVehicle(vehicleId: number, accessToken: string): Promise<void> {
  return deleteJson<void>(`/api/vehicles/${vehicleId}`, accessToken);
}
