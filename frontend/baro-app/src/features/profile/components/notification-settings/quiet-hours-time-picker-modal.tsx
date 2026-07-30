import { useEffect, useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';

import { AppButton, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { styles } from './quiet-hours-time-picker-modal.styles';

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const MINUTES = Array.from({ length: 60 }, (_, i) => i);

function pad2(value: number): string {
  return value.toString().padStart(2, '0');
}

type QuietHoursTimePickerModalProps = {
  visible: boolean;
  title: string;
  value: string; // "HH:mm"
  onConfirm: (value: string) => void;
  onClose: () => void;
};

// 방해 금지 시작/종료 시간을 24시간 기준 시·분으로 고르는 모달. 두 값을 같이 확정해야 해서
// (등록 방문일 모달처럼) 탭 한 번에 바로 닫히지 않고 "확인"을 눌러야 반영된다.
export function QuietHoursTimePickerModal({
  visible,
  title,
  value,
  onConfirm,
  onClose,
}: QuietHoursTimePickerModalProps) {
  const [selectedHour, setSelectedHour] = useState(0);
  const [selectedMinute, setSelectedMinute] = useState(0);

  useEffect(() => {
    if (!visible) return;
    const [hour, minute] = value.split(':').map(Number);
    setSelectedHour(hour || 0);
    setSelectedMinute(minute || 0);
  }, [visible, value]);

  return (
    <Modal visible={visible} transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Stack gap={Spacing.md}>
            <Text style={styles.title}>{title}</Text>

            <View style={styles.columns}>
              <ScrollView style={styles.column} showsVerticalScrollIndicator={false}>
                {HOURS.map((hour) => (
                  <Pressable
                    key={hour}
                    accessibilityRole="button"
                    accessibilityState={{ selected: hour === selectedHour }}
                    style={[styles.item, hour === selectedHour && styles.itemSelected]}
                    onPress={() => setSelectedHour(hour)}
                  >
                    <Text style={[styles.itemText, hour === selectedHour && styles.itemTextSelected]}>
                      {pad2(hour)}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>

              <Text style={styles.colon}>:</Text>

              <ScrollView style={styles.column} showsVerticalScrollIndicator={false}>
                {MINUTES.map((minute) => (
                  <Pressable
                    key={minute}
                    accessibilityRole="button"
                    accessibilityState={{ selected: minute === selectedMinute }}
                    style={[styles.item, minute === selectedMinute && styles.itemSelected]}
                    onPress={() => setSelectedMinute(minute)}
                  >
                    <Text style={[styles.itemText, minute === selectedMinute && styles.itemTextSelected]}>
                      {pad2(minute)}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
            </View>

            <Stack direction="row" gap={Spacing.sm}>
              <AppButton label="취소" variant="muted" size="md" style={styles.flexButton} onPress={onClose} />
              <AppButton
                label="확인"
                variant="primary"
                size="md"
                style={styles.flexButton}
                onPress={() => onConfirm(`${pad2(selectedHour)}:${pad2(selectedMinute)}`)}
              />
            </Stack>
          </Stack>
        </View>
      </View>
    </Modal>
  );
}
