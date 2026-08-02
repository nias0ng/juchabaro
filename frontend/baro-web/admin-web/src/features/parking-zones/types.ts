export type SpotType = 'GENERAL' | 'DISABLED' | 'EV_CHARGING';

// baro-app과 동일하게 MINE(내 차)도 상태값으로 남겨두되, 관리자 웹에서는 OCCUPIED와
// 동일하게 취급한다 (구역 지도에서 "누구 차인지"는 중요하지 않고 "사용 중인지"만 본다).
export type SpotStatus = 'OCCUPIED' | 'EMPTY' | 'VIOLATION' | 'MINE';

export type FloorKey = 'B1' | 'B2' | 'B3';

export type CellVariant = 'empty' | 'occupied' | 'violation' | 'disabled' | 'ev';

export type ParkingSpot = {
  code: string;
  floor: FloorKey;
  type: SpotType;
  // 현재 상태는 실제로는 AI 감지/센서 데이터로 채워지는 값이라 관리자가 직접 바꿀 수 없다.
  status: SpotStatus;
  lastOccupiedAt: string;
  /** 주차장 현황 맵에서 통로 옆 세로 칸(side column)에 놓이는 칸인지 여부 */
  isSide: boolean;
};
