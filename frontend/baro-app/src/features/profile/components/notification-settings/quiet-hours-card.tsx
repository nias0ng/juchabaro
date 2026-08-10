import { Pressable, Text, View } from 'react-native';

import { styles } from './quiet-hours-card.styles';

type QuietHoursCardProps = {
  startLabel: string;
  endLabel: string;
  disabled?: boolean;
  onPressStart: () => void;
  onPressEnd: () => void;
};

// 방해 금지 시작·종료 시간을 선택하는 카드. 저장 중에는 중복 요청을 막기 위해 비활성화한다.
export function QuietHoursCard({
  startLabel,
  endLabel,
  disabled = false,
  onPressStart,
  onPressEnd,
}: QuietHoursCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>방해 금지 시간</Text>

      <View style={styles.timeRow}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled }}
          disabled={disabled}
          style={({ pressed }) => [
            styles.timeBox,
            pressed && styles.timeBoxPressed,
            disabled && styles.timeBoxDisabled,
          ]}
          onPress={onPressStart}
        >
          <Text style={styles.timeLabel}>시작</Text>
          <Text style={styles.timeValue}>{startLabel}</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled }}
          disabled={disabled}
          style={({ pressed }) => [
            styles.timeBox,
            pressed && styles.timeBoxPressed,
            disabled && styles.timeBoxDisabled,
          ]}
          onPress={onPressEnd}
        >
          <Text style={styles.timeLabel}>종료</Text>
          <Text style={styles.timeValue}>{endLabel}</Text>
        </Pressable>
      </View>
    </View>
  );
}
