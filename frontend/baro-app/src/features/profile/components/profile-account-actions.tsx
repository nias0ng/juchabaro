import { useState } from 'react';
import { ActivityIndicator, Pressable, Text } from 'react-native';

import { Stack } from '@/components/ui';
import { useAccountWithdrawal } from '@/features/profile/hooks/use-account-withdrawal';
import { useAuth } from '@/providers/auth-provider';
import { Spacing } from '@/styles';

import { AccountWithdrawalModal } from './account-withdrawal-modal';
import { ProfileIcon } from './profile-icon';
import { LOGOUT_COLOR, styles } from './profile-account-actions.styles';

export function ProfileAccountActions() {
  const { logout } = useAuth();
  const accountWithdrawal = useAccountWithdrawal();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [isWithdrawalOpen, setIsWithdrawalOpen] = useState(false);
  const [withdrawalPassword, setWithdrawalPassword] = useState('');

  const handleLogout = async () => {
    if (isLoggingOut) return;
    setIsLoggingOut(true);
    await logout();
  };

  const closeWithdrawalModal = () => {
    if (accountWithdrawal.isSubmitting) return;
    setIsWithdrawalOpen(false);
    setWithdrawalPassword('');
    accountWithdrawal.clearError();
  };

  return (
    <>
      <Stack gap={Spacing.base + 2}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: isLoggingOut, busy: isLoggingOut }}
          disabled={isLoggingOut}
          style={({ pressed }) => [styles.logoutButton, pressed && styles.logoutButtonPressed]}
          onPress={handleLogout}
        >
          {isLoggingOut ? (
            <ActivityIndicator color={LOGOUT_COLOR} />
          ) : (
            <Stack direction="row" align="center" gap={Spacing.sm}>
              <ProfileIcon name="logout" size={18} />
              <Text style={styles.logoutText}>로그아웃</Text>
            </Stack>
          )}
        </Pressable>

        <Pressable
          accessibilityRole="button"
          style={styles.withdrawLink}
          onPress={() => setIsWithdrawalOpen(true)}
        >
          <Text style={styles.withdrawText}>회원 탈퇴</Text>
        </Pressable>
      </Stack>

      <AccountWithdrawalModal
        visible={isWithdrawalOpen}
        currentPassword={withdrawalPassword}
        isSubmitting={accountWithdrawal.isSubmitting}
        errorMessage={accountWithdrawal.errorMessage}
        onChangeCurrentPassword={(value) => {
          setWithdrawalPassword(value);
          accountWithdrawal.clearError();
        }}
        onCancel={closeWithdrawalModal}
        onConfirm={() => accountWithdrawal.submit(withdrawalPassword)}
      />
    </>
  );
}
