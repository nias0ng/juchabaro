import { Pressable, Text, View } from 'react-native';

import {
  floorZoneLayout,
  type ParkingFloorKey,
  type SpotCell,
} from '../utils/parking-zone';

import { styles } from './parking-spot-map.styles';

const MAP_COLUMNS = 3;
const ROWS_PER_GROUP = 2;

type ParkingSpotMapProps = {
  cells: SpotCell[];
  message?: string;
  /** 있으면 칸을 눌러서 고를 수 있게 된다(예: 이동 요청 작성의 구역 선택). 없으면 지금처럼 보여주기만 한다. */
  onPressCell?: (spotCode: string) => void;
  selectedSpotCode?: string | null;
  /** 관리자 웹과 동일한 실제 층 배치로 표시할 때 지정한다. */
  floor?: ParkingFloorKey;
};

function chunkCells(cells: SpotCell[]): SpotCell[][] {
  const rows: SpotCell[][] = [];

  for (let index = 0; index < cells.length; index += MAP_COLUMNS) {
    rows.push(cells.slice(index, index + MAP_COLUMNS));
  }

  return rows;
}

type LayoutRow = {
  cells: (string | null)[];
  rowIndex: number;
};

function groupRowsWithLeadingDivider(rows: LayoutRow[]): LayoutRow[][] {
  if (rows.length === 0) return [];
  const [firstRow, ...restRows] = rows;
  const groups: LayoutRow[][] = [[firstRow]];

  for (let index = 0; index < restRows.length; index += ROWS_PER_GROUP) {
    groups.push(restRows.slice(index, index + ROWS_PER_GROUP));
  }
  return groups;
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

export function ParkingSpotMap({
  cells,
  message,
  onPressCell,
  selectedSpotCode,
  floor,
}: ParkingSpotMapProps) {
  const rows = chunkCells(cells);
  const layout = floor ? floorZoneLayout(floor) : null;
  const layoutRowGroups = layout
    ? groupRowsWithLeadingDivider(
        layout.mainLayout.map((layoutCells, rowIndex) => ({ cells: layoutCells, rowIndex })),
      )
    : [];
  const lastLayoutRowIndex = layout ? layout.mainLayout.length - 1 : -1;
  const cellBySpotCode = new Map(cells.map((cell) => [cell.spotCode.trim(), cell]));

  const renderCell = (
    cell: SpotCell | null,
    key: string,
    sizeStyle?: object,
  ) => {
    if (!cell) {
      return <View key={key} style={[styles.mapCell, styles.mapCellMissing, sizeStyle]} />;
    }

    const variant = toCellVariant(cell, Boolean(onPressCell));
    const label = CELL_LABEL[variant];
    const selected = selectedSpotCode === cell.spotCode;
    // 고르는 화면(onPressCell 있음)에서는 어떤 칸인지 알아야 고를 수 있어서, 상태 라벨 대신 구역 번호를 보여준다.
    const displayText = onPressCell ? cell.spotCode : label?.text;
    const displayStyle = onPressCell ? styles.spotCodeLabel : label?.style;

    return (
      <Pressable
        key={key}
        disabled={!onPressCell}
        accessibilityRole={onPressCell ? 'button' : undefined}
        accessibilityLabel={cell.spotCode}
        accessibilityState={onPressCell ? { selected } : undefined}
        style={[
          styles.mapCell,
          sizeStyle,
          CELL_STYLE[variant],
          selected && styles.mapCellSelected,
        ]}
        onPress={onPressCell ? () => onPressCell(cell.spotCode) : undefined}
      >
        {displayText ? (
          <Text style={[styles.mapCellLabel, displayStyle]} numberOfLines={1} adjustsFontSizeToFit>
            {displayText}
          </Text>
        ) : null}
      </Pressable>
    );
  };

  return (
    <View style={[styles.mapPreview, message ? styles.messageContainer : null]}>
      {message ? (
        <Text style={styles.message}>{message}</Text>
      ) : layout ? (
        <View style={styles.floorLayout}>
          {layoutRowGroups.map((group, groupIndex) => (
            <View key={groupIndex} style={styles.layoutRowGroup}>
              {groupIndex > 0 ? <View style={styles.layoutDivider} /> : null}
              {group.map((row) => {
                const sideCode = layout.sideByRow[row.rowIndex];
                const sideCell = sideCode ? cellBySpotCode.get(sideCode) ?? null : null;

                return (
                  <View key={row.rowIndex} style={styles.layoutRow}>
                    {renderCell(sideCell, `side-${row.rowIndex}`, styles.sideCell)}
                    <View style={styles.gapSlot}>
                      {row.rowIndex === 0 ? (
                        <View style={[styles.accessBlock, styles.exitBlock]}>
                          <Text style={styles.accessBlockText}>출구</Text>
                        </View>
                      ) : row.rowIndex === lastLayoutRowIndex ? (
                        <View style={[styles.accessBlock, styles.entryBlock]}>
                          <Text style={styles.accessBlockText}>입구</Text>
                        </View>
                      ) : null}
                    </View>
                    <View style={styles.mainCells}>
                      {row.cells.map((spotCode, columnIndex) =>
                        renderCell(
                          spotCode ? cellBySpotCode.get(spotCode) ?? null : null,
                          spotCode ?? `${row.rowIndex}-${columnIndex}`,
                          styles.mainCell,
                        ),
                      )}
                    </View>
                  </View>
                );
              })}
            </View>
          ))}
        </View>
      ) : (
        rows.map((row, rowIndex) => (
          <View key={rowIndex} style={styles.mapRow}>
            {row.map((cell) => renderCell(cell, cell.spotCode))}
          </View>
        ))
      )}
    </View>
  );
}
