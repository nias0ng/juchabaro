export type ParkingSessionStatus = 'PARKED' | 'VIOLATION';

// GET /api/parking-sessions/me 응답의 result.sessions[] 항목.
export type ParkingSession = {
  sessionId: number;
  vehicleId: number;
  plateNumber: string;
  status: ParkingSessionStatus;
  zoneId: number;
  zoneNumber: string;
  floor: string;
  enteredAt: string; // ISO 8601
};

export type CongestionLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export type ParkingZoneType = 'GENERAL' | 'DISABLED' | 'EV_CHARGING';
export type ParkingOccupancyStatus = 'EMPTY' | 'OCCUPIED' | 'VIOLATION';

// parking_zones 한 행(주차면 한 칸)의 지도 표시용 요약 정보.
export type ParkingSpotSummary = {
  zoneId: number;
  zoneNumber: string;
  zoneType: ParkingZoneType;
  geometryData: string | null;
  occupancyStatus: ParkingOccupancyStatus;
};

// GET /api/parking-zones/summary 응답의 result.
export type ParkingZoneSummary = {
  floor: string;
  totalSpots: number;
  occupiedSpots: number;
  availableSpots: number;
  violationCount: number;
  congestionRate: number; // 0~100, 서버가 반올림해서 계산
  congestionLevel: CongestionLevel;
  spots: ParkingSpotSummary[];
};
