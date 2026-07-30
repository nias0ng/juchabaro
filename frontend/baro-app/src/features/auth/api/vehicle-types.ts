// Figma 목업의 네트워크 주석(POST /vehicles · ownerType 등)에서 유추한 임시 연결 해놔가지고 
// 백엔드 차량 등록 API 명세가 확정되면 실제 필드명에 맞춰 다시 확인해야 함

export type VehicleOwnerType = 'RESIDENT' | 'VISITOR';

export type RegisterVehicleRequest = {
  ownerType: VehicleOwnerType;
  plateNumber: string;
  carModel?: string;
  visitDate?: string;
  isElectric: boolean;
  isDisabled: boolean;
};

export type VehicleApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export type VehicleResult = {
  vehicleId: number;
  ownerType: VehicleOwnerType;
  plateNumber: string;
  carModel: string | null;
  visitDate: string | null;
  isElectric: boolean;
  isDisabled: boolean;
  // TODO(vehicle-api): Figma H-02-1/H-02-2 카드에 표시되는 필드(위치/등록일/방문 시작·종료/승인 상태)는
  // 백엔드 GET /vehicles 응답에 아직 없어 옵셔널로 추가해 둔다. 명세 확정되면 필수 여부와 필드명을 다시 확인해야 함.
  parkingSpotCode?: string | null;
  registeredAt?: string | null;
  visitStartAt?: string | null;
  visitEndAt?: string | null;
  approvalStatus?: VehicleApprovalStatus;
};
