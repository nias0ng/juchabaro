import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  Text,
  View,
} from 'react-native';

import { TextField } from '@/components/ui';
import { Palette } from '@/styles';

import { styles } from './account-withdrawal-modal.styles';

type AccountWithdrawalModalProps = {
  visible: boolean;
  currentPassword: string;
  isSubmitting: boolean;
  errorMessage?: string;
  onChangeCurrentPassword: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
};

export function AccountWithdrawalModal({
  visible,
  currentPassword,
  isSubmitting,
  errorMessage,
  onChangeCurrentPassword,
  onCancel,
  onConfirm,
}: AccountWithdrawalModalProps) {
  const canConfirm = currentPassword.length > 0;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={isSubmitting ? undefined : onCancel}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.overlay}
      >
        <View style={styles.sheet}>
          <View style={styles.iconCircle}>
            <Text style={styles.iconText}>!</Text>
          </View>

          <Text style={styles.title}>정말 회원 탈퇴하시겠어요?</Text>
          <Text style={styles.description}>
            탈퇴하면 계정과 서비스 이용이 중단됩니다.{`\n`}본인 확인을 위해 현재 비밀번호를 입력해 주세요.
          </Text>

          <TextField
            label="현재 비밀번호"
            value={currentPassword}
            onChangeText={onChangeCurrentPassword}
            secureTextEntry
            autoComplete="current-password"
            placeholder="현재 비밀번호를 입력해 주세요"
          />

          {errorMessage ? (
            <View style={styles.notice}>
              <Text style={styles.noticeText}>{errorMessage}</Text>
            </View>
          ) : null}

          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: !canConfirm || isSubmitting, busy: isSubmitting }}
              disabled={!canConfirm || isSubmitting}
              style={({ pressed }) => [
                styles.withdrawButton,
                pressed && styles.withdrawButtonPressed,
                (!canConfirm || isSubmitting) && styles.buttonDisabled,
              ]}
              onPress={onConfirm}
            >
              {isSubmitting ? (
                <ActivityIndicator color={Palette.white} />
              ) : (
                <Text style={styles.withdrawButtonText}>회원 탈퇴</Text>
              )}
            </Pressable>

            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: isSubmitting }}
              disabled={isSubmitting}
              style={({ pressed }) => [styles.cancelButton, pressed && styles.cancelButtonPressed]}
              onPress={onCancel}
            >
              <Text style={styles.cancelButtonText}>취소</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
