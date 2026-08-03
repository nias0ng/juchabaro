<script setup lang="ts">
import { HelpCircle } from '@lucide/vue';

defineProps<{ text: string }>();
</script>

<template>
  <span class="info-tooltip">
    <HelpCircle :size="14" class="icon" />
    <span class="bubble">{{ text }}</span>
  </span>
</template>

<style scoped>
/* 클릭 없이 마우스를 올리기만 해도 보이도록 상태 없이 CSS :hover만으로 구현한다. */
.info-tooltip {
  position: relative;
  display: inline-flex;
}

.icon {
  color: var(--panel-muted-foreground);
  cursor: help;
}

.bubble {
  position: absolute;
  bottom: 100%;
  left: 50%;
  z-index: 20;
  margin-bottom: var(--spacing-sm);
  width: 224px;
  transform: translateX(-50%);
  border-radius: var(--radius-sm);
  border: 1px solid var(--panel-border);
  background: var(--panel-card);
  padding: 10px;
  font-size: var(--font-size-sm);
  font-weight: 400;
  color: var(--panel-foreground);
  box-shadow: var(--panel-shadow-card);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s ease;
}

.info-tooltip:hover .bubble {
  opacity: 1;
}
</style>
