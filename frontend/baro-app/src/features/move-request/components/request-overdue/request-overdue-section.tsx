import { Pressable, Text, View } from 'react-native';

import { RequestOverdueTimelineCard, type RequestOverdueTimelineStep } from './request-overdue-timeline-card';
import { RequestOverdueTimerRing } from './request-overdue-timer-ring';
import { styles } from './request-overdue-section.styles';

type RequestOverdueSectionProps = {
  elapsedLabel: string;
  timeline: RequestOverdueTimelineStep[];
  onPressDetail: () => void;
};

export function RequestOverdueSection({ elapsedLabel, timeline, onPressDetail }: RequestOverdueSectionProps) {
  return (
    <View style={styles.container}>
      <View style={styles.textBlock}>
        <View style={styles.pill}>
          <Text style={styles.pillText}>미이동 확인</Text>
        </View>
        <Text style={styles.heading}>{'예정 시간 후에도 차량이\n확인되었습니다.'}</Text>
      </View>

      <RequestOverdueTimerRing label={elapsedLabel} />
      <RequestOverdueTimelineCard timeline={timeline} />

      <Pressable accessibilityRole="button" style={styles.detailButton} onPress={onPressDetail}>
        <Text style={styles.detailButtonText}>상세 요청 보기</Text>
      </Pressable>
    </View>
  );
}
