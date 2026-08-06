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

const LEVEL_LABEL: Record<CongestionLevel, string> = {
  LOW: '여유',
  MEDIUM: '보통',
  HIGH: '혼잡',
};

type ParkingCongestionBadgeProps = {
  level: CongestionLevel;
  rateLabel: string;
};

export function ParkingCongestionBadge({ level, rateLabel }: ParkingCongestionBadgeProps) {
  return (
    <View style={styles.row}>
      <Text style={styles.metric}>혼잡도 {rateLabel}</Text>
      <View style={[styles.pill, PILL_STYLE[level]]}>
        <Text style={[styles.value, VALUE_COLOR_STYLE[level]]}>{LEVEL_LABEL[level]}</Text>
      </View>
    </View>
  );
}
