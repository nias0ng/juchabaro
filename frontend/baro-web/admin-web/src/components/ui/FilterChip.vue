<script setup lang="ts">
// ParkingEventListView/HistoryView/ParkingZoneManagementView가 동일하게 구현하던 필터 칩
// 버튼(드롭다운 트리거 또는 단순 토글)을 공용으로 뺐다. 드롭다운 본문은 화면마다 완전히
// 달라서(옵션 목록/단일 날짜/기간) 여기서는 트리거 버튼만 맡고 내용은 슬롯으로 받는다.
withDefaults(defineProps<{ active?: boolean }>(), { active: false })

const emit = defineEmits<{ click: [] }>()
</script>

<template>
  <button type="button" class="chip" :class="{ active }" @click="emit('click')">
    <slot />
  </button>
</template>

<style scoped>
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
</style>
