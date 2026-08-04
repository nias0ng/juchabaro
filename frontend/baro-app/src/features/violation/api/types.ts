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
  meta: string;
  status: ViolationStatus;
  monthLabel: string;
};
