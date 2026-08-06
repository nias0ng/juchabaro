import { computed, ref } from 'vue';
import type { ComputedRef, Ref } from 'vue';

// ParkingEventListView/HistoryView가 똑같이 구현하던 "필터링된 배열을 pageSize 단위로
// 잘라서 보여주기" 로직을 공용으로 뺐다. rows가 바뀌어 결과 수가 줄면 이미 지나간 페이지
// 번호가 남아있을 수 있어 safePage로 totalPages 안쪽으로 자른 값만 쓴다.
export function useClientPagination<T>(rows: Ref<T[]> | ComputedRef<T[]>, pageSize: number) {
  const page = ref(1);

  const totalPages = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize)));
  const safePage = computed(() => Math.min(page.value, totalPages.value));
  const pagedRows = computed(() => rows.value.slice((safePage.value - 1) * pageSize, safePage.value * pageSize));
  const rangeStart = computed(() => (rows.value.length === 0 ? 0 : (safePage.value - 1) * pageSize + 1));
  const rangeEnd = computed(() => Math.min(safePage.value * pageSize, rows.value.length));

  function resetPage(): void {
    page.value = 1;
  }

  return { page, totalPages, safePage, pagedRows, rangeStart, rangeEnd, resetPage };
}
