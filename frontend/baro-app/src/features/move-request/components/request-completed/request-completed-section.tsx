import { Pressable, Text, View } from 'react-native';

import type { RequestTimelineStep } from '@/features/move-request/utils/move-request';

import { RequestTimelineCard } from '../request-timeline-card';
import { RequestCompletedBadge } from './request-completed-badge';
import { styles } from './request-completed-section.styles';

type RequestCompletedSectionProps = {
  endTimeLabel: string;
  durationLabel: string | null;
  timeline: RequestTimelineStep[];
  onPressHome: () => void;
};

export function RequestCompletedSection({
  endTimeLabel,
  durationLabel,
  timeline,
  onPressHome,
}: RequestCompletedSectionProps) {
  return (
    <View style={styles.container}>
      <RequestCompletedBadge />
      <View style={styles.textBlock}>
        <Text style={styles.heading}>{'차량 이동이\n확인되었습니다'}</Text>
        <Text style={styles.subheading}>{'매너 있는 주차 문화에 동참해주셔서\n감사합니다.'}</Text>
        {durationLabel ? (
          <View style={styles.pill}>
            <Text style={styles.pillText}>{`${durationLabel} 만에 이동 완료`}</Text>
          </View>
        ) : null}
      </View>
      <RequestTimelineCard header={{ label: '종료 시각', value: endTimeLabel }} timeline={timeline} />
      <Pressable accessibilityRole="button" style={styles.homeButton} onPress={onPressHome}>
        <Text style={styles.homeButtonText}>홈으로 돌아가기</Text>
      </Pressable>
    </View>
  );
}
