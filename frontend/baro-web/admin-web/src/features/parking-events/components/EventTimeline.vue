<script setup lang="ts">
import { computed } from 'vue'

import { normalizeEventId } from '@/features/parking-events/data'
import { INITIAL_TIMELINE, useParkingEventStore } from '@/features/parking-events/store'

// 사건 목록의 "사건 진행 이력"과 사건 상세 페이지의 "사건 진행 이력"이 완전히 같은
// 목록을 보여줘야 해서 공통 컴포넌트로 뺐다. 제목(h3/h4)은 화면마다 배치가 달라
// 이 컴포넌트에 넣지 않고 호출하는 쪽에서 그린다.
const props = defineProps<{ eventId: string }>()

const parkingEventStore = useParkingEventStore()

const timeline = computed(
  () => parkingEventStore.timelines[normalizeEventId(props.eventId)] ?? INITIAL_TIMELINE,
)
</script>

<template>
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
</template>

<style scoped>
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
