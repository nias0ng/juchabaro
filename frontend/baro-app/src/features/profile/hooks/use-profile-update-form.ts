import { useState } from 'react';

import { updateMyProfile } from '@/features/profile/api/profile-api';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

import { usePasswordChangeForm } from './use-password-change-form';

export function useProfileUpdateForm() {
  const { user, accessToken, updateUserProfile } = useAuth();
  const initialName = user?.nickname ?? '';
  const [name, setName] = useState(initialName);
  const password = usePasswordChangeForm();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();

  const hasChanges = name.trim() !== initialName || password.hasInput;
  const canSave = hasChanges && name.trim().length > 0 && password.isValid;

  const submit = async (): Promise<boolean> => {
    if (!canSave || !accessToken || isSubmitting) return false;

    setIsSubmitting(true);
    setErrorMessage(undefined);

    try {
      const trimmedName = name.trim();
      const result = await updateMyProfile(
        {
          ...(trimmedName !== initialName ? { name: trimmedName } : {}),
          ...(password.hasInput
            ? {
                currentPassword: password.currentPassword,
                newPassword: password.newPassword,
              }
            : {}),
        },
        accessToken,
      );

      updateUserProfile(result);
      return true;
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : '내 정보를 수정하지 못했습니다.');
      return false;
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    name,
    setName,
    password,
    canSave,
    isSubmitting,
    errorMessage,
    submit,
  };
}
