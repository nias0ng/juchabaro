<script setup lang="ts">
import { computed } from 'vue'
import { Accessibility, Car, ChevronDown, ChevronLeft, ChevronRight, LayoutGrid, Pencil, Plug, RotateCcw } from '@lucide/vue'

import { useDropdownFilter } from '@/composables/use-dropdown-filter'
import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import SearchBox from '@/components/ui/SearchBox.vue'
import FilterChip from '@/components/ui/FilterChip.vue'
import FilterOptionList from '@/components/ui/FilterOptionList.vue'
import DataTable from '@/components/ui/DataTable.vue'
import TableStateRow from '@/components/ui/TableStateRow.vue'
import ParkingSpotMap from '@/features/parking-zones/components/ParkingSpotMap.vue'
import type { FloorKey } from '@/features/parking-zones/types'
import {
  ZONE_TYPE_OPTIONS,
  OCCUPANCY_OPTIONS,
  allowedTimeLabel,
  congestionTone,
  occupancyLabel,
  occupancyTone,
  zoneFloorOf,
  zoneTypeLabel,
  zoneTypeTone,
} from '@/features/parking-zones/data'
import { useZoneManagement } from '@/features/parking-zones/composables/use-zone-management'

type DropdownName = 'floor' | 'type' | 'status'

const { filterBarRef, openDropdown, toggleDropdown } = useDropdownFilter<DropdownName>()

function floorLabel(floor: FloorKey): string {
  return `${floor.slice(1)}층`
}

const {
  FLOOR_KEYS,
  selectedFloor,
  zoneFloorFilter,
  selectFloor,
  zonesLoading,
  zonesError,
  spots,
  summaryLoading,
  summaryError,
  typeFilter,
  statusFilter,
  codeQuery,
  editDraft,
  saveError,
  saving,
  occupancyOf,
  congestion,
  zoneStats,
  filteredRows,
  hasActiveFilters,
  resetFilters,
  selectedZone,
  selectZoneId,
  selectSpot,
  startEdit,
  cancelEdit,
  saveEdit,
} = useZoneManagement()

