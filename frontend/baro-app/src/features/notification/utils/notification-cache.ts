import type { QueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/services/query-keys';

import type { NotificationNavigationData } from './notification-navigation';
import { getNotificationType, getRequestId } from './notification-navigation';

/**
 * 푸시 수신과 푸시 클릭이 공용으로 쓰는 무효화 helper. 알림 타입별로 실제 영향을 받는 쿼리만 좁혀서 무효화한다.
 * 알 수 없는 타입만 안전하게 전체 무효화로 fallback한다.
 */
export function invalidateForNotification(queryClient: QueryClient, data: NotificationNavigationData): void {
  const type = getNotificationType(data);
  const requestId = getRequestId(data.requestId);
  const numericRequestId = requestId ? Number(requestId) : NaN;
  const hasValidRequestId = Number.isInteger(numericRequestId) && numericRequestId > 0;

  void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.list() });

  if (type === 'MOVE_REQUEST' || type === 'MOVE_RESPONSE' || type === 'REMINDER' || type === 'EVENT_RESOLVED') {
    void queryClient.invalidateQueries({ queryKey: queryKeys.moveRequests.lists() });
    if (hasValidRequestId) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.moveRequests.detail(numericRequestId) });
    }
    if (type === 'EVENT_RESOLVED') {
      // 이관 처리 완료는 실제 차량 이동/출차를 동반할 수 있어 주차 현황·구역 요약·위반 통계까지 함께 갱신한다.
      void queryClient.invalidateQueries({ queryKey: queryKeys.parking.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.parking.zoneSummary() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.violation.stats() });
    }
    return;
  }

  if (type === 'EV_OVERSTAY') {
    void queryClient.invalidateQueries({ queryKey: queryKeys.parking.sessions() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.violation.stats() });
    if (hasValidRequestId) {
      // EV_OVERSTAY도 이동요청으로 연결되는 경우가 있어 함께 갱신한다.
      void queryClient.invalidateQueries({ queryKey: queryKeys.moveRequests.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.moveRequests.detail(numericRequestId) });
    }
    return;
  }

  // 알 수 없는 타입만 안전하게 전체 무효화
  void queryClient.invalidateQueries();
}
