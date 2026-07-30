import { router } from 'expo-router';
import { Pressable, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { Spacing } from '@/styles';

import { styles } from './screen-header.styles';
import { Stack } from './stack';

type ScreenHeaderProps = {
  title: string;
  onBack?: () => void;
  style?: StyleProp<ViewStyle>;
};

export function ScreenHeader({ title, onBack, style }: ScreenHeaderProps) {
  return (
    <Stack direction="row" align="center" gap={Spacing.base} style={[styles.container, style]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="뒤로 가기"
        style={styles.backButton}
        onPress={onBack ?? (() => router.back())}
      >
        <View style={styles.backIcon} />
      </Pressable>
      <Text style={styles.title}>{title}</Text>
    </Stack>
  );
}
