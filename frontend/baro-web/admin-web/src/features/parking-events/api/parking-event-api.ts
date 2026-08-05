import { getJson, postJson } from '@/services/http-client';

import type {
  AdminActionRequest,
  AdminEventDetail,
  AdminEventListParams,
  AdminEventListResult,
  AdminHistoryParams,
  AdminHistoryResult,
} from './types';

function toQueryString(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, value]) => value !== undefined && value !== '');
  if (entries.length === 0) return '';
  const search = new URLSearchParams(entries.map(([key, value]) => [key, String(value)]));
  return `?${search.toString()}`;
}

export function getParkingEvents(params: AdminEventListParams, accessToken: string): Promise<AdminEventListResult> {
  return getJson<AdminEventListResult>(`/api/admin/parking-events${toQueryString(params)}`, accessToken);
}

export function getEventHistory(params: AdminHistoryParams, accessToken: string): Promise<AdminHistoryResult> {
  return getJson<AdminHistoryResult>(`/api/admin/parking-events/history${toQueryString(params)}`, accessToken);
}

export function getEventDetail(eventId: number, accessToken: string): Promise<AdminEventDetail> {
  return getJson<AdminEventDetail>(`/api/admin/parking-events/${eventId}`, accessToken);
}

export function completeEvent(eventId: number, request: AdminActionRequest, accessToken: string): Promise<null> {
  return postJson<null>(`/api/admin/parking-events/${eventId}/complete`, request, accessToken);
}

// 재알림은 body가 없다 (연결된 이동요청이 없으면 백엔드가 409로 응답한다).
export function sendReminder(eventId: number, accessToken: string): Promise<null> {
  return postJson<null>(`/api/admin/parking-events/${eventId}/reminders`, undefined, accessToken);
}

// 오탐 처리는 단방향 확정이라 다시 눌러 취소할 수 없다.
export function dismissEvent(eventId: number, request: AdminActionRequest, accessToken: string): Promise<null> {
  return postJson<null>(`/api/admin/parking-events/${eventId}/dismiss`, request, accessToken);
}

export function acknowledgeEvent(eventId: number, request: AdminActionRequest, accessToken: string): Promise<null> {
  return postJson<null>(`/api/admin/parking-events/${eventId}/acknowledge`, request, accessToken);
}
