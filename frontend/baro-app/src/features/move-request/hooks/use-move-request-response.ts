import { useMutation, useQueryClient } from '@tanstack/react-query';

import { postMoveRequestResponse } from '@/features/move-request/api/move-request-api';
import type { MoveRequestDetail, MoveResponseRequest, MoveResponseResult } from '@/features/move-request/api/types';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';
import { queryKeys } from '@/services/query-keys';

export function useMoveRequestResponse(requestId: number | null) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (request: MoveResponseRequest) => {
      if (requestId === null || !accessToken) {
        throw new ApiError('이동 요청 정보를 찾을 수 없습니다.', 0);
      }
      return postMoveRequestResponse(requestId, request, accessToken);
    },
    onSuccess: (result: MoveResponseResult) => {
      if (requestId === null) return;

      // 상세 캐시 갱신은 이 mutation이 유일한 지점이다 — 다른 곳(예: useMoveRequestDetail)에서
      // 같은 응답을 다시 setQueryData하면 responses 배열에 중복 저장될 수 있다.
      queryClient.setQueryData<MoveRequestDetail>(queryKeys.moveRequests.detail(requestId), (prev) => {
        if (!prev) return prev;
        if (prev.responses.some((response) => response.responseId === result.responseId)) return prev;

        return {
          ...prev,
          requestStatus: result.requestStatus,
          dueAt: result.dueAt,
          responses: [
            ...prev.responses,
            {
              responseId: result.responseId,
              responseType: result.responseType,
              estimatedMinutes: result.estimatedMinutes,
              respondedAt: result.respondedAt,
            },
          ],
        };
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.moveRequests.lists() });
    },
  });

  const submit = async (request: MoveResponseRequest): Promise<MoveResponseResult | null> => {
    if (requestId === null || !accessToken || mutation.isPending) return null;

    try {
      return await mutation.mutateAsync(request);
    } catch {
      return null;
    }
  };

  const errorMessage =
    mutation.error instanceof ApiError ? mutation.error.message : mutation.error ? '응답을 보내지 못했습니다.' : undefined;

  return { submit, isSubmitting: mutation.isPending, errorMessage };
}
