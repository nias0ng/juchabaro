<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CheckCircle2, Eye } from '@lucide/vue'

import StatusTag from '@/components/ui/StatusTag.vue'
import {
  eventStatusLabel,
  eventTypeLabel,
  formatDateTime,
  formatEventId,
  requestStatusDescription,
  statusTone,
  typeTone,
} from '@/features/parking-events/data'
import { useParkingEventStore } from '@/features/parking-events/store'

// 사건 목록(아래쪽 "사건 상세" 패널)과 사건 상세 페이지가 완전히 동일한 내용(상태 배지,
// 필드 목록, 이미지, 관리자 확인 내용, 처리 메모 입력/이력)을 보여줘야 해서 공통 컴포넌트로 뺐다.
const props = defineProps<{ eventId: number }>()

const parkingEventStore = useParkingEventStore()

const detail = computed(() => parkingEventStore.eventDetails[props.eventId])
const loading = computed(() => Boolean(parkingEventStore.detailLoading[props.eventId]))
const loadError = computed(() => parkingEventStore.detailError[props.eventId] ?? null)

function load() {
  void parkingEventStore.fetchEventDetail(props.eventId)
}

watch(() => props.eventId, load, { immediate: true })

const isResolved = computed(() => detail.value?.eventStatus === 'RESOLVED')
const isDismissed = computed(() => detail.value?.eventStatus === 'DISMISSED')
// 완료·오탐은 둘 다 종결 상태라 그 이후로는 추가 처리를 할 수 없다.
const isTerminal = computed(() => isResolved.value || isDismissed.value)

const latestResponse = computed(() => {
  const responses = detail.value?.responses ?? []
  return responses.length > 0 ? responses[responses.length - 1] : null
})

const detailFields = computed(() => {
  if (!detail.value) return [] as [string, string][]
  const d = detail.value
  const location = [d.floor, d.zoneNumber].filter(Boolean).join(' ')
  return [
    ['사건 ID', formatEventId(d.eventId)],
    ['차량 번호', d.plateNumber],
    ['유형', eventTypeLabel(d.eventType)],
    ['위치', location || '-'],
    ['발생 시간', formatDateTime(d.detectedAt)],
    ['이동 요청', d.requestedAt ? `${formatDateTime(d.requestedAt)} (알림 ${d.reminderCount ?? 0}회)` : '이동 요청 없음'],
    ['차주 응답', latestResponse.value ? latestResponse.value.responseType : '응답 없음'],
  ] as [string, string][]
})

const memoText = ref('')
const actionError = ref<string | null>(null)
const submitting = ref<'complete' | 'acknowledge' | null>(null)

// 다른 사건으로 바뀌면(선택 행 변경, 라우트 파라미터 변경 등) 이전에 쓰던 메모나 에러가 새
// 사건에 잘못 남지 않도록 비운다.
watch(
  () => props.eventId,
  () => {
    memoText.value = ''
    actionError.value = null
  },
)

// 최신 처리 이력이 먼저 보이도록 정렬한다(백엔드가 순서를 보장하지 않음).
const sortedActionLogs = computed(() =>
  [...(detail.value?.actionLogs ?? [])].sort((a, b) => (a.actedAt < b.actedAt ? 1 : -1)),
)

async function runAction(kind: 'complete' | 'acknowledge', run: () => Promise<void>) {
  submitting.value = kind
  actionError.value = null
  try {
    await run()
    memoText.value = ''
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '처리에 실패했습니다.'
  } finally {
    submitting.value = null
  }
}

function handleCompleteClick() {
  const memo = memoText.value.trim()
  if (!memo) return
  void runAction('complete', () => parkingEventStore.completeEvent(props.eventId, memo))
}

function handleAcknowledgeClick() {
  const memo = memoText.value.trim()
  if (!memo) return
  void runAction('acknowledge', () => parkingEventStore.acknowledgeEvent(props.eventId, memo))
}
</script>

