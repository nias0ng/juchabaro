import type { MoveEventType } from '@/features/move-request/api/types';

export type ViolationStats = {
  totalCount: number;
  unresolvedCount: number;
  averageResponseMinutes: number;
};

export type ViolationStatus = 'UNRESOLVED' | 'RESOLVED';

export type ViolationHistoryItem = {
  requestId: number;
  type: MoveEventType;
  title: string;
  /** 날짜·구역처럼 짧게 붙여 보여주는 메타 정보. */
  meta: string;
  /** "관리사무소 전달"처럼 길어질 수 있는 처리 상태 설명 — meta와 줄을 분리해서 보여준다. */
  statusDescription: string;
  status: ViolationStatus;
  monthLabel: string;
};
