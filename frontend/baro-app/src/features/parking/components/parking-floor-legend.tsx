import { Text, View } from 'react-native';

import { LEGEND_DOT_COLOR, styles } from './parking-floor-legend.styles';

// 장애인/EV 구역은 색이 아니라 칸 안 텍스트로만 구분하므로 범례에는 상태(내 차/사용중/비어 있음)만 남긴다.
const LEGEND_ITEMS = [
  { key: 'mine', label: '내 차량' },
  { key: 'occupied', label: '사용중' },
  { key: 'empty', label: '비어 있음' },
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
