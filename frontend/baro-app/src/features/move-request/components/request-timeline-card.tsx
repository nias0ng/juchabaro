import { Text, View } from 'react-native';

import type { RequestTimelineStep } from '@/features/move-request/utils/move-request';

import { styles } from './request-timeline-card.styles';

type RequestTimelineCardProps = {
  title?: string;
  header?: { label: string; value: string };
  timeline: RequestTimelineStep[];
  pendingStep?: { label: string; status: string };
};

export function RequestTimelineCard({ title, header, timeline, pendingStep }: RequestTimelineCardProps) {
  return (
    <View style={styles.card}>
      {header ? (
        <View style={styles.headerRow}>
          <Text style={styles.headerLabel}>{header.label}</Text>
          <Text style={styles.headerValue}>{header.value}</Text>
        </View>
      ) : title ? (
        <Text style={styles.title}>{title}</Text>
      ) : null}

      <View>
        {timeline.map((step, index) => {
          const hasNext = index < timeline.length - 1 || Boolean(pendingStep);

          return (
            <View key={step.label} style={styles.row}>
              <View style={styles.dotColumn}>
                <View
                  style={[
                    styles.dot,
                    step.isFinal && styles.dotFinal,
                    step.dotColor ? { backgroundColor: step.dotColor } : null,
                  ]}
                />
                {hasNext ? <View style={styles.line} /> : null}
              </View>

              <View style={[styles.textColumn, hasNext && styles.textColumnSpaced]}>
                <Text
                  style={[
                    styles.stepLabel,
                    step.isFinal && styles.stepLabelFinal,
                    step.labelColor ? { color: step.labelColor } : null,
                  ]}
                >
                  {step.label}
                </Text>
                <Text style={styles.stepDetail}>{step.detail}</Text>
              </View>
            </View>
          );
        })}

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