function shiftFloor(delta: number) {
  const currentIndex = FLOOR_KEYS.indexOf(selectedFloor.value)
  const nextIndex = (currentIndex + delta + FLOOR_KEYS.length) % FLOOR_KEYS.length
  selectFloor(FLOOR_KEYS[nextIndex]!)
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

    <p v-if="zonesError" class="banner-error">{{ zonesError }}</p>

    <div class="main-grid">
      <section class="panel list-panel">
        <h3>구역 목록</h3>
        <div ref="filterBarRef" class="filter-bar">
          <div class="dropdown-wrap">
            <FilterChip :active="!!zoneFloorFilter" @click="toggleDropdown('floor')">
              {{ zoneFloorFilter ? floorLabel(zoneFloorFilter) : '전체 층' }} <ChevronDown :size="14" />
            </FilterChip>
            <FilterOptionList
              v-if="openDropdown === 'floor'"
              :options="FLOOR_KEYS"
              :selected="zoneFloorFilter"
              :label-for="floorLabel"
              width="112px"
              @select="selectFloor($event); openDropdown = null"
            />
          </div>

          <div class="dropdown-wrap">
            <FilterChip :active="!!typeFilter" @click="toggleDropdown('type')">
              {{ typeFilter ? zoneTypeLabel(typeFilter) : '전체 유형' }} <ChevronDown :size="14" />
            </FilterChip>
            <FilterOptionList
              v-if="openDropdown === 'type'"
              :options="ZONE_TYPE_OPTIONS"
              :selected="typeFilter"
              :label-for="zoneTypeLabel"
              width="160px"
              @select="typeFilter = $event; openDropdown = null"
            />
          </div>

          <div class="dropdown-wrap">
            <FilterChip :active="!!statusFilter" @click="toggleDropdown('status')">
              {{ statusFilter ? occupancyLabel(statusFilter) : '전체 상태' }} <ChevronDown :size="14" />
            </FilterChip>
            <FilterOptionList
              v-if="openDropdown === 'status'"
              :options="OCCUPANCY_OPTIONS"
              :selected="statusFilter"
              :label-for="occupancyLabel"
              width="128px"
              @select="statusFilter = $event; openDropdown = null"
            />
          </div>

          <SearchBox v-model="codeQuery" placeholder="구역 번호 검색" input-width="112px" />

          <div v-if="hasActiveFilters" class="filter-actions">
            <button type="button" class="reset-filter-button" @click="resetFilters">
              <RotateCcw :size="14" />
              필터 초기화
            </button>
          </div>
        </div>

        <DataTable clickable-rows>
          <thead class="zone-table-header">
            <tr>
              <th v-for="h in ['구역 번호', '층', '유형', '상태', '허용 시간']" :key="h">{{ h }}</th>
            </tr>
          </thead>
          <tbody class="zone-table-body">
            <TableStateRow v-if="zonesLoading" :colspan="5" variant="loading" message="불러오는 중입니다…" />
            <TableStateRow v-else-if="filteredRows.length === 0" :colspan="5" variant="empty" message="조건에 맞는 구역이 없습니다." />
            <tr
              v-for="zone in filteredRows"
              v-else
              :key="zone.zoneId"
              class="row"
              :class="{ selected: selectedZone?.zoneId === zone.zoneId }"
              @click="selectZoneId(zone.zoneId)"
            >
              <td class="strong" :class="{ 'text-primary': selectedZone?.zoneId === zone.zoneId }">{{ zone.zoneNumber }}</td>
              <td class="muted">{{ zoneFloorOf(zone.zoneNumber) ?? '-' }}</td>
              <td><StatusTag variant="text" :tone="zoneTypeTone(zone.zoneType)">{{ zoneTypeLabel(zone.zoneType) }}</StatusTag></td>
              <td>
                <StatusTag v-if="occupancyOf(zone.zoneId)" variant="text" :tone="occupancyTone(occupancyOf(zone.zoneId)!)">
                  {{ occupancyLabel(occupancyOf(zone.zoneId)!) }}
                </StatusTag>
                <span v-else class="muted">-</span>
              </td>
              <td class="muted nowrap">{{ allowedTimeLabel(zone.allowedMinutes) }}</td>
            </tr>
          </tbody>
        </DataTable>
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
                :class="{ active: selectedFloor === key }"
                @click="selectFloor(key)"
              >
                {{ key }}
              </button>
            </div>
          </div>

          <p v-if="summaryLoading" class="empty-hint">불러오는 중입니다…</p>
          <p v-else-if="summaryError" class="empty-hint error">{{ summaryError }}</p>
          <div v-else class="map-row">
            <button
              type="button"
              class="floor-nav-button floor-nav-prev"
              aria-label="이전 층"
              @click="shiftFloor(-1)"
            >
              <ChevronLeft :size="26" />
            </button>
            <div class="map-align">
              <div class="map-status-row">
                <div v-if="congestion" class="congestion-banner">
                  <span class="congestion-label">혼잡도</span>
                  <span class="congestion-rate" :class="`tone-${congestionTone(congestion.level)}`">{{ congestion.rate }}%</span>
                </div>
                <div class="legend">
                  <span class="legend-item"><span class="swatch" style="background: #e7e5f3" />사용 가능</span>
                  <span class="legend-item"><span class="swatch" style="background: #c3bcff" />사용 중</span>
                  <span class="legend-item"><span class="swatch" style="background: #c96a6a" />위반</span>
                </div>
              </div>
              <ParkingSpotMap
                :floor="selectedFloor"
                :spots="spots"
                :selected-zone-id="selectedZone?.zoneId"
                @select-spot="selectSpot"
              />
            </div>
            <button
              type="button"
              class="floor-nav-button floor-nav-next"
              aria-label="다음 층"
              @click="shiftFloor(1)"
            >
              <ChevronRight :size="26" />
            </button>
          </div>
        </section>

        <section class="panel selection-panel">
          <h3>선택 구역 정보</h3>

          <p v-if="!selectedZone" class="empty-hint">구역을 선택하면 상세 정보가 표시됩니다.</p>

          <template v-else>
            <div class="fields-grid">
              <div>
                <span class="field-label">구역 번호</span>
                <input v-if="editDraft" v-model="editDraft.zoneNumber" type="text" class="text-input">
                <p v-else class="field-value">{{ selectedZone.zoneNumber }}</p>
              </div>

              <div>
                <span class="field-label">층</span>
                <p class="field-value">{{ zoneFloorOf(selectedZone.zoneNumber) ?? '-' }}</p>
              </div>

              <div>
                <span class="field-label">유형</span>
                <div v-if="editDraft" class="type-buttons">
                  <button
                    v-for="opt in ZONE_TYPE_OPTIONS"
                    :key="opt"
                    type="button"
                    class="type-btn"
                    :class="{ active: editDraft.zoneType === opt }"
                    @click="editDraft.zoneType = opt"
                  >
                    {{ zoneTypeLabel(opt) }}
                  </button>
                </div>
                <StatusTag v-else :tone="zoneTypeTone(selectedZone.zoneType)">{{ zoneTypeLabel(selectedZone.zoneType) }}</StatusTag>
              </div>

              <div>
                <span class="field-label">현재 상태</span>
                <StatusTag v-if="occupancyOf(selectedZone.zoneId)" :tone="occupancyTone(occupancyOf(selectedZone.zoneId)!)">
                  {{ occupancyLabel(occupancyOf(selectedZone.zoneId)!) }}
                </StatusTag>
                <span v-else class="muted">정보 없음</span>
              </div>

              <div>
                <span class="field-label">허용 시간(시간)</span>
                <input
                  v-if="editDraft"
                  v-model="editDraft.allowedHours"
                  type="number"
                  min="0"
                  step="0.5"
                  class="text-input"
                  placeholder="비우면 변경 안 함"
                >
                <p v-else class="field-value">{{ allowedTimeLabel(selectedZone.allowedMinutes) }}</p>
              </div>
            </div>

            <p v-if="saveError" class="save-error">{{ saveError }}</p>

            <div class="edit-actions">
              <template v-if="editDraft">
                <button type="button" class="outline-btn" :disabled="saving" @click="cancelEdit">취소</button>
                <button type="button" class="primary-btn" :disabled="saving" @click="saveEdit">{{ saving ? '저장 중…' : '저장' }}</button>
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

.banner-error {
  margin-top: var(--spacing-base);
  font-size: var(--font-size-sm);
  color: var(--panel-danger);
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

/* 주차 현황 카드는 너비는 다른 카드와 같이 두되, 안의 요소(헤더/혼잡도/범례/지도)가
   너무 붙어 보이지 않게 세로 길이만 더 넉넉하게 준다. */
.map-panel {
  padding-bottom: var(--spacing-xl);
  min-height: 640px;
}

/* 지도 좌우에서 층을 순환 전환하는 버튼. 카드 경계가 아니라 지도 바로 옆(카드 안쪽)에 둔다. */
.map-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-xs);
  margin-top: var(--spacing-lg);
}

