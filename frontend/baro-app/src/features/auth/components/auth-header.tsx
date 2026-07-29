import { router } from 'expo-router';
import { Pressable, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import { styles } from './auth-header.styles';

type AuthHeaderProps = {
  title: string;
  onBack?: () => void;
  style?: StyleProp<ViewStyle>;
};

export function AuthHeader({ title, onBack, style }: AuthHeaderProps) {
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
