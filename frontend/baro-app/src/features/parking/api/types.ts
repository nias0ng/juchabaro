export type ParkingSessionStatus = 'PARKED' | 'VIOLATION';

// GET /api/parking-sessions/me 응답의 result.sessions[] 항목.
export type ParkingSession = {
  sessionId: number;
  vehicleId: number;
  plateNumber: string;
  status: ParkingSessionStatus;
  zoneId: number;
  zoneName: string;
  spotCode: string;
  enteredAt: string; // ISO 8601
};

export type CongestionLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export type SpotType = 'GENERAL' | 'DISABLED' | 'EV_CHARGING';
export type SpotStatus = 'EMPTY' | 'OCCUPIED' | 'VIOLATION';

export type ParkingSpot = {
  spotCode: string;
  spotType: SpotType;
  status: SpotStatus;
};

// GET /api/parking-zones/summary 응답의 result.
export type ParkingZoneSummary = {
  totalSpots: number;
  occupiedSpots: number;
  availableSpots: number;
  violationCount: number;
  congestionRate: number; // 0~100, 서버가 반올림해서 계산
  congestionLevel: CongestionLevel;
  spots: ParkingSpot[];
};
