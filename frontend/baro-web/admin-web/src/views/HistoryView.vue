<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  Bell,
  CalendarCheck,
  CheckCircle2,
  ChevronDown,
  Crosshair,
  Download,
  Search,
  Settings,
} from '@lucide/vue'

import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import AppPagination from '@/components/ui/AppPagination.vue'
import { HISTORY_ACTION_OPTIONS, MOCK_TODAY } from '@/features/parking-events/data'
import { useParkingEventStore } from '@/features/parking-events/store'
import type { HistoryLogEntry } from '@/features/parking-events/types'

const PAGE_SIZE = 10

// 로그 ID, 사건 ID, 차량 번호, 처리 유형, 처리자, 처리 시간 순(메모 제외).
// 메모는 줄바꿈을 허용하는 유일한 열이라 폭을 고정하지 않고, 이 여섯 열이 줄바꿈 없이
// 들어갈 최소 폭만 차지한 뒤 나머지 공간을 전부 메모가 가져가게 한다.
const COLUMN_WIDTHS = [71, 66, 85, 100, 71, 126]
// 창이 좁아 남는 공간이 이 값보다 작아지면(메모가 읽을 수 없이 눌리는 대신) 표 전체가
// 넘치면서 가로 스크롤로 전환된다.
const MEMO_MIN_WIDTH = 200

const SUMMARY = [
  { label: '오늘 처리', value: 24, icon: CalendarCheck, tone: 'info' },
  { label: '오탐 처리', value: 3, icon: Crosshair, tone: 'primary' },
  { label: '재알림', value: 7, icon: Bell, tone: 'primary' },
  { label: '설정 변경', value: 4, icon: Settings, tone: 'success' },
]

