import { router } from 'expo-router';

import type { NotificationType } from '../api/types';

type NotificationNavigationData = Record<string, unknown> & {
  type?: unknown;
  notificationType?: unknown;
  requestId?: unknown;
};

const REQUEST_DETAIL_TYPES = new Set<NotificationType>([
  'MOVE_REQUEST',
  'MOVE_RESPONSE',
  'REMINDER',
  'EVENT_RESOLVED',
]);

function getNotificationType(data: NotificationNavigationData): NotificationType | null {
  const value = data.type ?? data.notificationType;
  if (
    value === 'MOVE_REQUEST' ||
    value === 'MOVE_RESPONSE' ||
    value === 'REMINDER' ||
    value === 'EV_OVERSTAY' ||
    value === 'EVENT_RESOLVED'
  ) {
    return value;
  }

  return null;
}

function getRequestId(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'string' && value.trim().length > 0) return value.trim();
  return null;
}

export function navigateFromNotification(
  data: NotificationNavigationData,
  fallbackToNotificationList = true,
): boolean {
  const type = getNotificationType(data);
  const requestId = getRequestId(data.requestId);

  // 자동 EV 초과 알림은 현재 백엔드에서 MoveRequest 없이 생성되어 requestId가 null이다.
  // 후속 처리로 이동 요청이 연결된 알림이라면 상세로, 그렇지 않으면 남은 시간/초과 상태를
  // 보여주는 메인 주차 카드로 이동한다.
  if (type === 'EV_OVERSTAY') {
    if (requestId) {
      router.push({
        pathname: '/resident/request-detail',
        params: { requestId },
      });
    } else {
      router.push('/resident');
    }
    return true;
  }

  if (type && REQUEST_DETAIL_TYPES.has(type)) {
    if (requestId) {
      router.push({
        pathname: '/resident/request-detail',
        params: { requestId },
      });
    } else {
      router.push('/resident/requests');
    }
    return true;
  }

  if (fallbackToNotificationList) {
    router.push('/resident/notifications');
    return true;
  }

  return false;
}
