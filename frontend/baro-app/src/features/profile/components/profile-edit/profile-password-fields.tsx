import { Text, View } from 'react-native';

import { TextField } from '@/components/ui';
import type { PasswordChangeFormController } from '@/features/profile/hooks/use-password-change-form';

import { styles } from './profile-password-fields.styles';

type ProfilePasswordFieldsProps = {
  form: PasswordChangeFormController;
};

export function ProfilePasswordFields({ form }: ProfilePasswordFieldsProps) {
  return (
    <>
      <View style={styles.header}>
        <Text style={styles.title}>비밀번호 변경</Text>
        <Text style={styles.description}>
          비밀번호를 변경하지 않으려면 아래 항목은 비워 두세요.
        </Text>
      </View>

      <TextField
        label="현재 비밀번호"
        value={form.currentPassword}
        onChangeText={form.setCurrentPassword}
        secureTextEntry
        autoComplete="current-password"
        placeholder="현재 비밀번호를 입력해 주세요"
        error={
          form.hasInput && !form.currentPasswordValid
            ? '비밀번호를 변경하려면 현재 비밀번호가 필요해요'
            : undefined
        }
      />

      <TextField
        label="새 비밀번호"
        value={form.newPassword}
        onChangeText={form.setNewPassword}
        secureTextEntry
        autoComplete="password-new"
        placeholder="새 비밀번호를 입력해 주세요"
        helperText="최소 8자 · 영문 · 숫자 · 특수문자를 포함해 주세요"
        error={
          form.hasInput && !form.newPasswordValid
            ? '영문, 숫자, 특수문자를 모두 포함해 8자 이상 입력해 주세요'
            : undefined
        }
      />

      <TextField
        label="새 비밀번호 확인"
        value={form.confirmPassword}
        onChangeText={form.setConfirmPassword}
        secureTextEntry
        autoComplete="password-new"
        placeholder="새 비밀번호를 다시 입력해 주세요"
        error={
          form.confirmPassword.length > 0 && !form.confirmPasswordValid
            ? '비밀번호가 일치하지 않아요'
            : undefined
        }
      />
    </>
  );
}
