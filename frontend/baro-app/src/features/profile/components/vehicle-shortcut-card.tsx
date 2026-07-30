import { LinearGradient } from 'expo-linear-gradient';
import { Pressable, Text, View } from 'react-native';

import { Gradients } from '@/styles';

import { styles } from './vehicle-shortcut-card.styles';

type VehicleShortcutCardProps = {
  subtitle: string;
  onPress: () => void;
};

export function VehicleShortcutCard({ subtitle, onPress }: VehicleShortcutCardProps) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress}>
      <LinearGradient colors={Gradients.vehicleShortcut} style={styles.container}>
        <View style={styles.iconBadge} />
        <View style={styles.textGroup}>
          <Text style={styles.title}>차량 관리 ›</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>
      </LinearGradient>
    </Pressable>
  );
}
