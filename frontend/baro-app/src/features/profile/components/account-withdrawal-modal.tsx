import { Modal, Pressable, Text, View } from 'react-native';

import { TextField } from '@/components/ui';

import { styles } from './account-withdrawal-modal.styles';

type AccountWithdrawalModalProps = {
  visible: boolean;
  currentPassword: string;
  noticeMessage?: string;
  onChangeCurrentPassword: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
};

export function AccountWithdrawalModal({
  visible,
  currentPassword,
  noticeMessage,
  onChangeCurrentPassword,
  onCancel,
  onConfirm,
}: AccountWithdrawalModalProps) {
  const canConfirm = currentPassword.length > 0;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.overlay}>
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

          {noticeMessage ? (
            <View style={styles.notice}>
              <Text style={styles.noticeText}>{noticeMessage}</Text>
            </View>
          ) : null}

          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: !canConfirm }}
              disabled={!canConfirm}
              style={({ pressed }) => [
                styles.withdrawButton,
                pressed && styles.withdrawButtonPressed,
                !canConfirm && styles.buttonDisabled,
              ]}
              onPress={onConfirm}
            >
              <Text style={styles.withdrawButtonText}>회원 탈퇴</Text>
            </Pressable>

            <Pressable
              accessibilityRole="button"
              style={({ pressed }) => [styles.cancelButton, pressed && styles.cancelButtonPressed]}
              onPress={onCancel}
            >
              <Text style={styles.cancelButtonText}>취소</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
