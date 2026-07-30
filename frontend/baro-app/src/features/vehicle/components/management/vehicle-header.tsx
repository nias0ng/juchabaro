import { Pressable, Text, View } from 'react-native';

import { styles } from './vehicle-header.styles';

type VehicleHeaderProps = {
  title: string;
  onBack: () => void;
};

/** H-01/H-02-1/H-02-2 상단 헤더. Figma의 38px 원형 뒤로가기 버튼 + 제목 배치를 그대로 따른다. */
export function VehicleHeader({ title, onBack }: VehicleHeaderProps) {
  return (
    <View style={styles.container}>
      <Pressable accessibilityRole="button" onPress={onBack} style={styles.backButton}>
        <Text style={styles.backIcon}>‹</Text>
      </Pressable>
      <Text style={styles.title}>{title}</Text>
    </View>
  );
}
