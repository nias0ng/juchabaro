// POST /api/vehicles, GET /api/vehicles, GET /api/vehicles/{id} 요청/응답은 Swagger로 확인된 실제 명세.
export type VehicleOwnerType = 'RESIDENT' | 'VISITOR';

export type RegisterVehicleRequest = {
  plateNumber: string; // 공백 없이. 예: "12가3456"
  vehicleModel?: string;
  isDisabledVehicle: boolean;
  isElectric: boolean;
  ownerType: VehicleOwnerType;
  visitDate?: string; // YYYY-MM-DD
};

export type VehicleStatus = 'ACTIVE' | 'DELETED' | 'PENDING';

// GET /api/vehicles(목록) 응답 기준. POST/상세 응답과 필드가 조금씩 달라서(userId, createdAt 등은 상세에만 있음)
// 카드 UI는 목록 조회 결과에 상세 조회로 얻은 값을 덧붙여서 채운다.
export type VehicleResult = {
  vehicleId: number;
  plateNumber: string;
  ownerType: VehicleOwnerType;
  status: VehicleStatus;
  vehicleModel: string | null;
  isElectric: boolean;
  isDisabledVehicle: boolean;
  // GET /api/vehicles/{id}(상세 조회)에서만 채워진다. 목록만 조회한 시점엔 없다.
  userId?: number;
  createdAt?: string;
  updatedAt?: string;
  // TODO(vehicle-api): 위치(parkingSpotCode), 방문 시작/종료(visitStartAt/visitEndAt)는
  // 목록/상세/등록 응답 어디에도 없다. 다른 API가 있는지 확인 전까지는 카드에 "-"로 표시한다.
  visitDate?: string | null;
  parkingSpotCode?: string | null;
  visitStartAt?: string | null;
  visitEndAt?: string | null;
};

export type VehicleListResult = {
  totalCount: number;
  vehicles: VehicleResult[];
};

// GET /api/vehicles/{id} 응답.
export type VehicleDetailResult = {
  vehicleId: number;
  userId: number;
  plateNumber: string;
  vehicleModel: string | null;
  isDisabledVehicle: boolean;
  isElectric: boolean;
  ownerType: VehicleOwnerType;
  status: VehicleStatus;
  createdAt: string;
  updatedAt: string;
};
