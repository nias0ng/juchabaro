<script setup lang="ts">
import { computed } from 'vue';
import { ChevronLeft, ChevronRight } from '@lucide/vue';

const props = defineProps<{
  page: number;
  totalPages: number;
}>();

const emit = defineEmits<{
  pageChange: [page: number];
}>();

// 페이지가 많을 때 1 2 … 현재-1 현재 현재+1 … 마지막 형태로 줄여서 보여준다.
function getPageItems(page: number, totalPages: number): Array<number | '…'> {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const keep = new Set([1, 2, totalPages - 1, totalPages, page - 1, page, page + 1]);
  const items: Array<number | '…'> = [];
  let prev = 0;
  for (let p = 1; p <= totalPages; p += 1) {
    if (!keep.has(p)) continue;
    if (prev && p - prev > 1) items.push('…');
    items.push(p);
    prev = p;
  }
  return items;
}

const items = computed(() => getPageItems(props.page, Math.max(props.totalPages, 1)));
</script>

<template>
  <div class="pagination">
    <button
      type="button"
      aria-label="이전 페이지"
      :disabled="page <= 1"
      class="nav-btn"
      @click="emit('pageChange', page - 1)"
    >
      <ChevronLeft :size="16" />
    </button>

    <template v-for="(item, i) in items" :key="item === '…' ? `ellipsis-${i}` : item">
      <span v-if="item === '…'" class="ellipsis">…</span>
      <button
        v-else
        type="button"
        class="page-btn"
        :class="{ active: item === page }"
        :aria-current="item === page ? 'page' : undefined"
        @click="emit('pageChange', item)"
      >
        {{ item }}
      </button>
    </template>

    <button
      type="button"
      aria-label="다음 페이지"
      :disabled="page >= totalPages"
      class="nav-btn"
      @click="emit('pageChange', page + 1)"
    >
      <ChevronRight :size="16" />
    </button>
  </div>
</template>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  gap: var(--spacing-xxs);
}

.nav-btn,
.page-btn,
.ellipsis {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: var(--font-size-md);
  color: inherit;
}

.nav-btn,
.page-btn {
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.nav-btn:hover:not(:disabled),
.page-btn:hover:not(.active) {
  background: var(--panel-muted);
}

.nav-btn:disabled {
  pointer-events: none;
  opacity: 0.3;
}

.page-btn.active {
  background: var(--panel-primary);
  color: var(--panel-on-primary);
}

.ellipsis {
  color: var(--panel-muted-foreground);
  cursor: default;
}
</style>
