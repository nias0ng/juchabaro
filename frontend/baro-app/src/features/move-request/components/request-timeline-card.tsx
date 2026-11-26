import { Text, View } from 'react-native';

import type { RequestTimelineStep, TimelineTone } from '@/features/move-request/utils/move-request';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-timeline-card.styles';

type RequestTimelineCardProps = {
  title?: string;
  header?: { label: string; value: string };
  timeline: RequestTimelineStep[];
  pendingStep?: { label: string; status: string };
};

export function RequestTimelineCard({ title, header, timeline, pendingStep }: RequestTimelineCardProps) {
  const styles = useThemedStyles(createStyles);

  // 이전에는 톤이 있는 단계의 글자색이 마지막 단계 색보다 우선했다. 같은 순서를 유지한다.
  const toneStyles: Record<TimelineTone, { dot: object; label: object | null }> = {
    brand: { dot: styles.dotBrand, label: null },
    warning: { dot: styles.dotWarning, label: styles.stepLabelWarning },
    error: { dot: styles.dotError, label: styles.stepLabelError },
  };

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
          const tone = step.tone ? toneStyles[step.tone] : null;

          return (
            <View key={step.label} style={styles.row}>
              <View style={styles.dotColumn}>
                <View
                  style={[
                    styles.dot,
                    step.isFinal && styles.dotBrand,
                    tone?.dot,
                  ]}
                />
                {hasNext ? <View style={styles.line} /> : null}
              </View>

              <View style={[styles.textColumn, hasNext && styles.textColumnSpaced]}>
                <Text
                  style={[
                    styles.stepLabel,
                    step.isFinal && styles.stepLabelBrand,
                    tone?.label,
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
