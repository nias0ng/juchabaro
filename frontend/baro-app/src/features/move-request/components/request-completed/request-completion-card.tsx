import { Text, View } from 'react-native';

import type { RequestCompletedTimelineStep } from '@/features/move-request/utils/move-request';

import { styles } from './request-completion-card.styles';

type RequestCompletionCardProps = {
  endTimeLabel: string;
  timeline: RequestCompletedTimelineStep[];
};

export function RequestCompletionCard({ endTimeLabel, timeline }: RequestCompletionCardProps) {
  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.headerLabel}>종료 시각</Text>
        <Text style={styles.headerValue}>{endTimeLabel}</Text>
      </View>

      <View>
        {timeline.map((step, index) => (
          <View key={step.label} style={styles.row}>
            <View style={styles.dotColumn}>
              <View style={[styles.dot, step.isFinal && styles.dotFinal]} />
              {index < timeline.length - 1 ? <View style={styles.line} /> : null}
            </View>

            <View style={[styles.textColumn, index < timeline.length - 1 && styles.textColumnSpaced]}>
              <Text style={[styles.stepLabel, step.isFinal && styles.stepLabelFinal]}>{step.label}</Text>
              <Text style={styles.stepDetail}>{step.detail}</Text>
            </View>
          </View>
        ))}
      </View>
    </View>
  );
}
