import { Text, View } from 'react-native';

import { LEGEND_DOT_COLOR, styles } from './parking-floor-legend.styles';

// 자연스러운 flex-wrap 대신 줄을 직접 나눠서 항상 이 줄바꿈을 유지한다.
const LEGEND_ROWS = [
  [
    { key: 'mine', label: '내 차량' },
    { key: 'occupied', label: '사용중' },
    { key: 'empty', label: '비어 있음' },
  ],
  [
    { key: 'ev', label: '충전구역' },
    { key: 'disabled', label: '장애인구역' },
  ],
] as const;

export function ParkingFloorLegend() {
  return (
    <View style={styles.container}>
      {LEGEND_ROWS.map((row, rowIndex) => (
        <View key={rowIndex} style={styles.row}>
          {row.map((item) => (
            <View key={item.key} style={styles.item}>
              <View style={[styles.dot, { backgroundColor: LEGEND_DOT_COLOR[item.key] }]} />
              <Text style={styles.text}>{item.label}</Text>
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}
