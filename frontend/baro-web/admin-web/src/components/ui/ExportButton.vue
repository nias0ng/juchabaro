<script setup lang="ts">
import { Download } from '@lucide/vue'

// ParkingEventListView/HistoryView가 바이트 단위로 동일하게 구현하던 CSV 내보내기
// 버튼을 공용으로 뺐다.
const emit = defineEmits<{ click: [] }>()
</script>

<template>
  <button type="button" class="export-btn" @click="emit('click')">
    <Download :size="16" /> 내보내기
  </button>
</template>

<style scoped>
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
</style>
