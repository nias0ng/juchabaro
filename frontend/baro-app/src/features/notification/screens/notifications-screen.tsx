import { router } from 'expo-router';
import { Text, View } from 'react-native';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, Stack } from '@/components/ui';
import { NotificationCard } from '@/features/notification/components/list/notification-card';
import { NotificationTabs } from '@/features/notification/components/list/notification-tabs';
import type { NotificationSummary } from '@/features/notification/api/types';
import { useNotifications } from '@/features/notification/hooks/use-notifications';
import { Spacing } from '@/styles';

import { styles } from './notifications-screen.styles';

export default function NotificationsScreen() {
  const { notifications, isLoading, error, tab, setTab, isUnread, markAsRead } = useNotifications();

  const handlePressNotification = (notification: NotificationSummary) => {
    markAsRead(notification.notificationId);

    // 이번 스코프에서는 '차량 이동 요청' 알림만 실제 목적지(E-11)가 있다. 나머지 타입은 읽음 처리만 한다.
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
          <NotificationTabs active={tab} onChange={setTab} />

          {statusMessage ? (
            <View style={styles.statusContainer}>
              <Text style={styles.statusText}>{statusMessage}</Text>
            </View>
          ) : (
            <Stack gap={Spacing.base}>
              {notifications.map((notification) => (
                <NotificationCard
                  key={notification.notificationId}
                  notification={notification}
                  unread={isUnread(notification.notificationId)}
                  onPress={() => handlePressNotification(notification)}
                />
              ))}
            </Stack>
          )}
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
