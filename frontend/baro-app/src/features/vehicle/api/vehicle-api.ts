/** 차량 등록/조회/삭제 API 래퍼. */
import { deleteJson, getJson, postJson } from '@/services/http-client';

import type {
  RegisterVehicleRequest,
  VehicleDetailResult,
  VehicleListResult,
  VehicleResult,
} from './types';

/** POST /api/vehicles — 차량을 등록한다. 응답으로 저장된 차량 정보를 그대로 돌려받아 별도 조회 없이 등록 확인에 쓴다. */
export function registerVehicle(
  request: RegisterVehicleRequest,
  accessToken?: string,
): Promise<VehicleResult> {
  return postJson<VehicleResult>('/api/vehicles', request, accessToken);
}

/** GET /api/vehicles — 내 차량 목록을 조회한다. */
export async function getVehicles(accessToken: string): Promise<VehicleResult[]> {
  // result가 배열이 아니라 { totalCount, vehicles } 객체로 온다.
  const { vehicles } = await getJson<VehicleListResult>('/api/vehicles', accessToken);
  return vehicles;
}

/** GET /api/vehicles/{id} — 목록 조회엔 없는 등록일(createdAt) 등을 채우기 위한 차량 한 대 상세 조회. */
export function getVehicleDetail(vehicleId: number, accessToken: string): Promise<VehicleDetailResult> {
  return getJson<VehicleDetailResult>(`/api/vehicles/${vehicleId}`, accessToken);
}

/** DELETE /api/vehicles/{id} — 차량을 삭제한다. 주차 중인 차량은 서버가 409로 거부한다. */
export function deleteVehicle(vehicleId: number, accessToken: string): Promise<void> {
  return deleteJson<void>(`/api/vehicles/${vehicleId}`, accessToken);
}
