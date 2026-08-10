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

// baro-app 주차 현황 카드와 같은 팔레트를 쓴다(empty=lilac100, occupied=violet300).
// 앱에는 "내 차량(노란색)" 칸이 있지만 관리자 화면에는 그 개념이 없어서, 그 자리를
// 위반 주차 강조(빨강)로 대신 쓴다. 장애인/전기차 구역도 색으로 구분하지 않고 empty와
// 같은 배경을 쓰며, 구역 번호(D1-01/EV1-01)로만 구분한다.
const CELL_BG: Record<CellVariant, string> = {
  empty: '#e7e5f3',
  occupied: '#c3bcff',
  violation: '#c96a6a',
  disabled: '#e7e5f3',
  ev: '#e7e5f3',
}

// 장애인/전기차는 구역 번호(D1-01/EV1-01)만으로 구분되니 별도 라벨을 붙이지 않는다.
const CELL_LABEL: Partial<Record<CellVariant, { text: string; color: string }>> = {
  violation: { text: '위반', color: '#ffffff' },
}

// 장애인/전기차 구역도 실제 차량이 있으면(사용 중) 일반 구역과 똑같이 보라색으로 채워서,
// 지도만 보고도 어느 특수 구역에 차량이 들어와 있는지 바로 알 수 있게 한다. 구역 종류는
// 라벨 글자(DIS/EV)로 계속 구분하되, 배경이 보라색으로 바뀐 만큼 글자는 앱의 기존 보라색
// 토큰으로 더 짙게 바꿔 대비를 준다.
function isOccupiedSpecialZone(spot: ParkingSpotSummary): boolean {
  const variant = toCellVariant(spot)
  return (variant === 'disabled' || variant === 'ev') && spot.occupancyStatus === 'OCCUPIED'
}

function cellBg(spot: ParkingSpotSummary | null): string {
  // spot이 null이면 "실제 데이터가 아직 없는 자리"라는 뜻이라, 자리(크기)는 유지하되
  // 컨테이너 배경과 같은 색(lilac25)으로만 채워 눈에 띄지 않게 한다.
  if (!spot) return '#f7f6fb'
  if (isOccupiedSpecialZone(spot)) return CELL_BG.occupied
  return CELL_BG[toCellVariant(spot)]
}

function cellLabel(spot: ParkingSpotSummary | null) {
  if (!spot) return null
  const label = CELL_LABEL[toCellVariant(spot)] ?? null
  if (label && isOccupiedSpecialZone(spot)) return { ...label, color: 'var(--panel-primary)' }
  return label
}

// 위반은 빨간 배경이라 밝은 글자, 나머지는 무난한 회색 글자로 구역 번호를 작게 곁들인다.
function cellCodeColor(spot: ParkingSpotSummary | null): string {
  if (!spot) return 'transparent'
  return toCellVariant(spot) === 'violation' ? 'rgba(255, 255, 255, 0.85)' : 'var(--panel-muted-foreground)'
}

function isSelected(spot: ParkingSpotSummary | null): boolean {
  return Boolean(spot) && props.selectedZoneId === spot?.zoneId
}

function handleSelect(spot: ParkingSpotSummary | null) {
  if (spot) emit('selectSpot', spot)
}

type CellView = {
  spot: ParkingSpotSummary | null
  bg: string
  code: string | null
  label: { text: string; color: string } | null
  selected: boolean
}

// 칸 하나를 그리는 데 필요한 값(배경/라벨/구역 번호/선택 여부)을 한 번에 묶어서,
// 템플릿에서 spotAt()을 여러 번 반복 호출하지 않게 한다.
function cellView(zoneNumber: string | null): CellView {
  const spot = spotAt(zoneNumber)
  return {
    spot,
    bg: cellBg(spot),
    code: spot ? spot.zoneNumber.trim() : null,
    label: cellLabel(spot),
    selected: isSelected(spot),
  }
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
          :class="{ selected: cellView(SIDE_BY_ROW[row.rowIndex] ?? null).selected }"
          :style="{ background: cellView(SIDE_BY_ROW[row.rowIndex] ?? null).bg }"
          :title="SIDE_BY_ROW[row.rowIndex] ?? undefined"
          :disabled="!cellView(SIDE_BY_ROW[row.rowIndex] ?? null).spot"
          @click="handleSelect(cellView(SIDE_BY_ROW[row.rowIndex] ?? null).spot)"
        >
          <span class="cell-content">
            <span
              v-if="cellView(SIDE_BY_ROW[row.rowIndex] ?? null).label"
              class="cell-status"
              :style="{ color: cellView(SIDE_BY_ROW[row.rowIndex] ?? null).label!.color }"
            >
              {{ cellView(SIDE_BY_ROW[row.rowIndex] ?? null).label!.text }}
            </span>
            <span
              v-if="cellView(SIDE_BY_ROW[row.rowIndex] ?? null).code"
              class="cell-code"
              :style="{ color: cellCodeColor(cellView(SIDE_BY_ROW[row.rowIndex] ?? null).spot) }"
            >
              {{ cellView(SIDE_BY_ROW[row.rowIndex] ?? null).code }}
            </span>
          </span>
        </button>
        <div class="gap-slot">
          <div v-if="row.rowIndex === 0" class="access-block" title="출구(EXIT)">출구</div>
          <div v-else-if="row.rowIndex === LAST_ROW_INDEX" class="access-block" title="입구(ENTRY)">입구</div>
        </div>
        <div class="main-row">
          <button
            v-for="(zoneNumber, columnIndex) in row.cells"
            :key="zoneNumber ?? `${row.rowIndex}-${columnIndex}`"
            type="button"
            class="cell main-cell"
            :class="{ selected: cellView(zoneNumber).selected }"
            :style="{ background: cellView(zoneNumber).bg }"
            :title="zoneNumber ?? undefined"
            :disabled="!cellView(zoneNumber).spot"
            @click="handleSelect(cellView(zoneNumber).spot)"
          >
            <span class="cell-content">
              <span v-if="cellView(zoneNumber).label" class="cell-status" :style="{ color: cellView(zoneNumber).label!.color }">
                {{ cellView(zoneNumber).label!.text }}
              </span>
              <span v-if="cellView(zoneNumber).code" class="cell-code" :style="{ color: cellCodeColor(cellView(zoneNumber).spot) }">
                {{ cellView(zoneNumber).code }}
              </span>
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
  background: #f7f6fb;
}

.row-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.divider {
  height: 22px;
  margin: 0 calc(var(--spacing-base) * -1);
  background: #f7f6fb;
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
  width: 56px;
}

/* 입구/출구는 실제 주차 상태 정보가 아니라 구조 안내라, baro-app과 동일하게 배경 박스 없이
   글자만 둔다. */
.access-block {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 40px;
  font-size: 13px;
  font-weight: 700;
  color: var(--panel-muted-foreground);
}

.main-row {
  display: flex;
  gap: 6px;
}

.cell {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: outline-color 0.15s ease;
}

.cell:disabled {
  cursor: default;
}

.cell-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
}

.cell-status {
  font-size: 13px;
  line-height: 1.3;
}

.cell-code {
  font-size: 11px;
  font-weight: 600;
  /* 좁은 칸 폭 때문에 구역 번호(예: EV1-01)가 줄바꿈될 때 줄 사이가 너무 붙지 않게 한다. */
  line-height: 1.35;
}

.side-cell {
  width: 56px;
  height: 48px;
}

.main-cell {
  width: 48px;
  height: 64px;
}

.selected {
  outline: 2px solid var(--panel-primary);
  outline-offset: 1px;
}
</style>
