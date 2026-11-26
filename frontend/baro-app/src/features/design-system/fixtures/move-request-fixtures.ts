import type { RequestListItemDisplay } from '@/features/move-request/components/requests-list/request-list-card';
import type { RequestListStatus } from '@/features/move-request/components/requests-list/request-status-badge';
import type { RequestTimelineStep } from '@/features/move-request/utils/move-request';

export const STATUS_FIXTURES: RequestListStatus[] = ['RESPONDED', 'PENDING', 'REMINDER', 'ESCALATED', 'CLOSED'];

export const TIMELINE_DEFAULT: RequestTimelineStep[] = [
  { label: '요청 접수', detail: '14:30' },
  { label: '이동 진행', detail: '14:42' },
  { label: '이동 완료', detail: '14:55', isFinal: true },
];

export const TIMELINE_REMINDER: RequestTimelineStep[] = [
  { label: '이동 요청 전송', detail: '오후 2:30', tone: 'brand' },
  { label: '1차 재알림', detail: '오후 2:45 · 응답 없음', tone: 'warning' },
];

export const TIMELINE_OVERDUE: RequestTimelineStep[] = [
  { label: '요청 접수', detail: '14:30' },
  { label: '이동 예정 시간', detail: '오후 2:50 (20분)', tone: 'brand' },
  { label: '약속 시간 경과', detail: '15분 지남', tone: 'error' },
];

export const LIST_ITEM_PENDING: RequestListItemDisplay = {
  requestId: 1,
  status: 'PENDING',
  timestampLabel: '오늘 14:30',
  plateNumber: '12가 3456',
  situationLabel: '이중 주차 · B2 주차장',
};

export const LIST_ITEM_CLOSED: RequestListItemDisplay = {
  requestId: 2,
  status: 'CLOSED',
  timestampLabel: '어제 09:10',
  plateNumber: '34나 7890',
  situationLabel: '구역 외 주차',
  closedSummary: '25분 만에 이동 완료',
};
