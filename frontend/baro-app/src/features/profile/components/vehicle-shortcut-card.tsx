import { Pressable, Text, View } from 'react-native';

import { Palette } from '@/styles';

import { ProfileIcon } from './profile-icon';
import { styles } from './vehicle-shortcut-card.styles';

type VehicleShortcutCardProps = {
  subtitle: string;
  onPress: () => void;
};

export function VehicleShortcutCard({ subtitle, onPress }: VehicleShortcutCardProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="차량 관리"
      style={({ pressed }) => [styles.pressable, pressed && styles.pressablePressed]}
      onPress={onPress}
    >
      <View style={styles.container}>
        <View style={styles.iconBadge}>
          <ProfileIcon name="car" size={18} color={Palette.gray975} />
        </View>
        <View style={styles.textGroup}>
          <Text style={styles.title}>차량 관리</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>
        <Text style={styles.chevron}>›</Text>
      </View>
    </Pressable>
  );
}
