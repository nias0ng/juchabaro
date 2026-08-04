<script setup lang="ts">
import { computed } from 'vue'

import { actionTypeLabel, formatTime } from '@/features/parking-events/data'
import { useParkingEventStore } from '@/features/parking-events/store'
import type { TimelineEntry } from '@/features/parking-events/types'

// 사건 목록의 "사건 진행 이력"과 사건 상세 페이지의 "사건 진행 이력"이 완전히 같은
// 목록을 보여줘야 해서 공통 컴포넌트로 뺐다. 제목(h3/h4)은 화면마다 배치가 달라
// 이 컴포넌트에 넣지 않고 호출하는 쪽에서 그린다.
const props = defineProps<{ eventId: number }>()

const parkingEventStore = useParkingEventStore()

type RawEntry = { at: string; t: string; d: string }

// 사건 상세 응답에는 진행 이력이 하나의 배열로 오지 않고 감지 시각·이동요청 시각·차주
// 응답·관리자 처리 이력이 각각 다른 필드에 나뉘어 있다. 시각순으로 합쳐 하나의 타임라인으로
// 보여준다.
const timeline = computed<TimelineEntry[]>(() => {
  const detail = parkingEventStore.eventDetails[props.eventId]
  if (!detail) return []

  const entries: RawEntry[] = [{ at: detail.detectedAt, t: '감지됨', d: 'AI가 주차 사건을 감지했습니다.' }]

  if (detail.requestedAt) {
    entries.push({ at: detail.requestedAt, t: '요청 전송', d: '차주에게 이동 요청을 전송했습니다.' })
  }

  for (const response of detail.responses) {
    const minutes = response.estimatedMinutes !== null ? ` (예상 ${response.estimatedMinutes}분)` : ''
    entries.push({ at: response.respondedAt, t: '차주 응답', d: `${response.responseType}${minutes}` })
  }

  for (const log of detail.actionLogs) {
    entries.push({ at: log.actedAt, t: actionTypeLabel(log.actionType), d: `${log.adminName} · ${log.memo || '메모 없음'}` })
  }

  return entries
    .sort((a, b) => (a.at < b.at ? -1 : 1))
    .map((entry) => ({ t: entry.t, d: entry.d, time: formatTime(entry.at) }))
})
</script>

<template>
  <p v-if="timeline.length === 0" class="empty">진행 이력이 없습니다.</p>
  <ol v-else class="timeline">
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
</template>

<style scoped>
.empty {
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
