import { ApiError } from '@/services/api-error';

import type { RegisterVehicleRequest, VehicleDetailResult, VehicleResult } from './types';

const MOCK_RESPONSE_DELAY_MS = 600;

// 등록/조회/삭제가 같은 목 데이터를 공유해야 해서 차량 등록과 관리 화면 양쪽이 이 모듈 하나를 함께 쓴다.
// 모듈 상태이므로 앱을 완전히 새로고침하면 초기화된다 — 실제 백엔드 연동 전까지만 쓰는 임시 저장소다.
let mockVehicles: VehicleResult[] = [];
let nextVehicleId = 1;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** visitDate("YYYY-MM-DD")를 기준으로 24시간 방문 등록 시작/종료 시각 문자열을 만든다. */
function toVisitWindow(visitDate: string | undefined) {
  if (!visitDate) return { visitStartAt: null, visitEndAt: null };

  const start = `${visitDate} 00:00`;
  const end = `${visitDate} 23:59`;
  return { visitStartAt: start, visitEndAt: end };
}

export async function registerVehicleMock(request: RegisterVehicleRequest): Promise<VehicleResult> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  const isHousehold = request.ownerType === 'RESIDENT';
  const { visitStartAt, visitEndAt } = toVisitWindow(request.visitDate);

  const now = new Date().toISOString();

  const vehicle: VehicleResult = {
    vehicleId: nextVehicleId++,
    userId: 1,
    ownerType: request.ownerType,
    plateNumber: request.plateNumber,
    status: 'ACTIVE',
    visitDate: request.visitDate ?? null,
    vehicleModel: request.vehicleModel ?? null,
    isElectric: request.isElectric,
    isDisabledVehicle: request.isDisabledVehicle,
    parkingSpotCode: isHousehold ? 'B1 · EV-01' : null,
    createdAt: now,
    updatedAt: now,
    visitStartAt,
    visitEndAt,
  };

  mockVehicles = [...mockVehicles, vehicle];

  return vehicle;
}

export async function getVehiclesMock(): Promise<VehicleResult[]> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  return mockVehicles;
}

export async function getVehicleDetailMock(vehicleId: number): Promise<VehicleDetailResult> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  const vehicle = mockVehicles.find((item) => item.vehicleId === vehicleId);
  if (!vehicle) {
    throw new ApiError('차량을 찾을 수 없습니다.', 404);
  }

  return {
    vehicleId: vehicle.vehicleId,
    userId: vehicle.userId ?? 1,
    plateNumber: vehicle.plateNumber,
    vehicleModel: vehicle.vehicleModel,
    isDisabledVehicle: vehicle.isDisabledVehicle,
    isElectric: vehicle.isElectric,
    ownerType: vehicle.ownerType,
    status: vehicle.status,
    createdAt: vehicle.createdAt ?? new Date().toISOString(),
    updatedAt: vehicle.updatedAt ?? new Date().toISOString(),
  };
}

export async function deleteVehicleMock(vehicleId: number): Promise<void> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  const exists = mockVehicles.some((vehicle) => vehicle.vehicleId === vehicleId);
  if (!exists) {
    throw new ApiError('이미 삭제되었거나 존재하지 않는 차량입니다.', 404);
  }

  mockVehicles = mockVehicles.filter((vehicle) => vehicle.vehicleId !== vehicleId);
}
