import { Modal, Pressable, Text, View } from 'react-native';

import { useTheme } from '@/hooks/use-theme';

import { styles } from './vehicle-delete-confirm-modal.styles';

type VehicleDeleteConfirmModalProps = {
  visible: boolean;
  isDeleting: boolean;
  errorMessage?: string;
  onCancel: () => void;
  onConfirm: () => void;
};

/** H-03. 차량 삭제 확인 모달. UI만 담당하고, API 호출은 화면/훅(use-vehicle-management)에서 처리한다. */
export function VehicleDeleteConfirmModal({
  visible,
  isDeleting,
  errorMessage,
  onCancel,
  onConfirm,
}: VehicleDeleteConfirmModalProps) {
  const theme = useTheme();

  return (
    <Modal visible={visible} transparent onRequestClose={isDeleting ? undefined : onCancel}>
      <View style={styles.overlay}>
        <View style={styles.sheet}>
          <View style={styles.iconCircle}>
            <Text style={styles.iconText}>✕</Text>
          </View>

          <Text style={styles.title}>차량 정보를 삭제하시겠습니까?</Text>
          <Text style={styles.description}>
            {'삭제된 차량 정보는 복구할 수 없습니다.\n정말 차량 정보를 삭제하시겠습니까?'}
          </Text>

          {errorMessage ? (
            <View style={[styles.errorBanner, { backgroundColor: theme.dangerSurface }]}>
              <Text style={[styles.errorText, { color: theme.danger }]}>{errorMessage}</Text>
            </View>
          ) : null}

          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              disabled={isDeleting}
              style={({ pressed }) => [
                styles.deleteButton,
                pressed && styles.deleteButtonPressed,
                isDeleting && styles.buttonDisabled,
              ]}
              onPress={onConfirm}
            >
              <Text style={styles.deleteButtonText}>{isDeleting ? '삭제 중...' : '삭제'}</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              disabled={isDeleting}
              style={({ pressed }) => [
                styles.cancelButton,
                pressed && styles.cancelButtonPressed,
                isDeleting && styles.buttonDisabled,
              ]}
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
