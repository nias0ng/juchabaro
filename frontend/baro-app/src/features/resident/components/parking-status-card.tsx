import { Pressable, Text, View } from 'react-native';

import { Palette } from '@/styles';

import { styles } from './parking-status-card.styles';

type ParkingStatusCardProps = {
  title: string;
  congestionLabel: string;
  onPressViewAll?: () => void;
};

// 주차 맵 미리보기용 장식 그리드. 실제 주차면 데이터가 아니라 Figma의 축소 미리보기를 흉내낸 것이다.
const mapRows: Array<Array<'empty' | 'altEmpty' | 'mine' | 'violation'>> = [
  ['empty', 'altEmpty', 'empty', 'altEmpty', 'violation'],
  ['mine', 'altEmpty', 'empty'],
];

export function ParkingStatusCard({ title, congestionLabel, onPressViewAll }: ParkingStatusCardProps) {
  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>{title}</Text>
      </View>
      <View style={styles.card}>
        <View style={styles.congestionPill}>
          <Text style={styles.congestionText}>{congestionLabel}</Text>
        </View>

        <View style={styles.mapPreview}>
          {mapRows.map((row, rowIndex) => (
            <View key={rowIndex} style={styles.mapRow}>
              {row.map((cell, cellIndex) => (
                <View
                  key={cellIndex}
                  style={[
                    styles.mapCell,
                    cell === 'altEmpty' && styles.mapCellAlt,
                    cell === 'violation' && styles.mapCellViolation,
                    cell === 'mine' && styles.mapCellMine,
                  ]}
                >
                  {cell === 'violation' && (
                    <Text style={[styles.mapCellLabel, { color: '#e05f38' }]}>위반</Text>
                  )}
                  {cell === 'mine' && <Text style={[styles.mapCellLabel, { color: '#1e8d80' }]}>내 차</Text>}
                </View>
              ))}
            </View>
          ))}
        </View>

        <View style={styles.legendRow}>

          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: '#d9d5ee' }]} />
            <Text style={styles.legendText}>주차 중</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: '#e7e5f3' }]} />
            <Text style={styles.legendText}>비어 있음 42</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: Palette.peach100 }]} />
            <Text style={styles.legendText}>위반 1</Text>
          </View>
        </View>
      </View>

    </View>
  );
}
