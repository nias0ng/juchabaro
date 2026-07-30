export type MoveRequestType = 'AUTO' | 'MANUAL';
export type MoveRequestStatus =
  | 'SENT'
  | 'RESPONDED'
  | 'REMINDER_SENT'
  | 'COMPLETED'
  | 'NEED_ADMIN'
  | 'CANCELLED';
export type MoveEventType =
  | 'BAD_PARKING'
  | 'DOUBLE_PARKING'
  | 'DISABLED_ZONE_VIOLATION'
  | 'EV_OVERSTAY'
  | 'OUT_OF_ZONE';
export type MoveResponseType = 'WILL_MOVE' | 'CANNOT_MOVE_NOW';
export type MoveImageType = 'PLATE' | 'PARKING_STATE';
export type MoveHistoryNotificationType =
  | 'MOVE_REQUEST'
  | 'REMINDER'
  | 'EV_OVERSTAY'
  | 'EVENT_RESOLVED';

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

// POST /api/move-requests/{requestId}/responses 요청 body.
export type MoveResponseRequest = {
  responseType: MoveResponseType;
  estimatedMinutes: number | null; // WILL_MOVE일 때만 필수(10/30/60/120), CANNOT_MOVE_NOW면 null
};

// POST /api/move-requests/{requestId}/responses 응답의 result.
export type MoveResponseResult = {
  responseId: number;
  requestId: number;
  responseType: MoveResponseType;
  estimatedMinutes: number | null;
  requestStatus: MoveRequestStatus;
  dueAt: string | null;
  respondedAt: string;
};
