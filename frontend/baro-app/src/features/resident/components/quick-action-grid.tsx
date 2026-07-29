import { Pressable, Text, View } from 'react-native';

import { styles } from './quick-action-grid.styles';

export type QuickAction = {
  label: string;
  background: string;
  iconColor: string;
  onPress?: () => void;
};

type QuickActionGridProps = {
  actions: QuickAction[];
};

export function QuickActionGrid({ actions }: QuickActionGridProps) {
  return (
    <View style={styles.row}>
      {actions.map((action) => (
        <Pressable
          key={action.label}
          accessibilityRole="button"
          style={[styles.action, { backgroundColor: action.background }]}
          onPress={action.onPress}
        >
          <Text style={styles.label}>{action.label}</Text>
          <View style={[styles.icon, { backgroundColor: action.iconColor }]} />
        </Pressable>
      ))}
    </View>
  );
}