<template>
  <div class="detail-header">
    <h3>사건 상세</h3>
    <StatusTag :tone="detail ? statusTone(detail.eventStatus) : 'neutral'">
      {{ detail ? eventStatusLabel(detail.eventStatus, detail.requestType) : '-' }}
    </StatusTag>
  </div>

  <p v-if="loading" class="state-text">불러오는 중입니다…</p>
  <div v-else-if="loadError" class="state-text error">
    {{ loadError }}
    <button type="button" class="retry-btn" @click="load">다시 시도</button>
  </div>

  <template v-else-if="detail">
    <dl class="detail-list">
      <div v-for="[k, v] in detailFields" :key="k" class="detail-row">
        <dt>{{ k }}</dt>
        <dd>
          <StatusTag v-if="k === '유형'" :tone="typeTone(detail.eventType)">{{ v }}</StatusTag>
          <template v-else>{{ v }}</template>
        </dd>
      </div>
    </dl>

    <div class="image-grid">
      <div v-if="detail.images.length === 0" class="image-card">
        <p class="image-label">증거 이미지</p>
        <div class="image-placeholder">등록된 이미지가 없습니다</div>
      </div>
      <div v-for="image in detail.images" :key="image.imageId" class="image-card">
        <p class="image-label">{{ formatDateTime(image.capturedAt) }}</p>
        <img class="image-photo" :src="image.imageUrl" alt="증거 이미지">
      </div>
    </div>

    <hr class="divider">

    <div class="admin-check-section">
      <p class="admin-check-label">관리자 확인 내용</p>
      <p class="admin-check-value">{{ requestStatusDescription(detail.requestStatus) }}</p>
    </div>

    <div class="memo-section">
      <label class="memo-label" :for="`event-memo-${eventId}`">처리 메모</label>
      <textarea
        :id="`event-memo-${eventId}`"
        v-model="memoText"
        class="memo-input"
        rows="2"
        placeholder="완료 처리, 오탐 처리 또는 관리자 확인 사유를 입력하세요."
      />
      <p v-if="actionError" class="action-error">{{ actionError }}</p>
      <div class="memo-actions">
        <button
          type="button"
          class="outline-btn"
          :disabled="isTerminal || !memoText.trim() || submitting !== null"
          @click="handleAcknowledgeClick"
        >
          <Eye :size="16" /> 관리자 확인
        </button>
        <button
          type="button"
          class="primary-btn"
          :disabled="isTerminal || !memoText.trim() || submitting !== null"
          @click="handleCompleteClick"
        >
          <CheckCircle2 :size="16" /> {{ isResolved ? '완료됨' : '완료 처리' }}
        </button>
      </div>

      <ul v-if="sortedActionLogs.length" class="memo-log">
        <li v-for="entry in sortedActionLogs" :key="entry.logId" class="memo-log-item">
          <div class="memo-log-head">
            <StatusTag tone="primary">{{ entry.actionType }}</StatusTag>
            <span class="memo-log-time">{{ formatDateTime(entry.actedAt) }}</span>
          </div>
          <p class="memo-log-text">{{ entry.memo || '-' }} · {{ entry.adminName }}</p>
        </li>
      </ul>
    </div>
  </template>
</template>

<style scoped>
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

.state-text {
  padding: var(--spacing-md) 0;
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
}

.state-text.error {
  color: var(--panel-danger);
}

.retry-btn {
  margin-left: var(--spacing-sm);
  border: none;
  background: none;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--panel-primary);
  text-decoration: underline;
  cursor: pointer;
}

.detail-list {
  font-size: var(--font-size-sm);
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-base);
  padding: 10px 0;
  border-bottom: 1px solid var(--panel-border);
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-row dt {
  flex-shrink: 0;
  color: var(--panel-muted-foreground);
}

.detail-row dd {
  text-align: right;
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

.image-photo {
  display: block;
  width: 100%;
  height: 128px;
  object-fit: cover;
}

.divider {
  margin: 20px 0 0;
  border: none;
  border-top: 1px solid var(--panel-border);
}

.admin-check-section {
  margin-top: var(--spacing-base);
}

.admin-check-label {
  margin-bottom: 4px;
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.admin-check-value {
  font-size: var(--font-size-sm);
  color: var(--panel-muted-foreground);
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

.action-error {
  margin-top: var(--spacing-sm);
  font-size: 12px;
  color: var(--panel-danger);
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
</style>
