import { useCallback, useState } from 'react';

import { postMoveRequestResponse } from '@/features/move-request/api/move-request-api';
import type { MoveResponseRequest, MoveResponseResult } from '@/features/move-request/api/types';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

export function useMoveRequestResponse(requestId: number | null) {
  const { accessToken } = useAuth();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();

  const submit = useCallback(
    async (request: MoveResponseRequest): Promise<MoveResponseResult | null> => {
      if (requestId === null || !accessToken || isSubmitting) return null;

      setIsSubmitting(true);
      setErrorMessage(undefined);

      try {
        return await postMoveRequestResponse(requestId, request, accessToken);
      } catch (error) {
        setErrorMessage(error instanceof ApiError ? error.message : '응답을 보내지 못했습니다.');
        return null;
      } finally {
        setIsSubmitting(false);
      }
    },
    [requestId, accessToken, isSubmitting],
  );

  return { submit, isSubmitting, errorMessage };
}
