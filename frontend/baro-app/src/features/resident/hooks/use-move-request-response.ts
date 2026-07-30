import { useCallback, useState } from 'react';

import { postMoveRequestResponse } from '@/features/resident/api/move-request-api';
import type { MoveResponseRequest } from '@/features/resident/api/types';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

export function useMoveRequestResponse(requestId: number | null) {
  const { accessToken } = useAuth();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();

  const submit = useCallback(
    async (request: MoveResponseRequest) => {
      if (requestId === null || !accessToken || isSubmitting) return false;

      setIsSubmitting(true);
      setErrorMessage(undefined);

      try {
        const result = await postMoveRequestResponse(requestId, request, accessToken);
        // eslint-disable-next-line no-console -- 응답 확인용 임시 로그. 실제 화면에 결과가 반영되면 지운다.
        console.log('[move-request] 응답 제출됨', { requestId, request, result });
        return true;
      } catch (error) {
        setErrorMessage(error instanceof ApiError ? error.message : '응답을 보내지 못했습니다.');
        return false;
      } finally {
        setIsSubmitting(false);
      }
    },
    [requestId, accessToken, isSubmitting],
  );

  return { submit, isSubmitting, errorMessage };
}
