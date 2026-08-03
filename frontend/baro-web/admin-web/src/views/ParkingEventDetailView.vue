<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ArrowLeft } from '@lucide/vue'

import AppShell from '@/components/layout/AppShell.vue'
import PageHeading from '@/components/ui/PageHeading.vue'
import EventDetailCard from '@/features/parking-events/components/EventDetailCard.vue'
import EventTimeline from '@/features/parking-events/components/EventTimeline.vue'

const route = useRoute()
const eventId = computed(() => route.params.eventId as string)
</script>

<template>
  <AppShell title="사건 상세" breadcrumb="실시간 주차 관제 현황">
    <RouterLink to="/events" class="back-link">
      <ArrowLeft :size="16" /> 사건 목록으로
    </RouterLink>

    <PageHeading :title="`사건 상세 (#${eventId})`" />

    <div class="layout">
      <section class="panel detail-panel">
        <EventDetailCard :event-id="eventId ?? ''" />
      </section>

      <section class="panel timeline-panel">
        <h3>사건 진행 이력</h3>
        <EventTimeline :event-id="eventId ?? ''" />
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

.timeline-panel h3 {
  margin-bottom: var(--spacing-md);
  font-size: var(--font-size-lg);
  font-weight: 700;
}
</style>
