<script setup lang="ts">
import { computed } from 'vue'

import { floorZoneLayout, toCellVariant } from '@/features/parking-zones/data'
import type { CellVariant, FloorKey, ParkingSpotSummary } from '@/features/parking-zones/types'

// 첫 줄은 단독, 이후로는 두 줄씩 묶어 사이 통로(구분선)를 넣는다(사이드 스팟 배정과는 무관하게
// 순전히 시각적인 간격 표현이다).
const ROWS_PER_GROUP = 2

const props = defineProps<{
  floor: FloorKey
  spots: ParkingSpotSummary[]
  selectedZoneId?: number | null
}>()

const emit = defineEmits<{
  selectSpot: [spot: ParkingSpotSummary]
}>()

// B1의 실제 물리 배치를 그대로 복제한 층(B2/B3)도 같은 모양으로 그린다. 층별 zoneNumber
// 배치가 바뀌면(구역이 추가/삭제되면) data.ts의 floorZoneLayout도 함께 갱신해야 한다.
const layout = computed(() => floorZoneLayout(props.floor))
const SIDE_BY_ROW = computed(() => layout.value.sideByRow)

type LayoutRow = { cells: (string | null)[]; rowIndex: number }

function groupRowsWithLeadingDivider(rows: LayoutRow[]): LayoutRow[][] {
  if (rows.length === 0) return []
  const [firstRow, ...restRows] = rows
  const groups: LayoutRow[][] = [[firstRow!]]
  for (let index = 0; index < restRows.length; index += ROWS_PER_GROUP) {
    groups.push(restRows.slice(index, index + ROWS_PER_GROUP))
  }
  return groups
}

const rowGroups = computed<LayoutRow[][]>(() => {
  const rows: LayoutRow[] = layout.value.mainLayout.map((cells, rowIndex) => ({ cells, rowIndex }))
  return groupRowsWithLeadingDivider(rows)
})

const LAST_ROW_INDEX = computed(() => layout.value.mainLayout.length - 1)

// 실제 데이터에 zoneNumber 앞뒤로 공백/탭이 섞여 들어오는 경우가 있어(예: "\tB1-01"),
// trim한 값을 키로 써서 이런 자잘한 데이터 오염에 지도가 깨지지 않게 한다.
const spotByZoneNumber = computed(() => {
  const map = new Map<string, ParkingSpotSummary>()
  for (const spot of props.spots) map.set(spot.zoneNumber.trim(), spot)
  return map
})

function spotAt(zoneNumber: string | null): ParkingSpotSummary | null {
  if (!zoneNumber) return null
  return spotByZoneNumber.value.get(zoneNumber.trim()) ?? null
}

const CELL_BG: Record<CellVariant, string> = {
  empty: '#e7e5f3',
  occupied: '#c9c2f0',
  violation: '#ffdccd',
  disabled: '#d5e6ff',
  ev: '#dff3ef',
}

const CELL_LABEL: Partial<Record<CellVariant, { text: string; color: string }>> = {
  violation: { text: '위반', color: '#d4553a' },
  disabled: { text: '장애인', color: '#3f7bd6' },
  ev: { text: 'EV', color: '#1e8d80' },
}

function cellBg(spot: ParkingSpotSummary | null): string {
  // spot이 null이면 "실제 데이터가 아직 없는 자리"라는 뜻이라, 자리(크기)는 유지하되
  // 컨테이너 배경과 같은 색으로만 채워 눈에 띄지 않게 한다.
  if (!spot) return '#eeecf8'
  return CELL_BG[toCellVariant(spot)]
}

function cellLabel(spot: ParkingSpotSummary | null) {
  if (!spot) return null
  return CELL_LABEL[toCellVariant(spot)] ?? null
}

function isSelected(spot: ParkingSpotSummary | null): boolean {
  return Boolean(spot) && props.selectedZoneId === spot?.zoneId
}

function handleSelect(spot: ParkingSpotSummary | null) {
  if (spot) emit('selectSpot', spot)
}
</script>

<template>
  <div class="grid-container">
    <div v-for="(group, groupIndex) in rowGroups" :key="groupIndex" class="row-group">
      <div v-if="groupIndex > 0" class="divider" />
      <div v-for="row in group" :key="row.rowIndex" class="group-row">
        <button
          type="button"
          class="cell side-cell"
          :class="{ selected: isSelected(spotAt(SIDE_BY_ROW[row.rowIndex] ?? null)) }"
          :style="{ background: cellBg(spotAt(SIDE_BY_ROW[row.rowIndex] ?? null)) }"
          :title="SIDE_BY_ROW[row.rowIndex] ?? undefined"
          :disabled="!spotAt(SIDE_BY_ROW[row.rowIndex] ?? null)"
          @click="handleSelect(spotAt(SIDE_BY_ROW[row.rowIndex] ?? null))"
        >
          <span
            v-if="cellLabel(spotAt(SIDE_BY_ROW[row.rowIndex] ?? null))"
            :style="{ color: cellLabel(spotAt(SIDE_BY_ROW[row.rowIndex] ?? null))!.color }"
          >
            {{ cellLabel(spotAt(SIDE_BY_ROW[row.rowIndex] ?? null))!.text }}
          </span>
        </button>
        <div class="gap-slot">
          <div v-if="row.rowIndex === 0" class="exit-block" title="출구(EXIT)">출구</div>
          <div v-else-if="row.rowIndex === LAST_ROW_INDEX" class="entry-block" title="입구(ENTRY)">입구</div>
        </div>
        <div class="main-row">
          <button
            v-for="(zoneNumber, columnIndex) in row.cells"
            :key="zoneNumber ?? `${row.rowIndex}-${columnIndex}`"
            type="button"
            class="cell main-cell"
            :class="{ selected: isSelected(spotAt(zoneNumber)) }"
            :style="{ background: cellBg(spotAt(zoneNumber)) }"
            :title="zoneNumber ?? undefined"
            :disabled="!spotAt(zoneNumber)"
            @click="handleSelect(spotAt(zoneNumber))"
          >
            <span v-if="cellLabel(spotAt(zoneNumber))" :style="{ color: cellLabel(spotAt(zoneNumber))!.color }">
              {{ cellLabel(spotAt(zoneNumber))!.text }}
            </span>
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

.group-row {
  display: flex;
  align-items: center;
}

/* 사이드 칸과 메인 칸 사이의 통로 자리. 실제 입출구 좌표 데이터가 없어, 맨 위 줄(출구)과
   맨 아래 줄(입구)에서만 이 자리를 장식적으로 채운다. */
.gap-slot {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 48px;
}

.exit-block,
.entry-block {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 32px;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  border-radius: var(--radius-sm);
}

.exit-block {
  background: #3b82f6;
}

.entry-block {
  background: #22c55e;
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
