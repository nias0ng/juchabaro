import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { getNotifications } from '@/features/notification/api/notification-api';
import type { NotificationSummary } from '@/features/notification/api/types';
import {
  addDismissedNotificationId,
  getDismissedNotificationIds,
} from '@/features/notification/services/dismissed-notifications-storage';
import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

export type NotificationTab = 'all' | 'moveRequest';

const MOVE_REQUEST_TAB_TYPES = new Set(['MOVE_REQUEST', 'MOVE_RESPONSE', 'REMINDER']);

async function fetchNotifications(accessToken: string): Promise<NotificationSummary[]> {
  const result = await getNotifications(accessToken);
  return result.notifications;
}

/**
 * 알림 목록을 조회하고, 스와이프로 숨긴 알림(기기 로컬 기록)을 걸러내 탭별로 보여준다.
 * API: GET /api/notifications
 */
export function useNotifications() {
  const { accessToken, status } = useAuth();
  const [tab, setTab] = useState<NotificationTab>('all');

  const query = useQuery({
    queryKey: queryKeys.notifications.list(),
    queryFn: () => fetchNotifications(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  // 스와이프로 지운 알림은 서버 삭제 API가 없어 기기에만 기록해두고, 다음 조회 결과에서도 계속 걸러낸다.
  const [dismissedIds, setDismissedIds] = useState<Set<number>>(new Set());
  useEffect(() => {
    let isMounted = true;
    getDismissedNotificationIds().then((ids) => {
      if (isMounted) setDismissedIds(ids);
    });
    return () => {
      isMounted = false;
    };
  }, []);

  const dismissNotification = (notificationId: number) => {
    setDismissedIds((prev) => new Set(prev).add(notificationId));
    void addDismissedNotificationId(notificationId);
  };

  const filteredNotifications = useMemo(() => {
    const visible = (query.data ?? []).filter((item) => !dismissedIds.has(item.notificationId));
    return tab === 'all'
      ? visible
      : visible.filter((item) => MOVE_REQUEST_TAB_TYPES.has(item.notificationType));
  }, [query.data, tab, dismissedIds]);

  return {
    notifications: filteredNotifications,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    // 백그라운드 갱신 실패는 이미 화면에 표시된 데이터를 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    error: query.data === undefined ? query.error : null,
    refetch: query.refetch,
    tab,
    setTab,
    dismissNotification,
  };
}
