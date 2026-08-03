<script setup lang="ts">
import { computed, ref } from 'vue'
import { Accessibility, Car, ChevronDown, LayoutGrid, Pencil, Plug, Search } from '@lucide/vue'

import { useDropdownFilter } from '@/composables/use-dropdown-filter'
import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import ParkingFloorGrid from '@/features/parking-zones/components/ParkingFloorGrid.vue'
import {
  FLOOR_KEYS,
  INITIAL_SPOTS,
  MAIN_SPOTS_PER_FLOOR,
  SLOTS_PER_FLOOR,
  allowedTimeLabel,
  computeZoneStats,
  floorLabel,
  statusLabel,
} from '@/features/parking-zones/data'
import type { FloorKey, ParkingSpot, SpotStatus, SpotType } from '@/features/parking-zones/types'

const TYPE_OPTIONS: SpotType[] = ['GENERAL', 'DISABLED', 'EV_CHARGING']
const STATUS_OPTIONS: Array<{ label: string; status: 'OCCUPIED' | 'EMPTY' | 'VIOLATION' }> = [
  { label: '사용 중', status: 'OCCUPIED' },
  { label: '사용 가능', status: 'EMPTY' },
  { label: '위반', status: 'VIOLATION' },
]

function matchesStatusFilter(spotStatus: SpotStatus, filter: 'OCCUPIED' | 'EMPTY' | 'VIOLATION' | null) {
  if (!filter) return true
  if (filter === 'OCCUPIED') return spotStatus === 'OCCUPIED' || spotStatus === 'MINE'
  return spotStatus === filter
}

function statusTone(status: SpotStatus): 'danger' | 'warning' | 'success' {
  if (status === 'VIOLATION') return 'danger'
  if (status === 'EMPTY') return 'success'
  return 'warning'
}

function typeTone(type: SpotType): 'success' | 'info' | 'neutral' {
  if (type === 'EV_CHARGING') return 'success'
  if (type === 'DISABLED') return 'info'
  return 'neutral'
}

type DropdownName = 'floor' | 'type' | 'status'

// 구역 번호와 유형만 관리자가 바꿀 수 있다. 현재 상태는 실제 감지 데이터를 그대로 보여주는
// 값이라 고정이고, 허용 시간은 값을 따로 입력받지 않고 유형에서 자동으로 정해진다.
type EditDraft = {
  code: string
  type: SpotType
}

// 층마다 항상 main 24칸 + side 6칸 = 30자리 순서로 저장된다(일부는 null). 이 순서 덕분에
// 층 인덱스만으로 해당 층의 30자리를 그대로 잘라낼 수 있다.
const spots = ref<(ParkingSpot | null)[]>(INITIAL_SPOTS)
const floor = ref<FloorKey>('B1')
const typeFilter = ref<SpotType | null>(null)
const statusFilter = ref<'OCCUPIED' | 'EMPTY' | 'VIOLATION' | null>(null)
const codeQuery = ref('')
const selectedCode = ref<string | null>(null)
const editDraft = ref<EditDraft | null>(null)

const { filterBarRef, openDropdown, toggleDropdown } = useDropdownFilter<DropdownName>()

const realSpots = computed(() => spots.value.filter((s): s is ParkingSpot => s !== null))
const zoneStats = computed(() => computeZoneStats(realSpots.value))

const currentFloor = computed(() => {
  const floorIndex = FLOOR_KEYS.indexOf(floor.value)
  const floorSlots = spots.value.slice(floorIndex * SLOTS_PER_FLOOR, (floorIndex + 1) * SLOTS_PER_FLOOR)
  return {
    main: floorSlots.slice(0, MAIN_SPOTS_PER_FLOOR),
    side: floorSlots.slice(MAIN_SPOTS_PER_FLOOR),
  }
})

const filteredRows = computed(() => {
  const query = codeQuery.value.trim().toUpperCase()
  return realSpots.value.filter((s) => {
    if (s.floor !== floor.value) return false
    if (typeFilter.value && s.type !== typeFilter.value) return false
    if (!matchesStatusFilter(s.status, statusFilter.value)) return false
    if (query && !s.code.toUpperCase().includes(query)) return false
    return true
  })
})

const selectedSpot = computed(
  () => realSpots.value.find((s) => s.code === selectedCode.value) ?? filteredRows.value[0] ?? null,
)

function selectSpot(spot: ParkingSpot) {
  selectedCode.value = spot.code
  editDraft.value = null
}

function startEdit() {
  if (!selectedSpot.value) return
  editDraft.value = { code: selectedSpot.value.code, type: selectedSpot.value.type }
}

