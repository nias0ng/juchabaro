import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { Palette } from '@/styles';

import type { ViolationStats } from '../api/types';

import { styles } from './violation-summary-card.styles';

const SUMMARY_CARD_GRADIENT = [Palette.peach100, Palette.lavender100] as const;

type ViolationSummaryCardProps = {
  summary: ViolationStats;
};

export function ViolationSummaryCard({ summary }: ViolationSummaryCardProps) {
  return (
    <LinearGradient colors={SUMMARY_CARD_GRADIENT} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.card}>
      <Text style={styles.label}>최근 90일 기준</Text>

      <View style={styles.statRow}>
        <View style={styles.statTile}>
          <Text style={styles.statLabel}>누적</Text>
          <Text style={styles.statValue}>{summary.totalCount}건</Text>
        </View>
        <View style={styles.statTile}>
          <Text style={styles.statLabel}>미해결</Text>
          <Text style={[styles.statValue, styles.statValueDanger]}>{summary.unresolvedCount}건</Text>
        </View>
        <View style={styles.statTile}>
          <Text style={styles.statLabel}>평균 응답</Text>
          <Text style={styles.statValue}>{summary.averageResponseMinutes}분</Text>
        </View>
      </View>
    </LinearGradient>
  );
}