function exportRowsToCsv(rows: HistoryLogEntry[], dateRange: { start: string; end: string }) {
  const headers = ['로그 ID', '사건 ID', '차량 번호', '처리 유형', '처리자', '처리 시간', '메모']
  const escapeCsv = (value: string) => `"${value.replaceAll('"', '""')}"`
  // 처리 시간 앞에 작은따옴표를 붙이면 엑셀이 이 칸(날짜가 포함된 문자열)을 날짜로
  // 자동 변환하지 않고 텍스트 그대로 표시한다.
  const lines = [
    headers.map(escapeCsv).join(','),
    ...rows.map((r) =>
      [r.logId, r.eventId, r.car, r.actionType, r.handler, `'${r.time}`, r.memo].map(escapeCsv).join(','),
    ),
  ]
  // Excel에서 한글이 깨지지 않도록 UTF-8 BOM을 앞에 붙인다.
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const startStamp = dateRange.start.replaceAll('-', '')
  const endStamp = dateRange.end.replaceAll('-', '')
  const stamp = startStamp === endStamp ? startStamp : `${startStamp}-${endStamp}`

  const link = document.createElement('a')
  link.href = url
  link.download = `이력_${stamp}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function actionTone(a = ''): 'success' | 'info' | 'primary' {
  if (a === '완료 처리') return 'success'
  if (a === '오탐 처리' || a === '관리자 확인') return 'info'
  return 'primary'
}

function rowDate(row: HistoryLogEntry) {
  return row.time.split(' ')[0]!.replaceAll('.', '-')
}

type DropdownName = 'date' | 'type'

const dateRange = ref({ start: MOCK_TODAY, end: MOCK_TODAY })
const typeFilter = ref<string | null>(null)
const openDropdown = ref<DropdownName | null>(null)
const query = ref('')
const page = ref(1)

const filterBarRef = ref<HTMLElement | null>(null)
const parkingEventStore = useParkingEventStore()

// 활동 타임라인은 '더 보기'로 일부만 보여주는 대신, 오늘(MOCK_TODAY) 하루치 전체를
// 최신순으로 보여주고 넘치는 만큼은 스크롤로 본다(history는 이미 최신 항목이 앞에 온다).
const todayTimeline = computed(() => parkingEventStore.history.filter((entry) => rowDate(entry) === MOCK_TODAY))

function handleClickOutside(event: MouseEvent) {
  if (filterBarRef.value && !filterBarRef.value.contains(event.target as Node)) {
    openDropdown.value = null
  }
}

onMounted(() => document.addEventListener('mousedown', handleClickOutside))
onUnmounted(() => document.removeEventListener('mousedown', handleClickOutside))

function toggleDropdown(name: DropdownName) {
  openDropdown.value = openDropdown.value === name ? null : name
}

const filteredRows = computed(() => {
  const q = query.value.trim().replaceAll(' ', '').toUpperCase()
  return parkingEventStore.history.filter((r) => {
    const d = rowDate(r)
    if (d < dateRange.value.start || d > dateRange.value.end) return false
    if (typeFilter.value && r.actionType !== typeFilter.value) return false
    if (q) {
      const car = r.car.replaceAll(' ', '').toUpperCase()
      const eventId = r.eventId.toUpperCase()
      if (!car.includes(q) && !eventId.includes(q)) return false
    }
    return true
  })
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

      <div class="dropdown-wrap">
        <button type="button" class="chip" :class="{ active: !!typeFilter }" @click="toggleDropdown('type')">
          {{ typeFilter ?? '처리 유형' }} <ChevronDown :size="14" />
        </button>
        <div v-if="openDropdown === 'type'" class="dropdown-menu">
          <button
            type="button"
            class="dropdown-item"
            :class="{ selected: typeFilter === null }"
            @click="typeFilter = null; openDropdown = null"
          >
            전체
          </button>
          <button
            v-for="opt in HISTORY_ACTION_OPTIONS"
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

      <div class="search-box">
        <Search :size="16" />
        <input v-model="query" type="text" placeholder="차량 번호 또는 사건 ID 검색">
      </div>
      <button type="button" class="export-btn" @click="exportRowsToCsv(filteredRows, dateRange)">
        <Download :size="16" /> 내보내기
      </button>
    </div>

    <div class="layout">
      <section class="panel history-panel">
        <h3>처리 이력</h3>
        <div class="table-scroll">
          <table>
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
              <tr v-if="pagedRows.length === 0">
                <td colspan="7" class="empty">조건에 맞는 이력이 없습니다.</td>
              </tr>
              <tr v-for="r in pagedRows" v-else :key="r.logId" class="row">
                <td class="strong nowrap">{{ r.logId }}</td>
                <td class="muted nowrap">{{ r.eventId }}</td>
                <td class="nowrap">{{ r.car }}</td>
                <td class="nowrap"><StatusTag :tone="actionTone(r.actionType)">{{ r.actionType }}</StatusTag></td>
                <td class="muted nowrap">{{ r.handler }}</td>
                <td class="muted nowrap">{{ r.time }}</td>
                <td class="muted" :style="{ minWidth: `${MEMO_MIN_WIDTH}px` }">{{ r.memo }}</td>
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
      </section>

      <div class="side-col">
        <section class="panel summary-panel">
          <h3>이력 요약</h3>
          <div class="summary-grid">
            <div v-for="s in SUMMARY" :key="s.label" class="summary-card">
              <div class="summary-head">
                <span class="summary-icon" :class="`tone-${s.tone}`">
                  <component :is="s.icon" :size="16" />
                </span>
                <p class="summary-label">{{ s.label }}</p>
              </div>
              <p class="summary-value">{{ s.value }}<span class="summary-unit">건</span></p>
            </div>
          </div>
        </section>

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
                    <span class="timeline-time">{{ entry.time.split(' ')[1] }}</span>
                    <span class="timeline-title">{{ entry.handler }}가 {{ entry.eventId }} 사건을 {{ entry.actionType }}</span>
                  </p>
                  <p class="timeline-desc">{{ entry.memo }}</p>
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
  width: 176px;
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

.table-scroll {
  overflow-x: auto;
}

table {
  width: 100%;
  table-layout: auto;
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
}

.row:last-child {
  border-bottom: none;
}

.strong {
  font-weight: 600;
}

.muted {
  color: var(--panel-muted-foreground);
}

.nowrap {
  white-space: nowrap;
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

.side-col {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

.summary-panel,
.timeline-panel {
  padding: var(--spacing-lg);
}

.summary-panel h3 {
  margin-bottom: var(--spacing-md);
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-md);
}

.summary-card {
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-md);
}

.summary-head {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.summary-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
}

.summary-icon.tone-info {
  background: var(--panel-info-soft);
  color: var(--panel-info);
}

.summary-icon.tone-primary {
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
}

.summary-icon.tone-success {
  background: var(--panel-success-soft);
  color: var(--panel-success);
}

.summary-label {
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.summary-value {
  margin-top: var(--spacing-sm);
  font-size: var(--font-size-xl);
  font-weight: 800;
}

.summary-unit {
  margin-left: 4px;
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--panel-muted-foreground);
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