function cancelEdit() {
  editDraft.value = null
}

function saveEdit() {
  if (!editDraft.value || !selectedSpot.value) return
  const originalCode = selectedSpot.value.code
  const draft = editDraft.value
  spots.value = spots.value.map((s) => (s && s.code === originalCode ? { ...s, code: draft.code, type: draft.type } : s))
  selectedCode.value = draft.code
  editDraft.value = null
}

const STATS = computed(() => [
  { label: '전체 구역', value: zoneStats.value.total, icon: LayoutGrid, tone: 'primary' },
  { label: '일반 구역', value: zoneStats.value.general, icon: Car, tone: 'info' },
  { label: '장애인 구역', value: zoneStats.value.disabled, icon: Accessibility, tone: 'primary' },
  { label: '전기차 구역', value: zoneStats.value.ev, icon: Plug, tone: 'success' },
])
</script>

<template>
  <AppShell title="주차 구역 관리" breadcrumb="실시간 주차 관제 현황">
    <PageHeading title="주차 구역 관리" />

    <div class="stats-grid">
      <div v-for="s in STATS" :key="s.label" class="panel stat-card">
        <span class="stat-icon" :class="`tone-${s.tone}`">
          <component :is="s.icon" :size="24" />
        </span>
        <div>
          <p class="stat-label">{{ s.label }}</p>
          <p class="stat-value" :class="`tone-${s.tone}`">{{ s.value }}<span class="stat-unit">개</span></p>
        </div>
      </div>
    </div>

    <div class="main-grid">
      <section class="panel list-panel">
        <h3>구역 목록</h3>
        <div ref="filterBarRef" class="filter-bar">
          <div class="dropdown-wrap">
            <button type="button" class="chip active" @click="toggleDropdown('floor')">
              {{ floorLabel(floor) }} <ChevronDown :size="14" />
            </button>
            <div v-if="openDropdown === 'floor'" class="dropdown-menu">
              <button
                v-for="key in FLOOR_KEYS"
                :key="key"
                type="button"
                class="dropdown-item"
                :class="{ selected: floor === key }"
                @click="floor = key; openDropdown = null"
              >
                {{ floorLabel(key) }}
              </button>
            </div>
          </div>

          <div class="dropdown-wrap">
            <button type="button" class="chip" :class="{ active: !!typeFilter }" @click="toggleDropdown('type')">
              {{ typeFilter ?? '전체 유형' }} <ChevronDown :size="14" />
            </button>
            <div v-if="openDropdown === 'type'" class="dropdown-menu wide">
              <button
                type="button"
                class="dropdown-item"
                :class="{ selected: typeFilter === null }"
                @click="typeFilter = null; openDropdown = null"
              >
                전체
              </button>
              <button
                v-for="opt in TYPE_OPTIONS"
                :key="opt"
                type="button"
                class="dropdown-item"
                :class="{ selected: typeFilter === opt }"
                @click="typeFilter = opt; openDropdown = null"
              >
                {{ opt }}
              </button>
            </div>
          </div>

          <div class="dropdown-wrap">
            <button type="button" class="chip" :class="{ active: !!statusFilter }" @click="toggleDropdown('status')">
              {{ STATUS_OPTIONS.find((o) => o.status === statusFilter)?.label ?? '전체 상태' }} <ChevronDown :size="14" />
            </button>
            <div v-if="openDropdown === 'status'" class="dropdown-menu">
              <button
                type="button"
                class="dropdown-item"
                :class="{ selected: statusFilter === null }"
                @click="statusFilter = null; openDropdown = null"
              >
                전체
              </button>
              <button
                v-for="opt in STATUS_OPTIONS"
                :key="opt.status"
                type="button"
                class="dropdown-item"
                :class="{ selected: statusFilter === opt.status }"
                @click="statusFilter = opt.status; openDropdown = null"
              >
                {{ opt.label }}
              </button>
            </div>
          </div>

          <div class="search-box">
            <Search :size="16" />
            <input v-model="codeQuery" type="text" placeholder="구역 번호 검색">
          </div>
        </div>

        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th v-for="h in ['구역 번호', '층', '유형', '상태', '허용 시간']" :key="h">{{ h }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="filteredRows.length === 0">
                <td colspan="5" class="empty">조건에 맞는 구역이 없습니다.</td>
              </tr>
              <tr
                v-for="spot in filteredRows"
                v-else
                :key="spot.code"
                class="row"
                :class="{ selected: selectedSpot?.code === spot.code }"
                @click="selectSpot(spot)"
              >
                <td class="strong" :class="{ 'text-primary': selectedSpot?.code === spot.code }">{{ spot.code }}</td>
                <td class="muted">{{ spot.floor }}</td>
                <td><StatusTag :tone="typeTone(spot.type)">{{ spot.type }}</StatusTag></td>
                <td><StatusTag :tone="statusTone(spot.status)">{{ statusLabel(spot.status) }}</StatusTag></td>
                <td class="muted nowrap">{{ allowedTimeLabel(spot.type) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="side-col">
        <section class="panel map-panel">
          <div class="map-header">
            <h3>주차장 현황</h3>
            <div class="floor-tabs">
              <button
                v-for="key in FLOOR_KEYS"
                :key="key"
                type="button"
                class="floor-tab"
                :class="{ active: floor === key }"
                @click="floor = key"
              >
                {{ key }}
              </button>
            </div>
          </div>
          <div class="legend">
            <span class="legend-item"><span class="swatch" style="background: #e7e5f3" />사용 가능</span>
            <span class="legend-item"><span class="swatch" style="background: #c9c2f0" />사용 중</span>
            <span class="legend-item"><span class="swatch" style="background: #d5e6ff" />장애인 구역</span>
            <span class="legend-item"><span class="swatch" style="background: #dff3ef" />전기차 구역</span>
            <span class="legend-item"><span class="swatch" style="background: #ffdccd" />위반</span>
          </div>
          <ParkingFloorGrid
            :main-spots="currentFloor.main"
            :side-spots="currentFloor.side"
            :selected-code="selectedSpot?.code"
            @select-spot="selectSpot"
          />
        </section>

        <section class="panel selection-panel">
          <h3>선택 구역 정보</h3>

          <p v-if="!selectedSpot" class="empty-hint">구역을 선택하면 상세 정보가 표시됩니다.</p>

          <template v-else>
            <div class="fields-grid">
              <div>
                <span class="field-label">구역 번호</span>
                <input v-if="editDraft" v-model="editDraft.code" type="text" class="text-input">
                <p v-else class="field-value">{{ selectedSpot.code }}</p>
              </div>

              <div>
                <span class="field-label">최근 점유 시간</span>
                <p class="field-value">{{ selectedSpot.lastOccupiedAt }}</p>
              </div>

              <div>
                <span class="field-label">유형</span>
                <div v-if="editDraft" class="type-buttons">
                  <button
                    v-for="opt in TYPE_OPTIONS"
                    :key="opt"
                    type="button"
                    class="type-btn"
                    :class="{ active: editDraft.type === opt }"
                    @click="editDraft.type = opt"
                  >
                    {{ opt }}
                  </button>
                </div>
                <StatusTag v-else :tone="typeTone(selectedSpot.type)">{{ selectedSpot.type }}</StatusTag>
              </div>

              <div>
                <span class="field-label">현재 상태</span>
                <StatusTag :tone="statusTone(selectedSpot.status)">{{ statusLabel(selectedSpot.status) }}</StatusTag>
              </div>

              <div>
                <span class="field-label">허용 시간</span>
                <p class="field-value">{{ allowedTimeLabel(editDraft ? editDraft.type : selectedSpot.type) }}</p>
              </div>
            </div>

            <div class="edit-actions">
              <template v-if="editDraft">
                <button type="button" class="outline-btn" @click="cancelEdit">취소</button>
                <button type="button" class="primary-btn" @click="saveEdit">저장</button>
              </template>
              <button v-else type="button" class="outline-btn" @click="startEdit">
                <Pencil :size="16" /> 구역 수정
              </button>
            </div>
          </template>
        </section>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.stats-grid {
  display: grid;
  /* React판 gap-5(20px). 기존 spacing 토큰 단계(16/24)에 없어 그대로 px로 둔다. */
  gap: 20px;
  grid-template-columns: 1fr;
}

@media (min-width: 640px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (min-width: 1280px) {
  .stats-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: var(--spacing-base);
  padding: 20px;
}

.stat-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: var(--radius-lg);
}

.stat-icon.tone-primary {
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

.stat-icon.tone-info {
  background: var(--panel-info-soft);
  color: var(--panel-info);
}

.stat-icon.tone-success {
  background: var(--panel-success-soft);
  color: var(--panel-success);
}

.stat-label {
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.stat-value {
  font-size: var(--font-size-xl);
  font-weight: 800;
}

.stat-value.tone-primary {
  color: var(--panel-primary);
}

.stat-value.tone-info {
  color: var(--panel-info);
}

.stat-value.tone-success {
  color: var(--panel-success);
}

.stat-unit {
  margin-left: 4px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--panel-muted-foreground);
}

.main-grid {
  display: grid;
  gap: var(--spacing-lg);
  margin-top: var(--spacing-lg);
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 1280px) {
  .main-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.list-panel,
.map-panel,
.selection-panel {
  padding: var(--spacing-lg);
}

.list-panel h3,
.map-panel h3,
.selection-panel h3 {
  margin-bottom: var(--spacing-md);
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.dropdown-wrap {
  position: relative;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: none;
  padding: var(--spacing-sm) var(--spacing-base);
  white-space: nowrap;
  cursor: pointer;
  color: inherit;
}

.chip.active {
  border-color: color-mix(in oklch, var(--panel-primary) 40%, transparent);
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
  font-weight: 500;
}

.dropdown-menu {
  position: absolute;
  left: 0;
  top: 100%;
  z-index: 10;
  margin-top: var(--spacing-sm);
  width: 128px;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: var(--panel-card);
  padding: 6px;
  box-shadow: var(--panel-shadow-card);
}

.dropdown-menu.wide {
  width: 160px;
}

.dropdown-item {
  display: block;
  width: 100%;
  border: none;
  background: none;
  border-radius: 6px;
  padding: 6px var(--spacing-base);
  text-align: left;
  cursor: pointer;
  color: inherit;
}

.dropdown-item:hover {
  background: var(--panel-muted);
}

.dropdown-item.selected {
  color: var(--panel-primary);
  font-weight: 600;
}

.search-box {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
}

.search-box input {
  width: 112px;
  border: none;
  background: none;
  outline: none;
  color: inherit;
  font-size: var(--font-size-sm);
}

.table-scroll {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

thead tr {
  border-bottom: 1px solid var(--panel-border);
  color: var(--panel-muted-foreground);
}

th {
  padding: var(--spacing-sm);
  text-align: left;
  font-weight: 500;
  white-space: nowrap;
}

td {
  padding: 14px var(--spacing-sm);
}

.empty {
  padding: 40px var(--spacing-sm);
  text-align: center;
  color: var(--panel-muted-foreground);
}

.row {
  border-bottom: 1px solid color-mix(in oklch, var(--panel-border) 70%, transparent);
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.row:hover {
  background: var(--panel-muted);
}

.row.selected {
  background: var(--panel-primary-soft);
}

.row:last-child {
  border-bottom: none;
}

.strong {
  font-weight: 600;
}

.strong.text-primary {
  color: var(--panel-primary);
}

.muted {
  color: var(--panel-muted-foreground);
}

.nowrap {
  white-space: nowrap;
}

.map-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-base);
}

.map-header h3 {
  margin-bottom: 0;
}

.floor-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
}

.floor-tab {
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: none;
  padding: 6px var(--spacing-base);
  font-size: 12px;
  font-weight: 500;
  color: var(--panel-muted-foreground);
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.floor-tab:hover {
  background: var(--panel-muted);
}

.floor-tab.active {
  border-color: transparent;
  background: var(--panel-primary);
  color: var(--panel-on-primary);
  font-weight: 600;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-base);
  margin-bottom: var(--spacing-base);
  font-size: 12px;
  color: var(--panel-muted-foreground);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
}

.empty-hint {
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.fields-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--spacing-md);
}

@media (min-width: 640px) {
  .fields-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.field-label {
  display: block;
  margin-bottom: 6px;
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.field-value {
  font-weight: 500;
}

.text-input {
  width: 100%;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: var(--panel-background);
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
  color: inherit;
  outline: none;
}

.text-input:focus {
  border-color: var(--panel-primary);
}

.type-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.type-btn {
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: none;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--panel-muted-foreground);
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.type-btn:hover {
  background: var(--panel-muted);
}

.type-btn.active {
  border-color: transparent;
  background: var(--panel-primary);
  color: var(--panel-on-primary);
  font-weight: 600;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-lg);
}

.outline-btn,
.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  flex-shrink: 0;
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-md);
  font-size: var(--font-size-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
}

.outline-btn {
  border: 1px solid var(--panel-border);
  background: none;
  color: inherit;
  transition: background-color 0.15s ease;
}

.outline-btn:hover {
  background: var(--panel-muted);
}

.primary-btn {
  border: none;
  font-weight: 600;
  background: var(--panel-primary);
  color: var(--panel-on-primary);
  box-shadow: var(--panel-shadow-pop);
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}
</style>
