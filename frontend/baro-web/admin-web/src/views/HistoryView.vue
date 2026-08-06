<script setup lang="ts">
import { CheckCircle2, ChevronDown, Download } from '@lucide/vue'

import { useDropdownFilter } from '@/composables/use-dropdown-filter'
import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import SearchBox from '@/components/ui/SearchBox.vue'
import DataTable from '@/components/ui/DataTable.vue'
import TableStateRow from '@/components/ui/TableStateRow.vue'
import TableFooter from '@/components/ui/TableFooter.vue'
import { actionTone, actionTypeLabel, formatDateTime } from '@/features/parking-events/data'
import { useParkingEventStore } from '@/features/parking-events/store'
import { useHistoryFilters } from '@/features/parking-events/composables/use-history-filters'

// 로그 ID, 사건 ID, 차량 번호, 처리 유형, 처리자, 처리 시간 순(메모 제외).
// 메모는 줄바꿈을 허용하는 유일한 열이라 폭을 고정하지 않고, 이 여섯 열이 줄바꿈 없이
// 들어갈 최소 폭만 차지한 뒤 나머지 공간을 전부 메모가 가져가게 한다.
const COLUMN_WIDTHS = [71, 66, 85, 100, 71, 150]
// 창이 좁아 남는 공간이 이 값보다 작아지면(메모가 읽을 수 없이 눌리는 대신) 표 전체가
// 넘치면서 가로 스크롤로 전환된다.
const MEMO_MIN_WIDTH = 200

type DropdownName = 'date'

const parkingEventStore = useParkingEventStore()
const { filterBarRef, openDropdown, toggleDropdown } = useDropdownFilter<DropdownName>()

const {
  dateRange,
  query,
  filteredRows,
  page,
  totalPages,
  safePage,
  pagedRows,
  rangeStart,
  rangeEnd,
  todayTimeline,
  exportCsv,
} = useHistoryFilters()
</script>

