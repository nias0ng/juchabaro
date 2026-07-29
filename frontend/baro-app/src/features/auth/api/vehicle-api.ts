import { postJson } from '@/services/http-client';

import type { RegisterVehicleRequest, VehicleResult } from './vehicle-types';

/**
 * 차량 등록 API. 응답으로 저장된 차량 정보를 그대로 돌려받아 별도의 조회 호출 없이 등록 확인에 사용
 * TODO(vehicle-api): 백엔드 /vehicles 명세가 확정되면 요청/응답 필드를 다시 확인해야 함
 */
export function registerVehicle(
  request: RegisterVehicleRequest,
  accessToken?: string,
): Promise<VehicleResult> {
  return postJson<VehicleResult>('/vehicles', request, accessToken);
}
