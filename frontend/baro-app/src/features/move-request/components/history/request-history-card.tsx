import { Pressable, Text, View } from 'react-native';

import type { MoveRequestStatus } from '@/features/move-request/api/types';
import type { RequestSummaryDisplay } from '@/features/move-request/utils/move-request';
import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';
import type { ColorTokens } from '@/styles';

import { createStyles } from './request-history-card.styles';

function getStatusColor(status: MoveRequestStatus, t: ColorTokens): { bg: string; text: string } {
  switch (status) {
    case 'SENT':
    case 'RESPONDED':
      return { bg: t.fill.brand.weak, text: t.text.brand };
    case 'REMINDER_SENT':
    case 'NEED_ADMIN':
      return { bg: t.fill.warning.weak, text: t.text.warning };
    case 'COMPLETED':
      return { bg: t.fill.success.weak, text: t.text.success };
    case 'CANCELLED':
      return { bg: t.fill.neutral.weak, text: t.text.weaker };
  }
}

type RequestHistoryCardProps = {
  display: RequestSummaryDisplay;
  status: MoveRequestStatus;
  onPress: () => void;
};

export function RequestHistoryCard({ display, status, onPress }: RequestHistoryCardProps) {
  const styles = useThemedStyles(createStyles);
  const color = getStatusColor(status, useColorTokens());

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
