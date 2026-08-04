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
  // 문서상 오타가 아니라 백엔드가 실제로 이 철자로 내려준다("기타"의 오타 ECT를 그대로 씀).
  | 'ECT';
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
  message: string | null;
  requestedAt: string;
  dueAt: string | null;
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

// 목록 API(MoveRequestSummary)엔 없는 구역/응답시간/완료시각을 상세 조회로 채운 목록 항목.
// 상세 조회가 실패한 항목은 이 필드들이 전부 null로 남는다(카드 쪽에서 없는 값으로 처리).
export type MoveRequestListItem = MoveRequestSummary & {
  zoneNumber: string | null;
  estimatedMinutes: number | null;
  respondedAt: string | null;
  resolvedAt: string | null;
};
