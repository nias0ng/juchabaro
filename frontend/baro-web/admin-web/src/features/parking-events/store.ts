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
import { useAuthStore } from '@/stores/auth-store';

function requireAccessToken(): string {
  const accessToken = useAuthStore().accessToken;
  if (!accessToken) throw new Error('로그인이 필요합니다.');
  return accessToken;
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

  function setSelectedEventId(eventId: number | null) {
    selectedEventId.value = eventId;
  }

  function patchEventSummary(eventId: number, patch: Partial<AdminEventSummary>) {
    events.value = events.value.map((row) => (row.eventId === eventId ? { ...row, ...patch } : row));
  }

  async function fetchEvents(params: AdminEventListParams = {}): Promise<void> {
    eventsLoading.value = true;
    eventsError.value = null;
    try {
      const result = await getParkingEvents(params, requireAccessToken());
      events.value = result.events;
      if (selectedEventId.value === null && result.events.length > 0) {
        selectedEventId.value = result.events[0]!.eventId;
      }
    } catch (error) {
      eventsError.value = error instanceof Error ? error.message : '사건 목록을 불러오지 못했습니다.';
    } finally {
      eventsLoading.value = false;
    }
  }

  async function fetchEventDetail(eventId: number): Promise<void> {
    detailLoading[eventId] = true;
    detailError[eventId] = null;
    try {
      eventDetails[eventId] = await getEventDetail(eventId, requireAccessToken());
    } catch (error) {
      detailError[eventId] = error instanceof Error ? error.message : '사건 상세를 불러오지 못했습니다.';
    } finally {
      detailLoading[eventId] = false;
    }
  }

  async function fetchHistory(params: AdminHistoryParams = {}): Promise<void> {
    historyLoading.value = true;
    historyError.value = null;
    try {
      const result = await getEventHistory(params, requireAccessToken());
      history.value = result.history;
    } catch (error) {
      historyError.value = error instanceof Error ? error.message : '처리 이력을 불러오지 못했습니다.';
    } finally {
      historyLoading.value = false;
    }
  }

  async function completeEvent(eventId: number, memo: string): Promise<void> {
    await completeEventRequest(eventId, { memo }, requireAccessToken());
    patchEventSummary(eventId, { eventStatus: 'RESOLVED' });
    await fetchEventDetail(eventId);
  }

  async function dismissEvent(eventId: number, memo: string): Promise<void> {
    await dismissEventRequest(eventId, { memo }, requireAccessToken());
    patchEventSummary(eventId, { eventStatus: 'DISMISSED' });
    await fetchEventDetail(eventId);
  }

  async function acknowledgeEvent(eventId: number, memo: string): Promise<void> {
    await acknowledgeEventRequest(eventId, { memo }, requireAccessToken());
    // 상태는 바뀌지 않고 처리 이력에만 기록되므로 상세만 다시 불러온다.
    await fetchEventDetail(eventId);
  }

  async function sendReminder(eventId: number): Promise<void> {
    await sendReminderRequest(eventId, requireAccessToken());
    await fetchEventDetail(eventId);
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
