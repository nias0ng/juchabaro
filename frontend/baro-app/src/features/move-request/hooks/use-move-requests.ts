import { useEffect, useState } from 'react';

import { getMoveRequestDetail, getMoveRequests } from '@/features/move-request/api/move-request-api';
import type {
  MoveRequestListItem,
  MoveRequestScope,
  MoveRequestSummary,
} from '@/features/move-request/api/types';
import { useAuth } from '@/providers/auth-provider';

// 목록 API에 없는 구역/응답시간/완료시각은 카드마다 상세 조회를 한 번씩 더 불러서 채운다.
// 목록 API 자체가 이 필드들을 내려주게 되면(zoneNumber/estimatedMinutes/resolvedAt) 이 부분은 지운다.
async function enrichWithDetail(summary: MoveRequestSummary, accessToken: string): Promise<MoveRequestListItem> {
  try {
    const detail = await getMoveRequestDetail(summary.requestId, accessToken);
    const latestResponse = detail.responses[detail.responses.length - 1] ?? null;
    const resolvedEntry = [...detail.history].reverse().find((item) => item.notificationType === 'EVENT_RESOLVED');

    return {
      ...summary,
      zoneNumber: detail.event.zoneNumber,
      estimatedMinutes: latestResponse?.estimatedMinutes ?? null,
      respondedAt: latestResponse?.respondedAt ?? null,
      resolvedAt: resolvedEntry?.sentAt ?? null,
    };
  } catch {
    // 카드 하나의 상세 조회가 실패해도 목록 전체를 비우지 않고, 그 카드만 요약 정보로 보여준다.
    return { ...summary, zoneNumber: null, estimatedMinutes: null, respondedAt: null, resolvedAt: null };
  }
}

export function useMoveRequests(scope: MoveRequestScope) {
  const { accessToken, status } = useAuth();
  const [moveRequests, setMoveRequests] = useState<MoveRequestListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken) {
      setMoveRequests([]);
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    getMoveRequests(scope, accessToken)
      .then(async (result) => {
        const items = await Promise.all(
          result.moveRequests.map((summary) => enrichWithDetail(summary, accessToken)),
        );
        if (isMounted) setMoveRequests(items);
      })
      .catch((requestError: unknown) => {
        if (!isMounted) return;
        setMoveRequests([]);
        setError(
          requestError instanceof Error ? requestError : new Error('이동 요청 내역을 불러오지 못했습니다.'),
        );
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [scope, status, accessToken]);

  return { moveRequests, isLoading, error };
}
