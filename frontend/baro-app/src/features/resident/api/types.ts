
export type ParkingSessionStatus = 'PARKED' | 'VIOLATION';

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

export type MoveRequestType = 'AUTO' | 'MANUAL';
export type MoveRequestStatus = 'SENT' | 'RESPONDED' | 'REMINDER_SENT' | 'COMPLETED' | 'NEED_ADMIN' | 'CANCELLED';
export type MoveEventType = 'BAD_PARKING' | 'DOUBLE_PARKING' | 'DISABLED_ZONE_VIOLATION' | 'EV_OVERSTAY' | 'OUT_OF_ZONE';
export type MoveResponseType = 'WILL_MOVE' | 'CANNOT_MOVE_NOW';
export type MoveImageType = 'PLATE' | 'PARKING_STATE';
export type MoveHistoryNotificationType = 'MOVE_REQUEST' | 'REMINDER' | 'EV_OVERSTAY' | 'EVENT_RESOLVED';

export type MoveRequestImage = {
  imageId: number;
  imageType: MoveImageType;
  imageUrl: string;
};

export type MoveRequestResponseItem = {
  responseId: number;
  responseType: MoveResponseType;
  estimatedMinutes: number | null;
  respondedAt: string;
};

export type MoveRequestHistoryItem = {
  notificationType: MoveHistoryNotificationType;
  sentAt: string;
};

// GET /api/move-requests/{requestId} 응답의 result.
export type MoveRequestDetail = {
  requestId: number;
  requestType: MoveRequestType;
  requestStatus: MoveRequestStatus;
  requestedAt: string;
  dueAt: string | null; // 응답 전에는 null
  requester: unknown | null; // TODO(move-request): AUTO 요청만 다루는 화면이라 항상 null. MANUAL 지원 시 실제 필드 확인 필요.
  targetVehicle: {
    vehicleId: number;
    plateNumber: string;
  };
  event: {
    eventId: number;
    eventType: MoveEventType;
    reason: string | null;
    zoneNumber: string | null; // 구역 외 주차면이면 null
    images: MoveRequestImage[];
  };
  responses: MoveRequestResponseItem[];
  history: MoveRequestHistoryItem[]; // notifications를 requestId 기준, sentAt 순 정렬
};
