import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { ResponsiveContainer, Screen, Stack } from '@/components/ui';
import { NotificationCard } from '@/features/notification/components/list/notification-card';
import { NotificationTabs } from '@/features/notification/components/list/notification-tabs';
import type { NotificationSummary } from '@/features/notification/api/types';
import { useNotifications } from '@/features/notification/hooks/use-notifications';
import { Spacing } from '@/styles';

import { styles } from './notifications-screen.styles';

export default function NotificationsScreen() {
  const { notifications, isLoading, error, tab, setTab, isUnread, markAsRead, markAllAsRead } =
    useNotifications();

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
    <Screen scroll edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack gap={Spacing.md}>
          <View style={styles.headerRow}>
            <Text style={styles.headerTitle}>알림</Text>
            <Pressable accessibilityRole="button" onPress={markAllAsRead}>
              <Text style={styles.markAllText}>모두 읽음</Text>
            </Pressable>
          </View>

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
    </Screen>
  );
}
