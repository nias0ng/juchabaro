import { Pressable, Text, View } from 'react-native';

import type { SpotCell } from '../utils/parking-zone';

import { styles } from './parking-spot-map.styles';

const MAP_COLUMNS = 3;

type ParkingSpotMapProps = {
  cells: SpotCell[];
  message?: string;
  /** 있으면 칸을 눌러서 고를 수 있게 된다(예: 이동 요청 작성의 구역 선택). 없으면 지금처럼 보여주기만 한다. */
  onPressCell?: (spotCode: string) => void;
  selectedSpotCode?: string | null;
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

// pickMode(구역 선택)에서는 위반 여부를 구분해서 보여줄 필요가 없어서 위반도 그냥 "주차중"으로 취급한다.
function toCellVariant(cell: SpotCell, pickMode: boolean): CellVariant {
  if (cell.kind === 'violation') return pickMode ? 'occupied' : 'violation';
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

export function ParkingSpotMap({ cells, message, onPressCell, selectedSpotCode }: ParkingSpotMapProps) {
  const rows = chunkCells(cells);

  return (
    <View style={[styles.mapPreview, message ? styles.messageContainer : null]}>
      {message ? (
        <Text style={styles.message}>{message}</Text>
      ) : (
        rows.map((row, rowIndex) => (
          <View key={rowIndex} style={styles.mapRow}>
            {row.map((cell) => {
              const variant = toCellVariant(cell, Boolean(onPressCell));
              const label = CELL_LABEL[variant];
              const selected = selectedSpotCode === cell.spotCode;
              // 고르는 화면(onPressCell 있음)에서는 어떤 칸인지 알아야 고를 수 있어서, 상태 라벨 대신 구역 번호를 보여준다.
              const displayText = onPressCell ? cell.spotCode : label?.text;
              const displayStyle = onPressCell ? styles.spotCodeLabel : label?.style;

              return (
                <Pressable
                  key={cell.spotCode}
                  disabled={!onPressCell}
                  accessibilityRole={onPressCell ? 'button' : undefined}
                  accessibilityState={onPressCell ? { selected } : undefined}
                  style={[styles.mapCell, CELL_STYLE[variant], selected && styles.mapCellSelected]}
                  onPress={onPressCell ? () => onPressCell(cell.spotCode) : undefined}
                >
                  {displayText ? (
                    <Text style={[styles.mapCellLabel, displayStyle]} numberOfLines={1} adjustsFontSizeToFit>
                      {displayText}
                    </Text>
                  ) : null}
                </Pressable>
              );
            })}
          </View>
        ))
      )}
    </View>
  );
}
