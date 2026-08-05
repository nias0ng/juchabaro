import { useMemo } from 'react';

import { useMoveRequests } from '@/features/move-request/hooks/use-move-requests';

import { toViolationHistoryItem } from '../utils/violation-history';

export function useViolationHistory() {
  const { moveRequests, isLoading, error } = useMoveRequests('RECEIVED');
  const violations = useMemo(
    () => moveRequests.map(toViolationHistoryItem),
    [moveRequests],
  );

  return {
    violations,
    isLoading,
    error,
  };
}
