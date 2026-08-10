import { Pressable, Text, View } from 'react-native';

import { styles } from './vehicle-add-card.styles';

type VehicleAddCardProps = {
  onPress: () => void;
};

/** H-01/H-02-1/H-02-2에서 공통으로 쓰이는 "차량 추가하기" 점선 카드. */
export function VehicleAddCard({ onPress }: VehicleAddCardProps) {
  return (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [styles.container, pressed && styles.containerPressed]}
      onPress={onPress}
    >
      <View style={styles.iconCircle}>
        <Text style={styles.iconPlus}>+</Text>
      </View>
      <Text style={styles.title}>차량 추가하기</Text>
      <Text style={styles.subtitle}>새로운 차량을 등록하여 관리하세요</Text>
    </Pressable>
  );
}
