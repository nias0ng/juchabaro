<script setup lang="ts">
import { Search } from '@lucide/vue'

// ParkingEventListView/HistoryView/ParkingZoneManagementView가 동일하게 구현하던 검색창
// 마크업+스타일을 공용 컴포넌트로 뺐다. 화면마다 다른 입력창 폭만 prop으로 받는다.
withDefaults(defineProps<{ placeholder: string; inputWidth?: string }>(), {
  inputWidth: '128px',
})

const model = defineModel<string>({ required: true })
</script>

<template>
  <div class="search-box" :style="{ '--search-box-input-width': inputWidth }">
    <Search :size="16" />
    <input v-model="model" type="text" :placeholder="placeholder">
  </div>
</template>

<style scoped>
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
  width: var(--search-box-input-width, 128px);
  border: none;
  background: none;
  outline: none;
  color: inherit;
  font-size: var(--font-size-sm);
}
</style>
