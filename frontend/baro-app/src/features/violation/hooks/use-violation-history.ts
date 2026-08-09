import { useMemo } from 'react';

import { useMoveRequests } from '@/features/move-request/hooks/use-move-requests';

import { toViolationHistoryItem } from '../utils/violation-history';

/** 받은 이동 요청 목록을 위반 내역 형태로 변환해 보여준다(전용 위반 API는 없음). */
export function useViolationHistory() {
  const { moveRequests, isLoading, isRefreshing, error, refetch } = useMoveRequests('RECEIVED');
  const violations = useMemo(
    () => moveRequests.map(toViolationHistoryItem),
    [moveRequests],
  );

  return {
    violations,
    isLoading,
    isRefreshing,
    error,
    refetch,
  };
}