/* 범례를 지도 폭에 맞춰 그 위, 오른쪽 끝으로 정렬한다(카드 전체 폭이 아니라 지도 폭 기준). */
.map-align {
  display: flex;
  flex-direction: column;
  width: fit-content;
}

/* ParkingSpotMap 루트의 margin:0 auto가 flex item에서는 자동 여백을 먹어치워서 버튼이
   지도가 아니라 행 양 끝으로 밀려나 버린다. 정렬은 .map-row의 justify-content로 이미
   하고 있으니 여기서는 그 auto 여백을 꺼서 버튼이 지도 바로 옆에 붙게 한다. */
.map-row :deep(.grid-container) {
  margin: 0;
}

.floor-nav-button {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  background: none;
  color: var(--panel-muted-foreground);
  cursor: pointer;
  transition: color 0.15s ease;
}

.floor-nav-button:hover {
  color: var(--panel-foreground);
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

.zone-table-header th {
  text-align: center;
}

.zone-table-body td {
  text-align: center;
}

.dropdown-wrap {
  position: relative;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-left: auto;
}

.reset-filter-button {
  display: inline-flex;
  align-items: center;
  height: 34px;
  gap: 6px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  padding: 0 9px;
  color: var(--panel-muted-foreground);
  font-family: inherit;
  font-size: var(--font-size-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.reset-filter-button:hover {
  background: var(--panel-muted);
  color: var(--panel-primary);
}

.reset-filter-button:focus-visible {
  outline: 2px solid color-mix(in oklch, var(--panel-primary) 65%, transparent);
  outline-offset: 2px;
}

.strong.text-primary {
  color: var(--panel-primary);
}

.map-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-lg);
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

/* 혼잡도(왼쪽)와 범례(오른쪽)를 지도 폭에 맞춰 같은 줄에 둔다. */
.map-status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--spacing-base);
  margin-bottom: var(--spacing-xxs);
}

/* 배경 없이 글자로만 둔다. "혼잡도" 글자는 검은색으로 두고 수치(퍼센트)만 색으로 구분한다.
   base.css의 전역 리셋(`* { font-weight: normal }`)이 자식 span에도 직접 걸려서 상속을
   막기 때문에, 굵기는 부모가 아니라 각 span에 직접 지정해야 한다. */
.congestion-banner {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-xxs);
}

.congestion-label {
  font-size: var(--font-size-md);
  font-weight: 900;
  color: var(--panel-foreground);
}

.congestion-rate {
  font-size: var(--font-size-lg);
  font-weight: 900;
}

.congestion-rate.tone-success {
  color: var(--panel-success);
}

.congestion-rate.tone-warning {
  color: var(--panel-warning);
}

.congestion-rate.tone-danger {
  color: var(--panel-danger);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--spacing-base);
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

.empty-hint.error {
  color: var(--panel-danger);
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

.save-error {
  margin-top: var(--spacing-sm);
  font-size: 12px;
  color: var(--panel-danger);
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

.outline-btn:hover:not(:disabled) {
  background: var(--panel-muted);
}

.primary-btn {
  border: none;
  font-weight: 600;
  background: var(--panel-primary);
  color: var(--panel-on-primary);
  box-shadow: var(--panel-shadow-pop);
}

.outline-btn:disabled,
.primary-btn:disabled {
  opacity: 0.4;
  cursor: default;
  box-shadow: none;
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}
</style>
