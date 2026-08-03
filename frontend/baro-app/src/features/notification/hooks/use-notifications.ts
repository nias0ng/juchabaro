import { useMemo, useState } from 'react';

import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';
import { getNotifications } from '@/features/notification/api/notification-api';
import type { NotificationSummary } from '@/features/notification/api/types';

export type NotificationTab = 'all' | 'moveRequest';

// 백엔드 notificationType 필터는 값 1개만 받으므로, "이동 요청" 탭은 서버에 다시 요청하지 않고
// 전체 목록을 한 번만 받아 이 타입들로 클라이언트에서 걸러낸다.
const MOVE_REQUEST_TAB_TYPES = new Set(['MOVE_REQUEST', 'REMINDER']);

async function fetchNotifications(accessToken: string): Promise<NotificationSummary[]> {
  const result = await getNotifications(accessToken);
  return result.notifications;
}

export function useNotifications() {
  const [tab, setTab] = useState<NotificationTab>('all');
  const {
    data: notifications,
    isLoading,
    error,
  } = useAuthenticatedQuery<NotificationSummary[]>(fetchNotifications, [], '알림을 불러오지 못했습니다.');

  const filteredNotifications = useMemo(
    () =>
      tab === 'all'
        ? notifications
        : notifications.filter((item) => MOVE_REQUEST_TAB_TYPES.has(item.notificationType)),
    [notifications, tab],
  );

  return {
    notifications: filteredNotifications,
    isLoading,
    error,
    tab,
    setTab,
  };
}
