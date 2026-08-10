import { Text, View } from 'react-native';

import { RequestTimelineCard } from '@/features/move-request/components/request-timeline-card';
import { RequestStatCardRow } from '@/features/move-request/components/request-stat-card-row';
import type { RequestTimelineStep } from '@/features/move-request/utils/move-request';

import { RequestReminderCountdown } from './request-reminder-countdown';
import { styles } from './request-reminder-section.styles';

type RequestReminderSectionProps = {
  badgeLabel: string;
  description: string;
  countdownLabel: string;
  countdownCaption: string;
  countdownProgress: number;
  plateNumber: string;
  actionLabel: string;
  timeline: RequestTimelineStep[];
  pendingStep?: { label: string; status: string };
};

export function RequestReminderSection({
  badgeLabel,
  description,
  countdownLabel,
  countdownCaption,
  countdownProgress,
  plateNumber,
  actionLabel,
  timeline,
  pendingStep,
}: RequestReminderSectionProps) {
  return (
    <View style={styles.container}>
      <View style={styles.pill}>
        <Text style={styles.pillText}>{`⚠ ${badgeLabel}`}</Text>
      </View>

      <Text style={styles.description}>{description}</Text>

      <RequestReminderCountdown label={countdownLabel} caption={countdownCaption} progress={countdownProgress} />
      <RequestStatCardRow leftLabel="차량 번호" leftValue={plateNumber} rightLabel="조치" rightValue={actionLabel} />
      <RequestTimelineCard title="진행 기록" timeline={timeline} pendingStep={pendingStep} />
    </View>
  );
}
