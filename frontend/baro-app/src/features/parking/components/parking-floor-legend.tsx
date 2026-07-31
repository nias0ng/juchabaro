import { Text, View } from 'react-native';

import { LEGEND_DOT_COLOR, styles } from './parking-floor-legend.styles';

const LEGEND_ITEMS = [
  { key: 'occupied', label: '주차 중' },
  { key: 'empty', label: '비어 있음' },
  { key: 'ev', label: '충전구역' },
  { key: 'disabled', label: '장애인구역' },
  { key: 'violation', label: '위반' },
] as const;

export function ParkingFloorLegend() {
  return (
    <View style={styles.row}>
      {LEGEND_ITEMS.map((item) => (
        <View key={item.key} style={styles.item}>
          <View style={[styles.dot, { backgroundColor: LEGEND_DOT_COLOR[item.key] }]} />
          <Text style={styles.text}>{item.label}</Text>
        </View>
      ))}
    </View>
  );
}
