// 사건(주차 위반) 관련 관리자 API의 요청/응답 타입. Notion API 명세서(S15P11E202)의
// "관리자 사건 목록/상세/처리 이력 조회", "관리자 사건 완료/재알림/오탐/확인 처리" 기준.

export type EventType = 'BAD_PARKING' | 'DOUBLE_PARKING' | 'DISABLED_ZONE_VIOLATION' | 'EV_OVERSTAY' | 'OUT_OF_ZONE' | 'ETC';

export type EventStatus = 'DETECTED' | 'REQUESTED' | 'NEED_ADMIN' | 'RESOLVED' | 'DISMISSED';

// ERD(move_requests.request_status) 기준. 연결된 이동요청이 없으면 null.
export type RequestStatus = 'SENT' | 'RESPONDED' | 'REMINDER_SENT' | 'COMPLETED' | 'NEED_ADMIN' | 'CANCELLED';

// 이동요청이 AI 자동 감지로 발생했는지, 관리자가 수동으로 등록했는지 구분(목록 조회 전용 필드).
export type RequestType = 'AUTO' | 'MANUAL';

export type ActionType = 'COMPLETE' | 'DISMISS' | 'ACKNOWLEDGE' | 'REMINDER';

// GET /api/admin/parking-events 쿼리 파라미터
export type AdminEventListParams = {
  date?: string;
  eventStatus?: EventStatus;
  eventType?: EventType;
  page?: number;
  size?: number;
};

export type AdminEventSummary = {
  eventId: number;
  plateNumber: string;
  eventType: EventType;
  requestType: RequestType | null;
  requestStatus: RequestStatus | null;
  zoneNumber: string | null;
  detectedAt: string;
  eventStatus: EventStatus;
};

export type AdminEventListResult = {
  events: AdminEventSummary[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
};

// GET /api/admin/parking-events/{eventId}
export type EventImage = {
  imageId: number;
  imageUrl: string;
  capturedAt: string;
};

// 명세 예시로 'WILL_MOVE'만 확인됨.
export type DriverResponseType = string;

export type DriverResponse = {
  responseType: DriverResponseType;
  estimatedMinutes: number | null;
  respondedAt: string;
};

export type AdminActionLogEntry = {
  logId: number;
  actionType: ActionType;
  adminName: string;
  actedAt: string;
  memo: string | null;
};

export type AdminEventDetail = {
  eventId: number;
  plateNumber: string;
  eventType: EventType;
  eventStatus: EventStatus;
  requestType: RequestType | null;
  requestStatus: RequestStatus | null;
  zoneNumber: string | null;
  floor: string | null;
  detectedAt: string;
  resolvedAt: string | null;
  violationRatio: number | null;
  reason: string | null;
  reminderCount: number | null;
  requestedAt: string | null;
  images: EventImage[];
  responses: DriverResponse[];
  actionLogs: AdminActionLogEntry[];
};

// GET /api/admin/parking-events/history 쿼리 파라미터
export type AdminHistoryParams = {
  startDate?: string;
  endDate?: string;
  actionType?: ActionType;
  page?: number;
  size?: number;
};

export type AdminHistoryItem = {
  logId: number;
  eventId: number;
  plateNumber: string;
  actionType: ActionType;
  adminName: string;
  actedAt: string;
  memo: string | null;
};

export type AdminHistoryResult = {
  history: AdminHistoryItem[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
};

// POST .../complete, .../dismiss, .../acknowledge 공통 요청 body
export type AdminActionRequest = {
  memo?: string;
};
