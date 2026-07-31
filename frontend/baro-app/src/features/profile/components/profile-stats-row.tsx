import { Text, View } from 'react-native';

import { styles } from './profile-stats-row.styles';

type ProfileStatsRowProps = {
  vehicleCount: number;
};

// "누적 위반"은 대응하는 위반 집계 API가 없어 숫자 대신 준비 중으로만 표시한다.
export function ProfileStatsRow({ vehicleCount }: ProfileStatsRowProps) {
  return (
    <View style={styles.row}>
      <View style={styles.card}>
        <Text style={styles.label}>등록 차량</Text>
        <Text style={styles.value}>{vehicleCount}</Text>
      </View>
      <View style={[styles.card, styles.cardDisabled]}>
        <Text style={styles.label}>누적 위반</Text>
        <Text style={styles.valueDisabled}>준비 중</Text>
      </View>
    </View>
  );
}
