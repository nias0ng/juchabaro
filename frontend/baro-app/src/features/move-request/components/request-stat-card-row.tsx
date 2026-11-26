import { Text, View } from 'react-native';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-stat-card-row.styles';

type RequestStatCardRowProps = {
  leftLabel: string;
  leftValue: string;
  rightLabel: string;
  rightValue: string;
  rightValueColor?: string;
};

export function RequestStatCardRow({
  leftLabel,
  leftValue,
  rightLabel,
  rightValue,
  rightValueColor,
}: RequestStatCardRowProps) {
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.row}>
      <View style={styles.card}>
        <Text style={styles.label}>{leftLabel}</Text>
        <Text style={styles.value}>{leftValue}</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.label}>{rightLabel}</Text>
        <Text style={[styles.value, rightValueColor ? { color: rightValueColor } : null]}>{rightValue}</Text>
      </View>
    </View>
  );
}
