import { Modal, Text, View } from 'react-native';

import { AppButton, Stack } from '@/components/ui';
import { useTheme } from '@/hooks/use-theme';
import { Spacing } from '@/styles';

import type { VehicleResult } from '@/features/auth/api/vehicle-types';

import { maskPlateNumber } from '../../utils/mask-plate-number';

import { styles } from './vehicle-delete-confirm-modal.styles';

type VehicleDeleteConfirmModalProps = {
  visible: boolean;
  vehicle: VehicleResult | null;
  isDeleting: boolean;
  errorMessage?: string;
  onCancel: () => void;
  onConfirm: () => void;
};

/** H-03. 차량 삭제 확인 모달. 삭제 대상 차량 정보만 보여주고, API 호출은 화면/훅에서 처리한다. */
export function VehicleDeleteConfirmModal({
  visible,
  vehicle,
  isDeleting,
  errorMessage,
  onCancel,
  onConfirm,
}: VehicleDeleteConfirmModalProps) {
  const theme = useTheme();

  return (
    <Modal visible={visible} transparent onRequestClose={isDeleting ? undefined : onCancel}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Stack gap={Spacing.md}>
            <Text style={styles.title}>차량을 삭제할까요?</Text>
            {vehicle ? <Text style={styles.plate}>{maskPlateNumber(vehicle.plateNumber)}</Text> : null}
            <Text style={styles.description}>삭제한 차량 정보는 복구할 수 없습니다.</Text>

            {errorMessage ? (
              <View style={[styles.errorBanner, { backgroundColor: theme.dangerSurface }]}>
                <Text style={[styles.errorText, { color: theme.danger }]}>{errorMessage}</Text>
              </View>
            ) : null}

            <Stack direction="row" gap={Spacing.sm}>
              <View style={styles.actionItem}>
                <AppButton label="취소" variant="muted" size="md" fullWidth disabled={isDeleting} onPress={onCancel} />
              </View>
              <View style={styles.actionItem}>
                <AppButton
                  label="삭제"
                  variant="primary"
                  size="md"
                  fullWidth
                  loading={isDeleting}
                  style={{ backgroundColor: theme.danger, borderColor: theme.danger }}
                  onPress={onConfirm}
                />
              </View>
            </Stack>
          </Stack>
        </View>
      </View>
    </Modal>
  );
}
