import { useAuthenticatedQuery } from '@/hooks/use-authenticated-query';
import { getMoveRequestDetail, getMoveRequests } from '@/features/move-request/api/move-request-api';
import type {
  MoveRequestListItem,
  MoveRequestScope,
  MoveRequestSummary,
} from '@/features/move-request/api/types';

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

async function fetchMoveRequestListItems(scope: MoveRequestScope, accessToken: string): Promise<MoveRequestListItem[]> {
  const result = await getMoveRequests(scope, accessToken);
  return Promise.all(result.moveRequests.map((summary) => enrichWithDetail(summary, accessToken)));
}

export function useMoveRequests(scope: MoveRequestScope) {
  const {
    data: moveRequests,
    isLoading,
    error,
  } = useAuthenticatedQuery<MoveRequestListItem[]>(
    (accessToken) => fetchMoveRequestListItems(scope, accessToken),
    [],
    '이동 요청 내역을 불러오지 못했습니다.',
    [scope],
  );

  return { moveRequests, isLoading, error };
}
