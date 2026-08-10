import { useState } from 'react';

import { withdrawMyAccount } from '@/features/profile/api/profile-api';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

/**
 * 현재 비밀번호 확인 후 회원 탈퇴를 요청하고, 성공하면 로컬 세션도 정리한다.
 * API: POST /api/users/me/withdrawal
 */
export function useAccountWithdrawal() {
  const { accessToken, logout } = useAuth();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();

  const clearError = () => setErrorMessage(undefined);

  const submit = async (currentPassword: string): Promise<boolean> => {
    if (!accessToken || currentPassword.length === 0 || isSubmitting) return false;

    setIsSubmitting(true);
    setErrorMessage(undefined);

    try {
      await withdrawMyAccount({ currentPassword }, accessToken);
      await logout();
      return true;
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : '회원 탈퇴를 처리하지 못했습니다.');
      return false;
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    isSubmitting,
    errorMessage,
    clearError,
    submit,
  };
}
