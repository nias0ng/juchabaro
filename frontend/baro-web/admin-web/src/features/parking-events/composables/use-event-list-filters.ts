import { computed, ref, watch } from 'vue';

import { useAutoRefresh } from '@/composables/use-auto-refresh';
import { useClientPagination } from '@/composables/use-client-pagination';
import { downloadCsv } from '@/composables/use-csv-export';
import type { AdminEventSummary, EventType, RequestType } from '@/features/parking-events/api/types';
import { eventStatusLabel, eventTypeLabel, formatTime, localDateString, requestTypeLabel, todayDateString } from '@/features/parking-events/data';
import { useParkingEventStore } from '@/features/parking-events/store';

const PAGE_SIZE = 10;
// 백엔드는 날짜/상태/유형으로만 필터링하고 차량 번호 검색은 지원하지 않는다. 선택한
// 조건에 맞는 사건을 넉넉히 받아온 뒤 차량 번호 검색과 페이지네이션은 화면에서 처리한다.
const FETCH_SIZE = 200;

// "전체 상태" 필터는 EventStatus 5개(감지됨/이동요청됨/관리자 확인 필요/완료/오탐 종결)를
// 그대로 다 보여주지 않는다 — 관리자가 실제로 구분해서 봐야 하는 건 이동요청이 자동/수동으로
// 걸렸는지, 그리고 완료됐는지 3가지뿐이다. 감지됨·관리자 확인 필요·오탐 종결 사건은 "전체"를
// 고르면 그대로 목록에 나오지만, 따로 골라보는 옵션은 없다. 백엔드 EventStatus 계약 자체는
// 바꾸지 않고, 프런트엔드에서 보여주는 옵션과 필터링 방식만 이렇게 재구성한다.
export type EventKindFilter = RequestType | 'RESOLVED';

export const EVENT_KIND_OPTIONS: EventKindFilter[] = ['AUTO', 'MANUAL', 'RESOLVED'];

export function eventKindLabel(kind: EventKindFilter): string {
  return kind === 'RESOLVED' ? eventStatusLabel('RESOLVED') : requestTypeLabel(kind);
}

export function useEventListFilters() {
  const parkingEventStore = useParkingEventStore();

  const statusFilter = ref<EventKindFilter | null>(null);
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
    // statusFilter가 'RESOLVED'면 그 상태를 그대로 서버에 보내고, 'AUTO'/'MANUAL'이면
    // 서버에는 'REQUESTED'로 요청한 뒤 아래 filteredRows에서 requestType으로 한 번 더
    // 걸러낸다(자동/수동은 EventStatus가 아니라 이동요청의 requestType이라 서버 쿼리
    // 파라미터로 직접 표현할 수 없다).
    const eventStatus = statusFilter.value === 'RESOLVED' ? 'RESOLVED' : statusFilter.value ? 'REQUESTED' : undefined;
    return parkingEventStore.fetchEvents({
      date: dateFilter.value ?? undefined,
      eventStatus,
      eventType: typeFilter.value ?? undefined,
      size: FETCH_SIZE,
    }, { background });
  }

  const filteredRows = computed(() => {
    const query = carQuery.value.trim().replaceAll(' ', '');
    let rows = parkingEventStore.events;
    if (statusFilter.value === 'AUTO' || statusFilter.value === 'MANUAL') {
      rows = rows.filter((r) => r.requestType === statusFilter.value);
    }
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
