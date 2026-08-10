import { Text, View } from 'react-native';

import type { CongestionLevel } from '../api/types';

import { styles } from './parking-availability-label.styles';

type ParkingAvailabilityLabelProps = {
  availableCount: number;
  congestionLevel: CongestionLevel;
};

const VALUE_COLOR_STYLE: Record<CongestionLevel, object> = {
  LOW: styles.valueLow,
  MEDIUM: styles.valueMedium,
  HIGH: styles.valueHigh,
};

export function ParkingAvailabilityLabel({
  availableCount,
  congestionLevel,
}: ParkingAvailabilityLabelProps) {
  return (
    <View
      style={styles.row}
      accessible
      accessibilityLabel={`주차 가능 ${availableCount}칸`}
    >
      <Text style={styles.label}>주차 가능</Text>
      <View style={styles.countGroup}>
        <Text style={[styles.value, VALUE_COLOR_STYLE[congestionLevel]]}>{availableCount}</Text>
        <Text style={styles.unit}>칸</Text>
      </View>
    </View>
  );
}
