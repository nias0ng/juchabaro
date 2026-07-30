import { Pressable, Text } from 'react-native';

import { styles } from './vehicle-add-section.styles';

type VehicleAddSectionProps = {
  onPress: () => void;
};

/** H-02-1/H-02-2에서 차량 목록 아래에 표시되는 "차량 추가하기" 영역. */
export function VehicleAddSection({ onPress }: VehicleAddSectionProps) {
  return (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [styles.container, pressed && styles.pressed]}
      onPress={onPress}
    >
      <Text style={styles.plus}>+</Text>
      <Text style={styles.label}>차량 추가하기</Text>
    </Pressable>
  );
}
