import type {
  MoveEventType,
  MoveRequestSummary,
} from '@/features/move-request/api/types';
import { formatDurationLabel } from '@/features/move-request/utils/move-request';

import type { ViolationHistoryItem, ViolationStatus } from '../api/types';

const EVENT_TYPE_LABEL: Record<MoveEventType, string> = {
  BAD_PARKING: '불편 주차',
  DOUBLE_PARKING: '이중 주차',
  DISABLED_ZONE_VIOLATION: '장애인 주차구역 위반',
  EV_OVERSTAY: '전기차 충전구역 장기 점유',
  OUT_OF_ZONE: '구역 외 주차',
  ETC: '기타',
};

function getViolationStatus(request: MoveRequestSummary): ViolationStatus {
  return request.requestStatus === 'COMPLETED' || request.requestStatus === 'CANCELLED'
    ? 'RESOLVED'
    : 'UNRESOLVED';
}

function formatRequestedAt(iso: string): string {
  const date = new Date(iso);
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${month}/${day} ${hours}:${minutes}`;
}

function getMonthLabel(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}년 ${date.getMonth() + 1}월`;
}

function getStatusDescription(request: MoveRequestSummary): string {
  if (request.requestStatus === 'COMPLETED' && request.resolvedAt) {
    const duration = formatDurationLabel(request.requestedAt, request.resolvedAt);
    return duration ? `${duration} 만에 이동` : '이동 완료';
  }

  if (request.requestStatus === 'CANCELLED') return '요청 취소';
  if (request.requestStatus === 'NEED_ADMIN') return '관리사무소 전달';
  if (request.requestStatus === 'REMINDER_SENT') return `재알림 ${request.reminderCount}회`;
  if (request.requestStatus === 'RESPONDED' && request.estimatedMinutes !== null) {
    return `${request.estimatedMinutes}분 이내 이동 예정`;
  }

  return '처리 중';
}

export function toViolationHistoryItem(request: MoveRequestSummary): ViolationHistoryItem {
  const metaParts = [
    formatRequestedAt(request.requestedAt),
    request.zoneNumber,
    getStatusDescription(request),
  ].filter((value): value is string => Boolean(value));

  return {
    requestId: request.requestId,
    type: request.eventType,
    title: EVENT_TYPE_LABEL[request.eventType],
    meta: metaParts.join(' · '),
    status: getViolationStatus(request),
    monthLabel: getMonthLabel(request.requestedAt),
  };
}
