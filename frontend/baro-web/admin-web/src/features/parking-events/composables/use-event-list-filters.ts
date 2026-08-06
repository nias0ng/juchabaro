import { computed, ref, watch } from 'vue';

import { useAutoRefresh } from '@/composables/use-auto-refresh';
import { useClientPagination } from '@/composables/use-client-pagination';
import { downloadCsv } from '@/composables/use-csv-export';
import type { AdminEventSummary, EventStatus, EventType } from '@/features/parking-events/api/types';
import { eventStatusLabel, eventTypeLabel, formatTime, localDateString, todayDateString } from '@/features/parking-events/data';
import { useParkingEventStore } from '@/features/parking-events/store';

const PAGE_SIZE = 10;
// 백엔드는 날짜/상태/유형으로만 필터링하고 차량 번호 검색은 지원하지 않는다. 선택한
// 조건에 맞는 사건을 넉넉히 받아온 뒤 차량 번호 검색과 페이지네이션은 화면에서 처리한다.
const FETCH_SIZE = 200;

export function useEventListFilters() {
  const parkingEventStore = useParkingEventStore();

  const statusFilter = ref<EventStatus | null>(null);
  const typeFilter = ref<EventType | null>(null);
  // 날짜를 고르지 않으면(null) 전체 날짜를 최근 발생 순으로 보여준다.
  const dateFilter = ref<string | null>(null);
  const carQuery = ref('');
  // "관리자 확인 필요"는 사건 상태(eventStatus)가 아니라 이동요청 상태(requestStatus)에 실리는
  // 값이고, 목록 API 쿼리 파라미터에는 requestStatus 필터가 없어 서버에 요청할 수 없다. 그래서
  // 다른 필터와 달리 이미 받아온 목록을 filteredRows에서 화면단에서 걸러내는 방식으로 둔다.
  const needAdminOnly = ref(false);

  function toggleNeedAdminOnly() {
    needAdminOnly.value = !needAdminOnly.value;
  }

  function loadEvents(background = false) {
    return parkingEventStore.fetchEvents({
      date: dateFilter.value ?? undefined,
      eventStatus: statusFilter.value ?? undefined,
      eventType: typeFilter.value ?? undefined,
      size: FETCH_SIZE,
    }, { background });
  }

  const filteredRows = computed(() => {
    const query = carQuery.value.trim().replaceAll(' ', '');
    let rows = parkingEventStore.events;
    if (query) rows = rows.filter((r) => r.plateNumber.replaceAll(' ', '').includes(query));
    if (needAdminOnly.value) rows = rows.filter((r) => r.requestStatus === 'NEED_ADMIN');
    return rows;
  });

  const { page, totalPages, safePage, pagedRows, rangeStart, rangeEnd, resetPage } = useClientPagination(
    filteredRows,
    PAGE_SIZE,
  );

  watch([dateFilter, statusFilter, typeFilter], () => {
    resetPage();
    void loadEvents();
  }, { immediate: true });

  useAutoRefresh(() => loadEvents(true), 15_000);

  function exportCsv() {
    const headers = ['ID', '차량 번호', '종류', '유형', '위치', '발생 시간', '날짜'];
    // 날짜를 선택하지 않았으면(전체 조회) 행마다 실제 발생 날짜를 넣고, 선택했으면 필터 날짜를 그대로 쓴다.
    // 날짜 앞에 작은따옴표를 붙이면 엑셀이 이 칸을 날짜로 자동 변환하지 않고 텍스트 그대로 표시한다.
    const rows = filteredRows.value.map((r: AdminEventSummary) => [
      `#${r.eventId}`,
      r.plateNumber,
      eventStatusLabel(r.eventStatus, r.requestType),
      eventTypeLabel(r.eventType),
      r.zoneNumber ?? '-',
      formatTime(r.detectedAt),
      `'${dateFilter.value ?? localDateString(r.detectedAt)}`,
    ]);
    const stamp = (dateFilter.value ?? todayDateString()).replaceAll('-', '');
    downloadCsv(`사건_목록_${stamp}.csv`, headers, rows);
  }

  return {
    statusFilter,
    typeFilter,
    dateFilter,
    carQuery,
    needAdminOnly,
    toggleNeedAdminOnly,
    filteredRows,
    page,
    totalPages,
    safePage,
    pagedRows,
    rangeStart,
    rangeEnd,
    exportCsv,
  };
}
