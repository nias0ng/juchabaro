import { Pressable, ScrollView, Text, View } from 'react-native';

import { IconGlyph } from '@/components/ui';
import { Palette } from '@/styles';

import { styles } from './quick-action-grid.styles';

export type QuickAction = {
  label: string;
  background: string;
  iconColor: string;
  onPress?: () => void;
};

const CHEVRON_PATH = 'M9 6L15 12L9 18';

type QuickActionGridProps = {
  actions: QuickAction[];
};

export function QuickActionGrid({ actions }: QuickActionGridProps) {
  return (
    <ScrollView
      horizontal
      directionalLockEnabled
      nestedScrollEnabled
      showsHorizontalScrollIndicator={false}
      snapToAlignment="start"
      snapToInterval={104}
      decelerationRate="fast"
      style={styles.scroll}
      contentContainerStyle={styles.row}
    >
      {actions.map((action) => (
        <Pressable
          key={action.label}
          accessibilityRole="button"
          accessibilityState={{ disabled: !action.onPress }}
          disabled={!action.onPress}
          style={[styles.action, { backgroundColor: action.background }]}
          onPress={action.onPress}
        >
          <Text style={styles.label}>{action.label}</Text>
          <View style={[styles.chevronBox, { backgroundColor: action.iconColor }]}>
            <IconGlyph
              d={CHEVRON_PATH}
              size={12}
              viewBoxSize={24}
              strokeWidth={2.5}
              color={Palette.white}
            />
          </View>
        </Pressable>
      ))}
    </ScrollView>
  );
}
