import { useState } from 'react';

import { isConfirmPasswordValid, isPasswordValid } from '@/features/auth/validation/signup';
import { useAuth } from '@/providers/auth-provider';

export function useProfileEditForm() {
  const { user } = useAuth();
  const initialName = user?.nickname ?? '';
  const [name, setName] = useState(initialName);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const hasPasswordInput =
    currentPassword.length > 0 || newPassword.length > 0 || confirmPassword.length > 0;
  const currentPasswordValid = !hasPasswordInput || currentPassword.length > 0;
  const newPasswordValid = !hasPasswordInput || isPasswordValid(newPassword);
  const confirmPasswordValid = !hasPasswordInput || isConfirmPasswordValid(newPassword, confirmPassword);
  const hasChanges = name.trim() !== initialName || hasPasswordInput;
  const canSave =
    hasChanges &&
    name.trim().length > 0 &&
    currentPasswordValid &&
    newPasswordValid &&
    confirmPasswordValid;

  return {
    name,
    setName,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    confirmPassword,
    setConfirmPassword,
    hasPasswordInput,
    currentPasswordValid,
    newPasswordValid,
    confirmPasswordValid,
    canSave,
  };
}
