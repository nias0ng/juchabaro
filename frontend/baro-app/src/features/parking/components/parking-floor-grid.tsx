import { Text, View } from 'react-native';

import type { MockParkingSpot } from '../mocks/parking-floor-overview.mock';

import { styles } from './parking-floor-grid.styles';

const GRID_COLUMNS = 4;
// 두 줄씩 묶고 그 사이에 통로(구분선)를 넣어 Figma의 주차 구역 레이아웃을 재현한다.
const ROWS_PER_GROUP = 2;

type CellVariant = 'occupied' | 'empty' | 'violation' | 'mine' | 'disabled' | 'ev';

// 위반/내 차가 구역 유형(장애인/전기차) 표시보다 우선한다.
function toCellVariant(spot: MockParkingSpot): CellVariant {
  if (spot.status === 'VIOLATION') return 'violation';
  if (spot.status === 'MINE') return 'mine';
  if (spot.spotType === 'DISABLED') return 'disabled';
  if (spot.spotType === 'EV_CHARGING') return 'ev';
  if (spot.status === 'OCCUPIED') return 'occupied';
  return 'empty';
}

const CELL_STYLE: Record<CellVariant, object> = {
  occupied: styles.cellOccupied,
  empty: {},
  violation: styles.cellViolation,
  mine: styles.cellMine,
  disabled: styles.cellDisabled,
  ev: styles.cellEv,
};

const CELL_LABEL: Partial<Record<CellVariant, { text: string; style: object }>> = {
  violation: { text: '위반', style: styles.violationLabel },
  mine: { text: '내 차', style: styles.mineLabel },
  disabled: { text: '장애인', style: styles.disabledLabel },
  ev: { text: 'EV', style: styles.evLabel },
};

function chunk<T>(items: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    rows.push(items.slice(index, index + size));
  }
  return rows;
}

function chunkRows<T>(rows: T[], size: number): T[][] {
  const groups: T[][] = [];
  for (let index = 0; index < rows.length; index += size) {
    groups.push(rows.slice(index, index + size));
  }
  return groups;
}

// 첫 행만 따로 떼어 통로(구분선)를 한 칸 앞으로 당긴다.
// 그 결과 1행-2행 사이가 멀어지고, 2행-3행 사이가 가까워진다(이전과 반대 간격).
function chunkRowsWithLeadingDivider<T>(rows: T[], size: number): T[][] {
  if (rows.length === 0) return [];
  const [firstRow, ...restRows] = rows;
  return [[firstRow], ...chunkRows(restRows, size)];
}

type ParkingSpotCellProps = {
  spot: MockParkingSpot | null;
  style: object;
};

// spot이 null이면 "이 자리에는 주차 칸이 없다"는 뜻 — 자리(크기)는 유지하되 빈 배경으로만 남긴다.
function ParkingSpotCell({ spot, style }: ParkingSpotCellProps) {
  if (!spot) {
    return <View style={[style, styles.cellDeleted]} />;
  }

  const variant = toCellVariant(spot);
  const label = CELL_LABEL[variant];

  return (
    <View style={[style, CELL_STYLE[variant]]}>
      {label ? (
        <Text style={[styles.cellLabel, label.style]} numberOfLines={1} adjustsFontSizeToFit>
          {label.text}
        </Text>
      ) : null}
    </View>
  );
}

type ParkingFloorGridProps = {
  spots: (MockParkingSpot | null)[];
  /** 그리드 오른쪽에 세로 한 줄로 놓이는 가로형(가로세로 반전) 칸. 인덱스가 행 순서와 1:1로 대응한다. */
  sideSpots?: (MockParkingSpot | null)[];
};

export function ParkingFloorGrid({ spots, sideSpots }: ParkingFloorGridProps) {
  const rows = chunk(spots, GRID_COLUMNS);
  const rowGroups = chunkRowsWithLeadingDivider(rows, ROWS_PER_GROUP);

  let rowIndex = 0;

  return (
    <View style={styles.container}>
      {rowGroups.map((group, groupIndex) => (
        <View key={groupIndex}>
          {groupIndex > 0 ? <View style={styles.divider} /> : null}
          <View style={styles.rowGroup}>
            {group.map((row) => {
              const currentRowIndex = rowIndex;
              rowIndex += 1;
              const sideSpot = sideSpots?.[currentRowIndex];

              return (
                <View key={currentRowIndex} style={styles.rowWithSide}>
                  {sideSpots ? <ParkingSpotCell spot={sideSpot ?? null} style={styles.sideCell} /> : null}

                  <View style={styles.row}>
                    {row.map((cellSpot, columnIndex) => (
                      <ParkingSpotCell
                        key={`${currentRowIndex}-${columnIndex}`}
                        spot={cellSpot}
                        style={styles.cell}
                      />
                    ))}
                  </View>
                </View>
              );
            })}
          </View>
        </View>
      ))}
    </View>
  );
}
