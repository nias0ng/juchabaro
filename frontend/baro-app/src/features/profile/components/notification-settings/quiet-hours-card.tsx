import { Pressable, Text, View } from 'react-native';

import { styles } from './quiet-hours-card.styles';

type QuietHoursCardProps = {
  startLabel: string;
  endLabel: string;
  onPressStart: () => void;
  onPressEnd: () => void;
};

// 방해 금지 시간. 백엔드 저장 API가 없어 값은 화면 로컬 상태로만 반영한다.
export function QuietHoursCard({ startLabel, endLabel, onPressStart, onPressEnd }: QuietHoursCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>방해 금지 시간</Text>

      <View style={styles.timeRow}>
        <Pressable
          accessibilityRole="button"
          style={({ pressed }) => [styles.timeBox, pressed && styles.timeBoxPressed]}
          onPress={onPressStart}
        >
          <Text style={styles.timeLabel}>시작</Text>
          <Text style={styles.timeValue}>{startLabel}</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          style={({ pressed }) => [styles.timeBox, pressed && styles.timeBoxPressed]}
          onPress={onPressEnd}
        >
          <Text style={styles.timeLabel}>종료</Text>
          <Text style={styles.timeValue}>{endLabel}</Text>
        </Pressable>
      </View>
    </View>
  );
}
