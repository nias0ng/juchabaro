import { router } from 'expo-router';

import {
  AsyncStateView,
  GradientScreenBackground,
  ResponsiveContainer,
  ScreenHeader,
  SegmentedControl,
  Stack,
} from '@/components/ui';
import { NotificationCard } from '@/features/notification/components/list/notification-card';
import type { NotificationSummary } from '@/features/notification/api/types';
import { useNotifications, type NotificationTab } from '@/features/notification/hooks/use-notifications';
import { Spacing } from '@/styles';

const TAB_OPTIONS: { key: NotificationTab; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'moveRequest', label: '이동 요청' },
];

export default function NotificationsScreen() {
  const { notifications, isLoading, error, tab, setTab } = useNotifications();

  const handlePressNotification = (notification: NotificationSummary) => {
    // 이번 스코프에서는 '차량 이동 요청' 알림만 실제 목적지(E-11)가 있다. 나머지 타입은 눌러도 아무 동작이 없다.
    if (notification.notificationType === 'MOVE_REQUEST' && notification.requestId !== null) {
      router.push({
        pathname: '/resident/request-detail',
        params: { requestId: String(notification.requestId) },
      });
    }
  };

  const statusMessage = isLoading
    ? '알림을 불러오는 중입니다'
    : error
      ? '알림을 불러오지 못했습니다'
      : notifications.length === 0
        ? '받은 알림이 없습니다'
        : undefined;

  return (
    <GradientScreenBackground>
      <ResponsiveContainer>
        <ScreenHeader title="알림" showBackButton={false} />

        <Stack gap={Spacing.md} fill>
          <SegmentedControl options={TAB_OPTIONS} value={tab} onChange={setTab} />

          <AsyncStateView message={statusMessage}>
            <Stack gap={Spacing.base}>
              {notifications.map((notification) => (
                <NotificationCard
                  key={notification.notificationId}
                  notification={notification}
                  onPress={() => handlePressNotification(notification)}
                />
              ))}
            </Stack>
          </AsyncStateView>
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
