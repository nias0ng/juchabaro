import { Text, View } from 'react-native';

import { styles } from './parking-legend.styles';

export type ParkingLegendItem = {
  label: string;
  color: string;
};

type ParkingLegendProps = {
  items: ParkingLegendItem[];
};

/** 주차 지도 아래 "주차 중/비어 있음/충전구역/장애인구역/위반" 같은 색상 범례. */
export function ParkingLegend({ items }: ParkingLegendProps) {
  return (
    <View style={styles.row}>
      {items.map((item) => (
        <View key={item.label} style={styles.item}>
          <View style={[styles.dot, { backgroundColor: item.color }]} />
          <Text style={styles.text}>{item.label}</Text>
        </View>
      ))}
    </View>
  );
}
