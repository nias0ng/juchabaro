import { Text, View } from 'react-native';

import { Stack } from '@/components/ui';
import type { VehicleStatusDisplay } from '@/features/resident/utils/parking-session';
import { Spacing } from '@/styles';

import { styles } from './vehicle-status-card.styles';

type VehicleStatusCardProps = {
  session: VehicleStatusDisplay | null;
  additionalCount?: number;
  isLoading?: boolean;
  hasError?: boolean;
};

export function VehicleStatusCard({
  session,
  additionalCount = 0,
  isLoading = false,
  hasError = false,
}: VehicleStatusCardProps) {
  if (isLoading || hasError || !session) {
    const statusMessage = isLoading
      ? '주차 정보를 불러오는 중입니다'
      : hasError
        ? '주차 정보를 불러오지 못했습니다'
        : '주차된 차량이 없습니다';

    return (
      <View style={[styles.card, styles.emptyCard]}>
        <Text style={styles.emptyText}>{statusMessage}</Text>
      </View>
    );
  }

  const isViolation = session.status === 'VIOLATION';

  return (
    <View style={styles.card}>
      <View style={styles.headerGroup}>
        <View style={styles.statusRow}>
          <View style={[styles.statusDot, isViolation && styles.statusDotViolation]} />
          <Text style={[styles.statusLabel, isViolation && styles.statusLabelViolation]}>
            {session.statusLabel}
          </Text>
          <Text style={styles.statusTime}>{session.statusTime}</Text>
        </View>

        <View style={styles.plateRow}>
          <Text style={styles.plateText}>{session.plateNumber}</Text>
          {session.model ? <Text style={styles.modelText}>{session.model}</Text> : null}
        </View>
      </View>

      <Stack gap={Spacing.xxs}>
        <Text style={styles.fieldLabel}>위치</Text>
        <Text style={styles.fieldValue}>{session.location}</Text>
      </Stack>

      {additionalCount > 0 ? (
        <Text style={styles.additionalCountBadge}>+{additionalCount}대 더 주차 중</Text>
      ) : null}
    </View>
  );
}
