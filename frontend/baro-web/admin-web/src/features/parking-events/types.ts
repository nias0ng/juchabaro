export type { ActionType, AdminEventDetail, AdminEventSummary, AdminHistoryItem, EventStatus, EventType, RequestType } from './api/types';

// EventTimeline이 감지·요청·응답·재알림 등 여러 출처의 시각을 한 줄로 합쳐 보여주기 위한 화면 전용 타입.
export type TimelineEntry = {
  t: string;
  d: string;
  time: string;
};
