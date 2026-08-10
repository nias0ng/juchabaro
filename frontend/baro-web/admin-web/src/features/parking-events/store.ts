import { defineStore } from 'pinia';
import { reactive, ref } from 'vue';

import {
  acknowledgeEvent as acknowledgeEventRequest,
  completeEvent as completeEventRequest,
  dismissEvent as dismissEventRequest,
  getEventDetail,
  getEventHistory,
  getParkingEvents,
  sendReminder as sendReminderRequest,
} from '@/features/parking-events/api/parking-event-api';
import type {
  AdminEventDetail,
  AdminEventListParams,
  AdminEventSummary,
  AdminHistoryItem,
  AdminHistoryParams,
} from '@/features/parking-events/api/types';
import { dateStringDaysAgo, localDateString, todayDateString } from '@/features/parking-events/data';
import { useAuthStore } from '@/stores/auth-store';

function requireAccessToken(): string {
  const accessToken = useAuthStore().accessToken;
  if (!accessToken) throw new Error('로그인이 필요합니다.');
  return accessToken;
}

// 날짜를 선택하지 않은 목록은 오늘을 포함한 최근 14개 달력 날짜를 대상으로 한다.
const RECENT_EVENT_DAY_COUNT = 14;

function isDateInRecentRange(iso: string, fromDate: string, toDate: string): boolean {
  const eventDate = localDateString(iso);
  return eventDate >= fromDate && eventDate <= toDate;
}

async function getRecentParkingEvents(
  params: AdminEventListParams,
  accessToken: string,
): Promise<AdminEventSummary[]> {
  const fromDate = dateStringDaysAgo(RECENT_EVENT_DAY_COUNT - 1);
  const toDate = todayDateString();
  const eventsById = new Map<number, AdminEventSummary>();
  let page = 0;

  while (true) {
    const result = await getParkingEvents({ ...params, date: undefined, page }, accessToken);

    for (const event of result.events) {
      if (isDateInRecentRange(event.detectedAt, fromDate, toDate)) {
        eventsById.set(event.eventId, event);
      }
    }

    const reachedBeforeRange = result.events.some(
      (event) => localDateString(event.detectedAt) < fromDate,
    );
    const isLastPage = result.events.length === 0 || page + 1 >= result.totalPages;
    if (reachedBeforeRange || isLastPage) break;

    page += 1;
  }

  return [...eventsById.values()].sort(
    (left, right) => new Date(right.detectedAt).getTime() - new Date(left.detectedAt).getTime(),
  );
}

