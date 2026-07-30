import { Text, View } from 'react-native';

import { RequestEvidenceCard } from './request-evidence-card';
import { RequestOverdueBadge } from './request-overdue-badge';
import { RequestOverdueReminderCard } from './request-overdue-reminder-card';
import { RequestOverdueTimelineCard, type RequestOverdueTimelineStep } from './request-overdue-timeline-card';
import { styles } from './request-overdue-section.styles';

type RequestOverdueSectionProps = {
  countdownLabel: string;
  timeline: RequestOverdueTimelineStep[];
  plateNumber: string;
  location: string;
};

export function RequestOverdueSection({ countdownLabel, timeline, plateNumber, location }: RequestOverdueSectionProps) {
  return (
    <View style={styles.container}>
      <RequestOverdueBadge />

      <View style={styles.textBlock}>
        <Text style={styles.heading}>{'예정 시간 후에도 차량이\n확인되었습니다.'}</Text>
        <View style={styles.pill}>
          <Text style={styles.pillText}>약속 시간 미이동</Text>
        </View>
      </View>

      <RequestOverdueReminderCard countdownLabel={countdownLabel} />
      <RequestOverdueTimelineCard timeline={timeline} />
      <RequestEvidenceCard plateNumber={plateNumber} location={location} />
    </View>
  );
}
