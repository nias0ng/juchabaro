import { Text, View } from 'react-native';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-progress-card.styles';

type RequestProgressCardProps = {
  dueTimeLabel: string;
  respondedTimeLabel: string;
};

export function RequestProgressCard({ dueTimeLabel, respondedTimeLabel }: RequestProgressCardProps) {
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={[styles.dot, styles.dotActive]} />
        <Text style={styles.labelActive}>예정 시간</Text>
        <Text style={styles.valueActive}>{dueTimeLabel}까지 이동 예정</Text>
      </View>

      <View style={styles.divider} />

      <View style={styles.row}>
        <View style={[styles.dot, styles.dotDone]} />
        <Text style={styles.label}>요청 완료</Text>
        <Text style={styles.value}>{respondedTimeLabel}</Text>
      </View>

      <View style={styles.row}>
        <View style={[styles.dot, styles.dotNext]} />
        <Text style={styles.label}>차량 이동 대기 중</Text>
        <View style={styles.nextBadge}>
          <Text style={styles.nextBadgeText}>NEXT</Text>
        </View>
      </View>
    </View>
  );
}
