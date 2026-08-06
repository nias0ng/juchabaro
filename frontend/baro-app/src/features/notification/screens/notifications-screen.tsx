import {
  AsyncStateView,
  GradientScreenBackground,
  ResponsiveContainer,
  ScreenHeader,
  SegmentedControl,
  Stack,
} from '@/components/ui';
import type { NotificationSummary } from '@/features/notification/api/types';
import { NotificationCard } from '@/features/notification/components/list/notification-card';
import { useNotifications, type NotificationTab } from '@/features/notification/hooks/use-notifications';
import { navigateFromNotification } from '@/features/notification/utils/notification-navigation';
import { Spacing } from '@/styles';

const TAB_OPTIONS: { key: NotificationTab; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'moveRequest', label: '이동 요청' },
];

export default function NotificationsScreen() {
  const { notifications, isLoading, isRefreshing, error, refetch, tab, setTab, dismissNotification } =
    useNotifications();

  const handlePressNotification = (notification: NotificationSummary) => {
    navigateFromNotification(
      {
        notificationType: notification.notificationType,
        requestId: notification.requestId,
      },
      false,
    );
  };

  const statusMessage = isLoading
    ? '알림을 불러오는 중입니다.'
    : error
      ? '알림을 불러오지 못했습니다.'
      : notifications.length === 0
        ? '받은 알림이 없습니다.'
        : undefined;

  return (
    <GradientScreenBackground refreshing={isRefreshing} onRefresh={() => void refetch()}>
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
                  onDismiss={() => dismissNotification(notification.notificationId)}
                />
              ))}
            </Stack>
          </AsyncStateView>
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
