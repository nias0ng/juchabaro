import { Modal, Text, View } from 'react-native';

import { AppButton, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { RegisterCarCalendar } from './register-car-calendar';
import { styles } from './register-car-visit-date-picker-modal.styles';

type RegisterCarVisitDatePickerModalProps = {
  visible: boolean;
  selectedDate: Date | null;
  onSelectDate: (date: Date) => void;
  onClose: () => void;
};

/**
 * G-02 등록 방문일 선택 모달. 날짜를 탭하면 onSelectDate가 즉시 값 반영과 닫기까지 처리하므로
 * 여기서는 선택 UI만 그린다. "닫기"는 아무 것도 고르지 않고 취소할 때만 쓰인다.
 */
export function RegisterCarVisitDatePickerModal({
  visible,
  selectedDate,
  onSelectDate,
  onClose,
}: RegisterCarVisitDatePickerModalProps) {
  return (
    <Modal visible={visible} transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Stack gap={Spacing.md}>
            <Text style={styles.title}>방문일 선택</Text>
            <RegisterCarCalendar selectedDate={selectedDate} onSelectDate={onSelectDate} />
            <AppButton label="닫기" variant="muted" size="md" fullWidth onPress={onClose} />
          </Stack>
        </View>
      </View>
    </Modal>
  );
}
