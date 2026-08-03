import { useState } from 'react';

import { isConfirmPasswordValid, isPasswordValid } from '@/features/auth/validation/signup';

export function usePasswordChangeForm() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const hasInput =
    currentPassword.length > 0 || newPassword.length > 0 || confirmPassword.length > 0;
  const currentPasswordValid = !hasInput || currentPassword.length > 0;
  const newPasswordValid = !hasInput || isPasswordValid(newPassword);
  const confirmPasswordValid =
    !hasInput || isConfirmPasswordValid(newPassword, confirmPassword);

  return {
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    confirmPassword,
    setConfirmPassword,
    hasInput,
    currentPasswordValid,
    newPasswordValid,
    confirmPasswordValid,
    isValid: currentPasswordValid && newPasswordValid && confirmPasswordValid,
  };
}

export type PasswordChangeFormController = ReturnType<typeof usePasswordChangeForm>;
