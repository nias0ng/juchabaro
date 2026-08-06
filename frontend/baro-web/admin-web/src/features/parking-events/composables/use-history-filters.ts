import { computed, ref, watch } from 'vue';

import { useAutoRefresh } from '@/composables/use-auto-refresh';
import { useClientPagination } from '@/composables/use-client-pagination';
import { downloadCsv } from '@/composables/use-csv-export';
import type { AdminHistoryItem } from '@/features/parking-events/api/types';
import { actionTypeLabel, formatDateTime, localDateString, todayDateString } from '@/features/parking-events/data';
import { useParkingEventStore } from '@/features/parking-events/store';

const PAGE_SIZE = 10;
const FETCH_SIZE = 200;

export function useHistoryFilters() {
  const parkingEventStore = useParkingEventStore();

  const dateRange = ref({ start: todayDateString(), end: todayDateString() });
  const query = ref('');

  function loadHistory(background = false) {
    return parkingEventStore.fetchHistory({
      startDate: dateRange.value.start,
      endDate: dateRange.value.end,
      size: FETCH_SIZE,
    }, { background });
  }

  const filteredRows = computed(() => {
    const q = query.value.trim().replaceAll(' ', '').toUpperCase();
    if (!q) return parkingEventStore.history;
    return parkingEventStore.history.filter((r) => {
      const car = r.plateNumber.replaceAll(' ', '').toUpperCase();
      const eventId = `#${r.eventId}`.toUpperCase();
      return car.includes(q) || eventId.includes(q);
    });
  });

  const { page, totalPages, safePage, pagedRows, rangeStart, rangeEnd, resetPage } = useClientPagination(
    filteredRows,
    PAGE_SIZE,
  );

  watch(dateRange, () => {
    resetPage();
    void loadHistory();
  }, { immediate: true, deep: true });

  useAutoRefresh(() => loadHistory(true), 30_000);

  // 활동 타임라인은 '더 보기'로 일부만 보여주는 대신, 오늘 하루치 전체를 최신순으로
  // 보여주고 넘치는 만큼은 스크롤로 본다. 조회 기간과 무관하게 항상 실제 오늘 기준이다.
  const todayTimeline = computed(() =>
    parkingEventStore.history.filter((entry) => localDateString(entry.actedAt) === todayDateString()),
  );

  function exportCsv() {
    const headers = ['로그 ID', '사건 ID', '차량 번호', '처리 유형', '처리자', '처리 시간', '메모'];
    const rows = filteredRows.value.map((r: AdminHistoryItem) => [
      `#L-${r.logId}`,
      `#${r.eventId}`,
      r.plateNumber,
      actionTypeLabel(r.actionType),
      r.adminName,
      // 처리 시간 앞에 작은따옴표를 붙이면 엑셀이 이 칸(날짜가 포함된 문자열)을 날짜로
      // 자동 변환하지 않고 텍스트 그대로 표시한다.
      `'${formatDateTime(r.actedAt)}`,
      r.memo ?? '',
    ]);
    const startStamp = dateRange.value.start.replaceAll('-', '');
    const endStamp = dateRange.value.end.replaceAll('-', '');
    const stamp = startStamp === endStamp ? startStamp : `${startStamp}-${endStamp}`;
    downloadCsv(`이력_${stamp}.csv`, headers, rows);
  }

  return {
    dateRange,
    query,
    filteredRows,
    page,
    totalPages,
    safePage,
    pagedRows,
    rangeStart,
    rangeEnd,
    todayTimeline,
    exportCsv,
  };
}
