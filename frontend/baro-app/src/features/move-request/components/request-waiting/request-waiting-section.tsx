import { Pressable, Text, View } from 'react-native';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { RequestCountdownRing } from './request-countdown-ring';
import { RequestProgressCard } from './request-progress-card';
import { createStyles } from './request-waiting-section.styles';

type RequestWaitingSectionProps = {
  countdownLabel: string;
  progress: number;
  dueTimeLabel: string;
  respondedTimeLabel: string;
  onPressDetail: () => void;
};

// E-12: 응답 완료 후 차량 이동을 기다리는 화면 본문 (배지 + 카운트다운 + 진행 카드 + 상세 보기 버튼)
export function RequestWaitingSection({
  countdownLabel,
  progress,
  dueTimeLabel,
  respondedTimeLabel,
  onPressDetail,
}: RequestWaitingSectionProps) {
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.container}>
      <View style={styles.pill}>
        <Text style={styles.pillText}>이동 대기중</Text>
      </View>
      <Text style={styles.label}>차량 이동까지</Text>

      <RequestCountdownRing label={countdownLabel} progress={progress} />

      <RequestProgressCard dueTimeLabel={dueTimeLabel} respondedTimeLabel={respondedTimeLabel} />

      <Pressable accessibilityRole="button" style={styles.detailButton} onPress={onPressDetail}>
        <Text style={styles.detailButtonText}>요청 상세 보기</Text>
      </Pressable>
    </View>
  );
}
