import { Pressable, Text, View } from 'react-native';

import type { RequestCompletedTimelineStep } from '@/features/move-request/utils/move-request';

import { RequestCompletedBadge } from './request-completed-badge';
import { RequestCompletionCard } from './request-completion-card';
import { styles } from './request-completed-section.styles';

type RequestCompletedSectionProps = {
  endTimeLabel: string;
  timeline: RequestCompletedTimelineStep[];
  onPressHome: () => void;
};

export function RequestCompletedSection({ endTimeLabel, timeline, onPressHome }: RequestCompletedSectionProps) {
  return (
    <View style={styles.container}>
      <RequestCompletedBadge />
      <View style={styles.textBlock}>
        <Text style={styles.heading}>{'차량 이동이\n확인되었습니다'}</Text>
        <Text style={styles.subheading}>{'매너 있는 주차 문화에 동참해주셔서\n감사합니다.'}</Text>
      </View>
      <RequestCompletionCard endTimeLabel={endTimeLabel} timeline={timeline} />
      <Pressable accessibilityRole="button" style={styles.homeButton} onPress={onPressHome}>
        <Text style={styles.homeButtonText}>홈으로 돌아가기</Text>
      </Pressable>
    </View>
  );
}
