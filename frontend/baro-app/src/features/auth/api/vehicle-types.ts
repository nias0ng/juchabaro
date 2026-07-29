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

export type VehicleResult = {
  vehicleId: number;
  ownerType: VehicleOwnerType;
  plateNumber: string;
  carModel: string | null;
  visitDate: string | null;
  isElectric: boolean;
  isDisabled: boolean;
};
