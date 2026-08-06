import type { ActionType, EventStatus, EventType, RequestStatus, RequestType } from './api/types';

export const EVENT_TYPE_LABELS: Record<EventType, string> = {
  BAD_PARKING: '불법 주차',
  DOUBLE_PARKING: '이중 주차',
  DISABLED_ZONE_VIOLATION: '장애인 구역 위반',
  EV_OVERSTAY: '전기차 구역 초과',
  OUT_OF_ZONE: '구역 외 주차',
  ETC: '기타',
};

export const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  DETECTED: '감지됨',
  REQUESTED: '이동 요청됨',
  NEED_ADMIN: '관리자 확인 필요',
  RESOLVED: '완료',
  DISMISSED: '오탐 종결',
};

export const ACTION_TYPE_LABELS: Record<ActionType, string> = {
  COMPLETE: '완료 처리',
  DISMISS: '오탐 처리',
  ACKNOWLEDGE: '관리자 확인',
  REMINDER: '재알림 전송',
};

export const REQUEST_TYPE_LABELS: Record<RequestType, string> = {
  AUTO: '자동',
  MANUAL: '수동',
};

// ERD(move_requests.request_status) 정의 문구 그대로. 사건 상세의 "관리자 확인 내용" 칸에 쓴다.
export const REQUEST_STATUS_DESCRIPTIONS: Record<RequestStatus, string> = {
  SENT: '요청 발송됨',
  RESPONDED: '차주 응답함',
  REMINDER_SENT: '1차 확인에서 미이동이 확인되어 재알림을 보냄',
  COMPLETED: '처리 완료',
  NEED_ADMIN: '관리자 확인 필요 (미응답, 이동 어려움, 2차 미이동)',
  CANCELLED: '사건이 오탐 처리되거나 요청이 취소됨',
};

export const EVENT_TYPE_OPTIONS = Object.keys(EVENT_TYPE_LABELS) as EventType[];
export const EVENT_STATUS_OPTIONS = Object.keys(EVENT_STATUS_LABELS) as EventStatus[];
export const ACTION_TYPE_OPTIONS = Object.keys(ACTION_TYPE_LABELS) as ActionType[];

export function eventTypeLabel(type: EventType): string {
  return EVENT_TYPE_LABELS[type];
}

// REQUESTED 상태는 requestType(자동/수동)을 함께 받으면 "자동"/"수동"으로 세분화해서
// 보여준다. requestType이 없는 호출(필터 드롭다운 등 특정 사건과 무관한 곳)은 기존
// "이동 요청됨" 문구를 그대로 쓴다.
export function eventStatusLabel(status: EventStatus, requestType?: RequestType): string {
  if (status === 'REQUESTED' && requestType) {
    return requestTypeLabel(requestType);
  }
  return EVENT_STATUS_LABELS[status];
}

export function actionTypeLabel(action: ActionType): string {
  return ACTION_TYPE_LABELS[action];
}

export function requestTypeLabel(type: RequestType): string {
  return REQUEST_TYPE_LABELS[type];
}

export function requestStatusDescription(status: RequestStatus | null): string {
  if (!status) return '연결된 이동 요청 없음';
  return REQUEST_STATUS_DESCRIPTIONS[status];
}

export function typeTone(type: EventType) {
  if (type === 'DISABLED_ZONE_VIOLATION') return 'success' as const;
  if (type === 'EV_OVERSTAY') return 'sky' as const;
  if (type === 'ETC') return 'neutral' as const;
  return 'danger' as const;
}

// REQUESTED 상태(자동/수동)는 배지 없이 일반 텍스트로 보여줘서 이 함수가 호출되지 않는다
// (ParkingEventListView.vue, EventDetailCard.vue 참고). 그 외 상태만 배지 톤을 정한다.
export function statusTone(status: EventStatus) {
  if (status === 'RESOLVED') return 'success' as const;
  if (status === 'DISMISSED') return 'neutral' as const;
  if (status === 'NEED_ADMIN') return 'info' as const;
  return 'danger' as const;
}

export function actionTone(action: ActionType) {
  if (action === 'COMPLETE') return 'success' as const;
  if (action === 'DISMISS' || action === 'ACKNOWLEDGE') return 'info' as const;
  return 'primary' as const;
}

export function formatEventId(eventId: number): string {
  return `#${eventId}`;
}

function toDateString(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// yyyy-MM-dd 형식의 로컬 날짜(주로 날짜 필터 기본값과 CSV 파일명에 사용).
export function todayDateString(): string {
  return toDateString(new Date());
}

// 관리자 사건 목록 API(GET /api/admin/parking-events)는 date를 안 보내도 "전체 기간"이 아니라
// 서버가 오늘 하루로 채워서 그 하루치만 돌려준다. 날짜 필터를 고르지 않았을 때 오늘 데이터가
// 없으면 이 함수로 하루씩 과거로 거슬러 올라가며 데이터가 있는 날을 찾는 데 쓴다.
export function dateStringDaysAgo(daysAgo: number): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return toDateString(date);
}

// ISO 시각을 yyyy-MM-dd 로컬 날짜로 변환(같은 날짜의 항목만 모아 보여줄 때 사용).
export function localDateString(iso: string): string {
  return toDateString(new Date(iso));
}

export function formatDate(value: string): string {
  return value.replaceAll('-', '.');
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}.${month}.${day} ${formatTime(iso)}`;
}
