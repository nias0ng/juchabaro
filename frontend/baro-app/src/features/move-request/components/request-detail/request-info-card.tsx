import { Text, View } from 'react-native';

import { styles } from './request-info-card.styles';

type RequestInfoCardProps = {
  requestId: number;
  violationType: string;
  plateNumber: string;
  location: string;
  requestedAtLabel: string;
};

export function RequestInfoCard({
  requestId,
  violationType,
  plateNumber,
  location,
  requestedAtLabel,
}: RequestInfoCardProps) {
  return (
    <View style={styles.container}>
      <View style={styles.violationRow}>
        <Text style={styles.label}>위반 유형</Text>
        <Text style={styles.violationBadgeText}>{violationType}</Text>
      </View>

      <View style={styles.infoGrid}>
        <View style={styles.infoCard}>
          <Text style={styles.label}>내 차량</Text>
          <Text style={styles.value}>{plateNumber}</Text>
        </View>
        <View style={styles.infoCard}>
          <Text style={styles.label}>위치</Text>
          <Text style={styles.value}>{location}</Text>
        </View>
      </View>

      <View style={styles.infoGrid}>
        <View style={styles.infoCard}>
          <Text style={styles.label}>요청 번호</Text>
          <Text style={styles.value}>#{requestId}</Text>
        </View>
        <View style={styles.infoCard}>
          <Text style={styles.label}>요청 시각</Text>
          <Text style={styles.value}>{requestedAtLabel}</Text>
        </View>
      </View>
    </View>
  );
}
