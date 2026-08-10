import { Text, View } from 'react-native';

import { styles } from './household-info-row.styles';

type HouseholdInfoRowProps = {
  value: string;
};

// 세대 정보는 관리사무소를 통해서만 바뀌므로 항상 읽기 전용으로 보여준다.
export function HouseholdInfoRow({ value }: HouseholdInfoRowProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.label}>세대 정보</Text>
      <View style={styles.box}>
        <Text style={styles.value}>{value}</Text>
        <Text style={styles.caption}>변경은 관리사무소 문의</Text>
      </View>
    </View>
  );
}
