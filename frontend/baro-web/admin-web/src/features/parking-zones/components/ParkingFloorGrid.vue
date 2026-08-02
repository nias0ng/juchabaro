<script setup lang="ts">
import { computed } from 'vue';

import { toCellVariant } from '@/features/parking-zones/data';
import type { CellVariant, ParkingSpot } from '@/features/parking-zones/types';

const props = defineProps<{
  mainSpots: (ParkingSpot | null)[];
  sideSpots: (ParkingSpot | null)[];
  selectedCode?: string | null;
}>();

const emit = defineEmits<{
  selectSpot: [spot: ParkingSpot];
}>();

// baro-app(frontend/baro-app/src/features/parking/components/parking-floor-grid.tsx)의
// 팔레트/레이아웃을 그대로 가져온다.
const CELL_BG: Record<CellVariant, string> = {
  empty: '#e7e5f3',
  occupied: '#c9c2f0',
  violation: '#ffdccd',
  disabled: '#d5e6ff',
  ev: '#dff3ef',
};

const CELL_LABEL: Partial<Record<CellVariant, { text: string; color: string }>> = {
  violation: { text: '위반', color: '#d4553a' },
  disabled: { text: '장애인', color: '#3f7bd6' },
  ev: { text: 'EV', color: '#1e8d80' },
};

const MAIN_COLUMNS = 4;
const ROWS_PER_GROUP = 2;

function chunk<T>(items: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    rows.push(items.slice(index, index + size));
  }
  return rows;
}

// 첫 행만 따로 떼어 통로(구분선)를 한 칸 앞으로 당긴다 (baro-app과 동일한 방식).
function groupRowsWithLeadingDivider<T>(rows: T[], size: number): T[][] {
  if (rows.length === 0) return [];
  const [firstRow, ...restRows] = rows;
  const groups: T[][] = [[firstRow!]];
  for (let index = 0; index < restRows.length; index += size) {
    groups.push(restRows.slice(index, index + size));
  }
  return groups;
}

type IndexedRow = { spots: (ParkingSpot | null)[]; rowIndex: number };

const rowGroups = computed<IndexedRow[][]>(() => {
  const rows: IndexedRow[] = chunk(props.mainSpots, MAIN_COLUMNS).map((spots, rowIndex) => ({ spots, rowIndex }));
  return groupRowsWithLeadingDivider(rows, ROWS_PER_GROUP);
});

function cellBg(spot: ParkingSpot | null): string {
  // spot이 null이면 "이 자리에는 주차 칸이 없다"는 뜻이다(baro-app과 동일) — 자리(크기)는
  // 유지하되 컨테이너 배경과 같은 색으로만 채워 눈에 띄지 않게 한다.
  if (!spot) return '#eeecf8';
  return CELL_BG[toCellVariant(spot)];
}

function cellLabel(spot: ParkingSpot | null) {
  if (!spot) return null;
  return CELL_LABEL[toCellVariant(spot)] ?? null;
}

function isSelected(spot: ParkingSpot | null): boolean {
  return Boolean(spot) && props.selectedCode === spot?.code;
}

function handleSelect(spot: ParkingSpot | null) {
  if (spot) emit('selectSpot', spot);
}
</script>

<template>
  <div class="grid-container">
    <div v-for="(group, groupIndex) in rowGroups" :key="groupIndex" class="row-group">
      <div v-if="groupIndex > 0" class="divider" />
      <div v-for="row in group" :key="row.rowIndex" class="row">
        <button
          type="button"
          class="cell side-cell"
          :class="{ selected: isSelected(sideSpots[row.rowIndex] ?? null) }"
          :style="{ background: cellBg(sideSpots[row.rowIndex] ?? null) }"
          :title="sideSpots[row.rowIndex]?.code"
          :disabled="!sideSpots[row.rowIndex]"
          @click="handleSelect(sideSpots[row.rowIndex] ?? null)"
        >
          <span v-if="cellLabel(sideSpots[row.rowIndex] ?? null)" :style="{ color: cellLabel(sideSpots[row.rowIndex] ?? null)!.color }">
            {{ cellLabel(sideSpots[row.rowIndex] ?? null)!.text }}
          </span>
        </button>
        <div class="main-row">
          <button
            v-for="(spot, columnIndex) in row.spots"
            :key="spot?.code ?? `${row.rowIndex}-${columnIndex}`"
            type="button"
            class="cell main-cell"
            :class="{ selected: isSelected(spot) }"
            :style="{ background: cellBg(spot) }"
            :title="spot?.code"
            :disabled="!spot"
            @click="handleSelect(spot)"
          >
            <span v-if="cellLabel(spot)" :style="{ color: cellLabel(spot)!.color }">{{ cellLabel(spot)!.text }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid-container {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  width: fit-content;
  margin: 0 auto;
  padding: var(--spacing-base);
  border-radius: var(--radius-lg);
  background: #eeecf8;
}

.row-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.divider {
  height: 22px;
  margin: 0 calc(var(--spacing-base) * -1);
  background: #eeecf8;
}

.row {
  display: flex;
  align-items: center;
  gap: 48px;
}

.main-row {
  display: flex;
  gap: 5px;
}

.cell {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 9.5px;
  font-weight: 700;
  cursor: pointer;
  transition: outline-color 0.15s ease;
}

.cell:disabled {
  cursor: default;
}

.side-cell {
  width: 40px;
  height: 32px;
}

.main-cell {
  width: 32px;
  aspect-ratio: 0.78;
}

.selected {
  outline: 2px solid var(--panel-primary);
  outline-offset: 1px;
}
</style>
