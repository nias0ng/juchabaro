<script setup lang="ts">
import AppPagination from '@/components/ui/AppPagination.vue'

// ParkingEventListView/HistoryView가 동일하게 구현하던 "전체 N건 중 X-Y 표시" 문구 +
// 페이지네이션 wrapper를 공용 컴포넌트로 뺐다.
defineProps<{
  total: number
  rangeStart: number
  rangeEnd: number
  page: number
  totalPages: number
}>()

const emit = defineEmits<{ pageChange: [page: number] }>()
</script>

<template>
  <div class="footer">
    <span>전체 {{ total }}건 중 {{ rangeStart }}-{{ rangeEnd }} 표시</span>
    <div class="pagination-wrap">
      <AppPagination :page="page" :total-pages="totalPages" @page-change="emit('pageChange', $event)" />
    </div>
  </div>
</template>

<style scoped>
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
</style>
