import { Text, View } from 'react-native';

import { styles } from './response-summary-card.styles';

type ResponseSummaryCardProps = {
  responseLabel: string;
  vehicleLabel: string;
  dueAtLabel: string;
  deliveredAtLabel: string;
};

export function ResponseSummaryCard({
  responseLabel,
  vehicleLabel,
  dueAtLabel,
  deliveredAtLabel,
}: ResponseSummaryCardProps) {
  return (
    <View style={styles.container}>
      <View style={styles.row}>
        <Text style={styles.label}>내 응답</Text>
        <Text style={styles.value}>{responseLabel}</Text>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>차량</Text>
        <Text style={styles.value}>{vehicleLabel}</Text>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>이동 기한</Text>
        <Text style={styles.value}>{dueAtLabel}</Text>
      </View>

      <View style={styles.divider} />

      <View style={styles.statusRow}>
        <View style={styles.statusDot} />
        <Text style={styles.statusText}>요청자에게 전달 완료</Text>
        <Text style={styles.statusTime}>{deliveredAtLabel}</Text>
      </View>
    </View>
  );
}
