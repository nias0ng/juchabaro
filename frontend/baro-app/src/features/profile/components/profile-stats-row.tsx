import { Pressable, Text, View } from 'react-native';

import { styles } from './profile-stats-row.styles';

type ProfileStatsRowProps = {
  vehicleCount: number;
  violationCount: number | null;
  isViolationLoading: boolean;
  onPressVehicles: () => void;
  onPressViolations: () => void;
};

export function ProfileStatsRow({
  vehicleCount,
  violationCount,
  isViolationLoading,
  onPressVehicles,
  onPressViolations,
}: ProfileStatsRowProps) {
  return (
    <View style={styles.row}>
      <Pressable
        accessibilityRole="button"
        style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}
        onPress={onPressVehicles}
      >
        <Text style={styles.label}>등록 차량</Text>
        <Text style={styles.value}>{vehicleCount}</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}
        onPress={onPressViolations}
      >
        <Text style={styles.label}>누적 위반</Text>
        <Text style={styles.value}>{isViolationLoading ? '-' : (violationCount ?? '-')}</Text>
      </Pressable>
    </View>
  );
}
