import { Text, View } from 'react-native';

import type { SpotCell } from '@/features/resident/utils/parking-zone';

import { styles } from './parking-spot-map.styles';

const MAP_COLUMNS = 3;

type ParkingSpotMapProps = {
  cells: SpotCell[];
  message?: string;
};

function chunkCells(cells: SpotCell[]): SpotCell[][] {
  const rows: SpotCell[][] = [];

  for (let index = 0; index < cells.length; index += MAP_COLUMNS) {
    rows.push(cells.slice(index, index + MAP_COLUMNS));
  }

  return rows;
}

export function ParkingSpotMap({ cells, message }: ParkingSpotMapProps) {
  const rows = chunkCells(cells);

  return (
    <View style={[styles.mapPreview, message ? styles.messageContainer : null]}>
      {message ? (
        <Text style={styles.message}>{message}</Text>
      ) : (
        rows.map((row, rowIndex) => (
          <View key={rowIndex} style={styles.mapRow}>
            {row.map((cell) => (
              <View
                key={cell.spotCode}
                style={[
                  styles.mapCell,
                  cell.kind === 'occupied' && styles.mapCellOccupied,
                  cell.kind === 'violation' && styles.mapCellViolation,
                  cell.kind === 'mine' && styles.mapCellMine,
                  cell.spotType === 'DISABLED' && styles.mapCellDisabled,
                  cell.spotType === 'EV_CHARGING' && styles.mapCellEv,
                ]}
              >
                {cell.kind === 'violation' ? (
                  <Text style={[styles.mapCellLabel, styles.violationLabel]}>위반</Text>
                ) : null}
                {cell.kind === 'mine' ? (
                  <Text style={[styles.mapCellLabel, styles.mineLabel]}>내 차</Text>
                ) : null}
              </View>
            ))}
          </View>
        ))
      )}
    </View>
  );
}
