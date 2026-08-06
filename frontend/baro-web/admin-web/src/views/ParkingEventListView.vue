<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronDown } from '@lucide/vue'

import { useDropdownFilter } from '@/composables/use-dropdown-filter'
import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import SearchBox from '@/components/ui/SearchBox.vue'
import FilterChip from '@/components/ui/FilterChip.vue'
import FilterOptionList from '@/components/ui/FilterOptionList.vue'
import ExportButton from '@/components/ui/ExportButton.vue'
import DataTable from '@/components/ui/DataTable.vue'
import TableStateRow from '@/components/ui/TableStateRow.vue'
import TableFooter from '@/components/ui/TableFooter.vue'
import EventDetailCard from '@/features/parking-events/components/EventDetailCard.vue'
import EventTimeline from '@/features/parking-events/components/EventTimeline.vue'
import {
  EVENT_TYPE_OPTIONS,
  eventStatusLabel,
  eventTypeLabel,
  formatDate,
  formatTime,
  statusTone,
  typeTone,
} from '@/features/parking-events/data'
import { useParkingEventStore } from '@/features/parking-events/store'
import { EVENT_KIND_OPTIONS, eventKindLabel, useEventListFilters } from '@/features/parking-events/composables/use-event-list-filters'

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
              {{ statusFilter ? eventKindLabel(statusFilter) : '전체 상태' }} <ChevronDown :size="14" />
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

          <div class="dropdown-wrap">
            <FilterChip :active="!!dateFilter" @click="toggleDropdown('date')">
              {{ dateFilter ? formatDate(dateFilter) : '날짜' }} <ChevronDown :size="14" />
            </FilterChip>
            <div v-if="openDropdown === 'date'" class="dropdown-menu date-menu">
              <button
                type="button"
                class="dropdown-item"
                :class="{ selected: dateFilter === null }"
                @click="dateFilter = null; openDropdown = null"
              >
                전체
              </button>
              <input
                :value="dateFilter ?? ''"
                type="date"
                @change="dateFilter = ($event.target as HTMLInputElement).value || null; openDropdown = null"
              >
            </div>
          </div>

          <FilterChip :active="needAdminOnly" @click="toggleNeedAdminOnly">관리자 확인</FilterChip>

          <SearchBox v-model="carQuery" placeholder="차량 번호 검색" input-width="128px" />

          <ExportButton @click="exportCsv" />
        </div>

        <div class="panel table-panel">
          <DataTable clickable-rows>
            <thead>
              <tr>
                <th v-for="h in ['ID', '차량 번호', '종류', '유형', '위치', '발생 시간', '조치']" :key="h">
                  {{ h }}
                </th>
              </tr>
            </thead>
            <tbody>
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
                  <template v-if="r.eventStatus === 'REQUESTED' || r.eventStatus === 'RESOLVED'">{{ eventStatusLabel(r.eventStatus, r.requestType) }}</template>
                  <StatusTag v-else :tone="statusTone(r.eventStatus)">{{ eventStatusLabel(r.eventStatus, r.requestType) }}</StatusTag>
                </td>
                <td><StatusTag :tone="typeTone(r.eventType)">{{ eventTypeLabel(r.eventType) }}</StatusTag></td>
                <td class="nowrap muted">{{ r.zoneNumber ?? '-' }}</td>
                <td class="muted">{{ formatTime(r.detectedAt) }}</td>
                <td>
                  <div class="row-actions">
                    <RouterLink :to="`/events/${r.eventId}`" class="link-btn">상세 보기</RouterLink>
                    <StatusTag v-if="r.requestStatus === 'NEED_ADMIN'" tone="info">관리자 확인 필요</StatusTag>
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
          />
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

.dropdown-menu {
  position: absolute;
  left: 0;
  top: 100%;
  z-index: 10;
  margin-top: var(--spacing-sm);
  width: 144px;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: var(--panel-card);
  padding: 6px;
  box-shadow: var(--panel-shadow-card);
}

.dropdown-menu.date-menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: auto;
  padding: var(--spacing-base);
}

.dropdown-item {
  display: block;
  width: 100%;
  border: none;
  background: none;
  border-radius: 6px;
  padding: 6px var(--spacing-base);
  text-align: left;
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.dropdown-item:hover {
  background: var(--panel-muted);
}

.dropdown-item.selected {
  color: var(--panel-primary);
  font-weight: 600;
}

.table-panel {
  padding: var(--spacing-md);
}

.row-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.link-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-sm);
  background: none;
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
  background: var(--panel-muted);
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
