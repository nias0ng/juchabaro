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
import { dateStringDaysAgo } from '@/features/parking-events/data';
import { useAuthStore } from '@/stores/auth-store';

function requireAccessToken(): string {
  const accessToken = useAuthStore().accessToken;
  if (!accessToken) throw new Error('로그인이 필요합니다.');
  return accessToken;
}

// 날짜 필터를 고르지 않았을 때, 오늘 데이터가 없으면 이 안쪽으로 하루씩 과거를 훑는다.
// 그래도 없으면 실제로 최근 사건이 없는 것으로 보고 빈 목록을 보여준다(무한정 훑지 않음).
const MAX_LOOKBACK_DAYS = 14;

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
        // 날짜를 안 골랐으면 오늘부터 하루씩 과거로 거슬러 올라가며 사건이 있는 가장 최근 날을 찾는다.
        found = [];
        for (let daysAgo = 0; daysAgo <= MAX_LOOKBACK_DAYS; daysAgo++) {
          const result = await getParkingEvents({ ...params, date: dateStringDaysAgo(daysAgo) }, accessToken);
          if (result.events.length > 0) {
            found = result.events;
            break;
          }
        }
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
