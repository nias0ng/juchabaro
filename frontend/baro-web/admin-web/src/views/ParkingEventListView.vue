<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronDown, Download, Search, Send } from '@lucide/vue'

import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import AppPagination from '@/components/ui/AppPagination.vue'
import {
  EVENT_ROWS,
  STATUS_OPTIONS,
  TYPE_OPTIONS,
  formatDate,
  normalizeEventId,
  statusTone,
  typeTone,
} from '@/features/parking-events/data'
import { INITIAL_TIMELINE, useParkingEventStore } from '@/features/parking-events/store'
import type { EventRow } from '@/features/parking-events/types'

const PAGE_SIZE = 10

function exportRowsToCsv(rows: EventRow[], dateFilter: string) {
  const headers = ['ID', '차량 번호', '유형', '위치', '발생 시간', 'AI 신뢰도', '상태', '날짜']
  const escapeCsv = (value: string) => `"${value.replaceAll('"', '""')}"`
  const lines = [
    headers.map(escapeCsv).join(','),
    ...rows.map((r) => [r.id, r.car, r.type, r.loc, r.time, r.ai, r.st, r.date].map(escapeCsv).join(',')),
  ]
  // Excel에서 한글이 깨지지 않도록 UTF-8 BOM을 앞에 붙인다.
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  // 파일명에는 실제 오늘 날짜가 아니라, 목록에 적용된 날짜 필터(당일 기준)를 그대로 쓴다.
  const stamp = dateFilter.replaceAll('-', '')

  const link = document.createElement('a')
  link.href = url
  link.download = `사건_목록_${stamp}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

type DropdownName = 'status' | 'type' | 'date'

const statusFilter = ref<string | null>(null)
const typeFilter = ref<string | null>(null)
const dateFilter = ref('2026-07-22')
const carQuery = ref('')
const openDropdown = ref<DropdownName | null>(null)
const page = ref(1)

const parkingEventStore = useParkingEventStore()

const filterBarRef = ref<HTMLElement | null>(null)

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

const selectedRow = computed(
  () => EVENT_ROWS.find((r) => r.id === parkingEventStore.selectedId) ?? EVENT_ROWS[0]!,
)
const displayedType = computed(() =>
  parkingEventStore.oTamIds[normalizeEventId(selectedRow.value.id)] ? '오탐' : selectedRow.value.type,
)
const timeline = computed(
  () => parkingEventStore.timelines[normalizeEventId(selectedRow.value.id)] ?? INITIAL_TIMELINE,
)

const filteredRows = computed(() => {
  const query = carQuery.value.trim().replaceAll(' ', '')
  return EVENT_ROWS.filter((r) => {
    if (statusFilter.value && r.st !== statusFilter.value) return false
    if (typeFilter.value && r.type !== typeFilter.value) return false
    if (dateFilter.value && r.date !== dateFilter.value) return false
    if (query && !r.car.replaceAll(' ', '').includes(query)) return false
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

const detailFields = computed(
  () =>
    [
      ['사건 ID', selectedRow.value.id],
      ['차량 번호', selectedRow.value.car],
      ['유형', displayedType.value],
      ['위치', selectedRow.value.loc],
      ['발생 시간', selectedRow.value.time],
      ['이동 요청', '10분 경과'],
      ['차주 응답', '응답 없음'],
    ] as [string, string][],
)

function handleResendClick(event: MouseEvent, id: string) {
  event.stopPropagation()
  parkingEventStore.resend(id)
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
              @click="toggleDropdown('status')"
            >
              {{ statusFilter ?? '전체 상태' }} <ChevronDown :size="14" />
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
                :key="opt"
                type="button"
                class="dropdown-item"
                :class="{ selected: statusFilter === opt }"
                @click="statusFilter = opt; openDropdown = null"
              >
                {{ opt }}
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
            <button type="button" class="chip" @click="toggleDropdown('date')">
              {{ formatDate(dateFilter) }} <ChevronDown :size="14" />
            </button>
            <div v-if="openDropdown === 'date'" class="dropdown-menu date-menu">
              <input v-model="dateFilter" type="date">
            </div>
          </div>

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
                  <th v-for="h in ['ID', '차량 번호', '유형', '위치', '발생 시간', 'AI 신뢰도', '상태', '조치']" :key="h">
                    {{ h }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="pagedRows.length === 0">
                  <td colspan="8" class="empty">조건에 맞는 사건이 없습니다.</td>
                </tr>
                <tr
                  v-for="r in pagedRows"
                  v-else
                  :key="r.id"
                  class="row"
                  :class="{ selected: r.id === parkingEventStore.selectedId }"
                  @click="parkingEventStore.setSelectedId(r.id)"
                >
                  <td class="strong">{{ r.id }}</td>
                  <td class="nowrap">{{ r.car }}</td>
                  <td><StatusTag :tone="typeTone(r.type)">{{ r.type }}</StatusTag></td>
                  <td class="nowrap muted">{{ r.loc }}</td>
                  <td class="muted">{{ r.time }}</td>
                  <td class="muted">{{ r.ai }}</td>
                  <td><StatusTag :tone="statusTone(r.st)">{{ r.st }}</StatusTag></td>
                  <td>
                    <div class="row-actions">
                      <RouterLink :to="`/events/${normalizeEventId(r.id)}`" class="link-btn">상세 보기</RouterLink>
                      <button
                        type="button"
                        class="outline-btn"
                        :disabled="r.st === '완료' || Boolean(parkingEventStore.resentIds[normalizeEventId(r.id)])"
                        @click="handleResendClick($event, r.id)"
                      >
                        {{ parkingEventStore.resentIds[normalizeEventId(r.id)] ? '전송됨' : '재알림' }}
                      </button>
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
        <div class="detail-header">
          <h3>사건 상세</h3>
          <StatusTag :tone="statusTone(selectedRow.st)">{{ selectedRow.st }}</StatusTag>
        </div>
        <dl class="detail-list">
          <div v-for="[k, v] in detailFields" :key="k" class="detail-row">
            <dt>{{ k }}</dt>
            <dd>
              <StatusTag v-if="k === '유형'" :tone="typeTone(v)">{{ v }}</StatusTag>
              <template v-else>{{ v }}</template>
            </dd>
          </div>
        </dl>

        <div class="image-grid">
          <div v-for="label in ['번호판 이미지', '주차 상태 이미지']" :key="label" class="image-card">
            <p class="image-label">{{ label }}</p>
            <div class="image-placeholder">이미지 준비 중</div>
          </div>
        </div>

        <div class="actions">
          <button type="button" class="outline-btn" @click="parkingEventStore.markOtam(selectedRow.id)">오탐 처리</button>
          <button type="button" class="primary-btn" @click="parkingEventStore.resend(selectedRow.id)">
            <Send :size="16" /> 이동 요청 재전송
          </button>
        </div>

        <h4 class="timeline-title">사건 진행 이력</h4>
        <ol class="timeline">
          <li v-for="(t, i) in timeline" :key="`${t.t}-${i}`" class="timeline-item">
            <span class="timeline-dot-wrap">
              <span class="timeline-dot" :class="{ last: i === timeline.length - 1 }" />
              <span v-if="i < timeline.length - 1" class="timeline-line" />
            </span>
            <div class="timeline-body">
              <div class="timeline-head">
                <p class="timeline-t">{{ t.t }}</p>
                <span class="timeline-time">{{ t.time }}</span>
              </div>
              <p class="timeline-d">{{ t.d }}</p>
            </div>
          </li>
        </ol>
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
    grid-template-columns: minmax(0, 2.3fr) minmax(0, 1fr);
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
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  background: none;
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
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

.dropdown-menu.wide {
  width: 160px;
}

.dropdown-menu.date-menu {
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
  margin-left: auto;
  border: none;
  border-radius: var(--radius-md);
  background: var(--panel-primary);
  padding: var(--spacing-sm) var(--spacing-md);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--panel-on-primary);
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
  padding: var(--spacing-base);
  text-align: left;
  font-weight: 500;
  white-space: nowrap;
}

td {
  padding: var(--spacing-base);
}

.empty {
  padding: 40px var(--spacing-base);
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

.nowrap {
  white-space: nowrap;
}

.muted {
  color: var(--panel-muted-foreground);
}

.row-actions {
  display: flex;
  gap: var(--spacing-sm);
}

.link-btn,
.outline-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-sm);
  background: none;
  padding: 6px var(--spacing-base);
  font-size: 12px;
  font-weight: 500;
  color: inherit;
  text-decoration: none;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.link-btn:hover,
.outline-btn:hover:not(:disabled) {
  background: var(--panel-muted);
}

.outline-btn:disabled {
  opacity: 0.4;
  cursor: default;
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

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-md);
}

.detail-header h3 {
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.detail-list {
  font-size: var(--font-size-sm);
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--panel-border);
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-row dt {
  color: var(--panel-muted-foreground);
}

.detail-row dd {
  font-weight: 500;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-base);
  margin-top: 20px;
}

.image-card {
  overflow: hidden;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
}

.image-label {
  border-bottom: 1px solid var(--panel-border);
  background: var(--panel-muted);
  padding: 6px var(--spacing-sm);
  text-align: center;
  font-size: 12px;
  color: var(--panel-muted-foreground);
}

.image-placeholder {
  display: flex;
  height: 96px;
  align-items: center;
  justify-content: center;
  background: var(--panel-muted);
  font-size: 12px;
  color: var(--panel-muted-foreground);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  margin-top: 20px;
}

.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  border: none;
  border-radius: var(--radius-md);
  background: var(--panel-primary);
  padding: var(--spacing-sm) var(--spacing-base);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--panel-on-primary);
  box-shadow: var(--panel-shadow-pop);
  cursor: pointer;
}

.timeline-title {
  margin-bottom: var(--spacing-base);
  margin-top: 28px;
  font-weight: 700;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.timeline-item {
  display: flex;
  gap: var(--spacing-base);
}

.timeline-dot-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 4px;
}

.timeline-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--panel-muted-foreground);
}

.timeline-dot.last {
  border-color: var(--panel-primary);
}

.timeline-line {
  margin-top: 4px;
  width: 1px;
  height: 32px;
  background: var(--panel-border);
}

.timeline-body {
  flex: 1;
}

.timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.timeline-t {
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.timeline-time {
  font-size: 12px;
  color: var(--panel-muted-foreground);
}

.timeline-d {
  font-size: 12px;
  color: var(--panel-muted-foreground);
}
</style>
