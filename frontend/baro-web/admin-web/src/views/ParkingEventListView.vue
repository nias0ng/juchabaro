<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronDown, RotateCcw } from '@lucide/vue'

import { useDropdownFilter } from '@/composables/use-dropdown-filter'
import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import SearchBox from '@/components/ui/SearchBox.vue'
import FilterChip from '@/components/ui/FilterChip.vue'
import FilterOptionList from '@/components/ui/FilterOptionList.vue'
import CalendarDateFilter from '@/components/ui/CalendarDateFilter.vue'
import ExportButton from '@/components/ui/ExportButton.vue'
import DataTable from '@/components/ui/DataTable.vue'
import TableStateRow from '@/components/ui/TableStateRow.vue'
import TableFooter from '@/components/ui/TableFooter.vue'
import EventDetailCard from '@/features/parking-events/components/EventDetailCard.vue'
import EventTimeline from '@/features/parking-events/components/EventTimeline.vue'
import {
  EVENT_TYPE_OPTIONS,
  eventTypeLabel,
  formatMonthDayTime,
  formatZoneNumber,
  typeTone,
} from '@/features/parking-events/data'
import { useParkingEventStore } from '@/features/parking-events/store'
import { EVENT_KIND_OPTIONS, eventKindLabel, eventKindOf, eventKindTone, useEventListFilters } from '@/features/parking-events/composables/use-event-list-filters'

type DropdownName = 'status' | 'type' | 'date'

const parkingEventStore = useParkingEventStore()
const { filterBarRef, openDropdown, toggleDropdown } = useDropdownFilter<DropdownName>()

const {
  statusFilter,
  typeFilter,
  dateFilter,
  carQuery,
  needAdminOnly,
  toggleNeedAdminOnly,
  hasActiveFilters,
  resetFilters,
  filteredRows,
  page,
  totalPages,
  safePage,
  pagedRows,
  rangeStart,
  rangeEnd,
  exportCsv,
} = useEventListFilters()

const selectedRow = computed(
  () => parkingEventStore.events.find((r) => r.eventId === parkingEventStore.selectedEventId) ?? parkingEventStore.events[0] ?? null,
)
</script>

<template>
  <AppShell title="사건 목록" breadcrumb="실시간 주차 관제 현황">
    <PageHeading title="사건 목록" />

    <div class="layout">
      <div>
        <div ref="filterBarRef" class="panel filter-bar">
          <div class="dropdown-wrap">
            <FilterChip :active="!!statusFilter" @click="toggleDropdown('status')">
              {{ statusFilter ? eventKindLabel(statusFilter) : '전체 종류' }} <ChevronDown :size="14" />
            </FilterChip>
            <FilterOptionList
              v-if="openDropdown === 'status'"
              :options="EVENT_KIND_OPTIONS"
              :selected="statusFilter"
              :label-for="eventKindLabel"
              width="144px"
              @select="statusFilter = $event; openDropdown = null"
            />
          </div>

          <div class="dropdown-wrap">
            <FilterChip :active="!!typeFilter" @click="toggleDropdown('type')">
              {{ typeFilter ? eventTypeLabel(typeFilter) : '전체 유형' }} <ChevronDown :size="14" />
            </FilterChip>
            <FilterOptionList
              v-if="openDropdown === 'type'"
              :options="EVENT_TYPE_OPTIONS"
              :selected="typeFilter"
              :label-for="eventTypeLabel"
              width="180px"
              @select="typeFilter = $event; openDropdown = null"
            />
          </div>

          <CalendarDateFilter
            v-model="dateFilter"
            :open="openDropdown === 'date'"
            @toggle="toggleDropdown('date')"
            @close="openDropdown = null"
          />

          <FilterChip
            :active="needAdminOnly"
            title="관리자 확인이 필요한 사건만 보기"
            @click="toggleNeedAdminOnly"
          >
            확인 필요
          </FilterChip>

          <SearchBox
            v-model="carQuery"
            placeholder="차량 번호 검색"
            input-width="clamp(160px, 16vw, 240px)"
          />

          <div v-if="hasActiveFilters" class="filter-actions">
            <button type="button" class="reset-filter-button" @click="resetFilters">
              <RotateCcw :size="14" />
              필터 초기화
            </button>
          </div>
        </div>

        <div class="panel table-panel">
          <DataTable clickable-rows>
            <thead class="event-table-header">
              <tr>
                <th v-for="h in ['ID', '차량 번호', '종류', '유형', '위치', '발생 일시', '조치']" :key="h">
                  {{ h }}
                </th>
              </tr>
            </thead>
            <tbody class="event-table-body">
              <TableStateRow
                v-if="parkingEventStore.eventsLoading"
                :colspan="7"
                variant="loading"
                message="불러오는 중입니다…"
                horizontal-padding="var(--spacing-base)"
              />
              <TableStateRow
                v-else-if="parkingEventStore.eventsError"
                :colspan="7"
                variant="error"
                :message="parkingEventStore.eventsError"
                horizontal-padding="var(--spacing-base)"
              />
              <TableStateRow
                v-else-if="pagedRows.length === 0"
                :colspan="7"
                variant="empty"
                message="조건에 맞는 사건이 없습니다."
                horizontal-padding="var(--spacing-base)"
              />
              <tr
                v-for="r in pagedRows"
                v-else
                :key="r.eventId"
                class="row"
                :class="{ selected: r.eventId === parkingEventStore.selectedEventId }"
                @click="parkingEventStore.setSelectedEventId(r.eventId)"
              >
                <td class="strong">#{{ r.eventId }}</td>
                <td class="nowrap">{{ r.plateNumber }}</td>
                <td class="nowrap">
                  <StatusTag variant="text" :tone="eventKindTone(eventKindOf(r))">
                    {{ eventKindLabel(eventKindOf(r)) }}
                  </StatusTag>
                </td>
                <td>
                  <StatusTag variant="text" :tone="typeTone(r.eventType)">
                    {{ eventTypeLabel(r.eventType) }}
                  </StatusTag>
                </td>
                <td class="nowrap muted">{{ formatZoneNumber(r.zoneNumber) }}</td>
                <td class="nowrap muted">{{ formatMonthDayTime(r.detectedAt) }}</td>
                <td>
                  <div class="row-actions">
                    <RouterLink
                      :to="`/events/${r.eventId}`"
                      class="table-pill link-btn"
                      :class="{ 'needs-confirmation': r.requestStatus === 'NEED_ADMIN' }"
                      :title="r.requestStatus === 'NEED_ADMIN' ? '관리자 확인 필요' : '사건 상세 보기'"
                    >
                      {{ r.requestStatus === 'NEED_ADMIN' ? '확인 필요' : '상세' }}
                    </RouterLink>
                  </div>
                </td>
              </tr>
            </tbody>
          </DataTable>
          <TableFooter
            :total="filteredRows.length"
            :range-start="rangeStart"
            :range-end="rangeEnd"
            :page="safePage"
            :total-pages="totalPages"
            @page-change="page = $event"
          >
            <template #actions>
              <ExportButton @click="exportCsv" />
            </template>
          </TableFooter>
        </div>
      </div>

      <aside class="panel detail-panel">
        <template v-if="selectedRow">
          <EventDetailCard :event-id="selectedRow.eventId" />

          <h4 class="timeline-title">사건 진행 이력</h4>
          <EventTimeline :event-id="selectedRow.eventId" />
        </template>
        <p v-else class="empty-hint">선택된 사건이 없습니다.</p>
      </aside>
    </div>
  </AppShell>
