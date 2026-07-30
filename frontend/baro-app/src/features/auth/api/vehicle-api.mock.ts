import { ApiError } from '@/services/api-error';

import type { RegisterVehicleRequest, VehicleResult } from './vehicle-types';

const MOCK_RESPONSE_DELAY_MS = 600;

// 등록/조회/삭제가 같은 목 데이터를 공유해야 해서 auth(등록)와 resident(조회/삭제) 양쪽이 이 모듈 하나를 함께 쓴다.
// 모듈 상태이므로 앱을 완전히 새로고침하면 초기화된다 — 실제 백엔드 연동 전까지만 쓰는 임시 저장소다.
let mockVehicles: VehicleResult[] = [];
let nextVehicleId = 1;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function registerVehicleMock(request: RegisterVehicleRequest): Promise<VehicleResult> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  const vehicle: VehicleResult = {
    vehicleId: nextVehicleId++,
    ownerType: request.ownerType,
    plateNumber: request.plateNumber,
    carModel: request.carModel ?? null,
    visitDate: request.visitDate ?? null,
    isElectric: request.isElectric,
    isDisabled: request.isDisabled,
  };

  mockVehicles = [...mockVehicles, vehicle];

  return vehicle;
}

export async function getVehiclesMock(): Promise<VehicleResult[]> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  return mockVehicles;
}

export async function deleteVehicleMock(vehicleId: number): Promise<void> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  const exists = mockVehicles.some((vehicle) => vehicle.vehicleId === vehicleId);
  if (!exists) {
    throw new ApiError('이미 삭제되었거나 존재하지 않는 차량입니다.', 404);
  }

  mockVehicles = mockVehicles.filter((vehicle) => vehicle.vehicleId !== vehicleId);
}
