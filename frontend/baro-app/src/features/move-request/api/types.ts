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
  | 'OUT_OF_ZONE'
  | 'ETC';
export type MoveResponseType = 'WILL_MOVE' | 'CANNOT_MOVE_NOW';
export type MoveImageType = 'PLATE' | 'PARKING_STATE' | 'REPORT';
export type MoveHistoryNotificationType =
  | 'MOVE_REQUEST'
  | 'MOVE_RESPONSE'
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
  resolvedAt: string | null; // 사건이 종료되지 않았으면 null
  targetVehicle: {
    vehicleId: number;
    plateNumber: string;
  };
  event: {
    eventId: number;
    eventType: MoveEventType;
    zoneNumber: string | null; // 구역 외 주차면이면 null
    images: MoveRequestImage[];
  };
  // 이동 요청자가 남긴 사유. 예전엔 event.reason이었는데, 목록 API(MoveRequestSummary.message)와
  // 필드를 통일하면서 요청(request) 쪽 최상위 필드로 옮겨왔다.
  message: string | null;
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

// POST /api/move-requests 요청 파라미터.
export type MoveRequestCreateParams = {
  targetPlateNumber: string;
  eventType: MoveEventType;
  reason: string;
  zoneName?: string;
  images: string[]; // 로컬 이미지 uri 목록
};

// POST /api/move-requests 응답의 result.
export type MoveRequestCreateResult = {
  eventId: number;
  requestId: number;
  targetVehicleId: number;
  requestType: MoveRequestType;
  requestStatus: MoveRequestStatus;
  reminderCount: number;
  images: MoveRequestImage[];
  requestedAt: string;
};

export type MoveRequestScope = 'RECEIVED' | 'SENT' | 'ALL';

// GET /api/move-requests 응답의 result.moveRequests 항목.
export type MoveRequestSummary = {
  requestId: number;
  eventId: number;
  requesterUserId: number | null;
  targetVehicleId: number;
  targetPlateNumber: string;
  requestType: MoveRequestType;
  requestStatus: MoveRequestStatus;
  eventType: MoveEventType;
  zoneNumber: string | null; // 구역 외 주차면이면 null
  message: string | null;
  requestedAt: string;
  dueAt: string | null;
  resolvedAt: string | null; // COMPLETED 전에는 null
  estimatedMinutes: number | null; // 응답 전이거나 CANNOT_MOVE_NOW면 null
  reminderCount: number;
};

// GET /api/move-requests 응답의 result.
export type MoveRequestListResult = {
  moveRequests: MoveRequestSummary[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
};

// 목록 화면(E-04) 카드가 그대로 쓰는 목록 항목. 목록 API가 카드에 필요한 필드를 전부 내려준다.
export type MoveRequestListItem = MoveRequestSummary;
