import { Pressable, Text, View } from 'react-native';

import { Avatar } from '@/components/ui';
import { Spacing } from '@/styles';

import { styles } from './home-top-bar.styles';

type HomeTopBarProps = {
  unitLabel: string;
  avatarInitial: string;
  onPressNotification: () => void;
};

export function HomeTopBar({ unitLabel, avatarInitial, onPressNotification }: HomeTopBarProps) {
  return (
    <View style={styles.topBar}>
      <View style={styles.unitPill}>
        <Avatar label={avatarInitial} />
        <Text style={styles.unitText}>{unitLabel}</Text>
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="알림"
        hitSlop={Spacing.xs}
        style={styles.notificationButton}
        onPress={onPressNotification}
      >
        <View style={styles.bellShape} />
        <View style={styles.notificationDot} />
      </Pressable>
    </View>
  );
}
