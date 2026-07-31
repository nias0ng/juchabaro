import { Text, View } from 'react-native';

import { styles } from './request-overdue-timeline-card.styles';

export type RequestOverdueTimelineStep = {
  label: string;
  detail: string;
  dotColor: string;
  labelColor?: string;
};

type RequestOverdueTimelineCardProps = {
  timeline: RequestOverdueTimelineStep[];
  // 아직 발생하지 않은, 대기 중인 마지막 단계(예: "이동 확인 대기 · 진행중"). 있으면 한 줄짜리 회색 행으로 맨 아래 붙는다.
  pendingStep?: { label: string; status: string };
};

export function RequestOverdueTimelineCard({ timeline, pendingStep }: RequestOverdueTimelineCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>진행 기록</Text>

      <View>
        {timeline.map((step, index) => (
          <View key={step.label} style={styles.row}>
            <View style={styles.dotColumn}>
              <View style={[styles.dot, { backgroundColor: step.dotColor }]} />
              {index < timeline.length - 1 || pendingStep ? <View style={styles.line} /> : null}
            </View>

            <View style={[styles.textColumn, (index < timeline.length - 1 || pendingStep) && styles.textColumnSpaced]}>
              <Text style={[styles.stepLabel, step.labelColor ? { color: step.labelColor } : null]}>
                {step.label}
              </Text>
              <Text style={styles.stepDetail}>{step.detail}</Text>
            </View>
          </View>
        ))}

        {pendingStep ? (
          <View style={styles.pendingRow}>
            <View style={styles.pendingDot} />
            <Text style={styles.pendingLabel}>{pendingStep.label}</Text>
            <Text style={styles.pendingStatus}>{pendingStep.status}</Text>
          </View>
        ) : null}
      </View>
    </View>
  );
}