<template>
  <AppShell title="이력 관리" breadcrumb="사건 처리 이력">
    <PageHeading title="이력 관리" />

    <div ref="filterBarRef" class="panel filter-bar">
      <div class="dropdown-wrap">
        <button type="button" class="chip" @click="toggleDropdown('date')">
          {{ dateRange.start.replaceAll('-', '.') }} ~ {{ dateRange.end.replaceAll('-', '.') }} <ChevronDown :size="14" />
        </button>
        <div v-if="openDropdown === 'date'" class="dropdown-menu date-menu">
          <input v-model="dateRange.start" type="date">
          <span class="tilde">~</span>
          <input v-model="dateRange.end" type="date">
        </div>
      </div>

      <SearchBox v-model="query" placeholder="차량 번호 또는 사건 ID 검색" input-width="176px" />
      <button type="button" class="export-btn" @click="exportCsv">
        <Download :size="16" /> 내보내기
      </button>
    </div>

    <div class="layout">
      <section class="panel history-panel">
        <h3>처리 이력</h3>
        <DataTable>
          <colgroup>
            <col v-for="(w, i) in COLUMN_WIDTHS" :key="i" :style="{ width: `${w}px` }">
            <col>
          </colgroup>
          <thead>
            <tr>
              <th
                v-for="h in ['로그 ID', '사건 ID', '차량 번호', '처리 유형', '처리자', '처리 시간', '메모']"
                :key="h"
                :style="h === '메모' ? { minWidth: `${MEMO_MIN_WIDTH}px` } : undefined"
              >
                {{ h }}
              </th>
            </tr>
          </thead>
          <tbody>
            <TableStateRow v-if="parkingEventStore.historyLoading" :colspan="7" variant="loading" message="불러오는 중입니다…" />
            <TableStateRow
              v-else-if="parkingEventStore.historyError"
              :colspan="7"
              variant="error"
              :message="parkingEventStore.historyError"
            />
            <TableStateRow v-else-if="pagedRows.length === 0" :colspan="7" variant="empty" message="조건에 맞는 이력이 없습니다." />
            <tr v-for="r in pagedRows" v-else :key="r.logId" class="row">
              <td class="strong nowrap">#L-{{ r.logId }}</td>
              <td class="muted nowrap">#{{ r.eventId }}</td>
              <td class="nowrap">{{ r.plateNumber }}</td>
              <td class="nowrap"><StatusTag :tone="actionTone(r.actionType)">{{ actionTypeLabel(r.actionType) }}</StatusTag></td>
              <td class="muted nowrap">{{ r.adminName }}</td>
              <td class="muted nowrap">{{ formatDateTime(r.actedAt) }}</td>
              <td class="muted" :style="{ minWidth: `${MEMO_MIN_WIDTH}px` }">{{ r.memo || '-' }}</td>
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
      </section>

      <div class="side-col">
        <section class="panel timeline-panel">
          <div class="timeline-header">
            <h3>활동 타임라인</h3>
            <StatusTag tone="primary">오늘</StatusTag>
          </div>
          <div class="timeline-scroll">
            <ol v-if="todayTimeline.length" class="timeline">
              <li v-for="entry in todayTimeline" :key="entry.logId" class="timeline-item">
                <span class="timeline-icon">
                  <CheckCircle2 :size="16" />
                </span>
                <div>
                  <p class="timeline-title-row">
                    <span class="timeline-time">{{ formatDateTime(entry.actedAt).split(' ')[1] }}</span>
                    <span class="timeline-title">{{ entry.adminName }}가 #{{ entry.eventId }} 사건을 {{ actionTypeLabel(entry.actionType) }}</span>
                  </p>
                  <p class="timeline-desc">{{ entry.memo || '-' }}</p>
                </div>
              </li>
            </ol>
            <p v-else class="timeline-empty">오늘 남긴 활동이 없습니다.</p>
          </div>
        </section>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-base);
  margin-bottom: var(--spacing-lg);
  padding: var(--spacing-md);
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
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
  white-space: nowrap;
  cursor: pointer;
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
  align-items: center;
  gap: var(--spacing-sm);
  width: auto;
  padding: var(--spacing-base);
}

.dropdown-menu.date-menu input {
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: var(--panel-background);
  padding: 6px var(--spacing-sm);
  font-size: var(--font-size-sm);
  color: inherit;
  outline: none;
}

.tilde {
  color: var(--panel-muted-foreground);
}

.export-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  flex-shrink: 0;
  margin-left: auto;
  border: none;
  border-radius: var(--radius-md);
  background: var(--panel-primary);
  padding: var(--spacing-sm) var(--spacing-md);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--panel-on-primary);
  white-space: nowrap;
  box-shadow: var(--panel-shadow-pop);
  cursor: pointer;
}

.layout {
  display: grid;
  gap: var(--spacing-lg);
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 1280px) {
  .layout {
    grid-template-columns: minmax(0, 2.4fr) minmax(0, 1fr);
  }
}

.history-panel {
  padding: var(--spacing-lg);
}

.history-panel h3 {
  margin-bottom: var(--spacing-md);
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

.timeline-panel {
  padding: var(--spacing-lg);
}

.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-md);
}

.timeline-header h3 {
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline-item {
  display: flex;
  gap: var(--spacing-base);
}

.timeline-icon {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

.timeline-title-row {
  font-size: var(--font-size-sm);
}

.timeline-time {
  margin-right: var(--spacing-sm);
  color: var(--panel-muted-foreground);
}

.timeline-title {
  font-weight: 500;
}

.timeline-desc {
  font-size: 12px;
  color: var(--panel-muted-foreground);
}

.timeline-scroll {
  max-height: 360px;
  overflow-y: auto;
}

.timeline-empty {
  padding: var(--spacing-base) 0;
  text-align: center;
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}
</style>
