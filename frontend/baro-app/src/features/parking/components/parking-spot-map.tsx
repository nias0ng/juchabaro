import { Text, View } from 'react-native';

import type { SpotCell } from '../utils/parking-zone';

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

// 위반/내 차가 구역 유형(장애인/전기차) 표시보다 우선한다.
type CellVariant = 'violation' | 'mine' | 'disabled' | 'ev' | 'occupied' | 'empty';

function toCellVariant(cell: SpotCell): CellVariant {
  if (cell.kind === 'violation') return 'violation';
  if (cell.kind === 'mine') return 'mine';
  if (cell.spotType === 'DISABLED') return 'disabled';
  if (cell.spotType === 'EV_CHARGING') return 'ev';
  if (cell.kind === 'occupied') return 'occupied';
  return 'empty';
}

const CELL_STYLE: Partial<Record<CellVariant, object>> = {
  violation: styles.mapCellViolation,
  mine: styles.mapCellMine,
  disabled: styles.mapCellDisabled,
  ev: styles.mapCellEv,
  occupied: styles.mapCellOccupied,
};

const CELL_LABEL: Partial<Record<CellVariant, { text: string; style: object }>> = {
  violation: { text: '위반', style: styles.violationLabel },
  mine: { text: '내 차', style: styles.mineLabel },
  disabled: { text: '장애인', style: styles.disabledLabel },
  ev: { text: 'EV', style: styles.evLabel },
};

export function ParkingSpotMap({ cells, message }: ParkingSpotMapProps) {
  const rows = chunkCells(cells);

  return (
    <View style={[styles.mapPreview, message ? styles.messageContainer : null]}>
      {message ? (
        <Text style={styles.message}>{message}</Text>
      ) : (
        rows.map((row, rowIndex) => (
          <View key={rowIndex} style={styles.mapRow}>
            {row.map((cell) => {
              const variant = toCellVariant(cell);
              const label = CELL_LABEL[variant];

              return (
                <View key={cell.spotCode} style={[styles.mapCell, CELL_STYLE[variant]]}>
                  {label ? <Text style={[styles.mapCellLabel, label.style]}>{label.text}</Text> : null}
                </View>
              );
            })}
          </View>
        ))
      )}
    </View>
  );
}