</template>

<style scoped>
.layout {
  display: grid;
  gap: var(--spacing-lg);
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 1280px) {
  .layout {
    /* 사건 상세 패널은 폭이 고정이어도 내용이 깨지지 않는 최소값(296px)으로 두고,
       표 영역이 남는 공간을 전부 가져가게 해 좁은 랩탑 화면에서도 가로 스크롤 없이
       모든 열이 한 줄로 보이게 한다. */
    grid-template-columns: minmax(0, 1fr) 296px;
  }
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-base);
  /* React판 mb-5(20px). 기존 spacing 토큰 단계(16/24)에 없어 그대로 px로 둔다. */
  margin-bottom: 20px;
  padding: var(--spacing-md);
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

.table-panel {
  padding: var(--spacing-md);
}

.event-table-header th {
  text-align: center;
  font-weight: 700;
  color: var(--panel-foreground);
}

.event-table-body td {
  text-align: center;
}

.event-table-body :deep(.table-pill) {
  display: inline-flex;
  height: 30px;
  min-height: 30px;
  box-sizing: border-box;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  padding: 0 var(--spacing-base);
  font-size: var(--font-size-sm);
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: center;
}

.link-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 80px;
  box-sizing: border-box;
  gap: 6px;
  flex-shrink: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--panel-muted);
  padding: 6px var(--spacing-base);
  font-size: 12px;
  font-weight: 500;
  color: inherit;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.link-btn:hover {
  border-color: var(--panel-border);
  background: color-mix(in oklch, var(--panel-muted) 78%, var(--panel-foreground));
}

.link-btn.needs-confirmation {
  border-color: transparent;
  background: var(--panel-info-soft);
  color: var(--panel-info);
  font-weight: 600;
}

.link-btn.needs-confirmation:hover {
  border-color: color-mix(in oklch, var(--panel-info) 25%, transparent);
  background: color-mix(in oklch, var(--panel-info) 16%, transparent);
}

.detail-panel {
  height: fit-content;
  padding: var(--spacing-lg);
}

.timeline-title {
  margin-bottom: var(--spacing-base);
  margin-top: 28px;
  font-weight: 700;
}

.empty-hint {
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}
</style>
