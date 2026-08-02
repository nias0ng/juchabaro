<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ArrowLeft, CheckCircle2, Eye, Send } from '@lucide/vue'

import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import StatusTag from '@/components/ui/StatusTag.vue'
import { findEventRow, normalizeEventId, statusTone, typeTone } from '@/features/parking-events/data'
import { INITIAL_TIMELINE, useParkingEventStore } from '@/features/parking-events/store'

const route = useRoute()
const eventId = computed(() => route.params.eventId as string)

const parkingEventStore = useParkingEventStore()

const row = computed(() => findEventRow(eventId.value ?? ''))
const key = computed(() => normalizeEventId(eventId.value ?? ''))
const displayedType = computed(() =>
  row.value ? (parkingEventStore.oTamIds[key.value] ? '오탐' : row.value.type) : '-',
)
const displayedStatus = computed(() =>
  parkingEventStore.completedIds[key.value] ? '완료' : (row.value?.st ?? '알 수 없음'),
)
const timeline = computed(() => parkingEventStore.timelines[key.value] ?? INITIAL_TIMELINE)

const detailFields = computed(
  () =>
    [
      ['사건 ID', `#${eventId.value}`],
      ['차량 번호', row.value?.car ?? '-'],
      ['유형', displayedType.value],
      ['위치', row.value?.loc ?? '-'],
      ['발생 시간', row.value?.time ?? '-'],
      ['이동 요청', '10분 경과'],
      ['차주 응답', '응답 없음'],
    ] as [string, string][],
)

// 완료 처리·관리자 확인은 사유(메모)를 직접 남겨야 하는 수동 개입이라 별도 입력창을 둔다.
const memoText = ref('')
const isCompleted = computed(() => displayedStatus.value === '완료')
const isReviewed = computed(() => Boolean(parkingEventStore.reviewedIds[key.value]))

// 이 사건에 남긴 완료 처리·관리자 확인 메모만 최신순으로 모아 보여준다(history는 이미
// 최신 항목이 앞에 오도록 쌓이므로 필터만 하면 순서가 그대로 유지된다).
const memoLog = computed(() =>
  parkingEventStore.history.filter(
    (entry) =>
      normalizeEventId(entry.eventId) === key.value &&
      (entry.actionType === '관리자 확인' || entry.actionType === '완료 처리'),
  ),
)

// 다른 사건으로 이동하면(라우트 파라미터만 바뀌어 컴포넌트가 재사용되는 경우 포함) 이전에
// 쓰던 메모가 새 사건에 잘못 제출되지 않도록 비운다.
watch(eventId, () => {
  memoText.value = ''
})

function handleCompleteClick() {
  const memo = memoText.value.trim()
  if (!memo) return
  parkingEventStore.completeEvent(eventId.value ?? '', memo)
  memoText.value = ''
}

function handleAcknowledgeClick() {
  const memo = memoText.value.trim()
  if (!memo) return
  parkingEventStore.acknowledgeEvent(eventId.value ?? '', memo)
  memoText.value = ''
}
</script>

<template>
  <AppShell title="사건 상세" breadcrumb="실시간 주차 관제 현황">
    <RouterLink to="/events" class="back-link">
      <ArrowLeft :size="16" /> 사건 목록으로
    </RouterLink>

    <PageHeading :title="`사건 상세 (#${eventId})`" />

    <div class="layout">
      <section class="panel detail-panel">
        <div class="detail-header">
          <h3>사건 상세</h3>
          <StatusTag :tone="row ? statusTone(displayedStatus) : 'neutral'">{{ displayedStatus }}</StatusTag>
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
          <button
            type="button"
            class="outline-btn"
            :class="{ active: parkingEventStore.oTamIds[key] }"
            @click="parkingEventStore.markOtam(eventId ?? '')"
          >
            {{ parkingEventStore.oTamIds[key] ? '오탐 해제' : '오탐 처리' }}
          </button>
          <button type="button" class="primary-btn" @click="parkingEventStore.resend(eventId ?? '')">
            <Send :size="16" /> 이동 요청 재전송
          </button>
        </div>

        <div class="memo-section">
          <label class="memo-label" for="detail-memo">처리 메모</label>
          <textarea
            id="detail-memo"
            v-model="memoText"
            class="memo-input"
            rows="2"
            placeholder="완료 처리 또는 관리자 확인 사유를 입력하세요."
          />
          <div class="memo-actions">
            <button
              type="button"
              class="outline-btn"
              :disabled="isReviewed || !memoText.trim()"
              @click="handleAcknowledgeClick"
            >
              <Eye :size="16" /> {{ isReviewed ? '확인함' : '관리자 확인' }}
            </button>
            <button
              type="button"
              class="primary-btn"
              :disabled="isCompleted || !memoText.trim()"
              @click="handleCompleteClick"
            >
              <CheckCircle2 :size="16" /> {{ isCompleted ? '완료됨' : '완료 처리' }}
            </button>
          </div>

          <ul v-if="memoLog.length" class="memo-log">
            <li v-for="entry in memoLog" :key="entry.logId" class="memo-log-item">
              <div class="memo-log-head">
                <StatusTag tone="primary">{{ entry.actionType }}</StatusTag>
                <span class="memo-log-time">{{ entry.time }}</span>
              </div>
              <p class="memo-log-text">{{ entry.memo }}</p>
            </li>
          </ul>
        </div>
      </section>

      <section class="panel timeline-panel">
        <h3>사건 진행 이력</h3>
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
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 20px;
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
  text-decoration: none;
  transition: color 0.15s ease;
}

.back-link:hover {
  color: var(--panel-primary);
}

.layout {
  display: grid;
  gap: var(--spacing-lg);
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 1280px) {
  .layout {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
}

.detail-panel,
.timeline-panel {
  padding: var(--spacing-lg);
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-md);
}

.detail-header h3,
.timeline-panel h3 {
  font-size: var(--font-size-lg);
  font-weight: 700;
}

.timeline-panel h3 {
  margin-bottom: var(--spacing-md);
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
  height: 128px;
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

.outline-btn,
.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  flex-shrink: 0;
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
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

.outline-btn.active {
  border-color: color-mix(in oklch, var(--panel-primary) 40%, transparent);
  background: var(--panel-primary-soft);
  color: var(--panel-primary);
  font-weight: 600;
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

.memo-section {
  margin-top: 20px;
  border-top: 1px solid var(--panel-border);
  padding-top: var(--spacing-base);
}

.memo-label {
  display: block;
  margin-bottom: 6px;
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.memo-input {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
  font-family: inherit;
  font-size: var(--font-size-sm);
  color: inherit;
}

.memo-input:focus {
  outline: none;
  border-color: color-mix(in oklch, var(--panel-primary) 40%, transparent);
}

.memo-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);
}

.memo-log {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: var(--spacing-base) 0 0;
  padding: 0;
  list-style: none;
}

.memo-log-item {
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-base);
}

.memo-log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  margin-bottom: 4px;
}

.memo-log-time {
  font-size: 12px;
  color: var(--panel-muted-foreground);
}

.memo-log-text {
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  margin: 0;
  padding: 0;
  list-style: none;
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