// 사건 목록(ParkingEventListView)의 '사건 상세' 패널과 사건 상세 페이지(ParkingEventDetailView)가
// 같은 사건에 대해 목록·상세·처리 이력을 공유해야 해서 Pinia로 끌어올렸다.
export const useParkingEventStore = defineStore('parking-event', () => {
  const events = ref<AdminEventSummary[]>([]);
  const eventsLoading = ref(false);
  const eventsError = ref<string | null>(null);

  const selectedEventId = ref<number | null>(null);

  // eventId별로 따로 로딩·에러를 추적해야 목록 패널과 상세 페이지가 서로의 로딩 상태를
  // 덮어쓰지 않는다.
  const eventDetails = reactive<Record<number, AdminEventDetail>>({});
  const detailLoading = reactive<Record<number, boolean>>({});
  const detailError = reactive<Record<number, string | null>>({});

  const history = ref<AdminHistoryItem[]>([]);
  const historyLoading = ref(false);
  const historyError = ref<string | null>(null);
  let eventsRequestId = 0;
  let historyRequestId = 0;
  const detailRequestIds: Record<number, number> = {};

  function setSelectedEventId(eventId: number | null) {
    selectedEventId.value = eventId;
  }

  function patchEventSummary(eventId: number, patch: Partial<AdminEventSummary>) {
    events.value = events.value.map((row) => (row.eventId === eventId ? { ...row, ...patch } : row));
  }

  async function fetchEvents(
    params: AdminEventListParams = {},
    options: { background?: boolean } = {},
  ): Promise<void> {
    if (options.background && eventsLoading.value) return;
    const requestId = ++eventsRequestId;
    const showLoading = !options.background || events.value.length === 0;
    if (showLoading) eventsLoading.value = true;
    if (!options.background) eventsError.value = null;
    try {
      const accessToken = requireAccessToken();
      let found: AdminEventSummary[];

      if (params.date) {
        // 날짜를 직접 골랐으면 그 하루치만 조회한다(서버가 이미 detectedAt 내림차순으로 정렬해 줌).
        found = (await getParkingEvents(params, accessToken)).events;
      } else {
        // 날짜 미선택 시 최신순 페이지를 필요한 만큼만 읽어 최근 14일 전체 사건을 합친다.
        found = await getRecentParkingEvents(params, accessToken);
      }

      if (requestId !== eventsRequestId) return;
      events.value = found;
      eventsError.value = null;
      if (selectedEventId.value === null && found.length > 0) {
        selectedEventId.value = found[0]!.eventId;
      }
    } catch (error) {
      if (requestId === eventsRequestId && showLoading) {
        eventsError.value = error instanceof Error ? error.message : '사건 목록을 불러오지 못했습니다.';
      }
    } finally {
      if (requestId === eventsRequestId && showLoading) eventsLoading.value = false;
    }
  }

  async function fetchEventDetail(eventId: number, options: { background?: boolean } = {}): Promise<void> {
    if (options.background && detailLoading[eventId]) return;
    const requestId = (detailRequestIds[eventId] ?? 0) + 1;
    detailRequestIds[eventId] = requestId;
    const showLoading = !eventDetails[eventId];
    if (showLoading) detailLoading[eventId] = true;
    if (!options.background) detailError[eventId] = null;
    try {
      const result = await getEventDetail(eventId, requireAccessToken());
      if (detailRequestIds[eventId] === requestId) {
        eventDetails[eventId] = result;
        detailError[eventId] = null;
      }
    } catch (error) {
      if (detailRequestIds[eventId] === requestId && showLoading) {
        detailError[eventId] = error instanceof Error ? error.message : '사건 상세를 불러오지 못했습니다.';
      }
    } finally {
      if (detailRequestIds[eventId] === requestId && showLoading) detailLoading[eventId] = false;
    }
  }

  async function fetchHistory(
    params: AdminHistoryParams = {},
    options: { background?: boolean } = {},
  ): Promise<void> {
    if (options.background && historyLoading.value) return;
    const requestId = ++historyRequestId;
    const showLoading = !options.background || history.value.length === 0;
    if (showLoading) historyLoading.value = true;
    if (!options.background) historyError.value = null;
    try {
      const result = await getEventHistory(params, requireAccessToken());
      if (requestId === historyRequestId) {
        history.value = result.history;
        historyError.value = null;
      }
    } catch (error) {
      if (requestId === historyRequestId && showLoading) {
        historyError.value = error instanceof Error ? error.message : '처리 이력을 불러오지 못했습니다.';
      }
    } finally {
      if (requestId === historyRequestId && showLoading) historyLoading.value = false;
    }
  }

  async function completeEvent(eventId: number, memo: string): Promise<void> {
    await completeEventRequest(eventId, { memo }, requireAccessToken());
    patchEventSummary(eventId, { eventStatus: 'RESOLVED' });
    await fetchEventDetail(eventId, { background: true });
  }

  async function dismissEvent(eventId: number, memo: string): Promise<void> {
    await dismissEventRequest(eventId, { memo }, requireAccessToken());
    patchEventSummary(eventId, { eventStatus: 'DISMISSED' });
    await fetchEventDetail(eventId, { background: true });
  }

  async function acknowledgeEvent(eventId: number, memo: string): Promise<void> {
    await acknowledgeEventRequest(eventId, { memo }, requireAccessToken());
    // 상태는 바뀌지 않고 처리 이력에만 기록되므로 상세만 다시 불러온다.
    await fetchEventDetail(eventId, { background: true });
  }

  async function sendReminder(eventId: number): Promise<void> {
    await sendReminderRequest(eventId, requireAccessToken());
    await fetchEventDetail(eventId, { background: true });
  }

  return {
    events,
    eventsLoading,
    eventsError,
    selectedEventId,
    eventDetails,
    detailLoading,
    detailError,
    history,
    historyLoading,
    historyError,
    setSelectedEventId,
    fetchEvents,
    fetchEventDetail,
    fetchHistory,
    completeEvent,
    dismissEvent,
    acknowledgeEvent,
    sendReminder,
  };
});
