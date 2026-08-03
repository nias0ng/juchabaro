import { Text, View } from 'react-native';

import { RequestTimelineCard } from '@/features/move-request/components/request-timeline-card';
import { RequestStatCardRow } from '@/features/move-request/components/request-stat-card-row';
import type { RequestTimelineStep } from '@/features/move-request/utils/move-request';

import { RequestReminderCountdown } from './request-reminder-countdown';
import { styles } from './request-reminder-section.styles';

type RequestReminderSectionProps = {
  reminderRoundLabel: string; // 예: "1차 재알림"
  countdownLabel: string;
  plateNumber: string;
  actionLabel: string;
  timeline: RequestTimelineStep[];
  pendingStep?: { label: string; status: string };
};

export function RequestReminderSection({
  reminderRoundLabel,
  countdownLabel,
  plateNumber,
  actionLabel,
  timeline,
  pendingStep,
}: RequestReminderSectionProps) {
  return (
    <View style={styles.container}>
      <View style={styles.pill}>
        <Text style={styles.pillText}>{`⚠ ${reminderRoundLabel}`}</Text>
      </View>

      <Text style={styles.description}>
        {'예정 시간 이내에 차량이 이동되지 않았습니다.\n이후, 관리자에게 연락이 가며, 추가 조치가 있을 수 있습니다.'}
      </Text>

      <RequestReminderCountdown label={countdownLabel} />
      <RequestStatCardRow leftLabel="차량 번호" leftValue={plateNumber} rightLabel="조치" rightValue={actionLabel} />
      <RequestTimelineCard title="진행 기록" timeline={timeline} pendingStep={pendingStep} />
    </View>
  );
}
