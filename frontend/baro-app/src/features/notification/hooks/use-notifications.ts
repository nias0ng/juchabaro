import { useCallback, useEffect, useMemo, useState } from 'react';

import { getNotifications } from '@/features/notification/api/notification-api';
import type { NotificationSummary } from '@/features/notification/api/types';
import { useAuth } from '@/providers/auth-provider';

export type NotificationTab = 'all' | 'moveRequest';

// 백엔드 notificationType 필터는 값 1개만 받으므로, "이동 요청" 탭은 서버에 다시 요청하지 않고
// 전체 목록을 한 번만 받아 이 타입들로 클라이언트에서 걸러낸다.
const MOVE_REQUEST_TAB_TYPES = new Set(['MOVE_REQUEST', 'REMINDER']);

export function useNotifications() {
  const { accessToken, status } = useAuth();
  const [notifications, setNotifications] = useState<NotificationSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tab, setTab] = useState<NotificationTab>('all');
  // Notification 엔티티에 읽음 여부 필드가 없어 로컬 상태로만 처리한다(새로고침하면 전부 안읽음으로 초기화).
  const [readIds, setReadIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken) {
      setNotifications([]);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    getNotifications(accessToken)
      .then((result) => {
        if (isMounted) setNotifications(result.notifications);
      })
      .catch((requestError: unknown) => {
        if (!isMounted) return;
        setNotifications([]);
        setError(requestError instanceof Error ? requestError : new Error('알림을 불러오지 못했습니다.'));
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [status, accessToken]);

  const filteredNotifications = useMemo(
    () =>
      tab === 'all'
        ? notifications
        : notifications.filter((item) => MOVE_REQUEST_TAB_TYPES.has(item.notificationType)),
    [notifications, tab],
  );

  const isUnread = useCallback((notificationId: number) => !readIds.has(notificationId), [readIds]);

  const markAsRead = useCallback((notificationId: number) => {
    setReadIds((prev) => (prev.has(notificationId) ? prev : new Set(prev).add(notificationId)));
  }, []);

  const markAllAsRead = useCallback(() => {
    setReadIds(new Set(notifications.map((item) => item.notificationId)));
  }, [notifications]);

  return {
    notifications: filteredNotifications,
    isLoading,
    error,
    tab,
    setTab,
    isUnread,
    markAsRead,
    markAllAsRead,
  };
}
