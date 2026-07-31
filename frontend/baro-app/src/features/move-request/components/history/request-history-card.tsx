import { Pressable, Text, View } from 'react-native';

import type { MoveRequestStatus } from '@/features/move-request/api/types';
import type { RequestSummaryDisplay } from '@/features/move-request/utils/move-request';
import { Palette } from '@/styles';

import { styles } from './request-history-card.styles';

const STATUS_COLOR: Record<MoveRequestStatus, { bg: string; text: string }> = {
  SENT: { bg: Palette.lavender100, text: Palette.violet600 },
  RESPONDED: { bg: Palette.lavender100, text: Palette.violet600 },
  REMINDER_SENT: { bg: Palette.orange50, text: Palette.orange600 },
  COMPLETED: { bg: Palette.teal100, text: Palette.teal600 },
  NEED_ADMIN: { bg: Palette.orange50, text: Palette.orange600 },
  CANCELLED: { bg: Palette.gray100, text: Palette.gray500 },
};

type RequestHistoryCardProps = {
  display: RequestSummaryDisplay;
  status: MoveRequestStatus;
  onPress: () => void;
};

export function RequestHistoryCard({ display, status, onPress }: RequestHistoryCardProps) {
  const color = STATUS_COLOR[status];

  return (
    <Pressable accessibilityRole="button" style={styles.container} onPress={onPress}>
      <View style={styles.headerRow}>
        <Text style={styles.plateNumber}>{display.plateNumber}</Text>
        <View style={[styles.statusBadge, { backgroundColor: color.bg }]}>
          <Text style={[styles.statusText, { color: color.text }]}>{display.statusLabel}</Text>
        </View>
      </View>
      <Text style={styles.eventType}>{display.eventTypeLabel}</Text>
      {display.message ? <Text style={styles.message}>{display.message}</Text> : null}
      <Text style={styles.requestedAt}>{display.requestedAtLabel}</Text>
    </Pressable>
  );
}
