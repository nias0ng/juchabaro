import { Text, View } from 'react-native';

import { Stack } from '@/components/ui';
import type { VehicleStatusDisplay } from '@/features/resident/utils/parking-session';
import { Spacing } from '@/styles';

import { styles } from './vehicle-status-card.styles';

type VehicleStatusCardProps = {
  session: VehicleStatusDisplay | null;
};

export function VehicleStatusCard({ session }: VehicleStatusCardProps) {
  if (!session) {
    return (
      <View style={[styles.card, styles.emptyCard]}>
        <Text style={styles.emptyText}>주차된 차량이 없습니다</Text>
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
    </View>
  );
}
