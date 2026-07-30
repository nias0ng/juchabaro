import { Text, View } from 'react-native';

import { styles } from './request-info-card.styles';

type RequestInfoCardProps = {
  violationType: string;
  plateNumber: string;
  location: string;
};

export function RequestInfoCard({ violationType, plateNumber, location }: RequestInfoCardProps) {
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
    </View>
  );
}
