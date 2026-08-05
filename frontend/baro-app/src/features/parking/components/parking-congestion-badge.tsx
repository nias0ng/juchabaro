import { Text, View } from 'react-native';

import type { CongestionLevel } from '../api/types';

import { styles } from './parking-congestion-badge.styles';

const PILL_STYLE: Record<CongestionLevel, object> = {
  LOW: styles.pillLow,
  MEDIUM: styles.pillMedium,
  HIGH: styles.pillHigh,
};

const VALUE_COLOR_STYLE: Record<CongestionLevel, object> = {
  LOW: styles.valueLow,
  MEDIUM: styles.valueMedium,
  HIGH: styles.valueHigh,
};

type ParkingCongestionBadgeProps = {
  level: CongestionLevel;
  /** "여유 · 14%" 형태. "혼잡도"라는 접두어는 이 컴포넌트가 직접 붙인다. */
  valueLabel: string;
};

export function ParkingCongestionBadge({ level, valueLabel }: ParkingCongestionBadgeProps) {
  return (
    <View style={styles.row}>
      <Text style={styles.prefix}>혼잡도</Text>
      <View style={[styles.pill, PILL_STYLE[level]]}>
        <Text style={[styles.value, VALUE_COLOR_STYLE[level]]}>{valueLabel}</Text>
      </View>
    </View>
  );
}
