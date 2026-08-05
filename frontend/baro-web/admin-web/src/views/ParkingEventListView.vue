<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronDown, Download, Search } from '@lucide/vue'

import { useDropdownFilter } from '@/composables/use-dropdown-filter'
import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import AppPagination from '@/components/ui/AppPagination.vue'
import EventDetailCard from '@/features/parking-events/components/EventDetailCard.vue'
import EventTimeline from '@/features/parking-events/components/EventTimeline.vue'
import type { AdminEventSummary, EventStatus, EventType } from '@/features/parking-events/api/types'
import {
  EVENT_STATUS_OPTIONS,
  EVENT_TYPE_OPTIONS,
  eventStatusLabel,
  eventTypeLabel,
  formatDate,
  formatTime,
  localDateString,
  statusTone,
  todayDateString,
  typeTone,
} from '@/features/parking-events/data'
import { useParkingEventStore } from '@/features/parking-events/store'

const PAGE_SIZE = 10
// 백엔드는 날짜/상태/유형으로만 필터링하고 차량 번호 검색은 지원하지 않는다. 선택한
// 조건에 맞는 사건을 넉넉히 받아온 뒤 차량 번호 검색과 페이지네이션은 화면에서 처리한다.
const FETCH_SIZE = 200

function exportRowsToCsv(rows: AdminEventSummary[], dateFilter: string | null) {
  const headers = ['ID', '차량 번호', '유형', '위치', '발생 시간', '상태', '날짜']
  const escapeCsv = (value: string) => `"${value.replaceAll('"', '""')}"`
  // 날짜를 선택하지 않았으면(전체 조회) 행마다 실제 발생 날짜를 넣고, 선택했으면 필터 날짜를 그대로 쓴다.
  // 날짜 앞에 작은따옴표를 붙이면 엑셀이 이 칸을 날짜로 자동 변환하지 않고 텍스트 그대로 표시한다.
  const lines = [
    headers.map(escapeCsv).join(','),
    ...rows.map((r) =>
      [
        `#${r.eventId}`,
        r.plateNumber,
        eventTypeLabel(r.eventType),
        r.zoneNumber ?? '-',
        formatTime(r.detectedAt),
        eventStatusLabel(r.eventStatus, r.requestType),
        `'${dateFilter ?? localDateString(r.detectedAt)}`,
      ].map(escapeCsv).join(','),
    ),
  ]
  // Excel에서 한글이 깨지지 않도록 UTF-8 BOM을 앞에 붙인다.
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const stamp = (dateFilter ?? todayDateString()).replaceAll('-', '')

  const link = document.createElement('a')
  link.href = url
  link.download = `사건_목록_${stamp}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

type DropdownName = 'status' | 'type' | 'date'

const statusFilter = ref<EventStatus | null>(null)
const typeFilter = ref<EventType | null>(null)
// 날짜를 고르지 않으면(null) 전체 날짜를 최근 발생 순으로 보여준다.
const dateFilter = ref<string | null>(null)
const carQuery = ref('')
const page = ref(1)

const parkingEventStore = useParkingEventStore()

const { filterBarRef, openDropdown, toggleDropdown } = useDropdownFilter<DropdownName>()

function loadEvents() {
  void parkingEventStore.fetchEvents({
    date: dateFilter.value ?? undefined,
    eventStatus: statusFilter.value ?? undefined,
    eventType: typeFilter.value ?? undefined,
    size: FETCH_SIZE,
  })
}

watch([dateFilter, statusFilter, typeFilter], () => {
  page.value = 1
  loadEvents()
}, { immediate: true })

const selectedRow = computed(
  () => parkingEventStore.events.find((r) => r.eventId === parkingEventStore.selectedEventId) ?? parkingEventStore.events[0] ?? null,
)

const filteredRows = computed(() => {
  const query = carQuery.value.trim().replaceAll(' ', '')
  if (!query) return parkingEventStore.events
  return parkingEventStore.events.filter((r) => r.plateNumber.replaceAll(' ', '').includes(query))
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / PAGE_SIZE)))
// 필터가 바뀌어 결과 수가 줄면 이미 지나간 페이지 번호가 남아있을 수 있어 화면에는
// totalPages 안쪽으로 자른 값만 쓴다(별도 watcher 없이 계산식으로 처리).
const safePage = computed(() => Math.min(page.value, totalPages.value))
const pagedRows = computed(() =>
  filteredRows.value.slice((safePage.value - 1) * PAGE_SIZE, safePage.value * PAGE_SIZE),
)
const rangeStart = computed(() => (filteredRows.value.length === 0 ? 0 : (safePage.value - 1) * PAGE_SIZE + 1))
const rangeEnd = computed(() => Math.min(safePage.value * PAGE_SIZE, filteredRows.value.length))

// "관리자 확인" 버튼: 켜면 상태 필터를 NEED_ADMIN으로 고정해 관리자 확인이 필요한 사건만
// 보여주고, 상태 드롭다운은 그동안 손대지 못하게 비활성화한다. 끄면 전체 상태로 되돌린다.
const needAdminOnly = ref(false)

function toggleNeedAdminOnly() {
  needAdminOnly.value = !needAdminOnly.value
  statusFilter.value = needAdminOnly.value ? 'NEED_ADMIN' : null
}
</script>

<template>
  <AppShell title="사건 목록" breadcrumb="실시간 주차 관제 현황">
    <PageHeading title="사건 목록" />

    <div class="layout">
      <div>
        <div ref="filterBarRef" class="panel filter-bar">
          <div class="dropdown-wrap">
            <button
              type="button"
              class="chip"
              :class="{ active: !!statusFilter }"
              :disabled="needAdminOnly"
              @click="toggleDropdown('status')"
            >
              {{ statusFilter ? eventStatusLabel(statusFilter) : '전체 상태' }} <ChevronDown :size="14" />
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
                v-for="opt in EVENT_STATUS_OPTIONS"
                :key="opt"
                type="button"
                class="dropdown-item"
                :class="{ selected: statusFilter === opt }"
                @click="statusFilter = opt; openDropdown = null"
              >
                {{ eventStatusLabel(opt) }}
              </button>
            </div>
          </div>

          <div class="dropdown-wrap">
            <button
              type="button"
              class="chip"
              :class="{ active: !!typeFilter }"
              @click="toggleDropdown('type')"
            >
              {{ typeFilter ? eventTypeLabel(typeFilter) : '전체 유형' }} <ChevronDown :size="14" />
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
                v-for="opt in EVENT_TYPE_OPTIONS"
                :key="opt"
                type="button"
                class="dropdown-item"
                :class="{ selected: typeFilter === opt }"
                @click="typeFilter = opt; openDropdown = null"
              >
                {{ eventTypeLabel(opt) }}
              </button>
            </div>
          </div>

          <div class="dropdown-wrap">
            <button type="button" class="chip" :class="{ active: !!dateFilter }" @click="toggleDropdown('date')">
              {{ dateFilter ? formatDate(dateFilter) : '날짜' }} <ChevronDown :size="14" />
            </button>
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

          <button
            type="button"
            class="chip"
            :class="{ active: needAdminOnly }"
            @click="toggleNeedAdminOnly"
          >
            관리자 확인
          </button>

          <div class="search-box">
            <Search :size="16" />
            <input v-model="carQuery" type="text" placeholder="차량 번호 검색">
          </div>

          <button type="button" class="export-btn" @click="exportRowsToCsv(filteredRows, dateFilter)">
            <Download :size="16" /> 내보내기
          </button>
        </div>

        <div class="panel table-panel">
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th v-for="h in ['ID', '차량 번호', '유형', '위치', '발생 시간', '상태', '조치']" :key="h">
                    {{ h }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="parkingEventStore.eventsLoading">
                  <td colspan="7" class="empty">불러오는 중입니다…</td>
                </tr>
                <tr v-else-if="parkingEventStore.eventsError">
                  <td colspan="7" class="empty error">{{ parkingEventStore.eventsError }}</td>
                </tr>
                <tr v-else-if="pagedRows.length === 0">
                  <td colspan="7" class="empty">조건에 맞는 사건이 없습니다.</td>
                </tr>
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
                  <td><StatusTag :tone="typeTone(r.eventType)">{{ eventTypeLabel(r.eventType) }}</StatusTag></td>
                  <td class="nowrap muted">{{ r.zoneNumber ?? '-' }}</td>
                  <td class="muted">{{ formatTime(r.detectedAt) }}</td>
                  <td><StatusTag :tone="statusTone(r.eventStatus)">{{ eventStatusLabel(r.eventStatus, r.requestType) }}</StatusTag></td>
                  <td>
                    <div class="row-actions">
                      <RouterLink :to="`/events/${r.eventId}`" class="link-btn">상세 보기</RouterLink>
                      <StatusTag v-if="r.eventStatus === 'NEED_ADMIN'" tone="info">관리자 확인 필요</StatusTag>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="footer">
            <span>전체 {{ filteredRows.length }}건 중 {{ rangeStart }}-{{ rangeEnd }} 표시</span>
            <div class="pagination-wrap">
              <AppPagination :page="safePage" :total-pages="totalPages" @page-change="page = $event" />
            </div>
          </div>
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

.chip.active {
  border-color: color-mix(in oklch, var(--panel-primary) 40%, transparent);
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
  font-weight: 500;
}

.chip:disabled {
  opacity: 0.5;
  cursor: default;
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

.dropdown-menu.wide {
  width: 180px;
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

.search-box {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
  color: var(--panel-muted-foreground);
}

.search-box input {
  width: 128px;
  border: none;
  background: none;
  outline: none;
  color: inherit;
  font-size: var(--font-size-sm);
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

.table-panel {
  padding: var(--spacing-md);
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
  padding: 40px var(--spacing-base);
  text-align: center;
  color: var(--panel-muted-foreground);
}

.empty.error {
  color: var(--panel-danger);
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

.nowrap {
  white-space: nowrap;
}

.muted {
  color: var(--panel-muted-foreground);
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

.footer {
  position: relative;
  display: flex;
  align-items: center;
  margin-top: 20px;
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.pagination-wrap {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
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
