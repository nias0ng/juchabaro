import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { getNotifications } from '@/features/notification/api/notification-api';
import type { NotificationSummary } from '@/features/notification/api/types';
import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { queryKeys } from '@/services/query-keys';

export type NotificationTab = 'all' | 'moveRequest';

// 백엔드 notificationType 필터는 값 1개만 받으므로, "이동 요청" 탭은 서버에 다시 요청하지 않고
// 전체 목록을 한 번만 받아 이 타입들로 클라이언트에서 걸러낸다.
const MOVE_REQUEST_TAB_TYPES = new Set(['MOVE_REQUEST', 'MOVE_RESPONSE', 'REMINDER']);

async function fetchNotifications(accessToken: string): Promise<NotificationSummary[]> {
  const result = await getNotifications(accessToken);
  return result.notifications;
}

export function useNotifications() {
  const { accessToken, status } = useAuth();
  const [tab, setTab] = useState<NotificationTab>('all');

  const query = useQuery({
    queryKey: queryKeys.notifications.list(),
    queryFn: () => fetchNotifications(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
  });
  useRefetchOnFocus(query.refetch, query.isStale);

  const filteredNotifications = useMemo(() => {
    const notifications = query.data ?? [];
    return tab === 'all'
      ? notifications
      : notifications.filter((item) => MOVE_REQUEST_TAB_TYPES.has(item.notificationType));
  }, [query.data, tab]);

  return {
    notifications: filteredNotifications,
    isLoading: query.isLoading,
    isRefreshing: query.isFetching && !query.isLoading,
    error: query.error,
    refetch: query.refetch,
    tab,
    setTab,
  };
}
