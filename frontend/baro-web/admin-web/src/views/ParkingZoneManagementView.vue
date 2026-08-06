<script setup lang="ts">
import { computed } from 'vue'
import { Accessibility, Car, ChevronDown, LayoutGrid, Pencil, Plug, Search } from '@lucide/vue'

import { useDropdownFilter } from '@/composables/use-dropdown-filter'
import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import ParkingSpotMap from '@/features/parking-zones/components/ParkingSpotMap.vue'
import {
  ZONE_TYPE_OPTIONS,
  OCCUPANCY_OPTIONS,
  allowedTimeLabel,
  congestionLabel,
  congestionTone,
  occupancyLabel,
  occupancyTone,
  zoneFloorOf,
  zoneTypeLabel,
  zoneTypeTone,
} from '@/features/parking-zones/data'
import { useZoneManagement } from '@/features/parking-zones/composables/use-zone-management'

type DropdownName = 'type' | 'status'

const { filterBarRef, openDropdown, toggleDropdown } = useDropdownFilter<DropdownName>()

const {
  FLOOR_KEYS,
  selectedFloor,
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
  selectedZone,
  selectZoneId,
  selectSpot,
  startEdit,
  cancelEdit,
  saveEdit,
} = useZoneManagement()

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
            <button type="button" class="chip" :class="{ active: !!typeFilter }" @click="toggleDropdown('type')">
              {{ typeFilter ? zoneTypeLabel(typeFilter) : '전체 유형' }} <ChevronDown :size="14" />
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
                v-for="opt in ZONE_TYPE_OPTIONS"
                :key="opt"
                type="button"
                class="dropdown-item"
                :class="{ selected: typeFilter === opt }"
                @click="typeFilter = opt; openDropdown = null"
              >
                {{ zoneTypeLabel(opt) }}
              </button>
            </div>
          </div>

          <div class="dropdown-wrap">
            <button type="button" class="chip" :class="{ active: !!statusFilter }" @click="toggleDropdown('status')">
              {{ statusFilter ? occupancyLabel(statusFilter) : '전체 상태' }} <ChevronDown :size="14" />
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
                v-for="opt in OCCUPANCY_OPTIONS"
                :key="opt"
                type="button"
                class="dropdown-item"
                :class="{ selected: statusFilter === opt }"
                @click="statusFilter = opt; openDropdown = null"
              >
                {{ occupancyLabel(opt) }}
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
              <tr v-if="zonesLoading">
                <td colspan="5" class="empty">불러오는 중입니다…</td>
              </tr>
              <tr v-else-if="filteredRows.length === 0">
                <td colspan="5" class="empty">조건에 맞는 구역이 없습니다.</td>
              </tr>
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
                <td><StatusTag :tone="zoneTypeTone(zone.zoneType)">{{ zoneTypeLabel(zone.zoneType) }}</StatusTag></td>
                <td>
                  <StatusTag v-if="occupancyOf(zone.zoneId)" :tone="occupancyTone(occupancyOf(zone.zoneId)!)">
                    {{ occupancyLabel(occupancyOf(zone.zoneId)!) }}
                  </StatusTag>
                  <span v-else class="muted">정보 없음</span>
                </td>
                <td class="muted nowrap">{{ allowedTimeLabel(zone.allowedMinutes) }}</td>
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
                :class="{ active: selectedFloor === key }"
                @click="selectedFloor = key"
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
            <span class="legend-item"><span class="swatch" style="background: #3b82f6" />출구</span>
            <span class="legend-item"><span class="swatch" style="background: #22c55e" />입구</span>
            <StatusTag v-if="congestion" class="congestion-tag" :tone="congestionTone(congestion.level)">
              혼잡도 {{ congestionLabel(congestion.level) }} ({{ congestion.rate }}%)
            </StatusTag>
          </div>
          <p v-if="summaryLoading" class="empty-hint">불러오는 중입니다…</p>
          <p v-else-if="summaryError" class="empty-hint error">{{ summaryError }}</p>
          <ParkingSpotMap
            v-else
            :floor="selectedFloor"
            :spots="spots"
            :selected-zone-id="selectedZone?.zoneId"
            @select-spot="selectSpot"
          />
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
  align-items: center;
  gap: var(--spacing-base);
  margin-bottom: var(--spacing-base);
  font-size: 12px;
  color: var(--panel-muted-foreground);
}

.congestion-tag {
  margin-left: auto;
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
