import { Pressable, Text, View } from 'react-native';

import type { NotificationSummary } from '@/features/notification/api/types';
import { NOTIFICATION_ICON_COLORS, formatRelativeTime } from '@/features/notification/utils/notification';

import { styles } from './notification-card.styles';

type NotificationCardProps = {
  notification: NotificationSummary;
  unread: boolean;
  onPress: () => void;
};

export function NotificationCard({ notification, unread, onPress }: NotificationCardProps) {
  const colors = NOTIFICATION_ICON_COLORS[notification.notificationType];

  return (
    <Pressable
      accessibilityRole="button"
      style={[styles.container, unread && styles.containerUnread]}
      onPress={onPress}
    >
      <View style={[styles.iconOuter, { backgroundColor: colors.bg }]}>
        <View style={[styles.iconInner, { backgroundColor: colors.dot }]} />
      </View>

      <View style={styles.content}>
        <View style={styles.titleRow}>
          <Text style={styles.title}>{notification.title}</Text>
          {unread ? <View style={styles.unreadDot} /> : null}
        </View>
        <Text style={styles.body}>{notification.body}</Text>
        <Text style={styles.meta}>{formatRelativeTime(notification.sentAt)}</Text>
      </View>
    </Pressable>
  );
}
